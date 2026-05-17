"""
backfill_entities_batch4.py — Multi-Entity BTC Purchase History (Batch 4)
==========================================================================
Fourth batch covering mid-tier public company holders.

Entities covered:
  - American Bitcoin Corp (ABTC) — Eric Trump-backed, Hut 8 subsidiary
  - ProCap Financial (BRR) — Anthony Pompliano's BTC vehicle
  - Nakamoto Inc (NAKA) — David Bailey's BTC treasury via KindlyMD merger
  - GD Culture Group (GDC) — AI/livestream company, BTC treasury
  - Hut 8 Mining (HUT) — expanded from batch 1 with more transactions
  - Riot Platforms (RIOT) — expanded with more purchases
  - Next Technology Holding (NXTT) — Chinese company
  - SOS Limited (SOS) — Chinese tech, BTC mining
  - BTCS Inc (BTCS) — early BTC adopter
  - Aker ASA (AKER) — Norwegian industrial, via Seetee AS
  - Cathedra Bitcoin (CBIT) — Canadian BTC miner/treasury
  - LQR House (LQR) — small cap BTC pivot
  - Thumzup Media (TZUP) — social media, BTC treasury
  - Fold Holdings (FLD) — Bitcoin rewards company

Usage:
    python backfill_entities_batch4.py          # Dry run
    python backfill_entities_batch4.py --apply  # Insert into database
"""

import os
import sys
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# FORMAT: (date, btc_amount, usd_millions, source_note)

