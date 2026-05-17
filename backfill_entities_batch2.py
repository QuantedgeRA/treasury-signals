"""
backfill_entities_batch2.py — Multi-Entity BTC Purchase History (Batch 2)
==========================================================================
Second batch of historical backfills covering:
  - Twenty One Capital (XXI) — SPAC merger + Tether/Bitfinex contributions
  - Trump Media (DJT) — aggressive 2025 accumulation
  - Riot Platforms (RIOT) — mining + open market purchases
  - CleanSpark (CLSK) — mining accumulation
  - Coinbase (COIN) — corporate treasury
  - Cango (CANG) — Chinese company pivot
  - Galaxy Digital (GLXY) — early crypto adopter
  - Exodus Movement (EXOD) — crypto wallet company
  - Rumble (RUM) — video platform

Data sources: SEC 8-K filings, press releases, Arkham on-chain data,
BitcoinTreasuries.net, CoinGecko, bitbo.io. Cross-referenced where possible.

Usage:
    python backfill_entities_batch2.py          # Dry run
    python backfill_entities_batch2.py --apply  # Insert into database
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

# FORMAT: (date, btc_amount, usd_millions, source_note)

PURCHASES = {
    # ─── TWENTY ONE CAPITAL ───
    # Source: SEC 8-K (May 2025), press releases, The Block
    # Formed via SPAC merger (Cantor Equity Partners) with Tether/Bitfinex/SoftBank backing
    "XXI": {
        "company": "Twenty One Capital",
        "purchases": [
            ("2025-05-09", 4812, 458.7, "Initial PIPE purchase via Tether at $95,319/BTC; SEC 8-K filing"),
            ("2025-08-31", 33000, 3300, "Accumulated through 2025 from Tether/Bitfinex/SoftBank contributions + purchases; ~$100K avg"),
            ("2025-12-08", 5702, 550, "Additional BTC transferred from Tether at SPAC merger close; total 43,514 BTC"),
        ],
        "sales": [],
    },

    # ─── TRUMP MEDIA ───
    # Source: GlobeNewswire press releases, Arkham on-chain, CNBC, CoinDesk
    "DJT": {
        "company": "Trump Media",
        "purchases": [
            ("2025-05-27", 5000, 500, "Initial BTC acquisition from $2.5B capital raise; estimated batch"),
            ("2025-06-30", 3000, 300, "Continued accumulation Q2 2025; estimated from $2B total by Jul 21"),
            ("2025-07-21", 3091, 200, "Reached $2B total BTC + BTC-related securities per press release; ~11,091 BTC"),
            ("2025-12-22", 451, 40.3, "Purchase confirmed by Lookonchain; total reached 11,542 BTC"),
        ],
        "sales": [],
    },

    # ─── RIOT PLATFORMS ───
    # Source: Company press releases, SEC filings, Benzinga
    # Note: Riot accumulates BTC via mining AND open market purchases.
    # Only major strategic purchases tracked (not monthly mining output).
    "RIOT": {
        "company": "Riot Platforms",
        "purchases": [
            ("2024-12-16", 5784, 560, "Strategic open market purchase Dec 2024; $96,739 avg; total 17,722 BTC by year end"),
            ("2025-01-07", 293, 28, "Dec 2024 mining + additions; total ~18,015 BTC"),
        ],
        "sales": [
            ("2025-09-30", 1100, 96, "Sold ~1,100 BTC to fund $96M Rockdale mining site acquisition"),
        ],
    },

    # ─── CLEANSPARK ───
    # Source: Company monthly production updates, SEC filings
    # Primarily mining, not open market purchases. Balance changes from mining output.
    "CLSK": {
        "company": "CleanSpark",
        "purchases": [
            ("2024-12-31", 9952, 0, "End of year holdings; accumulated through mining throughout 2024; 7,024 BTC mined in 2024"),
            ("2025-09-30", 13011, 0, "Sep 2025 update; net addition of ~3,059 BTC through mining/accumulation"),
            ("2025-12-31", 13099, 0, "Year-end 2025 holdings per bitbo.io"),
        ],
        "sales": [],
    },

    # ─── COINBASE ───
    # Source: SEC filings, quarterly reports, press releases
    "COIN": {
        "company": "Coinbase Global",
        "purchases": [
            ("2021-04-14", 4487, 230, "IPO disclosure: $230M in BTC on balance sheet at ~$51,261 avg"),
            ("2024-12-31", 9480, 600, "Accumulated through 2024; various quarterly additions"),
            ("2025-07-31", 2296, 200, "Q3 2025 additions; part of $2B BTC + BTC-linked securities program; total ~11,776 BTC"),
        ],
        "sales": [],
    },

    # ─── CANGO ───
    # Source: Company announcements, CoinGecko, bitbo.io
    "CANG": {
        "company": "Cango",
        "purchases": [
            ("2025-03-31", 1000, 85, "Initial BTC accumulation; pivoted from auto dealership to BTC mining"),
            ("2025-06-30", 3200, 350, "Expanded mining operations; total ~4,200 BTC by Q2"),
            ("2025-09-30", 5810, 0, "Sep 2025; 616 BTC mined in Sep alone at 50 EH/s; total reached 5,810"),
        ],
        "sales": [],
    },

    # ─── GALAXY DIGITAL ───
    # Source: Company quarterly reports, CoinGecko
    "GLXY": {
        "company": "Galaxy Digital",
        "purchases": [
            ("2021-03-31", 16402, 900, "Early adopter; one of largest institutional holdings by 2021"),
            ("2024-06-30", 8100, 490, "Holdings as of mid-2024 after partial sales/rebalancing"),
        ],
        "sales": [
            ("2022-06-30", 5000, 150, "Reduced holdings during 2022 bear market; estimated"),
        ],
    },

    # ─── EXODUS MOVEMENT ───
    # Source: Company SEC filings, press releases
    "EXOD": {
        "company": "Exodus Movement",
        "purchases": [
            ("2024-12-31", 1500, 140, "BTC holdings as of end 2024; crypto wallet company"),
        ],
        "sales": [],
    },

    # ─── RUMBLE ───
    # Source: Company press release Nov 2024
    "RUM": {
        "company": "Rumble",
        "purchases": [
            ("2024-11-25", 188, 17, "Initial BTC treasury allocation; ~$90,000/BTC; announced Nov 25, 2024"),
        ],
        "sales": [],
    },

    # ─── NEXON ───
    # Source: SEC filings, press releases
    "NEXON": {
        "company": "Nexon",
        "purchases": [
            ("2021-04-28", 1717, 100, "Japanese gaming company purchased $100M in BTC at $58,226/BTC"),
        ],
        "sales": [],
    },

    # ─── MELIUZ (Brazil) ───
    # Source: Press releases, CoinGecko
    "CASH3": {
        "company": "Meliuz",
        "purchases": [
            ("2025-05-06", 274, 28.4, "Brazilian fintech; initial BTC purchase at ~$103,604/BTC"),
        ],
        "sales": [],
    },

    # ─── BOYAA INTERACTIVE (Hong Kong) ───
    # Source: Company announcements, CoinGecko
    "0434.HK": {
        "company": "Boyaa Interactive",
        "purchases": [
            ("2024-11-30", 3183, 310, "Hong Kong gaming company; accumulated ~3,183 BTC through 2024"),
        ],
        "sales": [],
    },
}


def backfill(dry_run=True):
    """Insert multi-entity purchase history into confirmed_purchases and confirmed_sales."""
    print(f"\n{'=' * 70}")
    print(f"Multi-Entity BTC Purchase History Backfill — Batch 2")
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

            purchase_id = f"backfill2_{ticker}_{date}_{btc}"

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

            sale_id = f"sale_bf2_{ticker}_{date}_{btc}"

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
        print(f"   python backfill_entities_batch2.py --apply")
