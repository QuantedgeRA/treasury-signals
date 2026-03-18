"""
purchase_tracker.py — v2.0
---------------------------
Auto-detecting BTC Purchases

Two data sources:
1. KNOWN_PURCHASES — Historical purchases (manually verified)
2. AUTO-DETECTED — Compares leaderboard snapshots to detect new purchases
   If a company's holdings increased between scans, we log it as a purchase.

Combined feed shows both historical + live detected purchases.
"""

import os
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from supabase import create_client
from treasury_leaderboard import get_leaderboard_with_live_price, fetch_live_leaderboard
import yfinance as yf

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# ============================================
# KNOWN HISTORICAL PURCHASES (verified)
# ============================================

KNOWN_PURCHASES = [
    {"company": "Strategy", "ticker": "MSTR", "btc_amount": 22337, "usd_amount": 1570000000, "price_per_btc": 70194, "filing_date": "2025-03-16", "source": "8-K Filing", "notes": "Saylor's 'Stretch the Orange Dots' signal preceded this purchase."},
    {"company": "Strategy", "ticker": "MSTR", "btc_amount": 20356, "usd_amount": 1990000000, "price_per_btc": 97514, "filing_date": "2025-02-24", "source": "8-K Filing", "notes": "Funded through STRC preferred stock offering."},
    {"company": "Strategy", "ticker": "MSTR", "btc_amount": 7633, "usd_amount": 742400000, "price_per_btc": 97255, "filing_date": "2025-02-10", "source": "8-K Filing", "notes": ""},
    {"company": "Strategy", "ticker": "MSTR", "btc_amount": 10107, "usd_amount": 1100000000, "price_per_btc": 105596, "filing_date": "2025-01-27", "source": "8-K Filing", "notes": ""},
    {"company": "Strategy", "ticker": "MSTR", "btc_amount": 11000, "usd_amount": 1100000000, "price_per_btc": 101191, "filing_date": "2025-01-21", "source": "8-K Filing", "notes": ""},
    {"company": "Strategy", "ticker": "MSTR", "btc_amount": 2530, "usd_amount": 243000000, "price_per_btc": 95972, "filing_date": "2025-01-13", "source": "8-K Filing", "notes": ""},
    {"company": "Strategy", "ticker": "MSTR", "btc_amount": 1070, "usd_amount": 101000000, "price_per_btc": 94004, "filing_date": "2025-01-06", "source": "8-K Filing", "notes": ""},
    {"company": "KULR Technology", "ticker": "KULR", "btc_amount": 213, "usd_amount": 21000000, "price_per_btc": 98500, "filing_date": "2025-01-06", "source": "Press Release", "notes": ""},
    {"company": "Metaplanet", "ticker": "3350.T", "btc_amount": 150, "usd_amount": 11250000, "price_per_btc": 75000, "filing_date": "2025-03-01", "source": "Press Release", "notes": "Japan's MicroStrategy."},
    {"company": "Semler Scientific", "ticker": "SMLR", "btc_amount": 871, "usd_amount": 88400000, "price_per_btc": 101500, "filing_date": "2025-02-14", "source": "8-K Filing", "notes": ""},
    {"company": "Hut 8 Mining", "ticker": "HUT", "btc_amount": 990, "usd_amount": 100000000, "price_per_btc": 101010, "filing_date": "2024-12-19", "source": "Press Release", "notes": ""},
    {"company": "Strategy", "ticker": "MSTR", "btc_amount": 15350, "usd_amount": 1500000000, "price_per_btc": 100386, "filing_date": "2024-12-16", "source": "8-K Filing", "notes": ""},
    {"company": "Strategy", "ticker": "MSTR", "btc_amount": 21550, "usd_amount": 2100000000, "price_per_btc": 98783, "filing_date": "2024-12-09", "source": "8-K Filing", "notes": ""},
    {"company": "Strategy", "ticker": "MSTR", "btc_amount": 15400, "usd_amount": 1500000000, "price_per_btc": 95976, "filing_date": "2024-12-02", "source": "8-K Filing", "notes": ""},
    {"company": "Strategy", "ticker": "MSTR", "btc_amount": 55500, "usd_amount": 5400000000, "price_per_btc": 97862, "filing_date": "2024-11-25", "source": "8-K Filing", "notes": "Largest single BTC purchase at the time."},
    {"company": "Strategy", "ticker": "MSTR", "btc_amount": 51780, "usd_amount": 4600000000, "price_per_btc": 88627, "filing_date": "2024-11-18", "source": "8-K Filing", "notes": ""},
]


