"""
purchase_tracker.py — v3.1
---------------------------
Comprehensive BTC Purchase Tracker

Tracks purchases from ALL entity types:
- Treasury companies, Governments, Banks, Asset managers,
  Hedge funds, ETF providers, Pension funds, Sovereign wealth funds

v3.1 changes:
- 30K BTC absolute cap on single-scan purchases (safety net)
- Suffix-stripping duplicate detection: RIOT.US and RIOT are recognized
  as the same entity, preventing false purchases from ticker format mismatches
  between CoinGecko (.US absent) and BitcoinTreasuries.net (.US present)
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

logger = get_logger(__name__)

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# Known historical purchases (for seeding)
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

# Comprehensive entity map
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


# ============================================
# TICKER NORMALIZATION
# ============================================
# Common suffixes added by different data sources:
#   CoinGecko:              RIOT, MSTR, COIN
#   BitcoinTreasuries.net:  RIOT.US, MSTR.US, COIN.US
#   Yahoo Finance:          RIOT, MSTR, 3350.T
#   London Stock Exchange:  ARGO.L
#   Toronto Exchange:       HUT.TO
#
# When comparing snapshots across sources, these must be
# treated as the same entity.
TICKER_SUFFIXES = [".US", ".L", ".TO", ".AX", ".DE", ".PA", ".SW", ".HK", ".KS", ".SS", ".SZ", ".SA", ".V", ".ST", ".CO", ".MI", ".BR", ".MC", ".OL", ".HE", ".IS"]


def _normalize_ticker(ticker):
    """
    Strip exchange suffixes to get the base ticker.
    MSTR.US → MSTR, RIOT.US → RIOT, HUT.TO → HUT
    Preserves Japanese tickers like 3350.T (Tokyo) since .T is not in suffix list.
    """
    upper = ticker.upper()
    for suffix in TICKER_SUFFIXES:
        if upper.endswith(suffix):
            return upper[:-len(suffix)]
    return upper


def _build_normalized_lookup(holdings):
    """
    Build a lookup dict that maps normalized tickers to their snapshot data.
    If RIOT and RIOT.US both exist, the one with more BTC wins.
    Returns: {normalized_ticker: {"btc": int, "name": str, "original_ticker": str}}
    """
    lookup = {}
    for ticker, data in holdings.items():
        norm = _normalize_ticker(ticker)
        if norm not in lookup or data["btc"] > lookup[norm]["btc"]:
            lookup[norm] = {
                "btc": data["btc"],
                "name": data["name"],
                "country": data.get("country", ""),
                "original_ticker": ticker,
            }
    return lookup


def scan_news_for_purchases():
    """Scan Google News RSS for recent BTC purchase announcements."""
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
        logger.info(f"Found {len(unique)} purchase(s) in news")
        freshness.record_success("google_news_purchases", detail=f"{len(unique)} purchases found")
        for d in unique[:5]:
            logger.debug(f"  {d['company']}: {d['btc_amount']:,} BTC (~${d['usd_amount']/1_000_000:,.0f}M) on {d['filing_date']}")
    else:
        logger.debug("No new purchases found in news")
        freshness.record_success("google_news_purchases", detail="No new purchases")

    return unique


def save_leaderboard_snapshot(btc_price=None):
    """Save today's leaderboard snapshot for comparison."""
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
        logger.info(f"Snapshot saved: {snapshot_date} | {len(holdings)} entities | {summary['total_btc']:,} BTC")
        return holdings
    except Exception as e:
        logger.error(f"Snapshot save failed: {e}", exc_info=True)
        return None


def get_previous_snapshot():
    """Get yesterday's snapshot for comparison."""
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


# Maximum credible BTC increase in a single scan cycle (60 minutes).
# Safety net — the real protection is suffix-stripping duplicate detection.
MAX_SINGLE_SCAN_PURCHASE_BTC = 30000


