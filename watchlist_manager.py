"""
watchlist_manager.py — Custom Watchlist Intelligence
------------------------------------------------------
Matches a subscriber's watchlist against all data streams
to surface relevant activity from companies they care about.

Checks:
- Recent purchases by watched companies
- Tweet signals from watched company executives
- SEC EDGAR filings from watched companies
- Leaderboard changes (holdings increase/decrease)

Usage:
    from watchlist_manager import get_watchlist_activity

    activity = get_watchlist_activity(
        watchlist=["MSTR", "MARA", "GME"],
        signals=signals,
        purchases=purchases,
        leaderboard=companies,
    )
"""

import json
from datetime import datetime, timedelta
from logger import get_logger

logger = get_logger(__name__)

# Map tickers to known executive Twitter accounts
TICKER_TO_ACCOUNTS = {
    "MSTR": ["saylor", "michael_saylor", "strategy", "phongle_"],
    "MARA": ["marathondh", "faborode"],
    "RIOT": ["RiotPlatforms"],
    "TSLA": ["elonmusk"],
    "GME": ["rikitrader"],
    "COIN": ["coinbase", "brian_armstrong"],
    "HUT": ["Haboratory"],
    "CLSK": ["CleanSpark"],
    "3350.T": ["metaplanet_jp", "simongerovich"],
    "SMLR": ["SemlerSci"],
    "KULR": ["KULRTech"],
    "CEP": ["jackmallers"],
    "BITF": ["Bitfarms_io"],
    "XYZ": ["blocks", "jack"],
}

# Map tickers to company names for display
TICKER_TO_NAME = {
    "MSTR": "Strategy (MicroStrategy)",
    "MARA": "MARA Holdings",
    "RIOT": "Riot Platforms",
    "TSLA": "Tesla",
    "GME": "GameStop",
    "COIN": "Coinbase",
    "HUT": "Hut 8 Mining",
    "CLSK": "CleanSpark",
    "3350.T": "Metaplanet",
    "SMLR": "Semler Scientific",
    "KULR": "KULR Technology",
    "CEP": "Twenty One Capital",
    "BITF": "Bitfarms",
    "XYZ": "Block (Square)",
    "CORZ": "Core Scientific",
    "CIFR": "Cipher Mining",
    "GLXY": "Galaxy Digital",
    "RUM": "Rumble",
    "DJT": "Trump Media",
    "BLK": "BlackRock",
    "ARKK": "ARK Invest",
    "GBTC": "Grayscale",
}

# All trackable tickers for the UI
TRACKABLE_COMPANIES = [
    {"ticker": "MSTR", "name": "Strategy (MicroStrategy)", "category": "BTC Treasury"},
    {"ticker": "MARA", "name": "MARA Holdings", "category": "Bitcoin Mining"},
    {"ticker": "RIOT", "name": "Riot Platforms", "category": "Bitcoin Mining"},
    {"ticker": "CLSK", "name": "CleanSpark", "category": "Bitcoin Mining"},
    {"ticker": "TSLA", "name": "Tesla", "category": "Automotive / EV"},
    {"ticker": "GME", "name": "GameStop", "category": "Retail / Gaming"},
    {"ticker": "COIN", "name": "Coinbase", "category": "Crypto Exchange"},
    {"ticker": "HUT", "name": "Hut 8 Mining", "category": "Bitcoin Mining"},
    {"ticker": "XYZ", "name": "Block (Square)", "category": "Fintech"},
    {"ticker": "3350.T", "name": "Metaplanet", "category": "BTC Treasury (Japan)"},
    {"ticker": "SMLR", "name": "Semler Scientific", "category": "Healthcare / BTC Treasury"},
    {"ticker": "KULR", "name": "KULR Technology", "category": "Energy / Battery"},
    {"ticker": "CEP", "name": "Twenty One Capital", "category": "BTC Treasury / Fintech"},
    {"ticker": "BITF", "name": "Bitfarms", "category": "Bitcoin Mining"},
    {"ticker": "CORZ", "name": "Core Scientific", "category": "Bitcoin Mining / AI"},
    {"ticker": "BLK", "name": "BlackRock", "category": "Asset Management"},
    {"ticker": "ARKK", "name": "ARK Invest", "category": "Asset Management"},
    {"ticker": "GBTC", "name": "Grayscale", "category": "Asset Management"},
    {"ticker": "RUM", "name": "Rumble", "category": "Media"},
    {"ticker": "DJT", "name": "Trump Media", "category": "Media"},
]


