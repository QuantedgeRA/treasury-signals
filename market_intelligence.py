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
from logger import get_logger
from freshness_tracker import freshness

logger = get_logger(__name__)

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# ============================================
# 1. ACTION SIGNAL
# ============================================

def generate_action_signal(correlation_score, active_streams, strc_ratio, signals_24h, btc_change, fear_greed_value, pattern_match=None, subscriber=None):
    """
    Generate a CEO-level action recommendation based on all data streams.
    v2.0 — Enriched with historical patterns, confidence breakdown, and personalized advice.
    """
    score = 0
    reasons = []
    confidence_breakdown = []
    pattern_match = pattern_match or {}

    # ---- STREAM 1: Correlation Engine ----
    cor_contribution = 0
    if correlation_score >= 80:
        cor_contribution = 35
        reasons.append(f"Correlation Engine at {correlation_score}/100 — strong multi-stream convergence")
    elif correlation_score >= 50:
        cor_contribution = 20
        reasons.append(f"Correlation Engine at {correlation_score}/100 — moderate signal activity")
    elif correlation_score >= 25:
        cor_contribution = 10
        reasons.append(f"Correlation Engine at {correlation_score}/100 — single stream active")
    score += cor_contribution
    confidence_breakdown.append({"stream": "Correlation Engine", "contribution": cor_contribution, "max": 35, "icon": "🔗"})

    # ---- STREAM 2: STRC Volume ----
    strc_contribution = 0
    if strc_ratio >= 2.0:
        strc_contribution = 25
        reasons.append(f"STRC volume {strc_ratio}x normal — aggressive capital raise underway")
    elif strc_ratio >= 1.5:
        strc_contribution = 15
        reasons.append(f"STRC volume {strc_ratio}x normal — elevated capital raise activity")
    score += strc_contribution
    confidence_breakdown.append({"stream": "STRC Volume", "contribution": strc_contribution, "max": 25, "icon": "💰"})

    # ---- STREAM 3: Tweet Signals ----
    tweet_contribution = 0
    high_signals = len([s for s in signals_24h if s.get("confidence_score", 0) >= 60])
    if high_signals >= 2:
        tweet_contribution = 20
        reasons.append(f"{high_signals} high-confidence tweet signals detected")
    elif high_signals == 1:
        tweet_contribution = 10
        reasons.append("1 high-confidence tweet signal detected")
    score += tweet_contribution
    confidence_breakdown.append({"stream": "Tweet Signals", "contribution": tweet_contribution, "max": 20, "icon": "⚡"})

    # ---- STREAM 4: Market Conditions ----
    market_contribution = 0
    if btc_change <= -5:
        market_contribution += 10
        reasons.append(f"BTC down {btc_change:.1f}% — potential buying opportunity")
    elif btc_change >= 5:
        market_contribution -= 5
        reasons.append(f"BTC up {btc_change:.1f}% — elevated entry price")

    if fear_greed_value <= 25:
        market_contribution += 15
        reasons.append(f"Fear & Greed at {fear_greed_value} (Extreme Fear) — historically optimal buy zone")
    elif fear_greed_value <= 40:
        market_contribution += 10
        reasons.append(f"Fear & Greed at {fear_greed_value} (Fear) — favorable for accumulation")
    elif fear_greed_value >= 80:
        market_contribution -= 10
        reasons.append(f"Fear & Greed at {fear_greed_value} (Extreme Greed) — caution advised")
    score += market_contribution
    confidence_breakdown.append({"stream": "Market Conditions", "contribution": market_contribution, "max": 25, "icon": "📊"})

    # ---- STREAM 5: Historical Pattern Match (Phase 14) ----
    pattern_contribution = 0
    pattern_score = pattern_match.get("score", 0)
    matched_patterns = pattern_match.get("matching_patterns", [])
    pattern_narrative = pattern_match.get("narrative", "")

    if pattern_score >= 70:
        pattern_contribution = 15
        reasons.append(f"Historical patterns: {pattern_score}/100 — {len(matched_patterns)} patterns active (high alignment)")
    elif pattern_score >= 40:
        pattern_contribution = 8
        reasons.append(f"Historical patterns: {pattern_score}/100 — {len(matched_patterns)} patterns developing")
    elif pattern_score > 0:
        pattern_contribution = 3
        reasons.append(f"Historical patterns: {pattern_score}/100 — limited pattern activity")
    score += pattern_contribution
    confidence_breakdown.append({"stream": "Historical Patterns", "contribution": pattern_contribution, "max": 15, "icon": "🔮"})

    # ---- Determine Action ----
    if score >= 60:
        action = "🟢 BUY SIGNAL"
        action_color = "#10B981"
        summary = "Multiple data streams are converging. This is a high-confidence buying opportunity."
    elif score >= 40:
        action = "🔵 ACCUMULATE"
        action_color = "#3B82F6"
        summary = "Conditions are favorable for steady accumulation. Continue your planned purchase schedule."
    elif score >= 20:
        action = "⚪ HOLD"
        action_color = "#9CA3AF"
        summary = "No strong signals in either direction. Maintain current positions and continue monitoring."
    elif score >= 0:
        action = "🟡 WAIT"
        action_color = "#F59E0B"
        summary = "Markets are quiet with no clear catalysts. Use this time to prepare for the next opportunity."
    else:
        action = "🔴 CAUTION"
        action_color = "#EF4444"
        summary = "Risk indicators are elevated. Consider pausing new purchases until conditions improve."

    # ---- Historical Context ----
    historical_context = ""
    if matched_patterns:
        top_pattern = matched_patterns[0]
        historical_context = f"Pattern alert: {top_pattern['name']}. {top_pattern.get('historical_frequency', '')}"
        if pattern_score >= 70:
            historical_context += " When this many patterns align, a purchase typically follows within 48-72 hours."
        elif pattern_score >= 40:
            historical_context += " Conditions are developing — monitor for additional pattern activation."

    # ---- Subscriber-Specific Advice ----
    subscriber_advice = ""
    if subscriber and float(subscriber.get("btc_holdings", 0)) > 0:
        holdings = float(subscriber["btc_holdings"])
        company = subscriber.get("company_name", "Your company")

        if "BUY" in action:
            subscriber_advice = f"For {company}: with {holdings:,.0f} BTC, this high-conviction window could be optimal for a strategic addition to your treasury."
        elif "ACCUMULATE" in action:
            subscriber_advice = f"For {company}: conditions support your ongoing accumulation strategy. Consider a measured purchase to strengthen your {holdings:,.0f} BTC position."
        elif "HOLD" in action or "WAIT" in action:
            subscriber_advice = f"For {company}: your {holdings:,.0f} BTC position is stable. No action required — preserve capital for higher-conviction opportunities."
        elif "CAUTION" in action:
            subscriber_advice = f"For {company}: protect your {holdings:,.0f} BTC position. Avoid new purchases until risk indicators normalize."
    elif subscriber and subscriber.get("company_name"):
        company = subscriber["company_name"]
        if "BUY" in action:
            subscriber_advice = f"For {company}: this is a historically strong entry window for companies considering their first Bitcoin treasury allocation."
        elif "WAIT" in action or "HOLD" in action:
            subscriber_advice = f"For {company}: no urgency to act. Use this period to research and prepare a treasury allocation strategy."

    # ---- Build Enhanced Summary ----
    enhanced_summary = summary
    if historical_context:
        enhanced_summary += f" {historical_context}"
    if subscriber_advice:
        enhanced_summary += f" {subscriber_advice}"

    logger.info(f"Action signal: {action} (score: {score})")

    return {
        "action": action,
        "action_color": action_color,
        "score": score,
        "summary": enhanced_summary,
        "reasons": reasons,
        "confidence_breakdown": confidence_breakdown,
        "historical_context": historical_context,
        "subscriber_advice": subscriber_advice,
        "pattern_score": pattern_score,
        "pattern_narrative": pattern_narrative,
    }


