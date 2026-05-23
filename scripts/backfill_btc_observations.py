"""
One-shot: backfill the btc_holdings_observations table from current state +
fresh source pulls, then reconcile every ticker to canonical values.

Run this immediately after migration 0016 to bootstrap the divergence-proof
architecture. Idempotent — re-running just appends a fresh round of
observations (each timestamped) and reconciles again.

Three passes, in order:

  1. INITIAL  — one observation per existing treasury_companies row, tagged
                'backfill_initial' with trust=10. This guarantees every
                ticker has at least one observation so reconcile_ticker()
                doesn't return None and zero out treasury_companies.

  2. COINGECKO — pull /companies/public_treasury/bitcoin and write one
                observation per matched ticker, source='coingecko' (trust=40).

  3. BITCOINTREASURIES — scrape bitcointreasuries.net/ and write one
                observation per ticker, source='bitcointreasuries' (trust=60).
                We extract the embedded JSON btc_balance values rather than
                parsing the HTML table — JSON is canonical, table layout is
                fragile (cf. KEEL parsing bug history).

After all three passes, runs btc_holdings_reconciler.reconcile_all() which:
  - picks the highest-effective-trust source per ticker
  - alerts (Telegram + divergence_alerts row) on disagreement
  - writes resolved values + provenance to treasury_companies

Usage:
    python scripts/backfill_btc_observations.py            # dry-run summary
    python scripts/backfill_btc_observations.py --apply    # actually write

Apply mode does:
  - inserts observations (additive, safe)
  - calls reconcile_all() which OVERWRITES treasury_companies.btc_holdings
    based on resolution. BACKUP treasury_companies BEFORE --apply.

Backup:
    CREATE TABLE treasury_companies_backup_pre_0016 AS
    SELECT * FROM treasury_companies;
"""
from __future__ import annotations

import os
import re
import sys
import json
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from supabase import create_client

# Allow imports from treasury_signals when invoked as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
if not (SUPABASE_URL and SUPABASE_KEY):
    sys.exit("SUPABASE_URL + SUPABASE_KEY required in .env")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
apply = "--apply" in sys.argv

HEADERS = {
    "User-Agent": "TreasurySignalIntelligence backfill admin@quantedgeriskadvisory.com",
    "Accept": "application/json, text/html",
}

print(f"Mode: {'APPLYING' if apply else 'DRY-RUN (pass --apply to write)'}")
print("=" * 70)


# ─── PASS 1: initial backfill from current treasury_companies ────────────