def get_watchlist_activity(watchlist, signals=None, purchases=None,
                           leaderboard=None, filings=None):
    """
    Get all recent activity for companies on the watchlist.

    Args:
        watchlist: List of ticker strings (e.g., ["MSTR", "MARA", "GME"])
        signals: Recent tweet signals (from get_recent_signals)
        purchases: Recent purchases (from get_recent_purchases)
        leaderboard: Current leaderboard data
        filings: Recent EDGAR filings (optional)

    Returns:
        List of activity dicts, sorted by relevance/recency.
    """
    if not watchlist:
        return []

    watchlist_upper = [t.upper().strip() for t in watchlist]
    activity = []

    # 1. Check purchases
    if purchases:
        for p in purchases:
            p_ticker = (p.get("ticker", "") or "").upper()
            if p_ticker in watchlist_upper:
                company = p.get("company", TICKER_TO_NAME.get(p_ticker, p_ticker))
                activity.append({
                    "type": "purchase",
                    "icon": "💰",
                    "company": company,
                    "ticker": p_ticker,
                    "headline": f"{company} bought {p.get('btc_amount', 0):,} BTC",
                    "detail": f"${p.get('usd_amount', 0)/1_000_000:,.0f}M at ${p.get('price_per_btc', 0):,.0f}/BTC on {p.get('filing_date', '')}",
                    "date": p.get("filing_date", ""),
                    "priority": "high",
                })

    # 2. Check tweet signals
    if signals:
        watched_accounts = set()
        for ticker in watchlist_upper:
            for account in TICKER_TO_ACCOUNTS.get(ticker, []):
                watched_accounts.add(account.lower())

        for sig in signals:
            author = (sig.get("author_username", "") or "").lower()
            if author in watched_accounts:
                # Find which ticker this author belongs to
                matched_ticker = ""
                for ticker in watchlist_upper:
                    if author in [a.lower() for a in TICKER_TO_ACCOUNTS.get(ticker, [])]:
                        matched_ticker = ticker
                        break

                score = sig.get("confidence_score", 0)
                company = TICKER_TO_NAME.get(matched_ticker, matched_ticker)
                activity.append({
                    "type": "signal",
                    "icon": "⚡",
                    "company": company,
                    "ticker": matched_ticker,
                    "headline": f"@{sig.get('author_username', '')} posted a signal (score: {score}/100)",
                    "detail": (sig.get("tweet_text", "") or "")[:120],
                    "date": sig.get("created_at", sig.get("inserted_at", "")),
                    "priority": "high" if score >= 60 else "medium",
                })

    # 3. Check leaderboard changes
    if leaderboard:
        for company in leaderboard:
            c_ticker = (company.get("ticker", "") or "").upper()
            if c_ticker in watchlist_upper and not company.get("is_government"):
                btc = company.get("btc_holdings", 0)
                rank = company.get("rank", 0)
                value_b = company.get("btc_value_b", 0)
                name = company.get("company", c_ticker)

                activity.append({
                    "type": "holding",
                    "icon": "📊",
                    "company": name,
                    "ticker": c_ticker,
                    "headline": f"{name} holds {btc:,} BTC (#{rank})",
                    "detail": f"Value: ${value_b:.2f}B",
                    "date": "",
                    "priority": "info",
                })

    # 4. Check EDGAR filings
    if filings:
        for filing in filings:
            f_ticker = (filing.get("ticker", "") or "").upper()
            if f_ticker in watchlist_upper:
                company = filing.get("company", TICKER_TO_NAME.get(f_ticker, f_ticker))
                btc_label = "Bitcoin-related" if filing.get("is_btc_related") else "General"
                activity.append({
                    "type": "filing",
                    "icon": "📋",
                    "company": company,
                    "ticker": f_ticker,
                    "headline": f"{company} filed 8-K ({btc_label})",
                    "detail": f"Filed {filing.get('date', '')} — {(filing.get('description', '') or '')[:80]}",
                    "date": filing.get("date", ""),
                    "priority": "high" if filing.get("is_btc_related") else "medium",
                })

    # Sort: high priority first, then by date
    priority_order = {"high": 0, "medium": 1, "info": 2}
    activity.sort(key=lambda x: (priority_order.get(x.get("priority", "info"), 2), x.get("date", "")), reverse=False)
    # Re-sort so high priority and recent items come first
    activity.sort(key=lambda x: (priority_order.get(x.get("priority", "info"), 2)))

    return activity


