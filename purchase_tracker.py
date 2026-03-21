"""
purchase_tracker.py — v3.0
---------------------------
Comprehensive BTC Purchase Tracker

Tracks purchases from ALL entity types:
- Treasury companies (Strategy, MARA, Riot, etc.)
- Governments (US, China, El Salvador, etc.)
- Banks (JPMorgan, Goldman Sachs, etc.)
- Asset managers (BlackRock, Fidelity, etc.)
- Hedge funds
- ETF providers
- Pension funds
- Sovereign wealth funds
- Any major financial institution worldwide

Sources:
1. Supabase database (auto-detected + seeded)
2. Known historical purchases
3. Google News RSS (real-time detection)
4. Leaderboard snapshot comparison (daily)
"""

import os
import re
import json
import hashlib
import requests
import xml.etree.ElementTree as ET
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
# KNOWN HISTORICAL PURCHASES
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


# ============================================
# COMPREHENSIVE ENTITY MAP
# Covers companies, governments, banks, funds
# ============================================

ENTITY_MAP = {
    # Treasury companies
    "strategy": ("Strategy", "MSTR"), "microstrategy": ("Strategy", "MSTR"), "mstr": ("Strategy", "MSTR"), "saylor": ("Strategy", "MSTR"),
    "mara": ("MARA Holdings", "MARA"), "marathon": ("MARA Holdings", "MARA"),
    "riot": ("Riot Platforms", "RIOT"), "riot platforms": ("Riot Platforms", "RIOT"),
    "tesla": ("Tesla", "TSLA"), "elon musk": ("Tesla", "TSLA"),
    "gamestop": ("GameStop", "GME"), "gme": ("GameStop", "GME"),
    "metaplanet": ("Metaplanet", "3350.T"),
    "semler": ("Semler Scientific", "SMLR"),
    "hut 8": ("Hut 8 Mining", "HUT"),
    "coinbase": ("Coinbase", "COIN"),
    "block": ("Block", "XYZ"), "square": ("Block", "XYZ"),
    "cleanspark": ("CleanSpark", "CLSK"),
    "twenty one": ("Twenty One Capital", "CEP"), "xxi": ("Twenty One Capital", "CEP"),
    "kulr": ("KULR Technology", "KULR"),
    "strive": ("Strive", "ASST"),
    "trump media": ("Trump Media", "DJT"),
    "core scientific": ("Core Scientific", "CORZ"),
    "bitfarms": ("Bitfarms", "BITF"),
    "cipher": ("Cipher Mining", "CIFR"),
    "galaxy digital": ("Galaxy Digital", "GLXY"),
    "exodus": ("Exodus Movement", "EXOD"),
    "rumble": ("Rumble", "RUM"),
    # Banks
    "jpmorgan": ("JPMorgan Chase", "JPM"), "jp morgan": ("JPMorgan Chase", "JPM"),
    "goldman sachs": ("Goldman Sachs", "GS"), "goldman": ("Goldman Sachs", "GS"),
    "morgan stanley": ("Morgan Stanley", "MS"),
    "bank of america": ("Bank of America", "BAC"), "bofa": ("Bank of America", "BAC"),
    "citigroup": ("Citigroup", "C"), "citi": ("Citigroup", "C"),
    "wells fargo": ("Wells Fargo", "WFC"),
    "hsbc": ("HSBC Holdings", "HSBC"),
    "ubs": ("UBS Group", "UBS"),
    "deutsche bank": ("Deutsche Bank", "DB"),
    "barclays": ("Barclays", "BCS"),
    "credit suisse": ("Credit Suisse", "CS"),
    "nomura": ("Nomura Holdings", "NMR"),
    "standard chartered": ("Standard Chartered", "SCBFF"),
    # Asset managers
    "blackrock": ("BlackRock", "BLK"), "ishares": ("BlackRock", "BLK"),
    "fidelity": ("Fidelity Investments", "FNF"),
    "vanguard": ("Vanguard", "VANGUARD"),
    "ark invest": ("ARK Invest", "ARKK"), "cathie wood": ("ARK Invest", "ARKK"),
    "grayscale": ("Grayscale (DCG)", "GBTC"),
    "bitwise": ("Bitwise Asset Management", "BITW"),
    "invesco": ("Invesco", "IVZ"),
    "wisdomtree": ("WisdomTree", "WT"),
    "vaneck": ("VanEck", "VANECK"),
    "franklin templeton": ("Franklin Templeton", "BEN"),
    "state street": ("State Street", "STT"),
    # Hedge funds
    "citadel": ("Citadel", "CITADEL"),
    "millennium": ("Millennium Management", "MILLENNIUM"),
    "bridgewater": ("Bridgewater Associates", "BRIDGEWATER"),
    "renaissance": ("Renaissance Technologies", "RENAISSANCE"),
    "point72": ("Point72", "POINT72"),
    "two sigma": ("Two Sigma", "TWOSIGMA"),
    "brevan howard": ("Brevan Howard", "BREVAN"),
    # Governments
    "el salvador": ("El Salvador Government", "SV-GOV"),
    "bukele": ("El Salvador Government", "SV-GOV"),
    "bhutan": ("Bhutan Government", "BT-GOV"),
    "us government": ("US Government", "US-GOV"),
    "us treasury": ("US Government", "US-GOV"),
    "uk government": ("UK Government", "UK-GOV"),
    "china government": ("China Government", "CN-GOV"),
    # ETF providers
    "ibit": ("BlackRock Bitcoin ETF (IBIT)", "IBIT"),
    "fbtc": ("Fidelity Bitcoin ETF (FBTC)", "FBTC"),
    "bitcoin etf": ("Bitcoin ETF", "ETF"),
    "spot bitcoin etf": ("Spot Bitcoin ETF", "ETF"),
    # Sovereign wealth funds
    "saudi": ("Saudi Arabia PIF", "SA-SWF"),
    "norway wealth fund": ("Norway Sovereign Fund", "NO-SWF"),
    "abu dhabi": ("Abu Dhabi Investment Authority", "AE-SWF"), "adia": ("Abu Dhabi Investment Authority", "AE-SWF"),
    "mubadala": ("Mubadala (Abu Dhabi)", "MUBADALA"),
    "temasek": ("Temasek (Singapore)", "TEMASEK"),
    "gic": ("GIC (Singapore)", "GIC"),
    # Pension funds
    "wisconsin pension": ("Wisconsin Pension Fund", "WI-PENSION"),
    "michigan pension": ("Michigan Pension Fund", "MI-PENSION"),
    "pension fund bitcoin": ("Pension Fund", "PENSION"),
    # Other financial institutions
    "paypal": ("PayPal", "PYPL"),
    "robinhood": ("Robinhood", "HOOD"),
    "mercadolibre": ("MercadoLibre", "MELI"),
    "nexon": ("Nexon", "3659.T"),
}

