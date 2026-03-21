"""
market_intelligence.py
----------------------
CEO Decision Intelligence Module

Provides:
1. Action Signal (Buy/Hold/Wait based on all data)
2. What Changed Overnight (diff vs yesterday)
3. Risk Dashboard (fear & greed, volatility, drawdown)
4. Peer Activity (who bought/sold since last briefing)
5. Week Ahead (upcoming events that could move markets)
"""

import os
import json
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from supabase import create_client
import yfinance as yf

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# ============================================
# 1. ACTION SIGNAL
# ============================================

def generate_action_signal(correlation_score, active_streams, strc_ratio, signals_24h, btc_change, fear_greed_value):
    """
    Generate a CEO-level action recommendation based on all data streams.
    Returns: BUY SIGNAL, ACCUMULATE, HOLD, WAIT, or CAUTION
    """

    score = 0
    reasons = []

    # Factor 1: Correlation Engine
    if correlation_score >= 80:
        score += 35
        reasons.append(f"Correlation Engine at {correlation_score}/100 — strong multi-stream convergence")
    elif correlation_score >= 50:
        score += 20
        reasons.append(f"Correlation Engine at {correlation_score}/100 — moderate signal activity")
    elif correlation_score >= 25:
        score += 10
        reasons.append(f"Correlation Engine at {correlation_score}/100 — single stream active")

    # Factor 2: STRC Capital Raise
    if strc_ratio >= 2.0:
        score += 25
        reasons.append(f"STRC volume {strc_ratio}x normal — aggressive capital raise underway")
    elif strc_ratio >= 1.5:
        score += 15
        reasons.append(f"STRC volume {strc_ratio}x normal — elevated capital raise activity")

    # Factor 3: Tweet Signals
    high_signals = len([s for s in signals_24h if s.get("confidence_score", 0) >= 60])
    if high_signals >= 2:
        score += 20
        reasons.append(f"{high_signals} high-confidence tweet signals detected")
    elif high_signals == 1:
        score += 10
        reasons.append(f"1 high-confidence tweet signal detected")

    # Factor 4: Price momentum
    if btc_change <= -5:
        score += 10
        reasons.append(f"BTC down {btc_change:.1f}% — potential buying opportunity (buy the dip)")
    elif btc_change >= 5:
        score -= 5
        reasons.append(f"BTC up {btc_change:.1f}% — momentum positive but elevated entry price")

    # Factor 5: Fear & Greed
    if fear_greed_value <= 25:
        score += 15
        reasons.append(f"Fear & Greed at {fear_greed_value} (Extreme Fear) — historically optimal buy zone")
    elif fear_greed_value <= 40:
        score += 10
        reasons.append(f"Fear & Greed at {fear_greed_value} (Fear) — favorable for accumulation")
    elif fear_greed_value >= 80:
        score -= 10
        reasons.append(f"Fear & Greed at {fear_greed_value} (Extreme Greed) — caution advised")

    # Determine action
    if score >= 60:
        action = "🟢 BUY SIGNAL"
        action_color = "#10B981"
        summary = "Multiple data streams are converging. This is a high-confidence buying opportunity. Treasury companies are likely accumulating. Consider accelerating your BTC acquisition strategy."
    elif score >= 40:
        action = "🔵 ACCUMULATE"
        action_color = "#3B82F6"
        summary = "Conditions are favorable for steady accumulation. No urgency, but the setup is positive. Continue your regular DCA or planned purchase schedule."
    elif score >= 20:
        action = "⚪ HOLD"
        action_color = "#9CA3AF"
        summary = "No strong signals in either direction. Maintain current positions and continue monitoring. Wait for higher-conviction signals before deploying additional capital."
    elif score >= 0:
        action = "🟡 WAIT"
        action_color = "#F59E0B"
        summary = "Markets are quiet with no clear catalysts. Patience is warranted. Use this time to prepare dry powder for the next high-conviction opportunity."
    else:
        action = "🔴 CAUTION"
        action_color = "#EF4444"
        summary = "Risk indicators are elevated. Consider pausing new purchases until conditions improve. Focus on risk management and position sizing."

    return {
        "action": action,
        "action_color": action_color,
        "score": score,
        "summary": summary,
        "reasons": reasons,
    }


# ============================================
# 2. WHAT CHANGED OVERNIGHT
# ============================================