def format_watchlist_telegram(activity, subscriber_name=""):
    """Format watchlist activity for a Telegram alert."""
    if not activity:
        return None

    high_priority = [a for a in activity if a["priority"] == "high"]
    if not high_priority:
        return None  # Only send Telegram for high-priority items

    greeting = f"for {subscriber_name}" if subscriber_name else ""
    lines = [f"👁️ WATCHLIST ALERT {greeting}\n"]

    for a in high_priority[:5]:
        lines.append(f"{a['icon']} {a['headline']}")
        if a.get("detail"):
            lines.append(f"   {a['detail']}")
        lines.append("")

    lines.append("---")
    lines.append("Treasury Signal Intelligence")
    lines.append("Custom Watchlist Alerts™")

    return "\n".join(lines)


def format_watchlist_email_html(activity, max_items=8):
    """Format watchlist activity as HTML for the email briefing."""
    if not activity:
        return ""

    # Filter out info-only items for email
    notable = [a for a in activity if a["priority"] in ("high", "medium")]
    if not notable:
        # Show top holdings as summary
        holdings = [a for a in activity if a["type"] == "holding"][:5]
        if not holdings:
            return ""
        notable = holdings

    rows = ""
    for a in notable[:max_items]:
        priority_color = {"high": "#EF4444", "medium": "#F59E0B", "info": "#6B7280"}[a.get("priority", "info")]
        rows += f"""
            <tr>
                <td style="padding: 10px 18px; border-bottom: 1px solid #1e2a3a;">
                    <span style="font-size: 14px;">{a['icon']}</span>
                    <strong style="color: #e0e0e0; font-size: 12px; margin-left: 4px;">{a['company'][:25]}</strong>
                    <span style="color: #4b5563; font-size: 10px;"> ({a['ticker']})</span>
                    <br><span style="color: #d1d5db; font-size: 12px;">{a['headline']}</span>
                    {'<br><span style="color: #9ca3af; font-size: 11px;">' + a["detail"][:100] + '</span>' if a.get("detail") and a["type"] != "holding" else ""}
                </td>
                <td style="padding: 10px 14px; border-bottom: 1px solid #1e2a3a; text-align: right; vertical-align: top;">
                    <span style="background: {priority_color}20; color: {priority_color}; padding: 2px 8px; border-radius: 4px; font-size: 9px; font-weight: 700; text-transform: uppercase;">{a['priority']}</span>
                </td>
            </tr>"""

    return f"""
        <tr><td style="padding: 8px 36px 12px 36px;">
            <span style="color: #6b7280; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.12em;">👁️ Your Watchlist</span>
            <p style="color: #4b5563; font-size: 11px; margin: 2px 0 8px 0;">Activity from companies you're tracking</p>
            <table width="100%" cellpadding="0" cellspacing="0" style="background: #111827; border-radius: 10px; overflow: hidden;">
                {rows}
            </table>
        </td></tr>
    """


# ============================================
# QUICK TEST
# ============================================
if __name__ == "__main__":
    logger.info("Watchlist Manager — testing...")

    mock_purchases = [
        {"company": "Strategy", "ticker": "MSTR", "btc_amount": 22337, "usd_amount": 1570000000, "price_per_btc": 70194, "filing_date": "2025-03-16"},
    ]

    mock_signals = [
        {"author_username": "saylor", "confidence_score": 85, "tweet_text": "Stretch the Orange Dots", "created_at": "2026-03-22"},
    ]

    activity = get_watchlist_activity(
        watchlist=["MSTR", "MARA", "GME"],
        signals=mock_signals,
        purchases=mock_purchases,
    )

    for a in activity:
        print(f"  {a['icon']} [{a['priority'].upper()}] {a['headline']}")
        if a.get("detail"):
            print(f"     {a['detail']}")

    logger.info("Watchlist Manager test complete")
