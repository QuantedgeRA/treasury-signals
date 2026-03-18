"""
treasury_leaderboard.py
-----------------------
BTC Treasury Company Leaderboard

Tracks all publicly traded companies holding Bitcoin on their balance sheet.
Provides rankings, holdings data, and purchase tracking.

Data sourced from public 8-K/10-Q filings and press releases.
Updated manually + automatically via SEC EDGAR monitor.
"""

import json
import os
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# ============================================
# MASTER LIST OF BTC TREASURY COMPANIES
# Updated as of March 2026
# Sources: SEC filings, press releases, BitcoinTreasuries.NET
# ============================================

TREASURY_COMPANIES = [
    {
        "company": "Strategy (MicroStrategy)",
        "ticker": "MSTR",
        "ceo": "Phong Le",
        "chairman": "Michael Saylor",
        "btc_holdings": 499096,
        "avg_purchase_price": 66357,
        "total_cost_usd": 33100000000,
        "last_purchase_date": "2025-03-17",
        "last_purchase_btc": 130,
        "country": "USA",
        "sector": "Software / BTC Treasury",
        "market_cap_b": 75.0,
        "notes": "Largest corporate BTC holder. Uses STRC preferred stock to fund purchases.",
    },
    {
        "company": "Marathon Digital (MARA)",
        "ticker": "MARA",
        "ceo": "Fred Thiel",
        "chairman": "",
        "btc_holdings": 46374,
        "avg_purchase_price": 0,
        "total_cost_usd": 0,
        "last_purchase_date": "2025-01-27",
        "last_purchase_btc": 0,
        "country": "USA",
        "sector": "Bitcoin Mining",
        "market_cap_b": 5.8,
        "notes": "Largest public Bitcoin miner. Holds mined + purchased BTC.",
    },
    {
        "company": "Riot Platforms",
        "ticker": "RIOT",
        "ceo": "Jason Les",
        "chairman": "",
        "btc_holdings": 19223,
        "avg_purchase_price": 0,
        "total_cost_usd": 0,
        "last_purchase_date": "2025-01-06",
        "last_purchase_btc": 0,
        "country": "USA",
        "sector": "Bitcoin Mining",
        "market_cap_b": 3.2,
        "notes": "Major Bitcoin miner with strategic HODL policy.",
    },
    {
        "company": "CleanSpark",
        "ticker": "CLSK",
        "ceo": "Zach Bradford",
        "chairman": "",
        "btc_holdings": 11869,
        "avg_purchase_price": 0,
        "total_cost_usd": 0,
        "last_purchase_date": "2025-01-06",
        "last_purchase_btc": 0,
        "country": "USA",
        "sector": "Bitcoin Mining",
        "market_cap_b": 2.1,
        "notes": "Fast-growing Bitcoin miner.",
    },
    {
        "company": "Tesla",
        "ticker": "TSLA",
        "ceo": "Elon Musk",
        "chairman": "",
        "btc_holdings": 11509,
        "avg_purchase_price": 32700,
        "total_cost_usd": 1500000000,
        "last_purchase_date": "2021-02-08",
        "last_purchase_btc": 0,
        "country": "USA",
        "sector": "Automotive / EV",
        "market_cap_b": 900.0,
        "notes": "Bought $1.5B in early 2021. Sold ~75%, holds remainder.",
    },
    {
        "company": "Coinbase Global",
        "ticker": "COIN",
        "ceo": "Brian Armstrong",
        "chairman": "",
        "btc_holdings": 9480,
        "avg_purchase_price": 0,
        "total_cost_usd": 0,
        "last_purchase_date": "2024-12-31",
        "last_purchase_btc": 0,
        "country": "USA",
        "sector": "Crypto Exchange",
        "market_cap_b": 45.0,
        "notes": "Largest US crypto exchange. Corporate treasury BTC.",
    },
    {
        "company": "Hut 8 Mining",
        "ticker": "HUT",
        "ceo": "Asher Genoot",
        "chairman": "",
        "btc_holdings": 10208,
        "avg_purchase_price": 24484,
        "total_cost_usd": 250000000,
        "last_purchase_date": "2024-12-19",
        "last_purchase_btc": 990,
        "country": "Canada",
        "sector": "Bitcoin Mining",
        "market_cap_b": 1.5,
        "notes": "Canadian miner with strategic reserve model.",
    },
    {
        "company": "GameStop",
        "ticker": "GME",
        "ceo": "Ryan Cohen",
        "chairman": "Ryan Cohen",
        "btc_holdings": 0,
        "avg_purchase_price": 0,
        "total_cost_usd": 0,
        "last_purchase_date": "",
        "last_purchase_btc": 0,
        "country": "USA",
        "sector": "Retail / Gaming",
        "market_cap_b": 12.0,
        "notes": "Board approved BTC treasury strategy in March 2025. First purchase pending.",
    },
    {
        "company": "Core Scientific",
        "ticker": "CORZ",
        "ceo": "Adam Sullivan",
        "chairman": "",
        "btc_holdings": 0,
        "avg_purchase_price": 0,
        "total_cost_usd": 0,
        "last_purchase_date": "",
        "last_purchase_btc": 0,
        "country": "USA",
        "sector": "Bitcoin Mining / AI",
        "market_cap_b": 3.8,
        "notes": "Major miner pivoting to AI hosting. Sold most BTC.",
    },
    {
        "company": "Bitfarms",
        "ticker": "BITF",
        "ceo": "Ben Gagnon",
        "chairman": "",
        "btc_holdings": 1147,
        "avg_purchase_price": 0,
        "total_cost_usd": 0,
        "last_purchase_date": "2024-10-01",
        "last_purchase_btc": 0,
        "country": "Canada",
        "sector": "Bitcoin Mining",
        "market_cap_b": 0.8,
        "notes": "Canadian miner with operations across multiple countries.",
    },
    {
        "company": "KULR Technology",
        "ticker": "KULR",
        "ceo": "Michael Mo",
        "chairman": "",
        "btc_holdings": 610,
        "avg_purchase_price": 97000,
        "total_cost_usd": 59200000,
        "last_purchase_date": "2025-01-06",
        "last_purchase_btc": 213,
        "country": "USA",
        "sector": "Energy / Battery Tech",
        "market_cap_b": 0.5,
        "notes": "Adopted BTC treasury strategy in Dec 2024. Small but growing.",
    },
    {
        "company": "Block (Square)",
        "ticker": "XYZ",
        "ceo": "Jack Dorsey",
        "chairman": "",
        "btc_holdings": 8211,
        "avg_purchase_price": 34600,
        "total_cost_usd": 284000000,
        "last_purchase_date": "2024-04-01",
        "last_purchase_btc": 0,
        "country": "USA",
        "sector": "Fintech / Payments",
        "market_cap_b": 38.0,
        "notes": "Jack Dorsey's payments company. Auto-purchases 10% of gross profit in BTC monthly.",
    },
    {
        "company": "MercadoLibre",
        "ticker": "MELI",
        "ceo": "Marcos Galperin",
        "chairman": "",
        "btc_holdings": 412,
        "avg_purchase_price": 48000,
        "total_cost_usd": 19800000,
        "last_purchase_date": "2021-05-01",
        "last_purchase_btc": 0,
        "country": "Argentina",
        "sector": "E-commerce",
        "market_cap_b": 85.0,
        "notes": "Largest e-commerce company in Latin America.",
    },
    {
        "company": "Metaplanet",
        "ticker": "3350.T",
        "ceo": "Simon Gerovich",
        "chairman": "",
        "btc_holdings": 3050,
        "avg_purchase_price": 75000,
        "total_cost_usd": 228000000,
        "last_purchase_date": "2025-03-01",
        "last_purchase_btc": 150,
        "country": "Japan",
        "sector": "Investment / BTC Treasury",
        "market_cap_b": 1.0,
        "notes": "Japan's 'MicroStrategy'. Aggressive BTC accumulation strategy.",
    },
    {
        "company": "Semler Scientific",
        "ticker": "SMLR",
        "ceo": "Eric Semler",
        "chairman": "",
        "btc_holdings": 3192,
        "avg_purchase_price": 81000,
        "total_cost_usd": 258600000,
        "last_purchase_date": "2025-02-14",
        "last_purchase_btc": 871,
        "country": "USA",
        "sector": "Healthcare / BTC Treasury",
        "market_cap_b": 0.4,
        "notes": "Medical device company pivoting to BTC treasury strategy.",
    },
    {
        "company": "Twenty One Capital",
        "ticker": "CEP",
        "ceo": "Jack Mallers",
        "chairman": "",
        "btc_holdings": 31500,
        "avg_purchase_price": 0,
        "total_cost_usd": 0,
        "last_purchase_date": "2025-05-01",
        "last_purchase_btc": 0,
        "country": "USA",
        "sector": "BTC Treasury / Fintech",
        "market_cap_b": 3.6,
        "notes": "Founded by Jack Mallers (Strike CEO). BTC-native treasury company backed by Tether, SoftBank, and Cantor Fitzgerald.",
    },
]