# Purchase-indicating keywords
PURCHASE_KEYWORDS = [
    "bought", "buys", "purchase", "purchased", "acquired", "acquisition",
    "adds", "added", "accumulate", "accumulated", "invest", "invested",
    "allocated", "allocation", "treasury", "reserve", "holdings",
    "increased holdings", "bought more", "added to", "snaps up",
    "acquires", "scoops up", "loads up", "stacks",
]


def scan_news_for_purchases():
    """
    Comprehensive news scanner for BTC purchases from ANY major entity.
    Scans Google News RSS for recent purchase announcements.
    """
    print("  Scanning news for recent BTC purchases (comprehensive)...")

    queries = [
        # Company purchases
        "bitcoin purchase company 2026",
        "bitcoin treasury buy 2026",
        "corporate bitcoin acquisition 2026",
        "company buys bitcoin 2026",
        "bitcoin added treasury 2026",
        "MicroStrategy Strategy bitcoin buy 2026",
        "Metaplanet bitcoin 2026",
        "MARA bitcoin purchase 2026",
        "GameStop bitcoin 2026",
        # Government purchases
        "government bitcoin purchase 2026",
        "El Salvador bitcoin buy 2026",
        "strategic bitcoin reserve purchase 2026",
        "country buys bitcoin 2026",
        # Banks and institutions
        "bank bitcoin investment 2026",
        "JPMorgan bitcoin 2026",
        "Goldman Sachs bitcoin 2026",
        "Morgan Stanley bitcoin 2026",
        "institutional bitcoin purchase 2026",
        # Asset managers and ETFs
        "BlackRock bitcoin ETF inflow 2026",
        "Fidelity bitcoin ETF 2026",
        "bitcoin ETF inflow record 2026",
        "ARK Invest bitcoin 2026",
        "Grayscale bitcoin 2026",
        # Hedge funds and sovereign wealth
        "hedge fund bitcoin 2026",
        "sovereign wealth fund bitcoin 2026",
        "pension fund bitcoin investment 2026",
        "Abu Dhabi bitcoin 2026",
        "Mubadala bitcoin 2026",
        # Broad catches
        "bitcoin billion purchase 2026",
        "bitcoin million acquisition 2026",
        "biggest bitcoin buy 2026",
        "bitcoin accumulation record 2026",
    ]

    detected = []
    seen_titles = set()
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    for query in queries:
        try:
            url = f"https://news.google.com/rss/search?q={requests.utils.quote(query)}&hl=en-US&gl=US&ceid=US:en"
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code != 200:
                continue

            root = ET.fromstring(response.content)

            for item in root.findall(".//item")[:5]:
                title = item.findtext("title", "")
                pub_date = item.findtext("pubDate", "")
                link = item.findtext("link", "")

                title_key = title[:50].lower()
                if title_key in seen_titles:
                    continue
                seen_titles.add(title_key)

                try:
                    date_obj = datetime.strptime(pub_date[:25], "%a, %d %b %Y %H:%M:%S")
                    date_str = date_obj.strftime("%Y-%m-%d")
                    if (datetime.now() - date_obj).days > 30:
                        continue
                except:
                    date_str = datetime.now().strftime("%Y-%m-%d")

                title_lower = title.lower()

                # Check for purchase keywords
                has_purchase = any(k in title_lower for k in PURCHASE_KEYWORDS)
                if not has_purchase:
                    continue

                # Match entity
                matched_company = None
                matched_ticker = None
                for key, (name, ticker) in ENTITY_MAP.items():
                    if key in title_lower:
                        matched_company = name
                        matched_ticker = ticker
                        break

                if not matched_company:
                    # Try to catch generic "company buys bitcoin" articles
                    if "bitcoin" in title_lower and any(k in title_lower for k in ["buys", "bought", "purchase", "acquired"]):
                        matched_company = "Unknown Entity"
                        matched_ticker = "UNKNOWN"
                    else:
                        continue

                # Extract BTC amount
                btc_amount = 0
                usd_amount = 0

                btc_match = re.search(r'([\d,]+)\s*(?:btc|bitcoin)', title_lower)
                if btc_match:
                    try:
                        btc_amount = int(btc_match.group(1).replace(",", ""))
                    except:
                        pass

                usd_match = re.search(r'\$\s*([\d.]+)\s*(b|billion|m|million)', title_lower)
                if usd_match:
                    try:
                        amount = float(usd_match.group(1))
                        unit = usd_match.group(2)
                        if unit in ["b", "billion"]:
                            usd_amount = int(amount * 1_000_000_000)
                        elif unit in ["m", "million"]:
                            usd_amount = int(amount * 1_000_000)
                    except:
                        pass

                if usd_amount > 0 and btc_amount == 0:
                    btc_amount = int(usd_amount / 72000)
                if btc_amount > 0 and usd_amount == 0:
                    usd_amount = btc_amount * 72000

                if btc_amount > 0 or usd_amount > 0:
                    detected.append({
                        "company": matched_company,
                        "ticker": matched_ticker,
                        "btc_amount": btc_amount,
                        "usd_amount": usd_amount,
                        "price_per_btc": round(usd_amount / btc_amount) if btc_amount > 0 else 0,
                        "filing_date": date_str,
                        "source": f"News: {title[:100]}",
                        "notes": f"Auto-detected. Source: {link[:150]}",
                        "detected": True,
                    })
        except:
            continue

    # Deduplicate
    seen = set()
    unique = []
    for d in detected:
        key = f"{d['company']}_{d['filing_date']}"
        if key not in seen:
            seen.add(key)
            unique.append(d)

    unique.sort(key=lambda x: x["filing_date"], reverse=True)

    if unique:
        print(f"  🔔 Found {len(unique)} purchase(s) in news:")
        for d in unique[:5]:
            print(f"    {d['company']}: {d['btc_amount']:,} BTC (~${d['usd_amount']/1_000_000:,.0f}M) on {d['filing_date']}")
    else:
        print(f"  No new purchases found in news")

    return unique