def save_leaderboard_snapshot(btc_price=None):
    """
    Save today's leaderboard snapshot to Supabase.
    This is called every scan cycle to enable purchase detection.
    """
    try:
        if not btc_price:
            btc = yf.Ticker("BTC-USD")
            hist = btc.history(period="5d")
            btc_price = float(hist["Close"].iloc[-1]) if not hist.empty else 72000

        companies, summary = get_leaderboard_with_live_price(btc_price)

        snapshot_date = datetime.now().strftime("%Y-%m-%d")

        # Build compact JSON of holdings
        holdings = {}
        for c in companies:
            if c["btc_holdings"] > 0:
                key = c.get("ticker", c["company"][:20])
                holdings[key] = {
                    "name": c["company"],
                    "btc": c["btc_holdings"],
                    "country": c.get("country", ""),
                }

        row = {
            "snapshot_date": snapshot_date,
            "btc_price": btc_price,
            "total_btc": summary["total_btc"],
            "total_value_b": summary["total_value_b"],
            "companies_json": json.dumps(holdings),
        }

        supabase.table("leaderboard_snapshots").upsert(row, on_conflict="snapshot_date").execute()
        print(f"  Snapshot saved: {snapshot_date} | {len(holdings)} companies | {summary['total_btc']:,} BTC")
        return holdings
    except Exception as e:
        print(f"  Snapshot save error: {e}")
        return None


def get_previous_snapshot():
    """Get the most recent snapshot before today."""
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        result = (
            supabase.table("leaderboard_snapshots")
            .select("*")
            .lt("snapshot_date", today)
            .order("snapshot_date", desc=True)
            .limit(1)
            .execute()
        )
        if result.data:
            snapshot = result.data[0]
            return {
                "date": snapshot["snapshot_date"],
                "btc_price": float(snapshot.get("btc_price", 0)),
                "holdings": json.loads(snapshot.get("companies_json", "{}")),
            }
        return None
    except Exception as e:
        print(f"  Error getting previous snapshot: {e}")
        return None


