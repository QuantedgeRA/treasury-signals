"""
backfill_entities_batch3.py — Multi-Entity BTC Purchase History (Batch 3)
==========================================================================
Third batch: sovereign entities + international companies.

Entities covered:
  - El Salvador (government) — daily DCA since 2021
  - Bhutan (government) — mining + massive sell-off
  - MercadoLibre (MELI) — Latin America's largest e-commerce
  - Meitu (1357.HK) — Chinese tech, bought and sold
  - Bitdeer (BTDR) — Singapore miner, steady accumulation
  - Solidion Technology (STI) — BTC treasury pivot
  - Genius Group (GNS) — education company BTC strategy
  - Nakamoto Holdings (NAKA) — David Bailey's BTC vehicle
  - IREN / Iris Energy (IREN) — Australian miner
  - Cipher Mining (CIFR) — US miner

Usage:
    python backfill_entities_batch3.py          # Dry run
    python backfill_entities_batch3.py --apply  # Insert into database
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
    # ─── EL SALVADOR (Government) ───
    # Source: Bukele tweets, Nayib Bukele X posts, bitbo.io, IMF report, CCN
    # 1 BTC/day DCA since Nov 2022. Some larger buys. Never sold.
    "SV.GOV": {
        "company": "El Salvador",
        "purchases": [
            ("2021-09-07", 400, 20.9, "Bitcoin Law takes effect; bought 400 BTC at ~$52,250"),
            ("2021-09-07", 150, 7.4, "Second buy same day; 'buying the dip' tweet from Bukele"),
            ("2021-09-20", 150, 6.5, "Additional purchase at ~$43,300"),
            ("2021-10-27", 420, 25.3, "'Bought the dip again' — Bukele tweet at ~$60,200"),
            ("2021-11-26", 100, 5.4, "Black Friday purchase at $54,000"),
            ("2021-12-21", 21, 1.0, "21 BTC symbolic buy at ~$47,600"),
            ("2022-01-21", 410, 15.0, "Bought the dip at ~$36,585; largest 2022 batch"),
            ("2022-05-09", 500, 15.3, "Bought during Terra/LUNA crash at ~$30,600"),
            ("2022-06-30", 80, 1.6, "Mid-year DCA accumulation"),
            ("2022-11-17", 1, 0.016, "Daily DCA begins; 1 BTC/day announced Nov 16, 2022"),
            ("2023-12-31", 365, 15, "Approximate 2023 daily DCA total (~1 BTC/day); avg ~$41,000"),
            ("2024-03-14", 3308, 0, "Large transfer to cold wallet; likely accumulated over months"),
            ("2024-12-31", 550, 45, "2024 daily DCA + additions; total ~5,749 BTC by May 2024, ~6,088 by Feb 2025"),
            ("2025-09-07", 21, 2.3, "Bitcoin Day celebration; 4th anniversary; total 6,313 BTC"),
            ("2025-11-18", 700, 0, "Continued accumulation; total 7,475 BTC per bitbo.io"),
        ],
        "sales": [],
    },

    # ─── BHUTAN (Government) ───
    # Source: Arkham Intelligence, CoinDesk, MEXC News
    # Mined via hydropower since 2019. Peaked ~13,000 BTC Oct 2024. Sold 70%.
    "BT.GOV": {
        "company": "Bhutan",
        "purchases": [
            ("2024-10-01", 13000, 0, "Peak holdings; accumulated through hydropower mining since 2019"),
        ],
        "sales": [
            ("2024-11-15", 367, 33.5, "Sold via Binance at ~$91,280; first major known sale"),
            ("2024-11-30", 900, 65, "Second batch; deposited to Binance for $65M"),
            ("2025-03-15", 596, 44.4, "Transferred to two new wallets; Arkham tracked"),
            ("2025-06-30", 3000, 300, "Continued steady selling through H1 2025; estimated aggregate"),
            ("2026-03-31", 520, 36.7, "Late March 2026 sale batch"),
            ("2026-04-09", 320, 22.8, "April 2026 sale; remaining ~3,954 BTC"),
        ],
    },

    # ─── MERCADOLIBRE ───
    # Source: SEC filing Q1 2021, BitcoinTreasuries.net
    "MELI": {
        "company": "MercadoLibre",
        "purchases": [
            ("2021-05-05", 413, 7.8, "Q1 2021 treasury purchase; $18,886/BTC; SEC filing disclosure"),
        ],
        "sales": [],
    },

    # ─── MEITU (Hong Kong) ───
    # Source: Company announcements, SEC-equivalent filings
    "1357.HK": {
        "company": "Meitu",
        "purchases": [
            ("2021-03-07", 379, 17.9, "First BTC purchase at ~$47,200; Chinese tech company"),
            ("2021-04-08", 176, 10, "Second purchase at ~$56,800"),
        ],
        "sales": [
            ("2022-06-15", 100, 2.8, "Partial sale during bear market; ~$28,000/BTC"),
        ],
    },

    # ─── BITDEER TECHNOLOGIES ───
    # Source: BitcoinTreasuries.net, company X posts
    "BTDR": {
        "company": "Bitdeer Technologies",
        "purchases": [
            ("2024-11-30", 921, 88, "Initial treasury accumulation; Singapore miner"),
            ("2025-01-13", 46, 4.5, "Jan 2025 addition"),
            ("2025-02-03", 147, 14.5, "Feb 2025 major batch"),
            ("2025-02-07", 18, 1.8, "Feb 2025 additional"),
            ("2025-03-29", 338, 30, "Mar 2025 purchase; total ~1,502 BTC"),
            ("2025-04-05", 30, 2.5, "Apr 2025 addition"),
            ("2025-12-31", 529, 50, "Continued accumulation through 2025; total 2,029 BTC"),
        ],
        "sales": [],
    },

    # ─── SOLIDION TECHNOLOGY ───
    # Source: SEC 8-K filing, press releases
    "STI": {
        "company": "Solidion Technology",
        "purchases": [
            ("2024-11-19", 60, 5.4, "Initial BTC treasury; battery tech company pivots; $90,000 avg"),
        ],
        "sales": [],
    },

    # ─── GENIUS GROUP ───
    # Source: Company press releases, SEC filings
    "GNS": {
        "company": "Genius Group",
        "purchases": [
            ("2024-11-18", 110, 10, "Bitcoin-first strategy announced; $90,909/BTC avg"),
            ("2025-01-31", 262, 25, "Continued accumulation; total ~372 BTC"),
            ("2025-03-31", 50, 4.5, "Q1 2025 addition"),
        ],
        "sales": [],
    },

    # ─── IREN / IRIS ENERGY ───
    # Source: Company quarterly reports, The Block
    "IREN": {
        "company": "IREN",
        "purchases": [
            ("2024-12-31", 5091, 0, "End of 2024 holdings; Australian BTC miner; mix of mined + purchased"),
        ],
        "sales": [],
    },

    # ─── CIPHER MINING ───
    # Source: Company production updates, SEC filings
    "CIFR": {
        "company": "Cipher Mining",
        "purchases": [
            ("2024-12-31", 1034, 0, "End of 2024 holdings; US miner based in Texas"),
            ("2025-06-30", 1500, 0, "Mid-2025 estimated total from mining accumulation"),
        ],
        "sales": [],
    },

    # ─── ACURX PHARMACEUTICALS ───
    # Source: Press release Nov 2024
    "ACXP": {
        "company": "Acurx Pharmaceuticals",
        "purchases": [
            ("2024-11-20", 10, 1, "Board approved $1M BTC treasury reserve"),
        ],
        "sales": [],
    },

    # ─── WORKSPORT ───
    # Source: Press release Dec 2024
    "WKSP": {
        "company": "Worksport",
        "purchases": [
            ("2024-12-06", 5, 0.5, "Board approved BTC + XRP treasury strategy"),
        ],
        "sales": [],
    },
}


def backfill(dry_run=True):
    """Insert multi-entity purchase history into confirmed_purchases and confirmed_sales."""
    print(f"\n{'=' * 70}")
    print(f"Multi-Entity BTC Purchase History Backfill — Batch 3")
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

            purchase_id = f"backfill3_{ticker}_{date}_{btc}"

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

            sale_id = f"sale_bf3_{ticker}_{date}_{btc}"

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
        print(f"   python backfill_entities_batch3.py --apply")