def save_leaderboard_snapshot(btc_price=None):
    try:
        if not btc_price:
            btc = yf.Ticker("BTC-USD")
            hist = btc.history(period="5d")
            btc_price = float(hist["Close"].iloc[-1]) if not hist.empty else 72000

        companies, summary = get_leaderboard_with_live_price(btc_price)
        snapshot_date = datetime.now().strftime("%Y-%m-%d")

        holdings = {}
        for c in companies:
            if c["btc_holdings"] > 0:
                key = c.get("ticker", c["company"][:20])
                holdings[key] = {"name": c["company"], "btc": c["btc_holdings"], "country": c.get("country", "")}

        row = {
            "snapshot_date": snapshot_date,
            "btc_price": btc_price,
            "total_btc": summary["total_btc"],
            "total_value_b": summary["total_value_b"],
            "companies_json": json.dumps(holdings),
        }
        supabase.table("leaderboard_snapshots").upsert(row, on_conflict="snapshot_date").execute()
        print(f"  Snapshot saved: {snapshot_date} | {len(holdings)} entities | {summary['total_btc']:,} BTC")
        return holdings
    except Exception as e:
        print(f"  Snapshot save error: {e}")
        return None


def get_previous_snapshot():
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        result = supabase.table("leaderboard_snapshots").select("*").lt("snapshot_date", today).order("snapshot_date", desc=True).limit(1).execute()
        if result.data:
            snapshot = result.data[0]
            return {"date": snapshot["snapshot_date"], "btc_price": float(snapshot.get("btc_price", 0)), "holdings": json.loads(snapshot.get("companies_json", "{}"))}
        return None
    except Exception as e:
        print(f"  Error getting previous snapshot: {e}")
        return None