def pass_initial() -> list[dict]:
    """One observation per current treasury_companies row, source='backfill_initial'."""
    print("\n[1/3] INITIAL — current treasury_companies state")
    r = (
        supabase.table("treasury_companies")
        .select("ticker, company, btc_holdings, last_updated")
        .gt("btc_holdings", 0)
        .execute()
    )
    rows = r.data or []
    obs = []
    for row in rows:
        ticker = (row.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        obs.append({
            "ticker": ticker,
            "source": "backfill_initial",
            "btc_value": float(row.get("btc_holdings") or 0),
            "observed_at": row.get("last_updated") or datetime.now(timezone.utc).isoformat(),
            "source_url": None,
            "excerpt": f"Backfill of pre-0016 state for {row.get('company') or ticker}",
            "components": {"backfill_at": datetime.now(timezone.utc).isoformat()},
        })
    print(f"  Generated {len(obs)} initial observations from treasury_companies")
    return obs


# ─── PASS 2: CoinGecko ───────────────────────────────────────────────────

def pass_coingecko() -> list[dict]:
    """Pull CoinGecko's public treasury list."""
    print("\n[2/3] COINGECKO — /companies/public_treasury/bitcoin")
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/companies/public_treasury/bitcoin",
            headers=HEADERS, timeout=30,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  ERROR: {e}")
        return []
    companies = data.get("companies", []) or []
    obs = []
    now_iso = datetime.now(timezone.utc).isoformat()
    for c in companies:
        sym = (c.get("symbol") or "").strip().upper()
        if not sym:
            continue
        # Strip Bloomberg .US suffix (CoinGecko uses MSTR.US, KEEL.US, etc.)
        if sym.endswith(".US") and len(sym) > 3:
            sym = sym[:-3]
        btc = c.get("total_holdings")
        if btc is None:
            continue
        obs.append({
            "ticker": sym,
            "source": "coingecko",
            "btc_value": float(btc),
            "observed_at": now_iso,
            "source_url": "https://api.coingecko.com/api/v3/companies/public_treasury/bitcoin",
            "excerpt": f"{c.get('name', '')} — {btc} BTC, {c.get('country', '')}, "
                       f"value=${c.get('total_current_value_usd', 0):,.0f}",
            "components": {
                "name": c.get("name"),
                "country": c.get("country"),
                "percentage_of_total_supply": c.get("percentage_of_total_supply"),
            },
        })
    print(f"  Pulled {len(obs)} observations from CoinGecko ({len(companies)} companies returned)")
    return obs


# ─── PASS 3: BitcoinTreasuries (JSON-from-page, not HTML table) ──────────

def pass_bitcointreasuries() -> list[dict]:
    """Extract BTC balances from BitcoinTreasuries.net's embedded data.

    Why this approach (vs the legacy HTML-table parser in treasury_sync.py):
    BT.net's HTML table has TWO layouts (desktop + responsive) and the
    column-indexed parser has historically picked the wrong cell (e.g.
    market_cap interpreted as BTC). The embedded Next.js data has unambiguous
    `symbol:"X"...btc_balance:N` pairs.

    Pairing algorithm: find every `btc_balance:N` occurrence in the page;
    for each, walk backwards to find the IMMEDIATELY PRECEDING `symbol:"X"`.
    This handles arbitrarily-nested objects (industries, tags, etc.) between
    the ticker block and the btc_balance field — which my first attempt at
    a single regex couldn't, and is why KEEL was being missed.
    """
    print("\n[3/3] BITCOINTREASURIES — embedded JSON across category pages")
    pages = [
        ("public_company", "https://bitcointreasuries.net/"),
        ("private_company", "https://bitcointreasuries.net/private-companies"),
        ("etf", "https://bitcointreasuries.net/etfs-and-exchanges"),
        ("government", "https://bitcointreasuries.net/governments"),
        ("defi", "https://bitcointreasuries.net/defi-and-other"),
    ]
    obs = []
    now_iso = datetime.now(timezone.utc).isoformat()
    seen_tickers: set[str] = set()

    sym_re = re.compile(r'symbol:"([A-Z0-9.\-]+)"')
    bal_re = re.compile(r'btc_balance:(\d+(?:\.\d+)?)')

    for category, url in pages:
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
        except Exception as e:
            print(f"  WARN  {category}: fetch failed: {e}")
            continue
        text = r.text

        # Collect (offset, symbol) and (offset, btc_balance) pairs separately.
        symbols = [(m.start(), m.group(1)) for m in sym_re.finditer(text)]
        balances = [(m.start(), float(m.group(1))) for m in bal_re.finditer(text)]

        new_for_page = 0
        # For each btc_balance, find the IMMEDIATELY PRECEDING symbol.
        # symbols list is already ordered by offset; bisect is overkill for
        # ~300 entries so we just scan.
        for bal_offset, bal_val in balances:
            preceding = None
            for sym_offset, sym_str in symbols:
                if sym_offset < bal_offset:
                    preceding = (sym_offset, sym_str)
                else:
                    break
            if not preceding:
                continue
            sym = preceding[1].strip().upper()
            # Strip .US suffix consistently with the codebase.
            if sym.endswith(".US") and len(sym) > 3:
                sym = sym[:-3]
            if not sym or sym in seen_tickers:
                continue
            if bal_val <= 0 or bal_val > 50_000_000:
                continue
            # Sanity gate: symbol and btc_balance shouldn't be > 50K chars apart.
            # If they are, we've crossed an entity boundary and the pairing is wrong.
            if bal_offset - preceding[0] > 50_000:
                continue
            seen_tickers.add(sym)
            obs.append({
                "ticker": sym,
                "source": "bitcointreasuries",
                "btc_value": bal_val,
                "observed_at": now_iso,
                "source_url": url,
                "excerpt": f"BitcoinTreasuries.net JSON ({category}): btc_balance={bal_val}",
                "components": {"category": category},
            })
            new_for_page += 1
        print(f"  {category:<16} {new_for_page:>4} new tickers (from {len(balances)} btc_balance fields, {len(symbols)} symbol fields)")
    print(f"  Total: {len(obs)} observations from BitcoinTreasuries")
    return obs


# ─── Insert helper (chunked) ─────────────────────────────────────────────

def insert_observations(rows: list[dict], label: str) -> int:
    if not apply:
        return 0
    CHUNK = 500
    inserted = 0
    for i in range(0, len(rows), CHUNK):
        batch = rows[i : i + CHUNK]
        try:
            supabase.table("btc_holdings_observations").insert(batch).execute()
            inserted += len(batch)
        except Exception as e:
            print(f"  ERROR inserting {label} chunk {i // CHUNK}: {e}")
    return inserted


# ─── Main ────────────────────────────────────────────────────────────────

def main():
    initial = pass_initial()
    cg = pass_coingecko()
    bt = pass_bitcointreasuries()

    print("\n" + "=" * 70)
    print(f"SUMMARY (pre-write):")
    print(f"  initial:          {len(initial)} observations")
    print(f"  coingecko:        {len(cg)} observations")
    print(f"  bitcointreasuries:{len(bt)} observations")

    # Spot-check the KEEL case
    print("\nKEEL spot-check (the canary):")
    for src_name, rows in [("initial", initial), ("coingecko", cg), ("bitcointreasuries", bt)]:
        matches = [r for r in rows if r["ticker"] == "KEEL"]
        if matches:
            print(f"  {src_name:<18} {matches[0]['btc_value']:>10,.0f} BTC")
        else:
            print(f"  {src_name:<18} (no row for KEEL)")

    if not apply:
        print("\nDry-run. Re-run with --apply to insert observations + reconcile.")
        print("Reminder: BACKUP treasury_companies FIRST.")
        return

    print("\nInserting observations…")
    n_initial = insert_observations(initial, "initial")
    n_cg = insert_observations(cg, "coingecko")
    n_bt = insert_observations(bt, "bitcointreasuries")
    print(f"  inserted: initial={n_initial}, coingecko={n_cg}, bt={n_bt}")

    print("\nReconciling all tickers…")
    from treasury_signals.pipelines.btc_holdings_reconciler import reconcile_all
    stats = reconcile_all(send_alerts=False)  # silence alerts during backfill flood
    print(f"  reconcile_all stats: {stats}")
    print()
    print("Backfill complete. Divergent tickers were detected silently (send_alerts=False)")
    print("to avoid a Telegram flood. Inspect them via:")
    print("  SELECT ticker, source_values, spread_pct, resolved_source, resolved_value")
    print("    FROM btc_holdings_divergence_alerts WHERE status='open' ORDER BY spread_pct DESC;")


if __name__ == "__main__":
    main()
