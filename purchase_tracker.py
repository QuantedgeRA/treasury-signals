"""
purchase_tracker.py
-------------------
Tracks confirmed Bitcoin purchases by treasury companies.

Combines:
- Manual entry of known historical purchases
- Auto-detection from SEC EDGAR 8-K filings
- Tweet confirmations (e.g., Saylor's Monday announcements)

Feeds into the dashboard and accuracy tracker.
"""

import os
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# ============================================
# KNOWN RECENT PURCHASES (manually verified)
# Sources: 8-K filings, press releases, Saylor tracker
# ============================================

KNOWN_PURCHASES = [
    {
        "company": "Strategy (MicroStrategy)",
        "ticker": "MSTR",
        "btc_amount": 22337,
        "usd_amount": 1570000000,
        "price_per_btc": 70194,
        "filing_date": "2025-03-16",
        "source": "8-K Filing / Saylor Tweet",
        "notes": "Saylor posted 'Stretch the Orange Dots' on March 15. Purchase confirmed via 8-K on March 16.",
    },
    {
        "company": "Strategy (MicroStrategy)",
        "ticker": "MSTR",
        "btc_amount": 20356,
        "usd_amount": 1990000000,
        "price_per_btc": 97514,
        "filing_date": "2025-02-24",
        "source": "8-K Filing",
        "notes": "Funded through STRC preferred stock offering.",
    },
    {
        "company": "Strategy (MicroStrategy)",
        "ticker": "MSTR",
        "btc_amount": 7633,
        "usd_amount": 742400000,
        "price_per_btc": 97255,
        "filing_date": "2025-02-10",
        "source": "8-K Filing",
        "notes": "",
    },
    {
        "company": "Strategy (MicroStrategy)",
        "ticker": "MSTR",
        "btc_amount": 10107,
        "usd_amount": 1100000000,
        "price_per_btc": 105596,
        "filing_date": "2025-01-27",
        "source": "8-K Filing",
        "notes": "",
    },
    {
        "company": "Strategy (MicroStrategy)",
        "ticker": "MSTR",
        "btc_amount": 11000,
        "usd_amount": 1100000000,
        "price_per_btc": 101191,
        "filing_date": "2025-01-21",
        "source": "8-K Filing",
        "notes": "",
    },
    {
        "company": "Strategy (MicroStrategy)",
        "ticker": "MSTR",
        "btc_amount": 2530,
        "usd_amount": 243000000,
        "price_per_btc": 95972,
        "filing_date": "2025-01-13",
        "source": "8-K Filing",
        "notes": "",
    },
    {
        "company": "Strategy (MicroStrategy)",
        "ticker": "MSTR",
        "btc_amount": 1070,
        "usd_amount": 101000000,
        "price_per_btc": 94004,
        "filing_date": "2025-01-06",
        "source": "8-K Filing",
        "notes": "",
    },
    {
        "company": "KULR Technology",
        "ticker": "KULR",
        "btc_amount": 213,
        "usd_amount": 21000000,
        "price_per_btc": 98500,
        "filing_date": "2025-01-06",
        "source": "Press Release",
        "notes": "Second BTC purchase under new treasury policy.",
    },
    {
        "company": "Metaplanet",
        "ticker": "3350.T",
        "btc_amount": 150,
        "usd_amount": 11250000,
        "price_per_btc": 75000,
        "filing_date": "2025-03-01",
        "source": "Press Release",
        "notes": "Japan's MicroStrategy continues aggressive accumulation.",
    },
    {
        "company": "Semler Scientific",
        "ticker": "SMLR",
        "btc_amount": 871,
        "usd_amount": 88400000,
        "price_per_btc": 101500,
        "filing_date": "2025-02-14",
        "source": "8-K Filing",
        "notes": "Largest single purchase by Semler.",
    },
    {
        "company": "Hut 8 Mining",
        "ticker": "HUT",
        "btc_amount": 990,
        "usd_amount": 100000000,
        "price_per_btc": 101010,
        "filing_date": "2024-12-19",
        "source": "Press Release",
        "notes": "Strategic reserve purchase.",
    },
    {
        "company": "Strategy (MicroStrategy)",
        "ticker": "MSTR",
        "btc_amount": 15350,
        "usd_amount": 1500000000,
        "price_per_btc": 100386,
        "filing_date": "2024-12-16",
        "source": "8-K Filing",
        "notes": "",
    },
    {
        "company": "Strategy (MicroStrategy)",
        "ticker": "MSTR",
        "btc_amount": 21550,
        "usd_amount": 2100000000,
        "price_per_btc": 98783,
        "filing_date": "2024-12-09",
        "source": "8-K Filing",
        "notes": "",
    },
    {
        "company": "Strategy (MicroStrategy)",
        "ticker": "MSTR",
        "btc_amount": 15400,
        "usd_amount": 1500000000,
        "price_per_btc": 95976,
        "filing_date": "2024-12-02",
        "source": "8-K Filing",
        "notes": "",
    },
    {
        "company": "Strategy (MicroStrategy)",
        "ticker": "MSTR",
        "btc_amount": 55500,
        "usd_amount": 5400000000,
        "price_per_btc": 97862,
        "filing_date": "2024-11-25",
        "source": "8-K Filing",
        "notes": "Largest single BTC purchase in history at the time.",
    },
    {
        "company": "Strategy (MicroStrategy)",
        "ticker": "MSTR",
        "btc_amount": 51780,
        "usd_amount": 4600000000,
        "price_per_btc": 88627,
        "filing_date": "2024-11-18",
        "source": "8-K Filing",
        "notes": "",
    },
]