# ============================================
# 2. WHAT CHANGED OVERNIGHT
# ============================================

def get_overnight_changes(btc_price, mstr_price, strc_ratio, total_signals, leaderboard_total_btc, reg_total):
    """Compare current state with yesterday's snapshot."""
    changes = []
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    prev_snapshot = None

    try:
        result = supabase.table("leaderboard_snapshots").select("*").eq("snapshot_date", yesterday).limit(1).execute()
        if result.data:
            prev_snapshot = result.data[0]
    except Exception as e:
        logger.warning(f"Could not fetch yesterday's snapshot: {e}")

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

    if total_signals > 0:
        changes.append({
            "icon": "🚨",
            "text": f"{total_signals} new purchase signal(s) detected overnight",
            "type": "positive",
        })

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
    Fetch risk indicators: Fear & Greed, Volatility, Drawdown.
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

    # Fear & Greed Index
    try:
        response = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get("data"):
                fg = data["data"][0]
                risk["fear_greed_value"] = int(fg.get("value", 50))
                risk["fear_greed_label"] = fg.get("value_classification", "Neutral")
                freshness.record_success("fear_greed", detail=f"Value: {risk['fear_greed_value']} ({risk['fear_greed_label']})")
        else:
            logger.warning(f"Fear & Greed API returned {response.status_code}")
            freshness.record_failure("fear_greed", error=f"HTTP {response.status_code}")
    except Exception as e:
        logger.warning(f"Fear & Greed API failed: {e}")
        freshness.record_failure("fear_greed", error=str(e))

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

            if len(hist) >= 30:
                returns = hist["Close"].pct_change().tail(30)
                risk["volatility_30d"] = round(float(returns.std() * (365 ** 0.5) * 100), 1)
    except Exception as e:
        logger.warning(f"BTC price data fetch failed for risk dashboard: {e}")

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

    logger.info(f"Risk dashboard: {risk['risk_level']} | F&G: {risk['fear_greed_value']} | Vol: {risk['volatility_30d']}%")

    return risk