def detect_new_purchases(btc_price=None):
    """
    Detect new purchases by comparing today's vs previous snapshot.
    
    Uses normalized ticker matching to prevent false positives from
    different data sources using different ticker formats (e.g.,
    CoinGecko uses "RIOT" while BitcoinTreasuries.net uses "RIOT.US").
    
    Government/sovereign entities are EXCLUDED because their holdings
    data comes from inconsistent sources which creates false positives.
    """
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

    # Tickers to exclude from snapshot comparison (government entities
    # have unreliable data that fluctuates between live/fallback sources)
    GOVERNMENT_TICKERS = {t for t in current_holdings if t.endswith("-GOV")}
    GOVERNMENT_TICKERS.update(t for t in prev_holdings if t.endswith("-GOV"))

    # Build normalized lookup for previous snapshot so we can match
    # RIOT.US (current) to RIOT (previous) as the same entity
    prev_normalized = _build_normalized_lookup(prev_holdings)

    for ticker, current in current_holdings.items():
        current_btc = current["btc"]
        company_name = current["name"]

        # Skip government entities — their data is inconsistent
        if ticker in GOVERNMENT_TICKERS:
            logger.debug(f"Skipping government entity {ticker} from purchase detection")
            continue

        # Normalize the current ticker for comparison
        norm_ticker = _normalize_ticker(ticker)

        # First: check exact ticker match in previous snapshot
        # Second: check normalized ticker match (handles RIOT vs RIOT.US)
        if ticker in prev_holdings:
            # Exact match — compare holdings directly
            prev_btc = prev_holdings[ticker]["btc"]
            increase = current_btc - prev_btc

            # Reject increases above the absolute cap
            if increase >= MAX_SINGLE_SCAN_PURCHASE_BTC:
                logger.warning(
                    f"Rejected: {company_name} ({ticker}): "
                    f"{prev_btc:,} → {current_btc:,} BTC (+{increase:,}). "
                    f"Exceeds {MAX_SINGLE_SCAN_PURCHASE_BTC:,} BTC single-scan cap."
                )
            # Reject increases >10x previous holdings (data glitch)
            elif increase > 50 and prev_btc > 0 and increase >= prev_btc * 10:
                logger.warning(
                    f"Suspicious increase for {company_name} ({ticker}): "
                    f"{prev_btc:,} → {current_btc:,} BTC (+{increase:,}). "
                    f"Likely a data source change. Skipping."
                )
            # Valid purchase detected
            elif increase > 50:
                detected.append({
                    "company": company_name, "ticker": ticker, "btc_amount": increase,
                    "usd_amount": round(increase * current_btc_price),
                    "price_per_btc": round(current_btc_price),
                    "filing_date": datetime.now().strftime("%Y-%m-%d"),
                    "source": "Auto-Detected (Snapshot Comparison)",
                    "notes": f"Holdings: {prev_btc:,} → {current_btc:,} BTC since {prev_date}",
                    "detected": True,
                })

        elif norm_ticker in prev_normalized:
            # No exact match, but normalized match found
            # e.g., current has RIOT.US, previous has RIOT → same entity
            prev_data = prev_normalized[norm_ticker]
            prev_btc = prev_data["btc"]
            increase = current_btc - prev_btc

            logger.debug(
                f"Matched {ticker} → {prev_data['original_ticker']} via normalization "
                f"({prev_btc:,} → {current_btc:,} BTC)"
            )

            # Reject increases above the absolute cap
            if increase >= MAX_SINGLE_SCAN_PURCHASE_BTC:
                logger.warning(
                    f"Rejected (normalized match): {company_name} ({ticker}↔{prev_data['original_ticker']}): "
                    f"{prev_btc:,} → {current_btc:,} BTC (+{increase:,}). "
                    f"Exceeds {MAX_SINGLE_SCAN_PURCHASE_BTC:,} BTC cap."
                )
            # Reject increases >10x previous holdings
            elif increase > 50 and prev_btc > 0 and increase >= prev_btc * 10:
                logger.warning(
                    f"Suspicious (normalized match): {company_name} ({ticker}↔{prev_data['original_ticker']}): "
                    f"{prev_btc:,} → {current_btc:,} BTC (+{increase:,}). Skipping."
                )
            # Valid purchase detected via normalized match
            elif increase > 50:
                detected.append({
                    "company": company_name, "ticker": ticker, "btc_amount": increase,
                    "usd_amount": round(increase * current_btc_price),
                    "price_per_btc": round(current_btc_price),
                    "filing_date": datetime.now().strftime("%Y-%m-%d"),
                    "source": "Auto-Detected (Snapshot Comparison)",
                    "notes": f"Holdings: {prev_btc:,} → {current_btc:,} BTC since {prev_date} (ticker: {prev_data['original_ticker']}→{ticker})",
                    "detected": True,
                })
            # If increase <= 50 or negative, it's just the same entity with no meaningful change

        else:
            # Truly new entity — not found in previous snapshot even after normalization
            if ticker in GOVERNMENT_TICKERS:
                continue

            if current_btc > 100 and current_btc < MAX_SINGLE_SCAN_PURCHASE_BTC:
                detected.append({
                    "company": company_name, "ticker": ticker, "btc_amount": current_btc,
                    "usd_amount": round(current_btc * current_btc_price),
                    "price_per_btc": round(current_btc_price),
                    "filing_date": datetime.now().strftime("%Y-%m-%d"),
                    "source": "Auto-Detected (New Entity)",
                    "notes": f"First appeared with {current_btc:,} BTC",
                    "detected": True,
                })
            elif current_btc >= MAX_SINGLE_SCAN_PURCHASE_BTC:
                logger.warning(
                    f"Rejected new entrant: {company_name} ({ticker}) with {current_btc:,} BTC. "
                    f"Exceeds {MAX_SINGLE_SCAN_PURCHASE_BTC:,} BTC cap — likely pre-existing entity."
                )

    detected.sort(key=lambda x: x["btc_amount"], reverse=True)
    if detected:
        logger.info(f"{len(detected)} purchase(s) detected!")
        for d in detected[:5]:
            logger.info(f"  {d['company']}: +{d['btc_amount']:,} BTC (~${d['usd_amount']/1_000_000:,.0f}M)")
    else:
        logger.info(f"No new purchases detected since {prev_date}")
    return detected


