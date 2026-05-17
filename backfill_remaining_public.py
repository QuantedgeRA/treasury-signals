"""
backfill_remaining_public.py — Fill in ALL remaining public companies
=======================================================================
For every public company in treasury_companies that does NOT already have
records in confirmed_purchases, creates a single "initial holdings" entry
using their current BTC balance from the database.

This ensures EVERY public company appears in the purchase history.
The 48+ entities from previous backfill scripts keep their detailed
multi-transaction histories — this only fills the gaps.

Safety:
- Only inserts for companies with ZERO existing confirmed_purchases
- Uses upsert with unique purchase_id (safe to re-run)
- Skips garbled/non-ASCII company names
- Skips zero-balance entries
- Dry run mode by default

Usage:
    python backfill_remaining_public.py          # Dry run
    python backfill_remaining_public.py --apply  # Insert into database
"""

import os
import sys
import re
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def normalize_ticker(t):
    """Strip exchange suffixes for matching."""
    if not t:
        return ""
    return re.sub(r'\.[A-Z]+$', '', t.strip(), flags=re.IGNORECASE).upper()


def get_public_companies():
    """Fetch all public companies with BTC holdings."""
    result = supabase.table("treasury_companies").select(
        "id, company, ticker, btc_holdings, country, sector, entity_type, source_updated_at"
    ).eq("entity_type", "public_company").gt("btc_holdings", 0).order(
        "btc_holdings", desc=True
    ).execute()
    return result.data or []


def get_covered_tickers():
    """Get set of normalized tickers that already have confirmed_purchases."""
    result = supabase.table("confirmed_purchases").select("ticker").execute()
    tickers = set()
    if result.data:
        for row in result.data:
            tk = (row.get("ticker") or "").strip()
            if tk:
                tickers.add(tk.upper())
                tickers.add(normalize_ticker(tk))
    return tickers


def backfill(dry_run=True):
    print(f"\n{'=' * 70}")
    print(f"Remaining Public Companies — Initial Holdings Backfill")
    print(f"{'=' * 70}")
    print(f"Mode: {'DRY RUN (preview only)' if dry_run else '⚡ LIVE — inserting into database'}")
    print(f"{'=' * 70}\n")

    companies = get_public_companies()
    covered = get_covered_tickers()

    print(f"Total public companies with BTC: {len(companies)}")
    print(f"Already have purchase records: {len(covered)} unique tickers\n")

    # Find companies without existing records
    missing = []
    already_covered = 0
    for c in companies:
        ticker = (c.get("ticker") or "").strip()
        if not ticker:
            continue

        raw_upper = ticker.upper()
        clean = normalize_ticker(ticker)

        if raw_upper in covered or clean in covered:
            already_covered += 1
            continue

        missing.append(c)

    print(f"Already covered: {already_covered}")
    print(f"Need backfill:   {len(missing)}")
    print(f"{'─' * 70}\n")

    if not missing:
        print("✅ All public companies already have purchase records!")
        return {"inserted": 0, "skipped": 0, "errors": 0}

    inserted = 0
    skipped = 0
    errors = 0

    for c in missing:
        ticker = (c.get("ticker") or "").strip()
        company_name = (c.get("company") or "").strip()
        btc = float(c.get("btc_holdings", 0) or 0)
        country = (c.get("country") or "")[:4]

        # Skip garbled names (non-ASCII artifacts from scraping)
        if company_name and not re.match(r'^[A-Za-z0-9\s\(\)]', company_name):
            skipped += 1
            continue

        # Skip tiny holdings
        if btc < 0.5:
            skipped += 1
            continue

        # Determine filing date — use source_updated_at or fallback
        filing_date = None
        if c.get("source_updated_at"):
            try:
                filing_date = str(c["source_updated_at"])[:10]
                # Validate it looks like a date
                if not re.match(r'^\d{4}-\d{2}-\d{2}$', filing_date):
                    filing_date = None
            except:
                filing_date = None
        if not filing_date:
            filing_date = "2026-04-01"  # Approximate current date

        # Create unique purchase_id
        btc_int = int(btc) if btc == int(btc) else round(btc, 1)
        purchase_id = f"initial_{ticker}_{btc_int}"

        if dry_run:
            print(f"  [DRY] {ticker:<14} | {company_name[:35]:<35} | {btc:>10,.1f} BTC | {country} | {filing_date}")
            inserted += 1
            continue

        try:
            supabase.table("confirmed_purchases").upsert({
                "purchase_id": purchase_id,
                "company": company_name,
                "ticker": ticker,
                "btc_amount": btc,
                "usd_amount": 0,
                "price_per_btc": 0,
                "filing_date": filing_date,
                "filing_url": "",
                "was_predicted": False,
                "source": "Initial holdings from treasury_companies (CoinGecko/BitcoinTreasuries.net)",
            }, on_conflict="purchase_id").execute()
            inserted += 1
            print(f"  ✅ {ticker:<14} | {company_name[:35]:<35} | {btc:>10,.1f} BTC")
        except Exception as e:
            errors += 1
            print(f"  ❌ {ticker:<14} | {company_name[:35]:<35} — ERROR: {e}")

    print(f"\n{'=' * 70}")
    print(f"RESULTS:")
    print(f"  Inserted:           {inserted}")
    print(f"  Skipped (garbled):  {skipped}")
    print(f"  Errors:             {errors}")
    print(f"  Previously covered: {already_covered}")
    print(f"  Total public cos:   {len(companies)}")
    print(f"{'=' * 70}")

    return {"inserted": inserted, "skipped": skipped, "errors": errors}


if __name__ == "__main__":
    apply = "--apply" in sys.argv

    if not apply:
        print("\n⚠️  DRY RUN MODE — no data will be written.")
        print("   Run with --apply to insert into database.\n")

    result = backfill(dry_run=not apply)

    if not apply and result["inserted"] > 0:
        print(f"\n💡 To apply these {result['inserted']} entries, run:")
        print(f"   python backfill_remaining_public.py --apply")