# ============================================
# 4. PEER ACTIVITY
# ============================================

def get_peer_activity():
    """Detect who bought, sold, or made announcements since yesterday."""
    activity = []
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    try:
        today_result = supabase.table("leaderboard_snapshots").select("*").eq("snapshot_date", today).limit(1).execute()
        yesterday_result = supabase.table("leaderboard_snapshots").select("*").eq("snapshot_date", yesterday).limit(1).execute()

        if not today_result.data or not yesterday_result.data:
            activity.append({
                "icon": "📊", "company": "System",
                "text": "Peer activity tracking will begin after 2 daily snapshots are recorded.",
                "type": "info", "btc_change": 0,
            })
            return activity

        today_holdings = json.loads(today_result.data[0].get("companies_json", "{}"))
        yesterday_holdings = json.loads(yesterday_result.data[0].get("companies_json", "{}"))

        for ticker, today_data in today_holdings.items():
            today_btc = today_data.get("btc", 0) if isinstance(today_data, dict) else today_data
            company_name = today_data.get("name", ticker) if isinstance(today_data, dict) else ticker

            if ticker in yesterday_holdings:
                yesterday_data = yesterday_holdings[ticker]
                yesterday_btc = yesterday_data.get("btc", 0) if isinstance(yesterday_data, dict) else yesterday_data
                change = today_btc - yesterday_btc

                if change > 50:
                    activity.append({
                        "icon": "🟢", "company": company_name,
                        "text": f"added {change:,} BTC (now holds {today_btc:,})",
                        "type": "bought", "btc_change": change,
                    })
                elif change < -50:
                    activity.append({
                        "icon": "🔴", "company": company_name,
                        "text": f"reduced by {abs(change):,} BTC (now holds {today_btc:,})",
                        "type": "sold", "btc_change": change,
                    })
            else:
                if today_btc > 100:
                    activity.append({
                        "icon": "🆕", "company": company_name,
                        "text": f"new treasury company with {today_btc:,} BTC",
                        "type": "new", "btc_change": today_btc,
                    })

        activity.sort(key=lambda x: abs(x.get("btc_change", 0)), reverse=True)

    except Exception as e:
        logger.error(f"Peer activity fetch failed: {e}", exc_info=True)
        activity.append({
            "icon": "⚠️", "company": "System",
            "text": f"Peer activity unavailable: {e}",
            "type": "error", "btc_change": 0,
        })

    if not activity:
        activity.append({
            "icon": "✅", "company": "All Companies",
            "text": "No significant changes in holdings detected since yesterday",
            "type": "quiet", "btc_change": 0,
        })

    return activity[:10]


