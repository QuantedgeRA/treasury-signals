"""
treasury_leaderboard.py — v2.0
-------------------------------
BTC Treasury Company Leaderboard — LIVE DATA

Pulls the latest holdings data from multiple sources:
1. BitcoinTreasuries.net (primary source)
2. Fallback to manually maintained data if scraping fails
3. Supabase for historical snapshots

Auto-updates every scan cycle.
"""

import json
import os
import requests
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client
from bs4 import BeautifulSoup

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

# ============================================
# SOVEREIGN / GOVERNMENT BTC HOLDERS
# These are NOT on CoinGecko — we track them separately
# Sources: Public records, blockchain analysis, press releases
# ============================================

SOVEREIGN_HOLDERS = [
    {
        "company": "🇺🇸 United States Government",
        "ticker": "US-GOV",
        "btc_holdings": 198109,
        "avg_purchase_price": 0,
        "total_cost_usd": 0,
        "country": "US",
        "sector": "Government (Seized Assets)",
        "is_government": True,
        "notes": "Seized from Silk Road, Bitfinex hack, and other criminal cases. Strategic Bitcoin Reserve established via Executive Order March 2025.",
    },
    {
        "company": "🇨🇳 China Government",
        "ticker": "CN-GOV",
        "btc_holdings": 194000,
        "avg_purchase_price": 0,
        "total_cost_usd": 0,
        "country": "CN",
        "sector": "Government (Seized Assets)",
        "is_government": True,
        "notes": "Seized from PlusToken Ponzi scheme and other criminal cases. Status of holdings unclear — may have been partially liquidated.",
    },
    {
        "company": "🇬🇧 United Kingdom Government",
        "ticker": "UK-GOV",
        "btc_holdings": 61000,
        "avg_purchase_price": 0,
        "total_cost_usd": 0,
        "country": "GB",
        "sector": "Government (Seized Assets)",
        "is_government": True,
        "notes": "Seized from criminal cases. Government exploring options for disposal or retention.",
    },
    {
        "company": "🇧🇹 Bhutan (Druk Holding)",
        "ticker": "BT-GOV",
        "btc_holdings": 13029,
        "avg_purchase_price": 0,
        "total_cost_usd": 0,
        "country": "BT",
        "sector": "Government (Sovereign Mining)",
        "is_government": True,
        "notes": "Mined using hydroelectric power via state-owned Druk Holding & Investments. One of the largest sovereign BTC holdings relative to GDP.",
    },
    {
        "company": "🇸🇻 El Salvador Government",
        "ticker": "SV-GOV",
        "btc_holdings": 6089,
        "avg_purchase_price": 44300,
        "total_cost_usd": 269700000,
        "country": "SV",
        "sector": "Government (Legal Tender)",
        "is_government": True,
        "notes": "First nation to adopt Bitcoin as legal tender. President Bukele continues daily BTC purchases. Unrealized profit exceeds $300M.",
    },
    {
        "company": "🇺🇦 Ukraine Government",
        "ticker": "UA-GOV",
        "btc_holdings": 46351,
        "avg_purchase_price": 0,
        "total_cost_usd": 0,
        "country": "UA",
        "sector": "Government (Donations)",
        "is_government": True,
        "notes": "Received as cryptocurrency donations during the Russia-Ukraine conflict. Partially liquidated to fund defense.",
    },
    {
        "company": "🇩🇪 Germany Government",
        "ticker": "DE-GOV",
        "btc_holdings": 0,
        "avg_purchase_price": 0,
        "total_cost_usd": 0,
        "country": "DE",
        "sector": "Government (Sold)",
        "is_government": True,
        "notes": "Sold ~50,000 BTC seized from Movie2k piracy site in July 2024. All holdings liquidated.",
    },
    {
        "company": "🇫🇮 Finland Government",
        "ticker": "FI-GOV",
        "btc_holdings": 90,
        "avg_purchase_price": 0,
        "total_cost_usd": 0,
        "country": "FI",
        "sector": "Government (Seized Assets)",
        "is_government": True,
        "notes": "Small amount remaining after selling ~1,981 BTC seized from drug trafficking in 2018.",
    },
]


# Cache for live data
_live_data_cache = {"data": None, "fetched_at": None}


