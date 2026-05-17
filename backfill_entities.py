"""
backfill_entities.py — Multi-Entity BTC Purchase History Backfill
===================================================================
One-time backfill for major BTC treasury entities (excluding Strategy,
which has its own dedicated backfill script).

Entities covered:
  - Tesla (TSLA) — 2 purchases, 2 sales
  - GameStop (GME) — 1 purchase
  - Block/Square (XYZ) — 2 major purchases + quarterly DCA
  - MARA Holdings (MARA) — major purchases + mining balance changes + sales
  - Metaplanet (3350.T) — quarterly purchases
  - Semler Scientific (SMLR) — multiple purchases
  - Riot Platforms (RIOT) — mining balance + purchases
  - Hut 8 Mining (HUT) — major purchase

Data sources: SEC 8-K filings, company press releases, BitcoinTreasuries.net,
CoinGecko, bitbo.io. Cross-referenced where possible.

Usage:
    python backfill_entities.py          # Dry run (preview only)
    python backfill_entities.py --apply  # Actually insert into database
"""

import os
import sys
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# ═══════════════════════════════════════════════════════════
# DATA FORMAT: (date, btc_amount, usd_millions, source_note)
# ═══════════════════════════════════════════════════════════

PURCHASES = {
    # ─── TESLA ───
    # Source: SEC 10-K/10-Q filings, CNBC, CoinDesk
    "TSLA": {
        "company": "Tesla",
        "purchases": [
            ("2021-01-31", 43000, 1500, "Initial BTC investment disclosed in SEC filing Feb 8, 2021"),
            ("2024-12-31", 1789, 0, "Added in Q4 2024 per SEC 10-K"),  # USD unknown, disclosed as BTC only
        ],
        "sales": [
            ("2021-03-31", 4320, 272, "Sold ~10% of holdings in Q1 2021 to test liquidity"),
            ("2022-06-30", 29160, 936, "Sold ~75% of remaining holdings in Q2 2022"),
        ],
    },

    # ─── GAMESTOP ───
    # Source: GameStop 8-K filing May 28, 2025; 10-K filed Mar 24, 2026
    "GME": {
        "company": "GameStop",
        "purchases": [
            ("2025-05-28", 4710, 500, "First BTC purchase; funded via $1.3B convertible notes"),
        ],
        "sales": [],
    },

    # ─── BLOCK (formerly Square) ───
    # Source: Block Bitcoin Blueprint (block.xyz), SEC filings, CoinDesk
    "XYZ": {
        "company": "Block",
        "purchases": [
            ("2020-10-07", 4709, 50, "Initial purchase at $10,618/BTC"),
            ("2021-02-23", 3318, 170, "Second major purchase at $51,236/BTC"),
            ("2024-03-31", 11, 0.7, "DCA program Q1 2024 (10% of BTC gross profit)"),
            ("2024-06-30", 173, 11.4, "DCA program Q2 2024"),
            ("2024-09-30", 152, 9.7, "DCA program Q3 2024; total cost basis $241.1M for 8,363 BTC"),
            ("2024-12-31", 340, 22, "Q4 2024 additions; total 8,883 BTC per earnings"),
            ("2025-06-30", 397, 0, "Q2 2025 additions (estimated from balance changes)"),
        ],
        "sales": [],
    },

    # ─── MARA HOLDINGS ───
    # Source: SEC filings, company press releases, bitbo.io
    # Note: MARA accumulates BTC via mining AND open market purchases.
    # Only explicit purchases and sales are tracked here, not mining production.
    "MARA": {
        "company": "MARA Holdings",
        "purchases": [
            ("2024-08-14", 4144, 249, "Open market purchase; total reached 24,962 BTC"),
            ("2024-09-03", 983, 59, "Continued accumulation Sep 2024"),
            ("2024-11-22", 7930, 618, "Major purchase Nov 2024 using convertible note proceeds"),
            ("2024-12-09", 6560, 630, "Purchased 11,774 BTC total in Dec; $1.1B via zero-coupon notes (split entry)"),
            ("2024-12-09", 5214, 470, "Remainder of Dec 2024 purchase batch"),
            ("2025-03-21", 5939, 500, "Q1 2025 accumulation"),
        ],
        "sales": [
            ("2026-03-26", 15133, 1100, "Sold to repurchase $1B convertible notes at 9% discount; cut debt by 30%"),
        ],
    },

    # ─── METAPLANET ───
    # Source: TDnet filings, company press releases, CoinGecko, Decrypt
    "3350.T": {
        "company": "Metaplanet",
        "purchases": [
            ("2024-04-08", 98, 6.5, "Initial BTC purchase; Japan hotel company pivots to BTC treasury"),
            ("2024-06-24", 160, 15.5, "Continued accumulation Q2 2024"),
            ("2024-08-12", 57, 3.4, "Additional purchase Aug 2024"),
            ("2024-10-07", 108, 6.9, "Q3 2024 purchase"),
            ("2024-10-28", 156, 10.6, "Oct 2024 purchase"),
            ("2024-11-18", 124, 11.6, "Nov 2024 purchase"),
            ("2024-11-28", 620, 60, "Major Nov purchase; reached ~1,762 BTC by year end"),
            ("2024-12-23", 620, 60, "Dec 2024 purchase batch"),
            ("2025-01-01", 4279, 380, "Massive Q1 start; $104,638 avg price"),
            ("2025-03-31", 5075, 405, "Q1 2026 total (announced Apr 2, 2026); $79,898 avg; total 40,177 BTC"),
            # Earlier 2025 purchases aggregated into quarterly totals where individual dates unavailable
            ("2025-04-30", 1241, 140, "Apr 2025 purchases (aggregated)"),
            ("2025-05-31", 1400, 150, "May 2025 purchases (aggregated)"),
            ("2025-06-23", 1111, 118, "Jun 2025; reached 11,111 BTC milestone"),
            ("2025-07-31", 2800, 330, "Jul 2025 purchases (aggregated)"),
            ("2025-08-31", 3500, 370, "Aug 2025 purchases (aggregated)"),
            ("2025-09-30", 5419, 632, "Sep 2025; reached 25,555 BTC; 5th largest globally"),
            ("2025-10-31", 2000, 200, "Oct 2025 (estimated from balance changes)"),
            ("2025-11-30", 2000, 200, "Nov 2025 (estimated from balance changes)"),
            ("2025-12-31", 4279, 447, "Dec 2025; 4,279 BTC at $104,638 avg; total 35,102 by year end"),
        ],
        "sales": [],
    },

    # ─── SEMLER SCIENTIFIC ───
    # Source: SEC 8-K filings, company press releases
    "SMLR": {
        "company": "Semler Scientific",
        "purchases": [
            ("2024-05-28", 581, 40, "Initial BTC treasury purchase"),
            ("2024-07-02", 247, 17, "Jul 2024 purchase"),
            ("2024-08-06", 101, 6, "Aug 2024 purchase"),
            ("2024-09-04", 83, 5, "Sep 2024 purchase"),
            ("2024-12-05", 211, 22, "Dec 2024 purchase; total reached ~1,873 BTC"),
            ("2025-01-14", 237, 23.3, "Jan 2025; post-merger with Strive announced"),
            ("2025-02-14", 871, 88.4, "Feb 2025 major purchase at $101,500 avg"),
        ],
        "sales": [],
    },

    # ─── HUT 8 MINING ───
    # Source: Press releases, SEC filings
    "HUT": {
        "company": "Hut 8 Mining",
        "purchases": [
            ("2024-12-19", 990, 100, "Strategic reserve purchase; ~$101,010/BTC"),
        ],
        "sales": [],
    },

    # ─── KULR TECHNOLOGY ───
    # Source: Press releases, SEC 8-K
    "KULR": {
        "company": "KULR Technology",
        "purchases": [
            ("2024-12-26", 217, 21, "Initial BTC treasury purchase at ~$96,774/BTC"),
            ("2025-01-06", 213, 21, "Second purchase; total ~430 BTC"),
        ],
        "sales": [],
    },

    # ─── STRIVE (formerly Semler merger) ───
    # Source: Press releases, SEC filings
    "ASST": {
        "company": "Strive",
        "purchases": [
            ("2025-12-31", 13131, 0, "Inherited from Semler merger + accumulation through 2025"),
            ("2026-03-11", 179, 13, "Purchased since last filing; total 13,311 BTC as of Mar 9, 2026"),
            ("2026-04-02", 113, 7.75, "April purchase at $68,584 avg; total 13,741 BTC"),
        ],
        "sales": [],
    },
}