def get_overnight_changes(btc_price, mstr_price, strc_ratio, total_signals, leaderboard_total_btc, reg_total):
    """
    Compare current state with yesterday's snapshot.
    Returns list of changes.
    """
    changes = []

    # Get yesterday's snapshot from Supabase
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    prev_snapshot = None

    try:
        result = supabase.table("leaderboard_snapshots").select("*").eq("snapshot_date", yesterday).limit(1).execute()
        if result.data:
            prev_snapshot = result.data[0]
    except:
        pass

    if prev_snapshot:
        prev_btc_price = float(prev_snapshot.get("btc_price", 0))
        prev_total_btc = int(prev_snapshot.get("total_btc", 0))

        if prev_btc_price > 0:
            btc_pct = ((btc_price - prev_btc_price) / prev_btc_price) * 100
            direction = "📈" if btc_pct >= 0 else "📉"
            changes.append({
                "icon": direction,
                "text": f"Bitcoin moved {btc_pct:+.1f}% (${prev_btc_price:,.0f} → ${btc_price:,.0f})",
                "type": "positive" if btc_pct >= 0 else "negative",
            })

        if prev_total_btc > 0 and leaderboard_total_btc > prev_total_btc:
            btc_increase = leaderboard_total_btc - prev_total_btc
            changes.append({
                "icon": "💰",
                "text": f"Corporate BTC holdings increased by {btc_increase:,} BTC across all treasury companies",
                "type": "positive",
            })
        elif prev_total_btc > 0 and leaderboard_total_btc < prev_total_btc:
            btc_decrease = prev_total_btc - leaderboard_total_btc
            changes.append({
                "icon": "📤",
                "text": f"Corporate BTC holdings decreased by {btc_decrease:,} BTC (possible sales or data revision)",
                "type": "negative",
            })
    else:
        changes.append({
            "icon": "📊",
            "text": f"Bitcoin at ${btc_price:,.0f} | MSTR at ${mstr_price:,.2f}",
            "type": "neutral",
        })

    # Signal changes
    if total_signals > 0:
        changes.append({
            "icon": "🚨",
            "text": f"{total_signals} new purchase signal(s) detected overnight",
            "type": "positive",
        })

    # STRC status
    if strc_ratio >= 1.5:
        changes.append({
            "icon": "⚡",
            "text": f"STRC volume at {strc_ratio}x normal — capital raise activity is elevated",
            "type": "alert",
        })

    if not changes:
        changes.append({
            "icon": "✅",
            "text": "No significant changes overnight — markets are stable",
            "type": "neutral",
        })

    return changes


# ============================================
# 3. RISK DASHBOARD
# ============================================

def get_risk_dashboard():
    """
    Fetch risk indicators:
    - Fear & Greed Index
    - BTC Volatility (30-day)
    - Max drawdown from ATH
    - Key risk levels
    """
    risk = {
        "fear_greed_value": 50,
        "fear_greed_label": "Neutral",
        "volatility_30d": 0,
        "drawdown_from_ath": 0,
        "ath_price": 0,
        "current_price": 0,
        "risk_level": "MODERATE",
        "risk_color": "#F59E0B",
    }

    # Fear & Greed Index from alternative.me
    try:
        response = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get("data"):
                fg = data["data"][0]
                risk["fear_greed_value"] = int(fg.get("value", 50))
                risk["fear_greed_label"] = fg.get("value_classification", "Neutral")
    except:
        pass

    # BTC price data for volatility and drawdown
    try:
        btc = yf.Ticker("BTC-USD")
        hist = btc.history(period="1y")
        if not hist.empty:
            current = float(hist["Close"].iloc[-1])
            ath = float(hist["Close"].max())
            risk["current_price"] = current
            risk["ath_price"] = ath
            risk["drawdown_from_ath"] = round(((current - ath) / ath) * 100, 1)

            # 30-day volatility (annualized)
            if len(hist) >= 30:
                returns = hist["Close"].pct_change().tail(30)
                risk["volatility_30d"] = round(float(returns.std() * (365 ** 0.5) * 100), 1)
    except:
        pass

    # Determine overall risk level
    fg = risk["fear_greed_value"]
    vol = risk["volatility_30d"]
    dd = abs(risk["drawdown_from_ath"])

    if fg <= 20 or vol >= 80 or dd >= 30:
        risk["risk_level"] = "HIGH"
        risk["risk_color"] = "#EF4444"
    elif fg <= 35 or vol >= 60 or dd >= 20:
        risk["risk_level"] = "ELEVATED"
        risk["risk_color"] = "#F59E0B"
    elif fg >= 80:
        risk["risk_level"] = "ELEVATED (GREED)"
        risk["risk_color"] = "#F59E0B"
    else:
        risk["risk_level"] = "MODERATE"
        risk["risk_color"] = "#10B981"

    return risk