def detect_new_purchases(btc_price=None):
    """
    Compare current leaderboard with previous snapshot.
    If a company's holdings increased, that's a detected purchase.
    Returns list of detected purchases.
    """
    print("  Detecting new purchases via snapshot comparison...")

    # Save current snapshot
    current_holdings = save_leaderboard_snapshot(btc_price)
    if not current_holdings:
        print("  Could not save current snapshot")
        return []

    # Get previous snapshot
    previous = get_previous_snapshot()
    if not previous:
        print("  No previous snapshot found — need at least 2 snapshots to detect purchases")
        print("  First snapshot saved. Purchases will be detected starting tomorrow.")
        return []

    prev_holdings = previous["holdings"]
    prev_date = previous["date"]
    current_btc_price = btc_price or 72000

    detected = []

    for ticker, current in current_holdings.items():
        current_btc = current["btc"]
        company_name = current["name"]

        # Check if company existed in previous snapshot
        if ticker in prev_holdings:
            prev_btc = prev_holdings[ticker]["btc"]
            increase = current_btc - prev_btc

            if increase > 0:
                # Purchase detected!
                usd_estimate = round(increase * current_btc_price)
                detected.append({
                    "company": company_name,
                    "ticker": ticker,
                    "btc_amount": increase,
                    "usd_amount": usd_estimate,
                    "price_per_btc": round(current_btc_price),
                    "filing_date": datetime.now().strftime("%Y-%m-%d"),
                    "source": "Auto-Detected (Snapshot Comparison)",
                    "notes": f"Holdings increased from {prev_btc:,} to {current_btc:,} BTC since {prev_date}",
                    "previous_holdings": prev_btc,
                    "current_holdings": current_btc,
                    "detected": True,
                })
        else:
            # New company appeared — first-time BTC holder
            if current_btc > 10:  # Ignore tiny holdings
                usd_estimate = round(current_btc * current_btc_price)
                detected.append({
                    "company": company_name,
                    "ticker": ticker,
                    "btc_amount": current_btc,
                    "usd_amount": usd_estimate,
                    "price_per_btc": round(current_btc_price),
                    "filing_date": datetime.now().strftime("%Y-%m-%d"),
                    "source": "Auto-Detected (New Treasury Company)",
                    "notes": f"First appeared on leaderboard with {current_btc:,} BTC",
                    "previous_holdings": 0,
                    "current_holdings": current_btc,
                    "detected": True,
                })

    if detected:
        detected.sort(key=lambda x: x["btc_amount"], reverse=True)
        print(f"  🔔 {len(detected)} new purchase(s) detected!")
        for d in detected[:5]:
            print(f"    {d['company']}: +{d['btc_amount']:,} BTC (~${d['usd_amount']/1_000_000:,.0f}M)")
    else:
        print(f"  No new purchases detected since {prev_date}")

    return detected


def log_detected_purchases(detected_purchases):
    """Log auto-detected purchases to the confirmed_purchases table."""
    logged = 0
    for p in detected_purchases:
        purchase_id = f"auto_{p['ticker']}_{p['filing_date']}"
        try:
            existing = supabase.table("confirmed_purchases").select("purchase_id").eq("purchase_id", purchase_id).execute()
            if existing.data:
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
            logged += 1
        except Exception as e:
            print(f"    Error logging {p['company']}: {e}")

    if logged:
        print(f"  {logged} purchase(s) logged to database")
    return logged


def get_recent_purchases(limit=20):
    """
    Get recent purchases from ALL sources:
    1. Auto-detected purchases from database
    2. Known historical purchases
    Merged and sorted by date (newest first), deduplicated.
    """
    all_purchases = []

    # Source 1: Database (auto-detected + seeded)
    try:
        result = (
            supabase.table("confirmed_purchases")
            .select("*")
            .order("filing_date", desc=True)
            .limit(50)
            .execute()
        )
        if result.data:
            for p in result.data:
                all_purchases.append({
                    "company": p.get("company", ""),
                    "ticker": p.get("ticker", ""),
                    "btc_amount": int(float(p.get("btc_amount", 0))),
                    "usd_amount": int(float(p.get("usd_amount", 0))),
                    "price_per_btc": int(float(p.get("price_per_btc", 0))),
                    "filing_date": p.get("filing_date", ""),
                    "source": p.get("filing_url", "") or "Database",
                    "notes": "",
                    "was_predicted": p.get("was_predicted", False),
                })
    except Exception as e:
        print(f"  Error fetching DB purchases: {e}")

    # Source 2: Known historical (fill in any not in DB)
    db_ids = set()
    for p in all_purchases:
        db_ids.add(f"{p['ticker']}_{p['filing_date']}")

    for p in KNOWN_PURCHASES:
        key = f"{p['ticker']}_{p['filing_date']}"
        if key not in db_ids:
            all_purchases.append(p)

    # Sort by date (newest first) and deduplicate
    all_purchases.sort(key=lambda x: x.get("filing_date", ""), reverse=True)

    # Deduplicate by company+date
    seen = set()
    unique = []
    for p in all_purchases:
        key = f"{p.get('company', '')}_{p.get('filing_date', '')}_{p.get('btc_amount', 0)}"
        if key not in seen:
            seen.add(key)
            unique.append(p)

    return unique[:limit]


