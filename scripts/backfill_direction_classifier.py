"""
One-shot: backfill direction classifier across historical confirmed_purchases
+ propagate the results into backtest_reactions.

WHY THIS EXISTS
===============
The direction classifier (pipelines/direction_classifier.py, migration
0013) only runs forward — on each new EDGAR filing as edgar_realtime
detects it. Historical confirmed_purchases (455 rows as of 2026-05-23)
have NULL direction. That means the killer chart on /backtest — the
direction-stratified stats ("pure buys +X%, raise-then-buy -Y%") —
renders as a single "Unclear" bucket and doesn't actually demonstrate
the alpha the strategic review called out.

This script:
  1. Pulls confirmed_purchases with NULL direction + non-empty filing_url
  2. Re-fetches each filing's text (cached in memory by ticker_filing_date
     so duplicate URLs are only hit once)
  3. Runs classify_direction()
  4. Updates confirmed_purchases.direction + direction_confidence
  5. Propagates into backtest_reactions for the matching (ticker, filing_date)

Approx 450 unique (ticker, filing_date) groups → ~8 min runtime
respecting EDGAR's 10-req/sec limit (we sleep 0.5s between fetches).

Usage:
    python scripts/backfill_direction_classifier.py            # dry-run
    python scripts/backfill_direction_classifier.py --apply    # write back

Idempotent: re-running only touches rows that still have NULL direction.
"""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
from supabase import create_client

# Allow imports when invoked as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from treasury_signals.pipelines.direction_classifier import classify_direction

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
if not (SUPABASE_URL and SUPABASE_KEY):
    sys.exit("SUPABASE_URL + SUPABASE_KEY required in .env")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
apply = "--apply" in sys.argv

HEADERS = {
    "User-Agent": "TreasurySignalIntelligence admin@quantedgeriskadvisory.com",
    "Accept": "text/html",
}

MAX_FETCHES_PER_RUN = 500
EDGAR_THROTTLE_SECONDS = 0.5

print(f"Mode: {'APPLYING' if apply else 'DRY-RUN (pass --apply to write)'}")
print("=" * 70)


def _fetch_filing_text(filing_url: str) -> str:
    """Same logic as edgar_realtime._fetch_filing_text. HTML-strip + cap."""
    if not filing_url:
        return ""
    try:
        time.sleep(EDGAR_THROTTLE_SECONDS)
        resp = requests.get(filing_url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        text = re.sub(r"<[^>]+>", " ", resp.text)
        text = re.sub(r"\s+", " ", text)
        return text[:50000]
    except Exception as e:
        print(f"  fetch failed for {filing_url[:80]}: {e}")
        return ""


def _fetch_uncllassified() -> list[dict]:
    """confirmed_purchases with NULL direction in the last 730 days."""
    from datetime import datetime, timedelta
    cutoff = (datetime.utcnow() - timedelta(days=730)).strftime("%Y-%m-%d")
    try:
        res = (
            supabase.table("confirmed_purchases")
            .select("id, ticker, company, filing_date, filing_url, direction")
            .gte("filing_date", cutoff)
            .is_("direction", "null")
            .order("filing_date", desc=True)
            .limit(MAX_FETCHES_PER_RUN)
            .execute()
        )
        return [r for r in (res.data or []) if r.get("filing_url")]
    except Exception as e:
        print(f"  ERROR fetching: {e}")
        return []


def main():
    rows = _fetch_uncllassified()
    print(f"Unclassified confirmed_purchases (with filing_url): {len(rows)}")
    if not rows:
        print("Nothing to backfill.")
        return

    # Dedupe by filing_url so we don't re-fetch the same URL twice. Some
    # purchases share a filing_url when a company files multiple BTC
    # events in one 8-K.
    seen_urls: dict[str, dict] = {}
    for r in rows:
        u = r.get("filing_url", "")
        if u and u not in seen_urls:
            seen_urls[u] = {"url": u, "result": None}
    print(f"Unique filing URLs to fetch: {len(seen_urls)}")

    # Fetch + classify each unique URL
    fetched = 0
    classified = 0
    by_dir: dict[str, int] = {}
    for i, (url, slot) in enumerate(seen_urls.items()):
        if i and i % 50 == 0:
            print(f"  ...processed {i}/{len(seen_urls)} URLs")
        text = _fetch_filing_text(url)
        if not text:
            continue
        fetched += 1
        try:
            res = classify_direction(text)
            slot["result"] = res
            classified += 1
            by_dir[res.direction] = by_dir.get(res.direction, 0) + 1
        except Exception as e:
            print(f"  classify failed for {url[:60]}: {e}")

    print()
    print(f"Fetched: {fetched} URLs, classified: {classified}")
    print(f"Distribution: {by_dir}")

    if not apply:
        print()
        print("Dry-run. Re-run with --apply to write.")
        for r in rows[:5]:
            u = r.get("filing_url", "")
            res = seen_urls.get(u, {}).get("result")
            if res:
                print(f"  sample {r['ticker']:<10} {r['filing_date']} -> {res.direction} (conf={res.confidence})")
        return

    # Write back: for each purchase, look up its URL's result + update.
    print()
    print("Writing back to confirmed_purchases + backtest_reactions...")
    ok = fail = 0
    bt_updated = 0
    # Build (ticker, filing_date) -> result so backtest update is clean
    bt_map: dict[tuple[str, str], object] = {}
    for r in rows:
        u = r.get("filing_url", "")
        res = seen_urls.get(u, {}).get("result")
        if not res or res.direction is None:
            continue
        try:
            supabase.table("confirmed_purchases").update({
                "direction": res.direction,
                "direction_confidence": int(res.confidence) if res.confidence is not None else None,
            }).eq("id", r["id"]).execute()
            ok += 1
            bt_map[(r["ticker"], r["filing_date"])] = res
        except Exception as e:
            fail += 1
            print(f"  update purchase {r['id']} failed: {e}")

    # Update backtest_reactions (ticker may have .US suffix in some rows)
    for (ticker, filing_date), res in bt_map.items():
        # Strip .US to match the canonical form the backtest table uses
        t_clean = ticker.upper()
        if t_clean.endswith(".US") and len(t_clean) > 3:
            t_clean = t_clean[:-3]
        try:
            r2 = supabase.table("backtest_reactions").update({
                "direction": res.direction,
                "direction_confidence": int(res.confidence) if res.confidence is not None else None,
            }).eq("ticker", t_clean).eq("filing_date", filing_date).execute()
            if r2.data:
                bt_updated += len(r2.data)
        except Exception as e:
            print(f"  bt update {t_clean}/{filing_date} failed: {e}")

    print()
    print(f"Updated confirmed_purchases: {ok} OK, {fail} failed")
    print(f"Propagated to backtest_reactions: {bt_updated} rows")


if __name__ == "__main__":
    main()