# ============================================
# 4. PEER ACTIVITY
# ============================================

def get_peer_activity():
    """
    Detect who bought, sold, or made announcements since yesterday.
    Uses leaderboard snapshot comparison.
    """
    activity = []

    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    try:
        # Get today's and yesterday's snapshots
        today_result = supabase.table("leaderboard_snapshots").select("*").eq("snapshot_date", today).limit(1).execute()
        yesterday_result = supabase.table("leaderboard_snapshots").select("*").eq("snapshot_date", yesterday).limit(1).execute()

        if not today_result.data or not yesterday_result.data:
            activity.append({
                "icon": "📊",
                "company": "System",
                "text": "Peer activity tracking will begin after 2 daily snapshots are recorded.",
                "type": "info",
                "btc_change": 0,
            })
            return activity

        today_holdings = json.loads(today_result.data[0].get("companies_json", "{}"))
        yesterday_holdings = json.loads(yesterday_result.data[0].get("companies_json", "{}"))

        # Compare holdings
        for ticker, today_data in today_holdings.items():
            today_btc = today_data.get("btc", 0) if isinstance(today_data, dict) else today_data
            company_name = today_data.get("name", ticker) if isinstance(today_data, dict) else ticker

            if ticker in yesterday_holdings:
                yesterday_data = yesterday_holdings[ticker]
                yesterday_btc = yesterday_data.get("btc", 0) if isinstance(yesterday_data, dict) else yesterday_data
                change = today_btc - yesterday_btc

                if change > 50:  # Meaningful purchase
                    activity.append({
                        "icon": "🟢",
                        "company": company_name,
                        "text": f"added {change:,} BTC (now holds {today_btc:,})",
                        "type": "bought",
                        "btc_change": change,
                    })
                elif change < -50:  # Meaningful sale
                    activity.append({
                        "icon": "🔴",
                        "company": company_name,
                        "text": f"reduced by {abs(change):,} BTC (now holds {today_btc:,})",
                        "type": "sold",
                        "btc_change": change,
                    })
            else:
                if today_btc > 100:  # New company appeared
                    activity.append({
                        "icon": "🆕",
                        "company": company_name,
                        "text": f"new treasury company with {today_btc:,} BTC",
                        "type": "new",
                        "btc_change": today_btc,
                    })

        # Sort by absolute BTC change
        activity.sort(key=lambda x: abs(x.get("btc_change", 0)), reverse=True)

    except Exception as e:
        activity.append({
            "icon": "⚠️",
            "company": "System",
            "text": f"Peer activity unavailable: {e}",
            "type": "error",
            "btc_change": 0,
        })

    if not activity:
        activity.append({
            "icon": "✅",
            "company": "All Companies",
            "text": "No significant changes in holdings detected since yesterday",
            "type": "quiet",
            "btc_change": 0,
        })

    return activity[:10]


# ============================================
# 5. WEEK AHEAD
# ============================================