def detect_new_purchases(btc_price=None):
    print("  Detecting new purchases via snapshot comparison...")
    current_holdings = save_leaderboard_snapshot(btc_price)
    if not current_holdings:
        return []

    previous = get_previous_snapshot()
    if not previous:
        print("  No previous snapshot — purchases detected starting tomorrow.")
        return []

    prev_holdings = previous["holdings"]
    prev_date = previous["date"]
    current_btc_price = btc_price or 72000
    detected = []

    for ticker, current in current_holdings.items():
        current_btc = current["btc"]
        company_name = current["name"]

        if ticker in prev_holdings:
            prev_btc = prev_holdings[ticker]["btc"]
            increase = current_btc - prev_btc
            if increase > 50:
                detected.append({
                    "company": company_name, "ticker": ticker, "btc_amount": increase,
                    "usd_amount": round(increase * current_btc_price),
                    "price_per_btc": round(current_btc_price),
                    "filing_date": datetime.now().strftime("%Y-%m-%d"),
                    "source": "Auto-Detected (Snapshot Comparison)",
                    "notes": f"Holdings: {prev_btc:,} → {current_btc:,} BTC since {prev_date}",
                    "detected": True,
                })
        else:
            if current_btc > 10:
                detected.append({
                    "company": company_name, "ticker": ticker, "btc_amount": current_btc,
                    "usd_amount": round(current_btc * current_btc_price),
                    "price_per_btc": round(current_btc_price),
                    "filing_date": datetime.now().strftime("%Y-%m-%d"),
                    "source": "Auto-Detected (New Entity)",
                    "notes": f"First appeared with {current_btc:,} BTC",
                    "detected": True,
                })

    detected.sort(key=lambda x: x["btc_amount"], reverse=True)
    if detected:
        print(f"  🔔 {len(detected)} purchase(s) detected!")
        for d in detected[:5]:
            print(f"    {d['company']}: +{d['btc_amount']:,} BTC (~${d['usd_amount']/1_000_000:,.0f}M)")
    else:
        print(f"  No new purchases detected since {prev_date}")
    return detected


def log_detected_purchases(detected_purchases):
    logged = 0
    for p in detected_purchases:
        purchase_id = f"auto_{p['ticker']}_{p['filing_date']}"
        try:
            existing = supabase.table("confirmed_purchases").select("purchase_id").eq("purchase_id", purchase_id).execute()
            if existing.data:
                continue
            row = {
                "purchase_id": purchase_id, "company": p["company"], "ticker": p["ticker"],
                "btc_amount": p["btc_amount"], "usd_amount": p["usd_amount"],
                "price_per_btc": p["price_per_btc"], "filing_date": p["filing_date"],
                "filing_url": "", "was_predicted": False,
            }
            supabase.table("confirmed_purchases").insert(row).execute()
            logged += 1
        except:
            pass
    if logged:
        print(f"  {logged} purchase(s) logged to database")
    return logged