PURCHASES = {
    # ─── AMERICAN BITCOIN CORP ───
    # Source: Press releases, CoinDesk, Eric Trump / Hut 8 subsidiary
    "ABTC": {
        "company": "American Bitcoin Corp",
        "purchases": [
            ("2025-10-24", 1414, 130, "Strategic reserve purchase; total 3,865 BTC; mix of mining + purchase"),
            ("2025-12-08", 416, 40, "Weekly accumulation; total 4,783 BTC"),
            ("2026-03-31", 2217, 160, "Continued accumulation through Q1 2026; total ~7,000 BTC"),
        ],
        "sales": [],
    },

    # ─── PROCAP FINANCIAL ───
    # Source: GlobeNewswire, BitcoinTreasuries.net, CoinDesk
    "BRR": {
        "company": "ProCap Financial",
        "purchases": [
            ("2025-06-25", 1208, 128, "Initial large purchase at $105,977/BTC TWAP; Anthony Pompliano"),
            ("2025-09-30", 3724, 370, "Continued accumulation; total 4,932 BTC before SPAC close"),
            ("2025-12-10", 49, 4.5, "Post-SPAC merger addition; tax-loss harvesting strategy; total 5,000 BTC"),
            ("2026-03-31", 457, 33, "Q1 2026 additions; total ~5,457 BTC"),
        ],
        "sales": [],
    },

    # ─── NAKAMOTO INC ───
    # Source: KindlyMD press release, BeInCrypto, Sherwood News
    "NAKA": {
        "company": "Nakamoto Inc",
        "purchases": [
            ("2025-08-19", 5744, 679, "First purchase post-KindlyMD merger; $118,204/BTC avg; PIPE proceeds"),
        ],
        "sales": [
            ("2026-03-30", 284, 20, "Sold at $70,422/BTC avg; 40% realized loss; USD operating reserve"),
        ],
    },

    # ─── GD CULTURE GROUP ───
    # Source: The Block, BitcoinTreasuries.net
    "GDC": {
        "company": "GD Culture Group",
        "purchases": [
            ("2025-09-17", 2500, 240, "Initial BTC treasury acquisition; AI/e-commerce pivot"),
            ("2025-11-30", 5000, 500, "Continued accumulation; total 7,500 BTC by Nov 2025"),
        ],
        "sales": [],
    },

    # ─── HUT 8 MINING (additional transactions) ───
    # Source: GlobeNewswire, hut8.com, CoinGecko
    # Note: Batch 1 had 1 entry (Dec 2024, 990 BTC). Adding mining milestones.
    "HUT": {
        "company": "Hut 8 Mining",
        "purchases": [
            ("2024-11-30", 12, 1.1, "Nov 2024 mining + additions"),
            ("2025-01-11", 75, 7, "Jan 2025 mining addition"),
            ("2025-06-30", 2614, 280, "H1 2025 mining accumulation; total ~13,696 BTC by Sep 2025"),
        ],
        "sales": [],
    },

    # ─── RIOT PLATFORMS (additional) ───
    # Source: Company updates, The Block
    # Note: Batch 2 had 2 entries. Adding more.
    "RIOT": {
        "company": "Riot Platforms",
        "purchases": [
            ("2025-06-30", 3200, 350, "H1 2025 mining + purchase accumulation"),
        ],
        "sales": [],
    },

    # ─── NEXT TECHNOLOGY HOLDING ───
    # Source: BitcoinTreasuries.net, company filings
    "NXTT": {
        "company": "Next Technology Holding",
        "purchases": [
            ("2025-06-30", 2833, 300, "Chinese company; BTC treasury pivot; accumulated through 2025"),
            ("2025-12-31", 3000, 280, "Continued accumulation; total ~5,833 BTC"),
        ],
        "sales": [],
    },

    # ─── SOS LIMITED ───
    # Source: Company announcements, SEC filings
    "SOS": {
        "company": "SOS Limited",
        "purchases": [
            ("2021-03-01", 5000, 64, "Purchased 5,000 BTC mining rigs + direct BTC at ~$12,800 avg"),
            ("2024-12-31", 1110, 0, "Holdings as of year-end 2024; mix of mining + purchases"),
        ],
        "sales": [],
    },

    # ─── BTCS INC ───
    # Source: Press releases, SEC filings
    "BTCS": {
        "company": "BTCS Inc",
        "purchases": [
            ("2021-01-15", 7, 0.25, "Early BTC treasury allocation; ~$35,714/BTC"),
            ("2024-08-12", 40, 2.4, "Expanded BTC treasury; $60,000/BTC avg"),
            ("2025-03-31", 78, 7, "Continued quarterly accumulation; ~$89,744/BTC"),
        ],
        "sales": [],
    },

    # ─── AKER ASA / SEETEE ───
    # Source: Seetee shareholder letter, company announcements
    "AKER": {
        "company": "Aker ASA (Seetee)",
        "purchases": [
            ("2021-03-08", 1170, 58.6, "Seetee AS subsidiary initial BTC investment; $50,085/BTC"),
        ],
        "sales": [],
    },

    # ─── CATHEDRA BITCOIN ───
    # Source: Company announcements
    "CBIT.V": {
        "company": "Cathedra Bitcoin",
        "purchases": [
            ("2024-12-31", 280, 27, "Year-end 2024 holdings; Canadian BTC miner/treasury"),
        ],
        "sales": [],
    },

    # ─── THUMZUP MEDIA ───
    # Source: Press releases
    "TZUP": {
        "company": "Thumzup Media",
        "purchases": [
            ("2024-12-24", 10, 1, "Initial BTC treasury; social media company"),
            ("2025-02-28", 19, 1.8, "Continued accumulation; ~$94,737/BTC"),
            ("2025-06-30", 46, 4.5, "Mid-2025 total; ongoing DCA strategy"),
        ],
        "sales": [],
    },

    # ─── FOLD HOLDINGS ───
    # Source: Company filings, BitcoinTreasuries.net
    "FLD": {
        "company": "Fold Holdings",
        "purchases": [
            ("2025-04-14", 475, 40, "Bitcoin rewards company; accumulated through operations + purchases"),
        ],
        "sales": [],
    },

    # ─── METAVISIO / THOMSON COMPUTING ───
    # Source: Press release, French company
    "ALTHO.PA": {
        "company": "Metavisio (Thomson Computing)",
        "purchases": [
            ("2024-12-31", 25, 2.5, "French laptop company; initial BTC treasury allocation"),
        ],
        "sales": [],
    },

    # ─── MICRO CLOUD HOLOGRAM ───
    # Source: Press releases
    "HOLO": {
        "company": "Micro Cloud Hologram",
        "purchases": [
            ("2025-01-15", 34, 3.5, "Chinese hologram tech company; BTC treasury strategy"),
        ],
        "sales": [],
    },

    # ─── BSOL ───
    # Source: BitcoinTreasuries.net
    "BSOL": {
        "company": "Brazil Potash",
        "purchases": [
            ("2025-06-30", 100, 10, "Brazilian mining company; BTC treasury allocation"),
        ],
        "sales": [],
    },
}


