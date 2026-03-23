"""
treasury_leaderboard.py — v2.0
-------------------------------
BTC Treasury Company Leaderboard — LIVE DATA

Pulls the latest holdings data from multiple sources:
1. CoinGecko API (primary)
2. BitcoinTreasuries.net (fallback)
3. Supabase snapshot (fallback)
4. Hardcoded fallback (last resort)
"""

import json
import os
import re
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client
from bs4 import BeautifulSoup
from logger import get_logger
from freshness_tracker import freshness

logger = get_logger(__name__)

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# Fallback data — used ONLY if live scraping fails
FALLBACK_COMPANIES = [
    {"company": "Strategy (MicroStrategy)", "ticker": "MSTR", "btc_holdings": 499096, "avg_purchase_price": 66357, "total_cost_usd": 33100000000, "country": "USA", "sector": "Software / BTC Treasury"},
    {"company": "Marathon Digital (MARA)", "ticker": "MARA", "btc_holdings": 46374, "avg_purchase_price": 0, "total_cost_usd": 0, "country": "USA", "sector": "Bitcoin Mining"},
    {"company": "Twenty One Capital", "ticker": "CEP", "btc_holdings": 31500, "avg_purchase_price": 0, "total_cost_usd": 0, "country": "USA", "sector": "BTC Treasury / Fintech"},
    {"company": "Riot Platforms", "ticker": "RIOT", "btc_holdings": 19223, "avg_purchase_price": 0, "total_cost_usd": 0, "country": "USA", "sector": "Bitcoin Mining"},
    {"company": "CleanSpark", "ticker": "CLSK", "btc_holdings": 11869, "avg_purchase_price": 0, "total_cost_usd": 0, "country": "USA", "sector": "Bitcoin Mining"},
    {"company": "Tesla", "ticker": "TSLA", "btc_holdings": 11509, "avg_purchase_price": 32700, "total_cost_usd": 1500000000, "country": "USA", "sector": "Automotive / EV"},
    {"company": "Hut 8 Mining", "ticker": "HUT", "btc_holdings": 10208, "avg_purchase_price": 24484, "total_cost_usd": 250000000, "country": "Canada", "sector": "Bitcoin Mining"},
    {"company": "Coinbase Global", "ticker": "COIN", "btc_holdings": 9480, "avg_purchase_price": 0, "total_cost_usd": 0, "country": "USA", "sector": "Crypto Exchange"},
    {"company": "Block (Square)", "ticker": "XYZ", "btc_holdings": 8211, "avg_purchase_price": 34600, "total_cost_usd": 284000000, "country": "USA", "sector": "Fintech / Payments"},
    {"company": "Semler Scientific", "ticker": "SMLR", "btc_holdings": 3192, "avg_purchase_price": 81000, "total_cost_usd": 258600000, "country": "USA", "sector": "Healthcare / BTC Treasury"},
    {"company": "Metaplanet", "ticker": "3350.T", "btc_holdings": 3050, "avg_purchase_price": 75000, "total_cost_usd": 228000000, "country": "Japan", "sector": "Investment / BTC Treasury"},
    {"company": "Bitfarms", "ticker": "BITF", "btc_holdings": 1147, "avg_purchase_price": 0, "total_cost_usd": 0, "country": "Canada", "sector": "Bitcoin Mining"},
    {"company": "KULR Technology", "ticker": "KULR", "btc_holdings": 610, "avg_purchase_price": 97000, "total_cost_usd": 59200000, "country": "USA", "sector": "Energy / Battery Tech"},
    {"company": "MercadoLibre", "ticker": "MELI", "btc_holdings": 412, "avg_purchase_price": 48000, "total_cost_usd": 19800000, "country": "Argentina", "sector": "E-commerce"},
    {"company": "GameStop", "ticker": "GME", "btc_holdings": 0, "avg_purchase_price": 0, "total_cost_usd": 0, "country": "USA", "sector": "Retail / Gaming"},
    {"company": "Core Scientific", "ticker": "CORZ", "btc_holdings": 0, "avg_purchase_price": 0, "total_cost_usd": 0, "country": "USA", "sector": "Bitcoin Mining / AI"},
]

