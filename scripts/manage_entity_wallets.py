"""
Manage entity_wallets — seed verified addresses + refresh observed balances.

DESIGN INTENT
=============
Per [[wallet_attribution_design]], wallet attribution requires PRIMARY-SOURCE
citation for confidence > 95. This script is structured so curation happens
with explicit evidence per address; you can NOT add a high-confidence row
without filling in source_citation.

Two modes:

  --seed     Read CURATED_WALLETS from this file and upsert. Idempotent.
             The CURATED_WALLETS list is intentionally EMPTY at MVP ship —
             see "How to add an address" below for how to populate.

  --verify   For every is_active=true row, query blockchain.com for the
             current balance and update observed_balance + balance_checked_at.
             Pure read on chain; never modifies confidence_score or method.

  (no args)  Dry-run: print what each mode would do.

Usage:
    python scripts/manage_entity_wallets.py            # dry-run summary
    python scripts/manage_entity_wallets.py --seed     # upsert curated
    python scripts/manage_entity_wallets.py --verify   # refresh balances


HOW TO ADD AN ADDRESS (the disciplined process)
================================================
1. Find a primary source: an SEC 8-K, a company IR page, a govt-published
   list (bitcoin.gob.sv, US Marshals auction docs, etc.).
2. Verify the address actually exists on-chain by pasting into
   blockchain.com/btc/address/<addr> — must return a valid page.
3. Add a dict to CURATED_WALLETS below with:
     - ticker: matches treasury_companies.ticker (the canonical bare form)
     - wallet_address: the FULL address (34-62 chars for BTC)
     - confidence_score: see methodology below
     - attribution_method: one of the documented values
     - source_citation: URL of the primary source — REQUIRED for conf > 95
     - first_seen: date the address first appeared on-chain (optional)
     - notes: anything that helps the next reader — e.g. "address #3 of
       MSTR's tranche disclosed 2024-Q1 10-Q p47"
4. Re-run with --seed.

CONFIDENCE METHODOLOGY (strict)
================================
  100        Signed SEC filing with explicit wallet disclosure
  90-99      Self-reported IR page (verified) OR govt-published list
  70-89      Single-source cluster expansion (Tier 2, not yet implemented)
  50-69      Heuristic match (Tier 2)
  <50        Don't surface; we don't guess

  HARD RULE: confidence > 95 requires non-empty source_citation.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
from supabase import create_client

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
if not (SUPABASE_URL and SUPABASE_KEY):
    sys.exit("SUPABASE_URL + SUPABASE_KEY required in .env")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ─── CURATED WALLETS (manually verified) ─────────────────────────────
#
# THIS LIST IS INTENTIONALLY EMPTY AT MVP SHIP.
#
# Per [[wallet_attribution_design]], we never fabricate addresses or
# claim attributions without primary-source citation. Populating this
# list requires manual research per address — see "How to add an
# address" in the module docstring above.
#
# Recommended first batch of sources to mine:
#   - Strategy (MSTR): their 10-Q + 10-K filings sometimes disclose
#     wallet addresses. SEC EDGAR full-text search "bitcoin wallet"
#     for cik 0001050446.
#   - El Salvador: bitcoin.gob.sv publishes the country's holdings
#     with at least one wallet address visible on the dashboard.
#   - US Marshals: court documents for seizure auctions disclose
#     addresses being sold (post-sale).
#   - Tesla: 2021 10-K filing mentioned BTC purchase; some wallet
#     attribution sources have cited specific addresses.
#   - bitcointreasuries.net: a few entities have published-address
#     columns; cite the BT page URL.
#
# An empty list is the HONEST starting point. Better empty than
# fabricated.

CURATED_WALLETS: list[dict] = [
    # Example shape (DO NOT add real entries without primary-source
    # citation):
    #
    # {
    #     "ticker": "MSTR",
    #     "entity_name": "Strategy (MicroStrategy)",
    #     "wallet_address": "bc1q...",          # full address
    #     "blockchain": "bitcoin",
    #     "confidence_score": 95,
    #     "attribution_method": "sec_filing",
    #     "source_citation": "https://www.sec.gov/Archives/edgar/data/...",
    #     "first_seen": "2024-03-15",
    #     "notes": "Disclosed in 2024-Q1 10-Q, page 47, address #3 of cold storage tranche",
    # },
]

MAX_BALANCE_FETCHES_PER_RUN = 100
BLOCKCHAIN_INFO_THROTTLE = 0.5  # seconds between requests


def _validate(row: dict) -> tuple[bool, str]:
    """Enforce the methodology invariants before allowing a row to land."""
    required = ["ticker", "wallet_address", "confidence_score", "attribution_method"]
    for f in required:
        if not row.get(f):
            return False, f"missing required field: {f}"
    if not isinstance(row["confidence_score"], int):
        return False, "confidence_score must be int 0-100"
    if not (0 <= row["confidence_score"] <= 100):
        return False, "confidence_score out of range"
    if row["confidence_score"] > 95 and not row.get("source_citation"):
        return False, "confidence > 95 requires source_citation (per strict honesty bound)"
    valid_methods = {
        "public_disclosure", "sec_filing", "company_irpage", "gov_published",
        "press_release", "bitcoin_treasuries",
        "cluster_expansion", "change_addr",  # Tier 2 (not yet active)
    }
    if row["attribution_method"] not in valid_methods:
        return False, f"attribution_method must be one of {valid_methods}"
    return True, ""


def cmd_seed(apply: bool):
    print(f"[seed] {len(CURATED_WALLETS)} entries in CURATED_WALLETS")
    if not CURATED_WALLETS:
        print("[seed] List is empty by design — populate via the process documented in the module docstring.")
        return

    valid = []
    for row in CURATED_WALLETS:
        ok, why = _validate(row)
        if not ok:
            print(f"  REJECT  {row.get('wallet_address', '?')}: {why}")
            continue
        valid.append(row)
    print(f"[seed] {len(valid)} valid entries after validation")

    if not apply:
        print("[seed] Dry-run. Re-run with --seed to upsert.")
        return

    ok = fail = 0
    for row in valid:
        try:
            supabase.table("entity_wallets").upsert(row, on_conflict="wallet_address").execute()
            ok += 1
        except Exception as e:
            fail += 1
            print(f"  upsert failed for {row.get('wallet_address')}: {e}")
    print(f"[seed] Done: {ok} OK, {fail} failed.")


def _fetch_btc_balance(address: str) -> float | None:
    """Query blockchain.com for the address's current confirmed balance (in BTC).
    Returns None on failure (network, malformed address, etc.)."""
    try:
        time.sleep(BLOCKCHAIN_INFO_THROTTLE)
        resp = requests.get(
            f"https://blockchain.info/q/addressbalance/{address}",
            headers={"User-Agent": "TreasurySignalIntelligence/1.0"},
            timeout=15,
        )
        if not resp.ok:
            return None
        sats = int(resp.text.strip())
        return sats / 1e8
    except Exception:
        return None


def cmd_verify(apply: bool):
    try:
        res = (
            supabase.table("entity_wallets")
            .select("id, ticker, wallet_address, blockchain")
            .eq("is_active", True)
            .eq("blockchain", "bitcoin")
            .limit(MAX_BALANCE_FETCHES_PER_RUN)
            .execute()
        )
    except Exception as e:
        print(f"[verify] fetch failed: {e}")
        return

    rows = res.data or []
    print(f"[verify] {len(rows)} active BTC wallets to check")

    updates = []
    for r in rows:
        bal = _fetch_btc_balance(r["wallet_address"])
        if bal is None:
            print(f"  miss  {r['ticker']:<10} {r['wallet_address'][:24]}... (network or invalid)")
            continue
        print(f"  OK    {r['ticker']:<10} {r['wallet_address'][:24]}... = {bal:,.4f} BTC")
        updates.append({"id": r["id"], "observed_balance": bal})

    if not apply:
        print(f"[verify] Dry-run. Re-run with --verify to write {len(updates)} balance updates.")
        return

    from datetime import datetime
    now_iso = datetime.utcnow().isoformat()
    ok = fail = 0
    for u in updates:
        try:
            supabase.table("entity_wallets").update({
                "observed_balance": u["observed_balance"],
                "balance_checked_at": now_iso,
            }).eq("id", u["id"]).execute()
            ok += 1
        except Exception as e:
            fail += 1
            print(f"  update {u['id']} failed: {e}")
    print(f"[verify] Done: {ok} OK, {fail} failed.")


def main():
    seed_flag = "--seed" in sys.argv
    verify_flag = "--verify" in sys.argv
    apply = seed_flag or verify_flag

    if not (seed_flag or verify_flag):
        print("Mode: DRY-RUN (pass --seed and/or --verify to write)")
        print("=" * 70)
        cmd_seed(apply=False)
        print()
        cmd_verify(apply=False)
        return

    if seed_flag:
        cmd_seed(apply=True)
    if verify_flag:
        cmd_verify(apply=True)


if __name__ == "__main__":
    main()