def backfill(dry_run=True):
    """Insert multi-entity purchase history into confirmed_purchases and confirmed_sales."""
    print(f"\n{'=' * 70}")
    print(f"Multi-Entity BTC Purchase History Backfill")
    print(f"{'=' * 70}")
    print(f"Mode: {'DRY RUN (preview only)' if dry_run else '⚡ LIVE — inserting into database'}")
    print(f"{'=' * 70}\n")

    total_inserted = 0
    total_skipped = 0
    total_errors = 0
    total_sales_inserted = 0

    for ticker, entity in PURCHASES.items():
        company = entity["company"]
        purchases = entity.get("purchases", [])
        sales = entity.get("sales", [])

        print(f"\n{'─' * 50}")
        print(f"  {company} ({ticker})")
        print(f"  {len(purchases)} purchases, {len(sales)} sales")
        print(f"{'─' * 50}")

        # Check existing
        existing_keys = set()
        try:
            result = supabase.table("confirmed_purchases").select("purchase_id, filing_date, btc_amount").or_(f"ticker.eq.{ticker},ticker.eq.{ticker}.US").execute()
            if result.data:
                for p in result.data:
                    existing_keys.add(f"{p.get('filing_date', '')}_{p.get('btc_amount', 0)}")
        except:
            pass

        existing_sale_keys = set()
        try:
            result = supabase.table("confirmed_sales").select("sale_id, filing_date, btc_amount").or_(f"ticker.eq.{ticker},ticker.eq.{ticker}.US").execute()
            if result.data:
                for s in result.data:
                    existing_sale_keys.add(f"{s.get('filing_date', '')}_{s.get('btc_amount', 0)}")
        except:
            pass

        # Insert purchases
        for date, btc, usd_m, note in purchases:
            usd = int(usd_m * 1_000_000)
            price_per_btc = round(usd / btc) if btc > 0 and usd > 0 else 0
            key = f"{date}_{btc}"

            if key in existing_keys:
                total_skipped += 1
                continue

            purchase_id = f"backfill_{ticker}_{date}_{btc}"

            if dry_run:
                print(f"    [DRY] {date} | +{btc:>7,} BTC | ${usd_m:>8,.1f}M | ${price_per_btc:>7,}/BTC | {note[:50]}")
                total_inserted += 1
                continue

            try:
                supabase.table("confirmed_purchases").upsert({
                    "purchase_id": purchase_id,
                    "company": company,
                    "ticker": ticker,
                    "btc_amount": btc,
                    "usd_amount": usd,
                    "price_per_btc": price_per_btc,
                    "filing_date": date,
                    "filing_url": "",
                    "was_predicted": False,
                    "source": f"Historical backfill ({note[:80]})",
                }, on_conflict="purchase_id").execute()
                total_inserted += 1
                print(f"    ✅ {date} | +{btc:>7,} BTC | ${usd_m:>8,.1f}M | {note[:50]}")
            except Exception as e:
                total_errors += 1
                print(f"    ❌ {date} | +{btc:,} BTC — ERROR: {e}")

        # Insert sales
        for date, btc, usd_m, note in sales:
            usd = int(usd_m * 1_000_000)
            price_per_btc = round(usd / btc) if btc > 0 and usd > 0 else 0
            key = f"{date}_{btc}"

            if key in existing_sale_keys:
                total_skipped += 1
                continue

            sale_id = f"sale_backfill_{ticker}_{date}_{btc}"

            if dry_run:
                print(f"    [DRY SALE] {date} | -{btc:>7,} BTC | ${usd_m:>8,.1f}M | {note[:50]}")
                total_sales_inserted += 1
                continue

            try:
                supabase.table("confirmed_sales").upsert({
                    "sale_id": sale_id,
                    "company": company,
                    "ticker": ticker,
                    "btc_amount": btc,
                    "usd_amount": usd,
                    "price_per_btc": price_per_btc,
                    "filing_date": date,
                    "filing_url": "",
                    "source": f"Historical backfill ({note[:80]})",
                }, on_conflict="sale_id").execute()
                total_sales_inserted += 1
                print(f"    ✅ SALE {date} | -{btc:>7,} BTC | ${usd_m:>8,.1f}M | {note[:50]}")
            except Exception as e:
                total_errors += 1
                print(f"    ❌ SALE {date} | -{btc:,} BTC — ERROR: {e}")

    print(f"\n{'=' * 70}")
    print(f"RESULTS:")
    print(f"  Purchases inserted: {total_inserted}")
    print(f"  Sales inserted:     {total_sales_inserted}")
    print(f"  Skipped (existing): {total_skipped}")
    print(f"  Errors:             {total_errors}")
    print(f"  Entities:           {len(PURCHASES)}")
    print(f"{'=' * 70}")

    return {"purchases": total_inserted, "sales": total_sales_inserted, "skipped": total_skipped, "errors": total_errors}


if __name__ == "__main__":
    apply = "--apply" in sys.argv

    if not apply:
        print("\n⚠️  DRY RUN MODE — no data will be written.")
        print("   Run with --apply to insert into database.\n")

    result = backfill(dry_run=not apply)

    if not apply and (result["purchases"] > 0 or result["sales"] > 0):
        print(f"\n💡 To apply, run:")
        print(f"   python backfill_entities.py --apply")