def get_recent_purchases(limit=20):
    """Get purchases from database + live news. No hardcoded data."""
    all_purchases = []
    db_ids = set()

    # Source 1: Database (seeded + auto-detected)
    try:
        result = supabase.table("confirmed_purchases").select("*").order("filing_date", desc=True).limit(50).execute()
        if result.data:
            for p in result.data:
                key = f"{p.get('ticker', '')}_{p.get('filing_date', '')}"
                db_ids.add(key)
                all_purchases.append({
                    "company": p.get("company", ""), "ticker": p.get("ticker", ""),
                    "btc_amount": int(float(p.get("btc_amount", 0))),
                    "usd_amount": int(float(p.get("usd_amount", 0))),
                    "price_per_btc": int(float(p.get("price_per_btc", 0))),
                    "filing_date": p.get("filing_date", ""),
                    "source": p.get("filing_url", "") or "Database",
                    "notes": "", "was_predicted": p.get("was_predicted", False),
                })
    except Exception as e:
        print(f"  Error fetching DB purchases: {e}")

    # Source 2: Live news scan (finds purchases not yet in DB)
    try:
        news_purchases = scan_news_for_purchases()
        for p in news_purchases:
            key = f"{p['ticker']}_{p['filing_date']}"
            if key not in db_ids:
                all_purchases.append(p)
                db_ids.add(key)
                # Auto-save to DB for next time
                try:
                    purchase_id = f"news_{p['ticker']}_{p['filing_date']}"
                    supabase.table("confirmed_purchases").insert({
                        "purchase_id": purchase_id, "company": p["company"], "ticker": p["ticker"],
                        "btc_amount": p["btc_amount"], "usd_amount": p["usd_amount"],
                        "price_per_btc": p["price_per_btc"], "filing_date": p["filing_date"],
                        "filing_url": p.get("source", ""), "was_predicted": False,
                    }).execute()
                except:
                    pass
    except Exception as e:
        print(f"  News scan error: {e}")

    all_purchases.sort(key=lambda x: x.get("filing_date", ""), reverse=True)

    # Deduplicate
    seen = set()
    unique = []
    for p in all_purchases:
        key = f"{p.get('company', '')}_{p.get('filing_date', '')}_{p.get('btc_amount', 0)}"
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique[:limit]


def get_purchases_by_company(ticker):
    return [p for p in get_recent_purchases(100) if p.get("ticker", "") == ticker]


def get_purchase_stats():
    all_p = get_recent_purchases(100)
    total_btc = sum(p.get("btc_amount", 0) for p in all_p)
    total_usd = sum(p.get("usd_amount", 0) for p in all_p)

    by_company = {}
    for p in all_p:
        ticker = p.get("ticker", p.get("company", "Unknown"))
        if ticker not in by_company:
            by_company[ticker] = {"company": p.get("company", ""), "ticker": ticker, "total_btc": 0, "total_usd": 0, "count": 0}
        by_company[ticker]["total_btc"] += p.get("btc_amount", 0)
        by_company[ticker]["total_usd"] += p.get("usd_amount", 0)
        by_company[ticker]["count"] += 1

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
        "total_purchases": len(all_p), "total_btc": total_btc, "total_usd": total_usd,
        "avg_price": round(total_usd / total_btc, 0) if total_btc > 0 else 0,
        "unique_companies": len(by_company),
        "by_company": sorted(by_company.values(), key=lambda x: x["total_btc"], reverse=True),
        "by_month": dict(sorted(by_month.items(), reverse=True)),
    }


def seed_confirmed_purchases():
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
            row = {"purchase_id": purchase_id, "company": p["company"], "ticker": p["ticker"],
                   "btc_amount": p["btc_amount"], "usd_amount": p["usd_amount"],
                   "price_per_btc": p["price_per_btc"], "filing_date": p["filing_date"], "filing_url": "", "was_predicted": False}
            supabase.table("confirmed_purchases").insert(row).execute()
            seeded += 1
            print(f"    ✅ {p['company']}: {p['btc_amount']:,} BTC on {p['filing_date']}")
        except:
            pass
    print(f"\n  Done: {seeded} seeded, {skipped} already existed.")
    return seeded, skipped


def format_purchase_telegram(purchase):
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


if __name__ == "__main__":
    print("\nBTC Purchase Tracker v3.0 — Comprehensive\n")
    print("=" * 60)

    print("\n[1] Saving leaderboard snapshot...")
    save_leaderboard_snapshot()

    print("\n[2] Detecting via snapshot comparison...")
    detected = detect_new_purchases()

    print("\n[3] Scanning news for purchases...")
    news = scan_news_for_purchases()

    print("\n[4] Combined purchase feed:")
    purchases = get_recent_purchases(10)
    for p in purchases:
        src = "🤖" if "Auto" in p.get("source", "") or "News" in p.get("source", "") else "📄"
        print(f"  {src} {p['filing_date']}: {p.get('company', '')} — {p.get('btc_amount', 0):,} BTC (${p.get('usd_amount', 0)/1_000_000:,.0f}M)")

    print("\n[5] Stats:")
    stats = get_purchase_stats()
    print(f"  Total: {stats['total_purchases']} purchases | {stats['total_btc']:,} BTC | ${stats['total_usd']/1_000_000_000:.1f}B")

    print("\nPurchase Tracker v3.0 is ready!")