def get_week_ahead():
    """
    Get upcoming events that could move Bitcoin markets this week.
    Combines known calendar events + auto-detected from news.
    """
    today = datetime.now()
    events = []

    # FOMC meetings 2026 (from Federal Reserve published schedule)
    fomc_dates = [
        "2026-01-28", "2026-03-18", "2026-05-06", "2026-06-17",
        "2026-07-29", "2026-09-16", "2026-11-04", "2026-12-16",
    ]
    # Note: These are published annually at federalreserve.gov
    # and don't change. This is the one acceptable "hardcoded" item
    # because the Fed publishes the full year's dates in advance.

    for date_str in fomc_dates:
        event_date = datetime.strptime(date_str, "%Y-%m-%d")
        days_until = (event_date - today).days
        if -1 <= days_until <= 7:
            if days_until == 0:
                timing = "TODAY"
            elif days_until == 1:
                timing = "TOMORROW"
            elif days_until < 0:
                timing = "YESTERDAY"
            else:
                timing = f"In {days_until} days"
            events.append({
                "date": date_str,
                "event": "FOMC Interest Rate Decision",
                "category": "Macro",
                "impact": "HIGH",
                "timing": timing,
                "description": "Federal Reserve interest rate decision. Rate cuts are bullish for Bitcoin; hawkish holds or hikes create short-term selling pressure.",
            })

    # Strategy Monday announcements (Saylor typically announces on Mondays)
    next_monday = today + timedelta(days=(7 - today.weekday()) % 7)
    if next_monday == today:
        timing = "TODAY"
    elif (next_monday - today).days == 1:
        timing = "TOMORROW"
    else:
        timing = f"In {(next_monday - today).days} days"

    events.append({
        "date": next_monday.strftime("%Y-%m-%d"),
        "event": "Strategy (MSTR) Potential BTC Purchase Announcement",
        "category": "Treasury",
        "impact": "HIGH",
        "timing": timing,
        "description": "Saylor historically announces Bitcoin purchases on Monday mornings via 8-K filing and tweet. Watch for weekend tweets hinting at upcoming purchase.",
    })

    # Quarterly earnings seasons (approximate)
    earnings_windows = [
        ("2026-01-20", "2026-02-15", "Q4 2025 Earnings Season"),
        ("2026-04-15", "2026-05-15", "Q1 2026 Earnings Season"),
        ("2026-07-15", "2026-08-15", "Q2 2026 Earnings Season"),
        ("2026-10-15", "2026-11-15", "Q3 2026 Earnings Season"),
    ]

    for start, end, label in earnings_windows:
        start_date = datetime.strptime(start, "%Y-%m-%d")
        end_date = datetime.strptime(end, "%Y-%m-%d")
        if start_date <= today <= end_date:
            events.append({
                "date": f"{start} to {end}",
                "event": label,
                "category": "Earnings",
                "impact": "MEDIUM",
                "timing": "NOW",
                "description": "Treasury companies report earnings and update BTC holdings. Watch for revised holding counts and new purchase announcements.",
            })

    # Bitcoin halving cycle check
    next_halving = datetime(2028, 4, 1)  # Approximate
    days_to_halving = (next_halving - today).days
    if days_to_halving <= 365:
        events.append({
            "date": "~April 2028",
            "event": "Bitcoin Halving",
            "category": "Bitcoin",
            "impact": "VERY HIGH",
            "timing": f"In ~{days_to_halving} days",
            "description": "Block reward halves from 3.125 to 1.5625 BTC. Historically triggers major bull runs 12-18 months before and after the event.",
        })

    # Options expiry (last Friday of month)
    last_day = today.replace(day=28)
    while last_day.weekday() != 4:  # Friday
        last_day -= timedelta(days=1)
    days_to_expiry = (last_day - today).days
    if 0 <= days_to_expiry <= 7:
        events.append({
            "date": last_day.strftime("%Y-%m-%d"),
            "event": "Monthly BTC Options Expiry",
            "category": "Market",
            "impact": "MEDIUM",
            "timing": f"In {days_to_expiry} days" if days_to_expiry > 0 else "TODAY",
            "description": "Large options expiry can cause volatility as market makers hedge positions. Max pain level often acts as a price magnet.",
        })

    # Sort by date proximity
    events.sort(key=lambda x: x.get("timing", ""), reverse=False)

    return events


# ============================================
# QUICK TEST
# ============================================
if __name__ == "__main__":
    print("\nCEO Decision Intelligence Module\n")
    print("=" * 60)

    # 1. Risk Dashboard
    print("\n[1] Risk Dashboard:")
    risk = get_risk_dashboard()
    print(f"  Fear & Greed: {risk['fear_greed_value']} ({risk['fear_greed_label']})")
    print(f"  30-Day Volatility: {risk['volatility_30d']}%")
    print(f"  Drawdown from ATH: {risk['drawdown_from_ath']}%")
    print(f"  Overall Risk: {risk['risk_level']}")

    # 2. Action Signal
    print("\n[2] Action Signal:")
    action = generate_action_signal(
        correlation_score=20, active_streams=1, strc_ratio=0.78,
        signals_24h=[], btc_change=-2.0, fear_greed_value=risk['fear_greed_value']
    )
    print(f"  {action['action']} (score: {action['score']})")
    print(f"  {action['summary']}")
    for r in action['reasons']:
        print(f"    • {r}")

    # 3. Overnight Changes
    print("\n[3] What Changed Overnight:")
    changes = get_overnight_changes(72000, 145, 0.78, 0, 1184886, 54)
    for c in changes:
        print(f"  {c['icon']} {c['text']}")

    # 4. Peer Activity
    print("\n[4] Peer Activity:")
    peers = get_peer_activity()
    for p in peers:
        print(f"  {p['icon']} {p['company']}: {p['text']}")

    # 5. Week Ahead
    print("\n[5] Week Ahead:")
    events = get_week_ahead()
    for e in events:
        print(f"  [{e['timing']}] {e['event']}")
        print(f"    Category: {e['category']} | Impact: {e['impact']}")

    print("\nCEO Intelligence Module is ready!")

