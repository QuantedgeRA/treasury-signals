"""
cleanup_placeholders.py — Remove placeholder purchase entries
================================================================
Identifies and removes placeholder entries in confirmed_purchases that:
- Have exactly 1 entry for that ticker
- Have usd_amount = 0 (no real price data)
- Have filing_date = '2026-04-01' (fallback date)
- Have source containing 'Initial holdings' or 'Current holdings'

These were created by backfill_remaining_public.py when real purchase
history wasn't available. Deleting them lets us attempt real scraping.

Safety:
- Dry run mode by default
- Only deletes entries matching ALL placeholder criteria
- Preserves detailed multi-transaction histories (Strategy, Metaplanet, etc.)
- Preserves any entry with real USD data

Usage:
    python cleanup_placeholders.py          # Dry run
    python cleanup_placeholders.py --apply  # Actually delete
"""

import os
import sys
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def cleanup(dry_run=True):
    print(f"\n{'=' * 70}")
    print(f"Cleanup Placeholder Purchase Entries")
    print(f"{'=' * 70}")
    print(f"Mode: {'DRY RUN (preview only)' if dry_run else '⚡ LIVE — deleting entries'}")
    print(f"{'=' * 70}\n")

    # Step 1: Find tickers with exactly 1 entry AND that entry has $0 USD
    # We need to do this in Python since Supabase doesn't easily support HAVING

    # Get all purchases
    all_purchases = []
    offset = 0
    batch_size = 1000
    while True:
        result = supabase.table("confirmed_purchases").select(
            "purchase_id, ticker, company, btc_amount, usd_amount, filing_date, source"
        ).range(offset, offset + batch_size - 1).execute()

        if not result.data:
            break
        all_purchases.extend(result.data)
        if len(result.data) < batch_size:
            break
        offset += batch_size

    print(f"Total purchase entries in database: {len(all_purchases)}\n")

    # Group by ticker
    by_ticker = {}
    for p in all_purchases:
        tk = p.get("ticker", "").strip()
        if not tk:
            continue
        by_ticker.setdefault(tk, []).append(p)

    # Find placeholders: ticker has exactly 1 entry AND that entry has $0 USD AND matches placeholder criteria
    placeholders = []
    for ticker, entries in by_ticker.items():
        if len(entries) != 1:
            continue  # Multiple entries = real history, skip

        entry = entries[0]
        if entry.get("usd_amount", 0) != 0:
            continue  # Has USD data, not a placeholder

        # Check if it matches placeholder patterns
        source = (entry.get("source") or "").lower()
        filing_date = entry.get("filing_date", "")

        is_placeholder = (
            "initial holdings" in source or
            "current holdings" in source or
            "snapshot" in source or
            filing_date == "2026-04-01"
        )

        if is_placeholder:
            placeholders.append(entry)

    print(f"Placeholder entries to delete: {len(placeholders)}\n")

    if not placeholders:
        print("✅ No placeholder entries found!")
        return {"deleted": 0}

    # Preview
    print(f"{'Ticker':<14} {'Company':<35} {'BTC':>12} {'Date':<12} Source")
    print(f"{'─' * 14} {'─' * 35} {'─' * 12} {'─' * 12} {'─' * 30}")

    for p in placeholders[:30]:  # Preview first 30
        ticker = (p.get("ticker") or "")[:13]
        company = (p.get("company") or "")[:34]
        btc = p.get("btc_amount", 0)
        date = p.get("filing_date", "")
        source = (p.get("source") or "")[:30]
        print(f"{ticker:<14} {company:<35} {btc:>12,.1f} {date:<12} {source}")

    if len(placeholders) > 30:
        print(f"... and {len(placeholders) - 30} more")

    print()

    if dry_run:
        print(f"⚠️  DRY RUN — would delete {len(placeholders)} entries")
        print(f"   Run with --apply to actually delete.")
        return {"deleted": 0, "would_delete": len(placeholders)}

    # Confirm before deleting
    print(f"\n⚠️  About to DELETE {len(placeholders)} entries from confirmed_purchases.")
    confirm = input("Type 'DELETE' to confirm: ").strip()
    if confirm != "DELETE":
        print("Aborted.")
        return {"deleted": 0}

    # Delete them
    deleted = 0
    errors = 0
    for p in placeholders:
        try:
            supabase.table("confirmed_purchases").delete().eq(
                "purchase_id", p["purchase_id"]
            ).execute()
            deleted += 1
            if deleted % 20 == 0:
                print(f"  Deleted {deleted}/{len(placeholders)}...")
        except Exception as e:
            errors += 1
            print(f"  ❌ Failed to delete {p.get('purchase_id')}: {e}")

    print(f"\n{'=' * 70}")
    print(f"RESULTS: {deleted} deleted, {errors} errors")
    print(f"{'=' * 70}")

    return {"deleted": deleted, "errors": errors}


if __name__ == "__main__":
    apply = "--apply" in sys.argv

    if not apply:
        print("\n⚠️  DRY RUN MODE — no data will be deleted.")
        print("   Run with --apply to actually delete.\n")

    result = cleanup(dry_run=not apply)

    if not apply and result.get("would_delete", 0) > 0:
        print(f"\n💡 To delete these {result['would_delete']} placeholder entries, run:")
        print(f"   python cleanup_placeholders.py --apply")