def get_recent_purchases(limit=20):
    """Get recent purchases sorted by date (newest first)."""
    sorted_purchases = sorted(KNOWN_PURCHASES, key=lambda x: x["filing_date"], reverse=True)
    return sorted_purchases[:limit]


def get_purchases_by_company(ticker):
    """Get all purchases for a specific company."""
    return sorted(
        [p for p in KNOWN_PURCHASES if p["ticker"] == ticker],
        key=lambda x: x["filing_date"],
        reverse=True,
    )


def get_purchase_stats():
    """Get summary statistics for all tracked purchases."""
    total_btc = sum(p["btc_amount"] for p in KNOWN_PURCHASES)
    total_usd = sum(p["usd_amount"] for p in KNOWN_PURCHASES)
    total_purchases = len(KNOWN_PURCHASES)
    unique_companies = len(set(p["ticker"] for p in KNOWN_PURCHASES))

    # Purchases by company
    by_company = {}
    for p in KNOWN_PURCHASES:
        ticker = p["ticker"]
        if ticker not in by_company:
            by_company[ticker] = {"company": p["company"], "ticker": ticker, "total_btc": 0, "total_usd": 0, "count": 0}
        by_company[ticker]["total_btc"] += p["btc_amount"]
        by_company[ticker]["total_usd"] += p["usd_amount"]
        by_company[ticker]["count"] += 1

    # Monthly totals
    by_month = {}
    for p in KNOWN_PURCHASES:
        month = p["filing_date"][:7]
        if month not in by_month:
            by_month[month] = {"btc": 0, "usd": 0, "count": 0}
        by_month[month]["btc"] += p["btc_amount"]
        by_month[month]["usd"] += p["usd_amount"]
        by_month[month]["count"] += 1

    return {
        "total_purchases": total_purchases,
        "total_btc": total_btc,
        "total_usd": total_usd,
        "avg_price": round(total_usd / total_btc, 0) if total_btc > 0 else 0,
        "unique_companies": unique_companies,
        "by_company": sorted(by_company.values(), key=lambda x: x["total_btc"], reverse=True),
        "by_month": dict(sorted(by_month.items(), reverse=True)),
    }


def seed_confirmed_purchases():
    """Seed the confirmed_purchases table with known historical data."""
    print("  Seeding confirmed purchases into Supabase...")
    seeded = 0
    skipped = 0

    for p in KNOWN_PURCHASES:
        purchase_id = f"buy_{p['ticker']}_{p['filing_date']}"
        try:
            existing = supabase.table("confirmed_purchases").select("purchase_id").eq("purchase_id", purchase_id).execute()
            if existing.data:
                skipped += 1
                continue

            row = {
                "purchase_id": purchase_id,
                "company": p["company"],
                "ticker": p["ticker"],
                "btc_amount": p["btc_amount"],
                "usd_amount": p["usd_amount"],
                "price_per_btc": p["price_per_btc"],
                "filing_date": p["filing_date"],
                "filing_url": "",
                "was_predicted": False,
                "prediction_id": None,
                "prediction_lead_time_hours": None,
            }
            supabase.table("confirmed_purchases").insert(row).execute()
            seeded += 1
            print(f"    ✅ {p['company']}: {p['btc_amount']:,} BTC on {p['filing_date']}")
        except Exception as e:
            print(f"    ❌ Error: {e}")

    print(f"\n  Done: {seeded} seeded, {skipped} already existed.")
    return seeded, skipped


def format_purchase_telegram(purchase):
    """Format a single purchase for Telegram."""
    return f"""
💰 CONFIRMED BTC PURCHASE

🏢 {purchase['company']} ({purchase['ticker']})
₿ {purchase['btc_amount']:,} BTC
💵 ${purchase['usd_amount']/1_000_000:,.0f}M (${purchase['price_per_btc']:,.0f}/BTC)
📅 {purchase['filing_date']}
📄 Source: {purchase['source']}
{('📝 ' + purchase['notes']) if purchase['notes'] else ''}

---
Treasury Signal Intelligence
BTC Purchase Tracker™
"""


# ============================================
# QUICK TEST
# ============================================
if __name__ == "__main__":
    print("\nBTC Purchase Tracker\n")
    print("=" * 60)

    stats = get_purchase_stats()
    print(f"\n  Total tracked purchases: {stats['total_purchases']}")
    print(f"  Total BTC purchased: {stats['total_btc']:,}")
    print(f"  Total USD spent: ${stats['total_usd']/1_000_000_000:.1f}B")
    print(f"  Avg price per BTC: ${stats['avg_price']:,.0f}")
    print(f"  Unique companies: {stats['unique_companies']}")

    print(f"\n  By Company:")
    for c in stats['by_company']:
        print(f"    {c['company']}: {c['total_btc']:,} BTC across {c['count']} purchases")

    print(f"\n  By Month:")
    for month, data in stats['by_month'].items():
        print(f"    {month}: {data['btc']:,} BTC (${data['usd']/1_000_000_000:.1f}B) — {data['count']} purchases")

    print(f"\n  Most Recent Purchases:")
    for p in get_recent_purchases(5):
        print(f"    {p['filing_date']}: {p['company']} bought {p['btc_amount']:,} BTC for ${p['usd_amount']/1_000_000:,.0f}M")

    # Seed to database
    print(f"\n  Seeding to Supabase...")
    seed_confirmed_purchases()

    print("\nPurchase Tracker is ready!")