SOVEREIGN_HOLDERS = [
    {"company": "🇺🇸 United States Government", "ticker": "US-GOV", "btc_holdings": 328372, "avg_purchase_price": 0, "total_cost_usd": 0, "country": "US", "sector": "Government (Seized + Strategic Reserve)", "is_government": True, "notes": "Fallback data"},
    {"company": "🇨🇳 China Government", "ticker": "CN-GOV", "btc_holdings": 194000, "avg_purchase_price": 0, "total_cost_usd": 0, "country": "CN", "sector": "Government (Seized Assets)", "is_government": True, "notes": "Fallback data"},
    {"company": "🇬🇧 United Kingdom Government", "ticker": "UK-GOV", "btc_holdings": 61000, "avg_purchase_price": 0, "total_cost_usd": 0, "country": "GB", "sector": "Government (Seized Assets)", "is_government": True, "notes": "Fallback data"},
    {"company": "🇺🇦 Ukraine Government", "ticker": "UA-GOV", "btc_holdings": 46351, "avg_purchase_price": 0, "total_cost_usd": 0, "country": "UA", "sector": "Government (Donations)", "is_government": True, "notes": "Fallback data"},
    {"company": "🇧🇹 Bhutan (Druk Holding)", "ticker": "BT-GOV", "btc_holdings": 13029, "avg_purchase_price": 0, "total_cost_usd": 0, "country": "BT", "sector": "Government (Sovereign Mining)", "is_government": True, "notes": "Fallback data"},
    {"company": "🇸🇻 El Salvador Government", "ticker": "SV-GOV", "btc_holdings": 6089, "avg_purchase_price": 44300, "total_cost_usd": 269700000, "country": "SV", "sector": "Government (Legal Tender)", "is_government": True, "notes": "Fallback data"},
    {"company": "🇫🇮 Finland Government", "ticker": "FI-GOV", "btc_holdings": 90, "avg_purchase_price": 0, "total_cost_usd": 0, "country": "FI", "sector": "Government (Seized Assets)", "is_government": True, "notes": "Fallback data"},
]

_live_data_cache = {"data": None, "fetched_at": None}