def fetch_live_leaderboard():
    """
    Fetch live BTC treasury data from multiple sources.
    Tries each source in order until one works.
    """
    global _live_data_cache

    # Use cache if less than 1 hour old
    if _live_data_cache["data"] and _live_data_cache["fetched_at"]:
        age_seconds = (datetime.now() - _live_data_cache["fetched_at"]).total_seconds()
        if age_seconds < 3600:
            print("  Using cached leaderboard data (less than 1 hour old)")
            return _live_data_cache["data"]

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    # Source 1: Try CoinGecko public companies endpoint
    try:
        print("  Trying CoinGecko public companies API...")
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
                except:
                    continue

            if companies:
                companies.sort(key=lambda x: x["btc_holdings"], reverse=True)
                _live_data_cache["data"] = companies
                _live_data_cache["fetched_at"] = datetime.now()
                print(f"  ✅ CoinGecko LIVE: {len(companies)} companies fetched")
                return companies
        else:
            print(f"  ⚠️ CoinGecko returned status {response.status_code}")
    except Exception as e:
        print(f"  ⚠️ CoinGecko failed: {e}")

    # Source 2: Try BitcoinTreasuries.net website scraping
    try:
        print("  Trying BitcoinTreasuries.net scraping...")
        response = requests.get("https://bitcointreasuries.net/", headers=headers, timeout=15)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "lxml")
            # Look for table data
            tables = soup.find_all("table")
            if tables:
                companies = []
                for row in tables[0].find_all("tr")[1:]:  # Skip header
                    cols = row.find_all("td")
                    if len(cols) >= 4:
                        try:
                            name = cols[0].get_text(strip=True)
                            ticker = cols[1].get_text(strip=True) if len(cols) > 1 else ""
                            btc_text = cols[2].get_text(strip=True).replace(",", "").replace(" ", "") if len(cols) > 2 else "0"
                            btc_holdings = int(float(btc_text)) if btc_text.replace(".", "").isdigit() else 0
                            if name and btc_holdings > 0:
                                companies.append({
                                    "company": name,
                                    "ticker": ticker,
                                    "btc_holdings": btc_holdings,
                                    "avg_purchase_price": 0,
                                    "total_cost_usd": 0,
                                    "country": "Unknown",
                                    "sector": "BTC Treasury",
                                })
                        except:
                            continue
                if companies:
                    companies.sort(key=lambda x: x["btc_holdings"], reverse=True)
                    _live_data_cache["data"] = companies
                    _live_data_cache["fetched_at"] = datetime.now()
                    print(f"  ✅ BitcoinTreasuries LIVE: {len(companies)} companies scraped")
                    return companies
            print("  ⚠️ Could not parse BitcoinTreasuries.net tables")
    except Exception as e:
        print(f"  ⚠️ BitcoinTreasuries.net scraping failed: {e}")

    # Source 3: Check Supabase for recent snapshot
    try:
        print("  Trying Supabase cached snapshot...")
        result = supabase.table("leaderboard_snapshots").select("*").order("snapshot_date", desc=True).limit(1).execute()
        if result.data:
            snapshot = result.data[0]
            snapshot_companies = json.loads(snapshot.get("companies_json", "[]"))
            if snapshot_companies:
                print(f"  ✅ Using Supabase snapshot from {snapshot['snapshot_date']}")
                # Merge snapshot data with fallback for full details
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
        print(f"  ⚠️ Supabase snapshot failed: {e}")

    print("  Using fallback data (all live sources unavailable)")
    return None



def get_treasury_companies():
    """
    Get the best available treasury company data.
    Tries live data first, falls back to hardcoded data.
    """
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
    """Get leaderboard with live BTC price. Merges corporate + sovereign holders."""
    companies = get_treasury_companies()

    # Add sovereign holders if requested
    if include_governments:
        for gov in SOVEREIGN_HOLDERS:
            if gov["btc_holdings"] > 0:
                # Check if already in list (avoid duplicates)
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
    lines.append(f"  Corporate: {summary.get('corporate_count', 0)} companies | Sovereign: {summary.get('sovereign_count', 0)} governments")
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
    source = "LIVE" if summary.get("data_source") == "live" else "CACHED"
    lines = []
    lines.append(f"🏆 BTC TREASURY LEADERBOARD [{source}]\n")
    lines.append(f"BTC: ${summary['btc_price_used']:,.0f}")
    lines.append(f"Total: {summary['total_btc']:,} BTC (${summary['total_value_b']:.1f}B)")
    lines.append(f"Corporate: {summary['total_corporate_btc']:,} BTC ({summary['corporate_count']} companies)")
    lines.append(f"Sovereign: {summary['total_sovereign_btc']:,} BTC ({summary['sovereign_count']} governments)\n")

    medals = ["🥇", "🥈", "🥉"]

    for c in companies[:top_n]:
        if c["btc_holdings"] > 0:
            rank = c["rank"]
            medal = medals[rank - 1] if rank <= 3 else f"#{rank}"
            name = c["company"][:25]
            gov_tag = " [GOV]" if c.get("is_government") else ""
            lines.append(f"{medal} {name}{gov_tag}")
            lines.append(f"   {c['btc_holdings']:,} BTC (${c['btc_value_b']:.2f}B)")
            if c.get("unrealized_pnl_pct") and c["unrealized_pnl_pct"] != 0:
                pnl_emoji = "📈" if c["unrealized_pnl_pct"] > 0 else "📉"
                lines.append(f"   {pnl_emoji} P&L: {c['unrealized_pnl_pct']:+.1f}%")
            lines.append("")

    lines.append("Full leaderboard: bitcointreasuries.net")
    lines.append("---")
    lines.append("Treasury Signal Intelligence")
    lines.append("BTC Treasury Leaderboard™")

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
                "ticker": c["ticker"],
                "btc_holdings": c["btc_holdings"],
                "rank": c["rank"],
            } for c in companies[:20]]),
        }
        supabase.table("leaderboard_snapshots").upsert(row, on_conflict="snapshot_date").execute()
        print(f"  Leaderboard snapshot saved for {row['snapshot_date']}")
        return True
    except Exception as e:
        print(f"  Could not save snapshot: {e}")
        return False


# ============================================
# QUICK TEST
# ============================================
if __name__ == "__main__":
    print("\nBTC Treasury Leaderboard v2.0 — LIVE DATA\n")

    btc_price = 72456

    companies, summary = get_leaderboard_with_live_price(btc_price)

    print(f"  Data source: {summary.get('data_source', 'unknown').upper()}")
    print(f"  Companies: {summary['total_companies']}")
    print(f"  Total BTC: {summary['total_btc']:,}")
    print(f"  Total Value: ${summary['total_value_b']:.2f}B\n")

    print(format_leaderboard_text(companies, summary))
    print("\n\nTelegram Format:\n")
    print(format_leaderboard_telegram(companies, summary))