def log_detected_purchases(detected_purchases):
    """Log detected purchases to Supabase."""
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
        except Exception as e:
            logger.error(f"Failed to log purchase {purchase_id}: {e}")
    if logged:
        logger.info(f"{logged} purchase(s) logged to database")
    return logged


def get_recent_purchases(limit=20):
    """Get purchases from database + live news."""
    all_purchases = []
    db_ids = set()

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
        logger.error(f"Error fetching DB purchases: {e}", exc_info=True)

    try:
        news_purchases = scan_news_for_purchases()
        for p in news_purchases:
            key = f"{p['ticker']}_{p['filing_date']}"
            if key not in db_ids:
                all_purchases.append(p)
                db_ids.add(key)
                try:
                    purchase_id = f"news_{p['ticker']}_{p['filing_date']}"
                    supabase.table("confirmed_purchases").insert({
                        "purchase_id": purchase_id, "company": p["company"], "ticker": p["ticker"],
                        "btc_amount": p["btc_amount"], "usd_amount": p["usd_amount"],
                        "price_per_btc": p["price_per_btc"], "filing_date": p["filing_date"],
                        "filing_url": p.get("source", ""), "was_predicted": False,
                    }).execute()
                except Exception as e:
                    logger.debug(f"Could not auto-save news purchase: {e}")
    except Exception as e:
        logger.error(f"News scan error in get_recent_purchases: {e}", exc_info=True)

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
            logger.info(f"Seeded: {p['company']}: {p['btc_amount']:,} BTC on {p['filing_date']}")
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
    logger.info("BTC Purchase Tracker v3.1 — testing...")
    purchases = get_recent_purchases(10)
    stats = get_purchase_stats()
    logger.info(f"Total: {stats['total_purchases']} purchases | {stats['total_btc']:,} BTC | ${stats['total_usd']/1_000_000_000:.1f}B")
    logger.info("Purchase Tracker test complete")