def get_leaderboard(sort_by="btc_holdings"):
    """
    Get the treasury leaderboard sorted by the given field.
    Returns list of companies sorted by BTC holdings (largest first).
    """
    companies = sorted(TREASURY_COMPANIES, key=lambda x: x.get(sort_by, 0), reverse=True)
    
    # Add rank and current BTC value
    for i, company in enumerate(companies):
        company["rank"] = i + 1
        company["btc_value_usd"] = company["btc_holdings"] * 72000  # Approximate; will use live price
    
    return companies


def get_leaderboard_with_live_price(btc_price):
    """Get leaderboard with live BTC price for value calculations."""
    companies = sorted(TREASURY_COMPANIES, key=lambda x: x.get("btc_holdings", 0), reverse=True)
    
    total_btc = 0
    total_value = 0
    
    for i, company in enumerate(companies):
        company["rank"] = i + 1
        company["btc_value_usd"] = round(company["btc_holdings"] * btc_price, 2)
        company["btc_value_b"] = round(company["btc_value_usd"] / 1_000_000_000, 2)
        
        # Unrealized P&L if we know the cost basis
        if company["total_cost_usd"] > 0:
            company["unrealized_pnl"] = round(company["btc_value_usd"] - company["total_cost_usd"], 2)
            company["unrealized_pnl_pct"] = round((company["unrealized_pnl"] / company["total_cost_usd"]) * 100, 1)
        else:
            company["unrealized_pnl"] = 0
            company["unrealized_pnl_pct"] = 0
        
        total_btc += company["btc_holdings"]
        total_value += company["btc_value_usd"]
    
    summary = {
        "total_companies": len(companies),
        "total_btc": total_btc,
        "total_value_usd": total_value,
        "total_value_b": round(total_value / 1_000_000_000, 2),
        "btc_price_used": btc_price,
        "updated_at": datetime.now().isoformat(),
    }
    
    return companies, summary