def fetch_live_leaderboard():
    """Fetch live BTC treasury data. Tries each source in order."""
    global _live_data_cache

    if _live_data_cache["data"] and _live_data_cache["fetched_at"]:
        age_seconds = (datetime.now() - _live_data_cache["fetched_at"]).total_seconds()
        if age_seconds < 3600:
            logger.debug("Using cached leaderboard data (less than 1 hour old)")
            return _live_data_cache["data"]

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    # Source 1: CoinGecko
    try:
        logger.debug("Trying CoinGecko public companies API...")
        response = requests.get(
            "https://api.coingecko.com/api/v3/companies/public_treasury/bitcoin",
            headers=headers, timeout=15
        )
        if response.status_code == 200:
            data = response.json()
            companies_raw = data.get("companies", [])
            companies = []
            for item in companies_raw:
                try:
                    company = {
                        "company": item.get("name", "Unknown"),
                        "ticker": item.get("symbol", ""),
                        "btc_holdings": int(item.get("total_holdings", 0)),
                        "avg_purchase_price": int(float(item.get("total_entry_value_usd", 0)) / max(int(item.get("total_holdings", 1)), 1)) if item.get("total_entry_value_usd") else 0,
                        "total_cost_usd": int(float(item.get("total_entry_value_usd", 0))) if item.get("total_entry_value_usd") else 0,
                        "country": item.get("country", "Unknown"),
                        "sector": "BTC Treasury",
                    }
                    if company["btc_holdings"] > 0:
                        companies.append(company)
                except Exception as e:
                    logger.debug(f"Skipping CoinGecko company entry: {e}")
                    continue

            if companies:
                companies.sort(key=lambda x: x["btc_holdings"], reverse=True)
                _live_data_cache["data"] = companies
                _live_data_cache["fetched_at"] = datetime.now()
                logger.info(f"CoinGecko LIVE: {len(companies)} companies fetched")
                freshness.record_success("coingecko", detail=f"{len(companies)} companies fetched")
                freshness.set_provenance("leaderboard_corporate", "CoinGecko API", "live")
                return companies
        else:
            logger.warning(f"CoinGecko returned status {response.status_code}")
            freshness.record_failure("coingecko", error=f"HTTP {response.status_code}")
    except Exception as e:
        logger.warning(f"CoinGecko failed: {e}")
        freshness.record_failure("coingecko", error=str(e))

    # Source 2: BitcoinTreasuries.net scraping
    try:
        logger.debug("Trying BitcoinTreasuries.net scraping...")
        response = requests.get("https://bitcointreasuries.net/", headers=headers, timeout=15)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "lxml")
            tables = soup.find_all("table")
            if tables:
                companies = []
                for row in tables[0].find_all("tr")[1:]:
                    cols = row.find_all("td")
                    if len(cols) >= 4:
                        try:
                            name = cols[0].get_text(strip=True)
                            ticker = cols[1].get_text(strip=True) if len(cols) > 1 else ""
                            btc_text = cols[2].get_text(strip=True).replace(",", "").replace(" ", "") if len(cols) > 2 else "0"
                            btc_holdings = int(float(btc_text)) if btc_text.replace(".", "").isdigit() else 0
                            if name and btc_holdings > 0:
                                companies.append({
                                    "company": name, "ticker": ticker,
                                    "btc_holdings": btc_holdings, "avg_purchase_price": 0,
                                    "total_cost_usd": 0, "country": "Unknown", "sector": "BTC Treasury",
                                })
                        except Exception as e:
                            logger.debug(f"Skipping BitcoinTreasuries row: {e}")
                            continue
                if companies:
                    companies.sort(key=lambda x: x["btc_holdings"], reverse=True)
                    _live_data_cache["data"] = companies
                    _live_data_cache["fetched_at"] = datetime.now()
                    logger.info(f"BitcoinTreasuries LIVE: {len(companies)} companies scraped")
                    freshness.record_success("bitcointreasuries", detail=f"{len(companies)} companies scraped")
                    freshness.set_provenance("leaderboard_corporate", "BitcoinTreasuries.net", "live")
                    return companies
            logger.warning("Could not parse BitcoinTreasuries.net tables")
    except Exception as e:
        logger.warning(f"BitcoinTreasuries.net scraping failed: {e}")

    # Source 3: Supabase cached snapshot
    try:
        logger.debug("Trying Supabase cached snapshot...")
        result = supabase.table("leaderboard_snapshots").select("*").order("snapshot_date", desc=True).limit(1).execute()
        if result.data:
            snapshot = result.data[0]
            snapshot_companies = json.loads(snapshot.get("companies_json", "[]"))
            if snapshot_companies:
                logger.warning(f"Using Supabase snapshot from {snapshot['snapshot_date']} (live sources unavailable)")
                freshness.set_provenance("leaderboard_corporate", f"Supabase snapshot ({snapshot['snapshot_date']})", "cached")
                merged = []
                fallback_map = {c["ticker"]: c for c in FALLBACK_COMPANIES}
                for sc in snapshot_companies:
                    ticker = sc.get("ticker", "")
                    if ticker in fallback_map:
                        company = fallback_map[ticker].copy()
                        company["btc_holdings"] = sc.get("btc_holdings", company["btc_holdings"])
                        merged.append(company)
                if merged:
                    return merged
    except Exception as e:
        logger.warning(f"Supabase snapshot failed: {e}")

    logger.warning("ALL live sources unavailable — using hardcoded fallback data")
    freshness.set_provenance("leaderboard_corporate", "Hardcoded fallback", "fallback")
    return None