# ============================================
# 5. WEEK AHEAD
# ============================================

def get_week_ahead():
    """Get upcoming events that could move Bitcoin markets this week."""
    today = datetime.now()
    events = []

    fomc_dates = [
        "2026-01-28", "2026-03-18", "2026-05-06", "2026-06-17",
        "2026-07-29", "2026-09-16", "2026-11-04", "2026-12-16",
    ]

    for date_str in fomc_dates:
        try:
            event_date = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError as e:
            logger.warning(f"Invalid FOMC date '{date_str}': {e}")
            continue
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
                "category": "Macro", "impact": "HIGH", "timing": timing,
                "description": "Federal Reserve interest rate decision. Rate cuts are bullish for Bitcoin; hawkish holds or hikes create short-term selling pressure.",
            })

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
        "category": "Treasury", "impact": "HIGH", "timing": timing,
        "description": "Saylor historically announces Bitcoin purchases on Monday mornings via 8-K filing and tweet.",
    })

    earnings_windows = [
        ("2026-01-20", "2026-02-15", "Q4 2025 Earnings Season"),
        ("2026-04-15", "2026-05-15", "Q1 2026 Earnings Season"),
        ("2026-07-15", "2026-08-15", "Q2 2026 Earnings Season"),
        ("2026-10-15", "2026-11-15", "Q3 2026 Earnings Season"),
    ]

    for start, end, label in earnings_windows:
        try:
            start_date = datetime.strptime(start, "%Y-%m-%d")
            end_date = datetime.strptime(end, "%Y-%m-%d")
        except ValueError as e:
            logger.warning(f"Invalid earnings date: {e}")
            continue
        if start_date <= today <= end_date:
            events.append({
                "date": f"{start} to {end}",
                "event": label,
                "category": "Earnings", "impact": "MEDIUM", "timing": "NOW",
                "description": "Treasury companies report earnings and update BTC holdings.",
            })

    next_halving = datetime(2028, 4, 1)
    days_to_halving = (next_halving - today).days
    if days_to_halving <= 365:
        events.append({
            "date": "~April 2028",
            "event": "Bitcoin Halving",
            "category": "Bitcoin", "impact": "VERY HIGH",
            "timing": f"In ~{days_to_halving} days",
            "description": "Block reward halves from 3.125 to 1.5625 BTC. Historically triggers major bull runs.",
        })

    last_day = today.replace(day=28)
    while last_day.weekday() != 4:
        last_day -= timedelta(days=1)
    days_to_expiry = (last_day - today).days
    if 0 <= days_to_expiry <= 7:
        events.append({
            "date": last_day.strftime("%Y-%m-%d"),
            "event": "Monthly BTC Options Expiry",
            "category": "Market", "impact": "MEDIUM",
            "timing": f"In {days_to_expiry} days" if days_to_expiry > 0 else "TODAY",
            "description": "Large options expiry can cause volatility as market makers hedge positions.",
        })

    events.sort(key=lambda x: x.get("timing", ""), reverse=False)
    return events


# ============================================
# QUICK TEST
# ============================================
if __name__ == "__main__":
    logger.info("CEO Decision Intelligence Module — testing...")

    risk = get_risk_dashboard()
    action = generate_action_signal(
        correlation_score=20, active_streams=1, strc_ratio=0.78,
        signals_24h=[], btc_change=-2.0, fear_greed_value=risk['fear_greed_value']
    )
    changes = get_overnight_changes(72000, 145, 0.78, 0, 1184886, 54)
    peers = get_peer_activity()
    events = get_week_ahead()

    logger.info(f"Action: {action['action']} | Risk: {risk['risk_level']} | Changes: {len(changes)} | Peers: {len(peers)} | Events: {len(events)}")
    logger.info("CEO Intelligence Module test complete")
