"""
purchase_tracker.py — v3.2
---------------------------
Comprehensive BTC Purchase Tracker

All purchase detections now go through purchase_reconciler.py which handles:
- Deduplication (same company, ±3 days, ±20% BTC)
- Source hierarchy (EDGAR > Global Filing > News > Snapshot)
- Pending verification for snapshot "new entrants"
- Confirmation bridge and expiry

v3.2 changes:
- All writes go through reconcile_and_save() instead of direct DB inserts
- Snapshot "new entrants" go to pending_purchases (not confirmed)
- Snapshot "existing entity increases" go through reconciler for dedup
- News-detected purchases go through reconciler for dedup
- Ticker normalization for cross-source entity matching
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
from logger import get_logger
from freshness_tracker import freshness
from purchase_reconciler import reconcile_and_save

logger = get_logger(__name__)

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


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

ENTITY_MAP = {
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
    "jpmorgan": ("JPMorgan Chase", "JPM"), "jp morgan": ("JPMorgan Chase", "JPM"),
    "goldman sachs": ("Goldman Sachs", "GS"), "goldman": ("Goldman Sachs", "GS"),
    "morgan stanley": ("Morgan Stanley", "MS"),
    "bank of america": ("Bank of America", "BAC"), "bofa": ("Bank of America", "BAC"),
    "blackrock": ("BlackRock", "BLK"), "ishares": ("BlackRock", "BLK"),
    "fidelity": ("Fidelity Investments", "FNF"),
    "ark invest": ("ARK Invest", "ARKK"), "cathie wood": ("ARK Invest", "ARKK"),
    "grayscale": ("Grayscale (DCG)", "GBTC"),
    "el salvador": ("El Salvador Government", "SV-GOV"),
    "bukele": ("El Salvador Government", "SV-GOV"),
    "bhutan": ("Bhutan Government", "BT-GOV"),
    "ibit": ("BlackRock Bitcoin ETF (IBIT)", "IBIT"),
    "fbtc": ("Fidelity Bitcoin ETF (FBTC)", "FBTC"),
    "bitcoin etf": ("Bitcoin ETF", "ETF"),
    "spot bitcoin etf": ("Spot Bitcoin ETF", "ETF"),
    "mubadala": ("Mubadala (Abu Dhabi)", "MUBADALA"),
    "abu dhabi": ("Abu Dhabi Investment Authority", "AE-SWF"),
}

PURCHASE_KEYWORDS = [
    "bought", "buys", "purchase", "purchased", "acquired", "acquisition",
    "adds", "added", "accumulate", "accumulated", "invest", "invested",
    "allocated", "allocation", "treasury", "reserve", "holdings",
    "increased holdings", "bought more", "added to", "snaps up",
    "acquires", "scoops up", "loads up", "stacks",
]

TICKER_SUFFIXES = [".US", ".L", ".TO", ".AX", ".DE", ".PA", ".SW", ".HK", ".KS", ".SS", ".SZ", ".SA", ".V", ".ST", ".CO", ".MI", ".BR", ".MC", ".OL", ".HE", ".IS"]


def _normalize_ticker(ticker):
    upper = ticker.upper()
    for suffix in TICKER_SUFFIXES:
        if upper.endswith(suffix):
            return upper[:-len(suffix)]
    return upper


def _build_normalized_lookup(holdings):
    lookup = {}
    for ticker, data in holdings.items():
        norm = _normalize_ticker(ticker)
        if norm not in lookup or data["btc"] > lookup[norm]["btc"]:
            lookup[norm] = {"btc": data["btc"], "name": data["name"], "country": data.get("country", ""), "original_ticker": ticker}
    return lookup


def scan_news_for_purchases():
    logger.info("Scanning news for recent BTC purchases...")
    queries = [
        "bitcoin purchase company 2026", "bitcoin treasury buy 2026",
        "corporate bitcoin acquisition 2026", "company buys bitcoin 2026",
        "MicroStrategy Strategy bitcoin buy 2026", "Metaplanet bitcoin 2026",
        "MARA bitcoin purchase 2026", "GameStop bitcoin 2026",
        "government bitcoin purchase 2026", "El Salvador bitcoin buy 2026",
        "BlackRock bitcoin ETF inflow 2026", "Fidelity bitcoin ETF 2026",
        "bitcoin billion purchase 2026", "bitcoin million acquisition 2026",
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
                except ValueError:
                    date_str = datetime.now().strftime("%Y-%m-%d")
                title_lower = title.lower()
                has_purchase = any(k in title_lower for k in PURCHASE_KEYWORDS)
                if not has_purchase:
                    continue
                matched_company = None
                matched_ticker = None
                for key, (name, ticker) in ENTITY_MAP.items():
                    if key in title_lower:
                        matched_company = name
                        matched_ticker = ticker
                        break
                if not matched_company:
                    if "bitcoin" in title_lower and any(k in title_lower for k in ["buys", "bought", "purchase", "acquired"]):
                        matched_company = "Unknown Entity"
                        matched_ticker = "UNKNOWN"
                    else:
                        continue
                btc_amount = 0
                usd_amount = 0
                btc_match = re.search(r'([\d,]+)\s*(?:btc|bitcoin)', title_lower)
                if btc_match:
                    try:
                        btc_amount = int(btc_match.group(1).replace(",", ""))
                    except ValueError:
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
                    except ValueError:
                        pass
                if usd_amount > 0 and btc_amount == 0:
                    btc_amount = int(usd_amount / 72000)
                if btc_amount > 0 and usd_amount == 0:
                    usd_amount = btc_amount * 72000
                if btc_amount > 0 or usd_amount > 0:
                    detected.append({
                        "company": matched_company, "ticker": matched_ticker,
                        "btc_amount": btc_amount, "usd_amount": usd_amount,
                        "price_per_btc": round(usd_amount / btc_amount) if btc_amount > 0 else 0,
                        "filing_date": date_str,
                        "source": f"News: {title[:100]}",
                        "notes": f"Auto-detected. Source: {link[:150]}",
                        "detected": True,
                    })
        except Exception as e:
            logger.debug(f"News query failed for '{query}': {e}")
            continue

    seen = set()
    unique = []
    for d in detected:
        key = f"{d['company']}_{d['filing_date']}"
        if key not in seen:
            seen.add(key)
            unique.append(d)
    unique.sort(key=lambda x: x["filing_date"], reverse=True)

    if unique:
        logger.info(f"Found {len(unique)} purchase(s) in news")
        freshness.record_success("google_news_purchases", detail=f"{len(unique)} purchases found")
    else:
        logger.debug("No new purchases found in news")
        freshness.record_success("google_news_purchases", detail="No new purchases")

    reconciled = 0
    for p in unique:
        result = reconcile_and_save(p, source_type="news", is_new_entrant=False)
        if result["action"] in ("confirmed", "upgraded", "pending_confirmed"):
            reconciled += 1
    if reconciled:
        logger.info(f"News scanner: {reconciled} purchase(s) reconciled")
    return unique


def save_leaderboard_snapshot(btc_price=None):
    try:
        if not btc_price:
            btc = yf.Ticker("BTC-USD")
            hist = btc.history(period="5d")
            btc_price = float(hist["Close"].iloc[-1]) if not hist.empty else 72000

        # Query ALL entities from treasury_companies (not just leaderboard)
        # This captures private companies, ETFs, DeFi — not just CoinGecko public companies
        result = supabase.table("treasury_companies").select(
            "ticker, company, btc_holdings, country, is_government"
        ).gt("btc_holdings", 0).execute()

        all_entities = result.data if result.data else []
        snapshot_date = datetime.now().strftime("%Y-%m-%d")

        holdings = {}
        total_btc = 0
        for c in all_entities:
            btc_held = c.get("btc_holdings", 0) or 0
            if btc_held > 0:
                key = c.get("ticker", c.get("company", "UNK")[:20])
                holdings[key] = {
                    "name": c.get("company", key),
                    "btc": btc_held,
                    "country": c.get("country", ""),
                }
                total_btc += btc_held

        total_value_b = round((total_btc * btc_price) / 1_000_000_000, 2)

        row = {
            "snapshot_date": snapshot_date, "btc_price": btc_price,
            "total_btc": total_btc, "total_value_b": total_value_b,
            "companies_json": json.dumps(holdings),
        }
        supabase.table("leaderboard_snapshots").upsert(row, on_conflict="snapshot_date").execute()
        logger.info(f"Snapshot saved: {snapshot_date} | {len(holdings)} entities | {total_btc:,} BTC")
        return holdings
    except Exception as e:
        logger.error(f"Snapshot save failed: {e}", exc_info=True)
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
        logger.error(f"Error getting previous snapshot: {e}", exc_info=True)
        return None


MAX_SINGLE_SCAN_PURCHASE_BTC = 30000


def detect_new_purchases(btc_price=None):
    logger.info("Detecting new purchases via snapshot comparison...")
    current_holdings = save_leaderboard_snapshot(btc_price)
    if not current_holdings:
        return []
    previous = get_previous_snapshot()
    if not previous:
        logger.info("No previous snapshot — purchases detected starting tomorrow")
        return []

    prev_holdings = previous["holdings"]
    prev_date = previous["date"]
    current_btc_price = btc_price or 72000
    detected = []

    GOVERNMENT_TICKERS = {t for t in current_holdings if t.endswith("-GOV")}
    GOVERNMENT_TICKERS.update(t for t in prev_holdings if t.endswith("-GOV"))
    prev_normalized = _build_normalized_lookup(prev_holdings)

    for ticker, current in current_holdings.items():
        current_btc = current["btc"]
        company_name = current["name"]
        if ticker in GOVERNMENT_TICKERS:
            continue
        # Skip garbled entities — non-ASCII names or tickers with BTC amounts
        if company_name and not (company_name[0].isascii() and company_name[0].isalpha()):
            continue
        if ticker and not ticker[0].isascii():
            continue
        norm_ticker = _normalize_ticker(ticker)

        # ─── Exact ticker match ───
        if ticker in prev_holdings:
            prev_btc = prev_holdings[ticker]["btc"]
            increase = current_btc - prev_btc
            if increase >= MAX_SINGLE_SCAN_PURCHASE_BTC:
                logger.warning(f"Rejected: {company_name} ({ticker}): +{increase:,} BTC exceeds cap")
            elif increase > 50 and prev_btc > 0 and increase >= prev_btc * 10:
                logger.warning(f"Suspicious: {company_name} ({ticker}): +{increase:,} BTC (>10x). Skipping.")
            elif increase > 50:
                purchase = {
                    "company": company_name, "ticker": ticker, "btc_amount": increase,
                    "usd_amount": round(increase * current_btc_price),
                    "price_per_btc": round(current_btc_price),
                    "filing_date": datetime.now().strftime("%Y-%m-%d"),
                    "source": "Auto-Detected (Snapshot Comparison)",
                    "notes": f"Holdings: {prev_btc:,} → {current_btc:,} BTC since {prev_date}",
                }
                result = reconcile_and_save(purchase, source_type="snapshot", is_new_entrant=False)
                if result["action"] in ("confirmed", "upgraded"):
                    detected.append(purchase)

        # ─── Normalized ticker match ───
        elif norm_ticker in prev_normalized:
            prev_data = prev_normalized[norm_ticker]
            prev_btc = prev_data["btc"]
            increase = current_btc - prev_btc
            logger.debug(f"Matched {ticker} → {prev_data['original_ticker']} via normalization")
            if increase >= MAX_SINGLE_SCAN_PURCHASE_BTC:
                logger.warning(f"Rejected (normalized): {company_name} ({ticker}↔{prev_data['original_ticker']}): +{increase:,} BTC exceeds cap")
            elif increase > 50 and prev_btc > 0 and increase >= prev_btc * 10:
                logger.warning(f"Suspicious (normalized): {company_name} ({ticker}↔{prev_data['original_ticker']}): +{increase:,} BTC. Skipping.")
            elif increase > 50:
                purchase = {
                    "company": company_name, "ticker": ticker, "btc_amount": increase,
                    "usd_amount": round(increase * current_btc_price),
                    "price_per_btc": round(current_btc_price),
                    "filing_date": datetime.now().strftime("%Y-%m-%d"),
                    "source": "Auto-Detected (Snapshot Comparison)",
                    "notes": f"Holdings: {prev_btc:,} → {current_btc:,} BTC since {prev_date} (ticker: {prev_data['original_ticker']}→{ticker})",
                }
                result = reconcile_and_save(purchase, source_type="snapshot", is_new_entrant=False)
                if result["action"] in ("confirmed", "upgraded"):
                    detected.append(purchase)

        # ─── Truly new entity → PENDING (not confirmed) ───
        else:
            if ticker in GOVERNMENT_TICKERS:
                continue
            if current_btc >= 10:  # 10 BTC minimum — filters scraping noise but catches real small purchases
                purchase = {
                    "company": company_name, "ticker": ticker, "btc_amount": current_btc,
                    "usd_amount": round(current_btc * current_btc_price),
                    "price_per_btc": round(current_btc_price),
                    "filing_date": datetime.now().strftime("%Y-%m-%d"),
                    "source": "Auto-Detected (New Entity — Pending Verification)",
                    "notes": f"First appeared with {current_btc:,} BTC. Awaiting confirmation.",
                }
                result = reconcile_and_save(purchase, source_type="snapshot", is_new_entrant=True)
                logger.debug(f"New entrant {company_name}: {result['action']}")

    detected.sort(key=lambda x: x["btc_amount"], reverse=True)
    if detected:
        logger.info(f"{len(detected)} purchase(s) detected and reconciled!")
        for d in detected[:5]:
            logger.info(f"  {d['company']}: +{d['btc_amount']:,} BTC (~${d['usd_amount']/1_000_000:,.0f}M)")
    else:
        logger.info(f"No new purchases detected since {prev_date}")
    return detected


def log_detected_purchases(detected_purchases):
    return len(detected_purchases)


def get_recent_purchases(limit=20):
    all_purchases = []
    try:
        result = supabase.table("confirmed_purchases").select("*").order("filing_date", desc=True).limit(50).execute()
        if result.data:
            for p in result.data:
                all_purchases.append({
                    "company": p.get("company", ""), "ticker": p.get("ticker", ""),
                    "btc_amount": int(float(p.get("btc_amount", 0))),
                    "usd_amount": int(float(p.get("usd_amount", 0))),
                    "price_per_btc": int(float(p.get("price_per_btc", 0))),
                    "filing_date": p.get("filing_date", ""),
                    "source": p.get("filing_url", "") or p.get("source", "") or "Database",
                    "notes": "", "was_predicted": p.get("was_predicted", False),
                })
    except Exception as e:
        logger.error(f"Error fetching DB purchases: {e}", exc_info=True)

    all_purchases.sort(key=lambda x: x.get("filing_date", ""), reverse=True)
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
    logger.info("Seeding confirmed purchases into Supabase...")
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
        except Exception as e:
            logger.error(f"Seed failed for {purchase_id}: {e}")
    logger.info(f"Seeding complete: {seeded} seeded, {skipped} already existed")
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
    logger.info("BTC Purchase Tracker v3.2 — testing...")
    purchases = get_recent_purchases(10)
    stats = get_purchase_stats()
    logger.info(f"Total: {stats['total_purchases']} purchases | {stats['total_btc']:,} BTC | ${stats['total_usd']/1_000_000_000:.1f}B")
    logger.info("Purchase Tracker test complete")