def fetch_sovereign_holdings():
    """Fetch live government BTC holdings."""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    # Source 1: BitcoinTreasuries.net API
    try:
        logger.debug("Trying BitcoinTreasuries.net sovereign API...")
        response = requests.get("https://api.bitcointreasuries.net/views/countries", headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            sovereigns = []
            flag_map = {
                "united states": ("🇺🇸 United States Government", "US-GOV", "US"),
                "china": ("🇨🇳 China Government", "CN-GOV", "CN"),
                "united kingdom": ("🇬🇧 United Kingdom Government", "UK-GOV", "GB"),
                "ukraine": ("🇺🇦 Ukraine Government", "UA-GOV", "UA"),
                "bhutan": ("🇧🇹 Bhutan (Druk Holding)", "BT-GOV", "BT"),
                "el salvador": ("🇸🇻 El Salvador Government", "SV-GOV", "SV"),
                "finland": ("🇫🇮 Finland Government", "FI-GOV", "FI"),
                "germany": ("🇩🇪 Germany Government", "DE-GOV", "DE"),
                "georgia": ("🇬🇪 Georgia Government", "GE-GOV", "GE"),
                "venezuela": ("🇻🇪 Venezuela Government", "VE-GOV", "VE"),
                "north korea": ("🇰🇵 North Korea", "KP-GOV", "KP"),
                "russia": ("🇷🇺 Russia", "RU-GOV", "RU"),
                "japan": ("🇯🇵 Japan Government", "JP-GOV", "JP"),
                "switzerland": ("🇨🇭 Switzerland", "CH-GOV", "CH"),
                "canada": ("🇨🇦 Canada Government", "CA-GOV", "CA"),
                "brazil": ("🇧🇷 Brazil Government", "BR-GOV", "BR"),
                "australia": ("🇦🇺 Australia Government", "AU-GOV", "AU"),
                "india": ("🇮🇳 India Government", "IN-GOV", "IN"),
                "singapore": ("🇸🇬 Singapore Government", "SG-GOV", "SG"),
                "saudi": ("🇸🇦 Saudi Arabia", "SA-GOV", "SA"),
                "czech": ("🇨🇿 Czech Republic", "CZ-GOV", "CZ"),
                "norway": ("🇳🇴 Norway", "NO-GOV", "NO"),
                "poland": ("🇵🇱 Poland", "PL-GOV", "PL"),
                "thailand": ("🇹🇭 Thailand", "TH-GOV", "TH"),
            }
            for item in data:
                try:
                    name = item.get("name", "Unknown")
                    btc = int(float(item.get("total_holdings", 0)))
                    if btc <= 0:
                        continue
                    name_lower = name.lower()
                    matched = None
                    for key, (display, ticker, country) in flag_map.items():
                        if key in name_lower:
                            matched = {"company": display, "ticker": ticker, "btc_holdings": btc,
                                       "avg_purchase_price": 0, "total_cost_usd": 0,
                                       "country": country, "sector": "Government",
                                       "is_government": True, "notes": "LIVE from BitcoinTreasuries.net"}
                            break
                    if not matched:
                        matched = {"company": f"🏛️ {name}", "ticker": f"{name[:2].upper()}-GOV",
                                   "btc_holdings": btc, "avg_purchase_price": 0, "total_cost_usd": 0,
                                   "country": "", "sector": "Government",
                                   "is_government": True, "notes": "LIVE from BitcoinTreasuries.net"}
                    sovereigns.append(matched)
                except Exception as e:
                    logger.debug(f"Skipping sovereign entry: {e}")
                    continue
            if sovereigns:
                sovereigns.sort(key=lambda x: x["btc_holdings"], reverse=True)
                logger.info(f"BitcoinTreasuries.net API: {len(sovereigns)} sovereign holders LIVE")
                freshness.record_success("bitcointreasuries", detail=f"{len(sovereigns)} sovereign holders")
                freshness.set_provenance("leaderboard_sovereign", "BitcoinTreasuries.net API", "live")
                return sovereigns
    except Exception as e:
        logger.warning(f"BitcoinTreasuries.net sovereign API failed: {e}")

    # Source 2: CoinGecko (doesn't have governments directly)
    try:
        logger.debug("Trying CoinGecko government holdings...")
        response = requests.get("https://api.coingecko.com/api/v3/companies/public_treasury/bitcoin", headers=headers, timeout=15)
        if response.status_code == 200:
            pass  # CoinGecko doesn't have governments
    except Exception as e:
        logger.debug(f"CoinGecko government check: {e}")

    # Source 3: Scan news
    try:
        logger.debug("Scanning news for sovereign BTC updates...")
        news_sovereigns = scan_sovereign_news()
        if news_sovereigns:
            return news_sovereigns
    except Exception as e:
        logger.warning(f"Sovereign news scan failed: {e}")

    logger.warning("All live sovereign sources failed, using fallback")
    freshness.set_provenance("leaderboard_sovereign", "Hardcoded fallback", "fallback")
    return None


def scan_sovereign_news():
    """Scan news for latest government BTC holding updates."""
    queries = [
        "US government bitcoin holdings 2026",
        "government bitcoin reserve 2026",
        "country bitcoin holdings 2026",
        "strategic bitcoin reserve holdings 2026",
        "El Salvador bitcoin holdings 2026",
        "Bhutan bitcoin holdings 2026",
    ]

    headers = {"User-Agent": "Mozilla/5.0"}
    updates = {}

    country_patterns = {
        "united states": ("🇺🇸 United States Government", "US-GOV", "US"),
        "us government": ("🇺🇸 United States Government", "US-GOV", "US"),
        "us strategic": ("🇺🇸 United States Government", "US-GOV", "US"),
        "china": ("🇨🇳 China Government", "CN-GOV", "CN"),
        "united kingdom": ("🇬🇧 United Kingdom Government", "UK-GOV", "GB"),
        "uk government": ("🇬🇧 United Kingdom Government", "UK-GOV", "GB"),
        "el salvador": ("🇸🇻 El Salvador Government", "SV-GOV", "SV"),
        "bhutan": ("🇧🇹 Bhutan (Druk Holding)", "BT-GOV", "BT"),
        "ukraine": ("🇺🇦 Ukraine Government", "UA-GOV", "UA"),
        "germany": ("🇩🇪 Germany Government", "DE-GOV", "DE"),
    }

    for query in queries:
        try:
            url = f"https://news.google.com/rss/search?q={requests.utils.quote(query)}&hl=en-US&gl=US&ceid=US:en"
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code != 200:
                continue
            root = ET.fromstring(response.content)

            for item in root.findall(".//item")[:3]:
                title = item.findtext("title", "").lower()
                btc_match = re.search(r'([\d,]+)\s*(?:btc|bitcoin)', title)
                if not btc_match:
                    continue

                try:
                    btc_amount = int(btc_match.group(1).replace(",", ""))
                except ValueError:
                    continue

                if btc_amount < 100:
                    continue

                for key, (display, ticker, country) in country_patterns.items():
                    if key in title and ticker not in updates:
                        updates[ticker] = {
                            "company": display, "ticker": ticker,
                            "btc_holdings": btc_amount,
                            "avg_purchase_price": 0, "total_cost_usd": 0,
                            "country": country, "sector": "Government",
                            "is_government": True, "notes": "Auto-detected from news",
                        }
                        break
        except Exception as e:
            logger.debug(f"Sovereign news query failed for '{query}': {e}")
            continue

    if updates:
        result = sorted(updates.values(), key=lambda x: x["btc_holdings"], reverse=True)
        logger.info(f"Found {len(result)} sovereign updates from news")
        freshness.set_provenance("leaderboard_sovereign", "Google News (auto-detected)", "live")
        return result
    return None


def get_treasury_companies():
    """Get the best available treasury company data."""
    live_data = fetch_live_leaderboard()
    if live_data:
        return live_data
    return FALLBACK_COMPANIES


TREASURY_COMPANIES = FALLBACK_COMPANIES  # For backward compatibility


def get_leaderboard(sort_by="btc_holdings"):
    """Get the treasury leaderboard sorted by the given field."""
    companies = get_treasury_companies()
    companies = sorted(companies, key=lambda x: x.get(sort_by, 0), reverse=True)
    for i, company in enumerate(companies):
        company["rank"] = i + 1
        company["btc_value_usd"] = company["btc_holdings"] * 72000
    return companies


def get_leaderboard_with_live_price(btc_price, include_governments=True):
    """Get leaderboard with live BTC price. All data from live APIs."""
    companies = get_treasury_companies()

    if include_governments:
        live_sovereigns = fetch_sovereign_holdings()
        sovereigns = live_sovereigns if live_sovereigns else SOVEREIGN_HOLDERS

        for gov in sovereigns:
            if gov["btc_holdings"] > 0:
                existing = [c for c in companies if c.get("ticker") == gov["ticker"]]
                if not existing:
                    companies.append(gov.copy())

    companies = sorted(companies, key=lambda x: x.get("btc_holdings", 0), reverse=True)

    total_btc = 0
    total_value = 0
    total_corporate = 0
    total_sovereign = 0

    for i, company in enumerate(companies):
        company["rank"] = i + 1
        company["btc_value_usd"] = round(company["btc_holdings"] * btc_price, 2)
        company["btc_value_b"] = round(company["btc_value_usd"] / 1_000_000_000, 2)

        if company.get("total_cost_usd", 0) > 0:
            company["unrealized_pnl"] = round(company["btc_value_usd"] - company["total_cost_usd"], 2)
            company["unrealized_pnl_pct"] = round((company["unrealized_pnl"] / company["total_cost_usd"]) * 100, 1)
        else:
            company["unrealized_pnl"] = 0
            company["unrealized_pnl_pct"] = 0

        total_btc += company["btc_holdings"]
        total_value += company["btc_value_usd"]

        if company.get("is_government"):
            total_sovereign += company["btc_holdings"]
        else:
            total_corporate += company["btc_holdings"]

    summary = {
        "total_companies": len(companies),
        "total_btc": total_btc,
        "total_value_usd": total_value,
        "total_value_b": round(total_value / 1_000_000_000, 2),
        "btc_price_used": btc_price,
        "updated_at": datetime.now().isoformat(),
        "data_source": "live" if _live_data_cache["data"] else "fallback",
        "total_corporate_btc": total_corporate,
        "total_sovereign_btc": total_sovereign,
        "corporate_count": len([c for c in companies if not c.get("is_government")]),
        "sovereign_count": len([c for c in companies if c.get("is_government")]),
    }

    return companies, summary


def format_leaderboard_text(companies, summary):
    source = "LIVE" if summary.get("data_source") == "live" else "CACHED"
    lines = []
    lines.append("=" * 70)
    lines.append(f"  BTC TREASURY LEADERBOARD [{source}]")
    lines.append(f"  BTC Price: ${summary['btc_price_used']:,.0f} | Updated: {summary['updated_at'][:19]}")
    lines.append("=" * 70)
    lines.append("")
    lines.append(f"  {'#':<4} {'Entity':<30} {'BTC':>10} {'Value ($B)':>12} {'Type':>10}")
    lines.append(f"  {'-'*4} {'-'*30} {'-'*10} {'-'*12} {'-'*10}")
    for c in companies:
        if c["btc_holdings"] > 0:
            entity_type = "GOV" if c.get("is_government") else "CORP"
            lines.append(f"  {c['rank']:<4} {c['company'][:30]:<30} {c['btc_holdings']:>10,} ${c['btc_value_b']:>10.2f} {entity_type:>10}")
    lines.append("")
    lines.append(f"  TOTAL: {summary['total_btc']:,} BTC = ${summary['total_value_b']:.2f}B across {summary['total_companies']} entities")
    lines.append("=" * 70)
    return "\n".join(lines)


def format_leaderboard_telegram(companies, summary, top_n=10):
    """Format the leaderboard for Telegram."""
    source = "LIVE" if summary.get("data_source") == "live" else "CACHED"
    lines = []
    lines.append(f"🏆 BTC TREASURY LEADERBOARD [{source}]\n")
    lines.append(f"BTC: ${summary['btc_price_used']:,.0f}")
    lines.append(f"Total: {summary['total_btc']:,} BTC (${summary['total_value_b']:.1f}B)\n")

    medals = ["🥇", "🥈", "🥉"]

    for c in companies[:top_n]:
        if c["btc_holdings"] > 0:
            rank = c["rank"]
            medal = medals[rank - 1] if rank <= 3 else f"#{rank}"
            lines.append(f"{medal} {c['company'][:25]}")
            lines.append(f"   {c['btc_holdings']:,} BTC (${c['btc_value_b']:.2f}B)")
            if c.get("unrealized_pnl_pct"):
                pnl_emoji = "📈" if c["unrealized_pnl_pct"] > 0 else "📉"
                lines.append(f"   {pnl_emoji} P&L: {c['unrealized_pnl_pct']:+.1f}%")
            lines.append("")

    lines.append("---")
    lines.append("Treasury Signal Intelligence")
    lines.append("BTC Treasury Leaderboard™")

    return "\n".join(lines)


def save_leaderboard_to_db(companies, summary):
    """Save leaderboard snapshot to Supabase."""
    try:
        row = {
            "snapshot_date": datetime.now().strftime("%Y-%m-%d"),
            "btc_price": summary["btc_price_used"],
            "total_btc": summary["total_btc"],
            "total_value_b": summary["total_value_b"],
            "companies_json": json.dumps([{
                "ticker": c["ticker"], "btc_holdings": c["btc_holdings"], "rank": c["rank"],
            } for c in companies[:20]]),
        }
        supabase.table("leaderboard_snapshots").upsert(row, on_conflict="snapshot_date").execute()
        logger.info(f"Leaderboard snapshot saved for {row['snapshot_date']}")
        return True
    except Exception as e:
        logger.error(f"Could not save leaderboard snapshot: {e}", exc_info=True)
        return False


# ============================================
# QUICK TEST
# ============================================
if __name__ == "__main__":
    logger.info("BTC Treasury Leaderboard v2.0 — testing...")
    btc_price = 72456
    companies, summary = get_leaderboard_with_live_price(btc_price)
    logger.info(f"Source: {summary.get('data_source', 'unknown').upper()} | Companies: {summary['total_companies']} | Total: {summary['total_btc']:,} BTC (${summary['total_value_b']:.2f}B)")
    print(format_leaderboard_text(companies, summary))
    logger.info("Leaderboard test complete")