def get_purchases_by_company(ticker):
    """Get all purchases for a specific company."""
    all_p = get_recent_purchases(100)
    return [p for p in all_p if p.get("ticker", "") == ticker]


def get_purchase_stats():
    """Get summary statistics for all tracked purchases."""
    all_p = get_recent_purchases(100)

    total_btc = sum(p.get("btc_amount", 0) for p in all_p)
    total_usd = sum(p.get("usd_amount", 0) for p in all_p)
    total_purchases = len(all_p)
    unique_companies = len(set(p.get("ticker", p.get("company", "")) for p in all_p))

    # Purchases by company
    by_company = {}
    for p in all_p:
        ticker = p.get("ticker", p.get("company", "Unknown"))
        if ticker not in by_company:
            by_company[ticker] = {"company": p.get("company", ""), "ticker": ticker, "total_btc": 0, "total_usd": 0, "count": 0}
        by_company[ticker]["total_btc"] += p.get("btc_amount", 0)
        by_company[ticker]["total_usd"] += p.get("usd_amount", 0)
        by_company[ticker]["count"] += 1

    # Monthly totals
    by_month = {}
    for p in all_p:
        month = p.get("filing_date", "")[:7]
        if month:
            if month not in by_month:
                by_month[month] = {"btc": 0, "usd": 0, "count": 0}
            by_month[month]["btc"] += p.get("btc_amount", 0)
            by_month[month]["usd"] += p.get("usd_amount", 0)
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
    source_label = "🤖 AUTO-DETECTED" if purchase.get("detected") else "📄 CONFIRMED"
    return f"""
💰 {source_label} BTC PURCHASE

🏢 {purchase['company']} ({purchase.get('ticker', '')})
₿ {purchase['btc_amount']:,} BTC
💵 ${purchase['usd_amount']/1_000_000:,.0f}M (${purchase['price_per_btc']:,.0f}/BTC)
📅 {purchase['filing_date']}
📄 Source: {purchase.get('source', 'Unknown')}
{('📝 ' + purchase['notes']) if purchase.get('notes') else ''}

---
Treasury Signal Intelligence
BTC Purchase Tracker™
"""


# ============================================
# QUICK TEST
# ============================================
if __name__ == "__main__":
    print("\nBTC Purchase Tracker v2.0 — Auto-Detecting\n")
    print("=" * 60)

    # Step 1: Save today's snapshot
    print("\n[1] Saving leaderboard snapshot...")
    save_leaderboard_snapshot()

    # Step 2: Detect new purchases
    print("\n[2] Detecting new purchases...")
    detected = detect_new_purchases()

    if detected:
        print(f"\n  🔔 Detected {len(detected)} purchase(s):")
        for d in detected[:10]:
            print(f"    {d['company']}: +{d['btc_amount']:,} BTC (~${d['usd_amount']/1_000_000:,.0f}M)")
            print(f"      {d['notes']}")

        # Log to database
        print("\n[3] Logging detected purchases to database...")
        log_detected_purchases(detected)
    else:
        print("\n  No new purchases detected (need 2+ daily snapshots)")

    # Step 3: Show combined feed
    print("\n[4] Combined purchase feed (DB + historical):")
    purchases = get_recent_purchases(10)
    for p in purchases:
        src = "🤖" if "Auto" in p.get("source", "") else "📄"
        print(f"  {src} {p['filing_date']}: {p.get('company', '')} — {p.get('btc_amount', 0):,} BTC (${p.get('usd_amount', 0)/1_000_000:,.0f}M)")

    # Stats
    print("\n[5] Purchase stats:")
    stats = get_purchase_stats()
    print(f"  Total: {stats['total_purchases']} purchases | {stats['total_btc']:,} BTC | ${stats['total_usd']/1_000_000_000:.1f}B")

    print("\nPurchase Tracker v2.0 is ready!")