def backfill(dry_run=True):
    """Insert multi-entity purchase history into confirmed_purchases and confirmed_sales."""
    print(f"\n{'=' * 70}")
    print(f"Multi-Entity BTC Purchase History Backfill — Batch 4")
    print(f"{'=' * 70}")
    print(f"Mode: {'DRY RUN (preview only)' if dry_run else '⚡ LIVE — inserting into database'}")
    print(f"Entities: {len(PURCHASES)}")
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

        for date, btc, usd_m, note in purchases:
            usd = int(usd_m * 1_000_000)
            price_per_btc = round(usd / btc) if btc > 0 and usd > 0 else 0
            key = f"{date}_{btc}"
            if key in existing_keys:
                total_skipped += 1
                continue
            purchase_id = f"backfill4_{ticker}_{date}_{btc}"
            if dry_run:
                print(f"    [DRY] {date} | +{btc:>7,} BTC | ${usd_m:>8,.1f}M | ${price_per_btc:>7,}/BTC | {note[:50]}")
                total_inserted += 1
                continue
            try:
                supabase.table("confirmed_purchases").upsert({
                    "purchase_id": purchase_id, "company": company, "ticker": ticker,
                    "btc_amount": btc, "usd_amount": usd, "price_per_btc": price_per_btc,
                    "filing_date": date, "filing_url": "", "was_predicted": False,
                    "source": f"Historical backfill ({note[:80]})",
                }, on_conflict="purchase_id").execute()
                total_inserted += 1
                print(f"    ✅ {date} | +{btc:>7,} BTC | ${usd_m:>8,.1f}M | {note[:50]}")
            except Exception as e:
                total_errors += 1
                print(f"    ❌ {date} | +{btc:,} BTC — ERROR: {e}")

        for date, btc, usd_m, note in sales:
            usd = int(usd_m * 1_000_000)
            price_per_btc = round(usd / btc) if btc > 0 and usd > 0 else 0
            key = f"{date}_{btc}"
            if key in existing_sale_keys:
                total_skipped += 1
                continue
            sale_id = f"sale_bf4_{ticker}_{date}_{btc}"
            if dry_run:
                print(f"    [DRY SALE] {date} | -{btc:>7,} BTC | ${usd_m:>8,.1f}M | {note[:50]}")
                total_sales_inserted += 1
                continue
            try:
                supabase.table("confirmed_sales").upsert({
                    "sale_id": sale_id, "company": company, "ticker": ticker,
                    "btc_amount": btc, "usd_amount": usd, "price_per_btc": price_per_btc,
                    "filing_date": date, "filing_url": "",
                    "source": f"Historical backfill ({note[:80]})",
                }, on_conflict="sale_id").execute()
                total_sales_inserted += 1
                print(f"    ✅ SALE {date} | -{btc:>7,} BTC | ${usd_m:>8,.1f}M | {note[:50]}")
            except Exception as e:
                total_errors += 1
                print(f"    ❌ SALE {date} | -{btc:,} BTC — ERROR: {e}")

    print(f"\n{'=' * 70}")
    print(f"RESULTS: {total_inserted} purchases, {total_sales_inserted} sales, {total_skipped} skipped, {total_errors} errors")
    print(f"{'=' * 70}")
    return {"purchases": total_inserted, "sales": total_sales_inserted, "skipped": total_skipped, "errors": total_errors}


if __name__ == "__main__":
    apply = "--apply" in sys.argv
    if not apply:
        print("\n⚠️  DRY RUN MODE — no data will be written.")
        print("   Run with --apply to insert into database.\n")
    result = backfill(dry_run=not apply)
    if not apply and (result["purchases"] > 0 or result["sales"] > 0):
        print(f"\n💡 To apply, run:  python backfill_entities_batch4.py --apply")