def format_leaderboard_text(companies, summary):
    """Format the leaderboard as a text report."""
    
    lines = []
    lines.append("=" * 70)
    lines.append("  BTC TREASURY LEADERBOARD — Top Corporate Bitcoin Holders")
    lines.append(f"  BTC Price: ${summary['btc_price_used']:,.0f} | Updated: {summary['updated_at'][:19]}")
    lines.append("=" * 70)
    lines.append("")
    lines.append(f"  {'#':<4} {'Company':<30} {'BTC':>10} {'Value ($B)':>12} {'Country':>10}")
    lines.append(f"  {'-'*4} {'-'*30} {'-'*10} {'-'*12} {'-'*10}")
    
    for c in companies:
        if c["btc_holdings"] > 0:
            lines.append(f"  {c['rank']:<4} {c['company']:<30} {c['btc_holdings']:>10,} ${c['btc_value_b']:>10.2f} {c['country']:>10}")
    
    lines.append("")
    lines.append(f"  TOTAL: {summary['total_btc']:,} BTC = ${summary['total_value_b']:.2f}B across {summary['total_companies']} companies")
    lines.append("=" * 70)
    
    return "\n".join(lines)


def format_leaderboard_telegram(companies, summary, top_n=10):
    """Format the leaderboard for Telegram."""
    
    lines = []
    lines.append("🏆 BTC TREASURY LEADERBOARD\n")
    lines.append(f"BTC: ${summary['btc_price_used']:,.0f}")
    lines.append(f"Total: {summary['total_btc']:,} BTC (${summary['total_value_b']:.1f}B)\n")
    
    medals = ["🥇", "🥈", "🥉"]
    
    for c in companies[:top_n]:
        if c["btc_holdings"] > 0:
            rank = c["rank"]
            medal = medals[rank - 1] if rank <= 3 else f"#{rank}"
            lines.append(f"{medal} {c['company']}")
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
    """Save leaderboard snapshot to Supabase for historical tracking."""
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
            } for c in companies]),
        }
        supabase.table("leaderboard_snapshots").upsert(row, on_conflict="snapshot_date").execute()
        print(f"  Leaderboard snapshot saved for {row['snapshot_date']}")
        return True
    except Exception as e:
        print(f"  Could not save snapshot (table may not exist yet): {e}")
        return False


# ============================================
# QUICK TEST
# ============================================
if __name__ == "__main__":
    print("\nBTC Treasury Leaderboard\n")
    
    btc_price = 72456  # Will use live price in production
    
    companies, summary = get_leaderboard_with_live_price(btc_price)
    
    # Text version
    print(format_leaderboard_text(companies, summary))
    
    # Telegram version
    print("\n\nTelegram Format:\n")
    print(format_leaderboard_telegram(companies, summary))
