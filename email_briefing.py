"""
email_briefing.py
-----------------
Executive Daily Intelligence Briefing v4.0

Full CEO intelligence report with:
- Action Signal (Buy/Hold/Wait)
- Risk Dashboard (Fear & Greed, Volatility, Drawdown)
- What Changed Overnight
- Peer Activity
- Week Ahead
- Executive Summary
- Market Snapshot + STRC Status
- Correlation Engine
- Purchase Signals
- Recent Confirmed Purchases
- BTC Treasury Leaderboard (Top 10 + link to all)
- Global Regulatory Landscape
- Notable Statements
- Intelligence Performance (Accuracy)
"""

import os
import resend
from datetime import datetime, timedelta
from dotenv import load_dotenv
from supabase import create_client
from strc_tracker import get_strc_volume_data, analyze_strc_signal
from treasury_leaderboard import get_leaderboard_with_live_price
from regulatory_tracker import get_all_regulatory_items, get_summary_stats as get_reg_stats, get_all_statements_combined as get_all_statements
from purchase_tracker import get_recent_purchases, get_purchase_stats
from correlation_engine import CorrelationEngine
from market_intelligence import generate_action_signal, get_overnight_changes, get_risk_dashboard, get_peer_activity, get_week_ahead
import yfinance as yf
from logger import get_logger
from freshness_tracker import freshness
from subscriber_manager import subscribers as sub_mgr
from watchlist_manager import get_watchlist_activity, format_watchlist_email_html

logger = get_logger(__name__)

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
RESEND_API_KEY = os.getenv("RESEND_API_KEY")

# Email sender configuration
# Update these in .env after setting up your custom domain on Resend
EMAIL_FROM_NAME = os.getenv("EMAIL_FROM_NAME", "Treasury Signal Intelligence")
EMAIL_FROM_ADDRESS = os.getenv("EMAIL_FROM_ADDRESS", "onboarding@resend.dev")
EMAIL_REPLY_TO = os.getenv("EMAIL_REPLY_TO", "")
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "https://treasury-signals-jqyywcwr8l8pbtv66rvbbg.streamlit.app")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
resend.api_key = RESEND_API_KEY


def get_market_data():
    data = {}
    try:
        btc = yf.Ticker("BTC-USD")
        hist = btc.history(period="5d")
        if not hist.empty:
            data["btc_price"] = round(float(hist["Close"].iloc[-1]), 2)
            data["btc_prev"] = round(float(hist["Close"].iloc[-2]), 2) if len(hist) > 1 else data["btc_price"]
            data["btc_change"] = round(((data["btc_price"] - data["btc_prev"]) / data["btc_prev"]) * 100, 2)
            freshness.record_success("btc_yfinance", detail=f"BTC ${data['btc_price']:,.0f}")
            freshness.set_provenance("btc_price", "Yahoo Finance", "live")
    except Exception as e:
        logger.warning(f"BTC price fetch failed for briefing: {e}")
        freshness.record_failure("btc_yfinance", error=str(e))
        freshness.set_provenance("btc_price", "Unavailable", "fallback")
        data["btc_price"] = 0
        data["btc_change"] = 0
    try:
        mstr = yf.Ticker("MSTR")
        hist = mstr.history(period="5d")
        if not hist.empty:
            data["mstr_price"] = round(float(hist["Close"].iloc[-1]), 2)
            data["mstr_prev"] = round(float(hist["Close"].iloc[-2]), 2) if len(hist) > 1 else data["mstr_price"]
            data["mstr_change"] = round(((data["mstr_price"] - data["mstr_prev"]) / data["mstr_prev"]) * 100, 2)
            freshness.record_success("mstr_yfinance", detail=f"MSTR ${data['mstr_price']:,.2f}")
            freshness.set_provenance("mstr_price", "Yahoo Finance", "live")
    except Exception as e:
        logger.warning(f"MSTR price fetch failed for briefing: {e}")
        freshness.record_failure("mstr_yfinance", error=str(e))
        freshness.set_provenance("mstr_price", "Unavailable", "fallback")
        data["mstr_price"] = 0
        data["mstr_change"] = 0
    try:
        strc_data = get_strc_volume_data()
        if strc_data:
            data["strc_price"] = strc_data["price"]
            data["strc_volume_m"] = strc_data["dollar_volume_m"]
            data["strc_ratio"] = strc_data["volume_ratio"]
        else:
            data["strc_price"] = 0
            data["strc_volume_m"] = 0
            data["strc_ratio"] = 0
    except Exception as e:
        logger.warning(f"STRC data fetch failed for briefing: {e}")
        data["strc_price"] = 0
        data["strc_volume_m"] = 0
        data["strc_ratio"] = 0
    return data


def get_recent_signals(hours=24):
    try:
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        result = supabase.table("tweets").select("*").eq("is_signal", True).gte("inserted_at", cutoff).order("confidence_score", desc=True).limit(10).execute()
        return result.data if result.data else []
    except Exception as e:
        logger.error(f"Failed to fetch recent signals: {e}", exc_info=True)
        return []


def get_all_signals():
    try:
        result = supabase.table("tweets").select("*").eq("is_signal", True).order("inserted_at", desc=True).execute()
        return result.data if result.data else []
    except Exception as e:
        logger.error(f"Failed to fetch all signals: {e}", exc_info=True)
        return []


def get_accuracy_data():
    try:
        purchases = supabase.table("confirmed_purchases").select("*").execute()
        predictions = supabase.table("predictions").select("*").execute()
        all_purchases = purchases.data if purchases.data else []
        all_predictions = predictions.data if predictions.data else []
        total = len(all_purchases)
        predicted = len([p for p in all_purchases if p.get("was_predicted")])
        hit_rate = round(predicted / total * 100, 1) if total > 0 else 0
        return {"total_purchases": total, "predicted": predicted, "hit_rate": hit_rate, "total_predictions": len(all_predictions)}
    except Exception as e:
        logger.error(f"Failed to fetch accuracy data: {e}", exc_info=True)
        return {"total_purchases": 0, "predicted": 0, "hit_rate": 0, "total_predictions": 0}


def _get_feedback_email_html():
    """Get feedback loop insights HTML for the email."""
    try:
        from feedback_loop import feedback_engine
        return feedback_engine.format_for_email_html()
    except Exception:
        return ""


def build_briefing_html(market, signals, all_signals, leaderboard, lb_summary, reg_stats, reg_items, accuracy, statements, purchases, purchase_stats, correlation, action=None, risk=None, changes=None, peers=None, week_ahead=None, subscriber=None, personalization=None, pattern_match=None):

    today = datetime.now().strftime("%A, %B %d, %Y")
    time_now = datetime.now().strftime("%I:%M %p ET")
    personalization = personalization or {}
    pattern_match = pattern_match or {"score": 0, "matching_patterns": [], "narrative": ""}

    # Personalization
    subscriber_name = subscriber.get("name", "").split()[0] if subscriber else ""
    subscriber_company = subscriber.get("company_name", "") if subscriber else ""
    subscriber_ticker = subscriber.get("ticker", "") if subscriber else ""
    subscriber_btc = float(subscriber.get("btc_holdings", 0)) if subscriber else 0
    subscriber_cost = float(subscriber.get("total_invested_usd", 0)) if subscriber else 0
    subscriber_avg_price = float(subscriber.get("avg_purchase_price", 0)) if subscriber else 0
    has_profile = subscriber is not None and subscriber_company

    # Build personalized greeting
    if has_profile and subscriber_name:
        greeting_html = f'<span style="color: #e0e0e0; font-size: 22px; font-weight: 700; letter-spacing: -0.02em;">Good morning, {subscriber_name}</span>'
    else:
        greeting_html = '<span style="color: #e0e0e0; font-size: 22px; font-weight: 700; letter-spacing: -0.02em;">Executive Daily Briefing</span>'

    # Build "Your Position" section if subscriber has holdings
    your_position_html = ""
    if has_profile and subscriber_btc > 0:
        btc_price = market.get("btc_price", 0)
        position_value = subscriber_btc * btc_price
        position_value_m = position_value / 1_000_000

        # Calculate P&L
        pnl_html = ""
        if subscriber_cost > 0:
            pnl = position_value - subscriber_cost
            pnl_pct = (pnl / subscriber_cost) * 100
            pnl_color = "#10B981" if pnl >= 0 else "#EF4444"
            pnl_arrow = "▲" if pnl >= 0 else "▼"
            pnl_html = f"""
                <td width="25%" style="padding: 14px 8px; text-align: center; background: #111827; border-radius: 10px;">
                    <span style="color: {pnl_color}; font-size: 20px; font-weight: 800; font-family: 'Courier New', monospace;">{pnl_arrow}{abs(pnl_pct):.1f}%</span>
                    <br><span style="color: #4b5563; font-size: 9px; font-weight: 600; text-transform: uppercase;">Unrealized P&L</span>
                    <br><span style="color: {pnl_color}; font-size: 10px;">${pnl/1_000_000:+,.1f}M</span>
                </td>
                <td width="2%"></td>"""

        # Find rank
        corporate = [c for c in leaderboard if not c.get("is_government") and c.get("btc_holdings", 0) > 0]
        corporate.sort(key=lambda x: x.get("btc_holdings", 0), reverse=True)
        rank = len(corporate) + 1
        next_gap = 0
        for i, c in enumerate(corporate):
            if subscriber_btc >= c.get("btc_holdings", 0):
                rank = i + 1
                if i > 0:
                    next_gap = corporate[i-1]["btc_holdings"] - subscriber_btc
                break

        rank_html = f"""
            <td width="25%" style="padding: 14px 8px; text-align: center; background: #111827; border-radius: 10px; border: 1px solid #E67E2240;">
                <span style="color: #E67E22; font-size: 24px; font-weight: 800; font-family: 'Courier New', monospace;">#{rank}</span>
                <br><span style="color: #4b5563; font-size: 9px; font-weight: 600; text-transform: uppercase;">Your Rank</span>
                <br><span style="color: #6b7280; font-size: 10px;">of {len(corporate)} companies</span>
            </td>"""

        gap_html = ""
        if next_gap > 0 and rank > 1:
            gap_html = f'<p style="color: #9ca3af; font-size: 11px; margin: 8px 0 0 0; text-align: center;">🎯 Buy <span style="color: #E67E22; font-weight: 700;">{next_gap:,.0f} BTC</span> to move up to #{rank-1}</p>'

        your_position_html = f"""
            <!-- YOUR POSITION -->
            <tr><td style="padding: 16px 36px 8px 36px;">
                <span style="color: #E67E22; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.12em;">📍 Your Position — {subscriber_company}</span>
                {f'<span style="color: #4b5563; font-size: 10px; margin-left: 8px;">({subscriber_ticker})</span>' if subscriber_ticker else ''}
                <table width="100%" cellpadding="0" cellspacing="0" style="margin-top: 10px;">
                    <tr>
                        <td width="25%" style="padding: 14px 8px; text-align: center; background: #111827; border-radius: 10px;">
                            <span style="color: #f0f0f0; font-size: 20px; font-weight: 800; font-family: 'Courier New', monospace;">{subscriber_btc:,.0f}</span>
                            <br><span style="color: #4b5563; font-size: 9px; font-weight: 600; text-transform: uppercase;">Your BTC</span>
                        </td>
                        <td width="2%"></td>
                        <td width="25%" style="padding: 14px 8px; text-align: center; background: #111827; border-radius: 10px;">
                            <span style="color: #f0f0f0; font-size: 20px; font-weight: 800; font-family: 'Courier New', monospace;">${position_value_m:,.1f}M</span>
                            <br><span style="color: #4b5563; font-size: 9px; font-weight: 600; text-transform: uppercase;">Current Value</span>
                        </td>
                        <td width="2%"></td>
                        {pnl_html}
                        {rank_html}
                    </tr>
                </table>
                {gap_html}
            </td></tr>
            <tr><td style="padding: 8px 36px;"><div style="border-top: 1px solid #1e2a3a;"></div></td></tr>
        """
    elif has_profile and subscriber_btc == 0:
        # Subscriber has profile but no BTC yet — show encouragement
        corporate = [c for c in leaderboard if not c.get("is_government") and c.get("btc_holdings", 0) > 0]
        smallest = corporate[-1] if corporate else None
        smallest_text = f"The smallest holder on our leaderboard ({smallest['company']}) holds {smallest['btc_holdings']:,} BTC." if smallest else ""
        your_position_html = f"""
            <!-- YOUR POSITION (no holdings yet) -->
            <tr><td style="padding: 16px 36px 8px 36px;">
                <div style="background: linear-gradient(135deg, #1a0f00 0%, #111827 100%); border: 1px solid #E67E2230; border-radius: 12px; padding: 18px 24px; text-align: center;">
                    <span style="color: #E67E22; font-size: 12px; font-weight: 700;">📍 {subscriber_company}</span>
                    <p style="color: #9ca3af; font-size: 12px; margin: 8px 0 0 0;">Your company hasn't added Bitcoin to the treasury yet. {smallest_text}</p>
                </div>
            </td></tr>
        """

    # ============================================
    # DEEP PERSONALIZATION SECTIONS (Phase 6)
    # ============================================

    # Holdings change acknowledgment
    holdings_change_html = ""
    holdings_change = personalization.get("holdings_change")
    if holdings_change:
        direction = holdings_change["direction"]
        change = abs(holdings_change["change_btc"])
        prev = holdings_change["previous_btc"]
        curr = holdings_change["current_btc"]
        ch_color = "#10B981" if direction == "increased" else "#EF4444"
        ch_icon = "📈" if direction == "increased" else "📉"
        holdings_change_html = f"""
            <tr><td style="padding: 4px 36px 8px 36px;">
                <div style="background: rgba(16,185,129,0.06); border: 1px solid {ch_color}30; border-radius: 8px; padding: 10px 16px;">
                    <span style="color: {ch_color}; font-size: 12px; font-weight: 600;">{ch_icon} Your holdings {direction} from {prev:,.0f} to {curr:,.0f} BTC ({'+' if direction == 'increased' else '-'}{change:,.0f} BTC since yesterday)</span>
                </div>
            </td></tr>
        """

    # Personalized context paragraph (after action signal)
    personalized_context_html = ""
    context_text = personalization.get("context", "")
    if context_text and has_profile:
        personalized_context_html = f"""
            <tr><td style="padding: 0 36px 12px 36px;">
                <div style="background: linear-gradient(135deg, #1a0f00 0%, #111827 100%); border-left: 3px solid #E67E22; border-radius: 0 8px 8px 0; padding: 14px 18px;">
                    <span style="color: #E67E22; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.1em;">What This Means For {subscriber_company}</span>
                    <p style="color: #d1d5db; font-size: 13px; line-height: 1.6; margin: 8px 0 0 0;">{context_text}</p>
                </div>
            </td></tr>
        """

    # Competitor spotlight
    competitor_spotlight_html = ""
    spotlight = personalization.get("competitor_spotlight", [])
    if spotlight and has_profile:
        rows = ""
        for comp in spotlight[:3]:
            rel_color = "#10B981" if comp["relationship"] == "behind" else "#EF4444" if comp["relationship"] == "ahead" else "#F59E0B"
            rel_icon = "⬇️" if comp["relationship"] == "behind" else "⬆️" if comp["relationship"] == "ahead" else "↔️"
            purchase_badge = f'<br><span style="color: #E67E22; font-size: 10px;">💰 {comp["recent_purchase"]}</span>' if comp.get("recent_purchase") else ""
            rows += f"""
                <tr>
                    <td style="padding: 10px 18px; border-bottom: 1px solid #1e2a3a;">
                        <span style="color: #9ca3af; font-size: 11px;">#{comp['rank']}</span>
                        <strong style="color: #e0e0e0; font-size: 13px; margin-left: 6px;">{comp['company'][:30]}</strong>
                        {f'<span style="color: #4b5563; font-size: 11px;"> ({comp["ticker"]})</span>' if comp.get("ticker") else ""}
                    </td>
                    <td style="padding: 10px 14px; border-bottom: 1px solid #1e2a3a; text-align: right;">
                        <span style="color: #f0f0f0; font-family: 'Courier New', monospace; font-size: 12px; font-weight: 600;">{comp['btc_holdings']:,}</span>
                        <span style="color: #6b7280; font-size: 10px;"> BTC</span>
                    </td>
                    <td style="padding: 10px 18px; border-bottom: 1px solid #1e2a3a; text-align: right;">
                        <span style="color: {rel_color}; font-size: 11px; font-weight: 600;">{rel_icon} {comp['rel_text']}</span>
                        {purchase_badge}
                    </td>
                </tr>"""

        competitor_spotlight_html = f"""
            <tr><td style="padding: 8px 36px 12px 36px;">
                <span style="color: #6b7280; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.12em;">🔍 Competitor Spotlight</span>
                <p style="color: #4b5563; font-size: 11px; margin: 2px 0 8px 0;">Companies closest to {subscriber_company} on the leaderboard</p>
                <table width="100%" cellpadding="0" cellspacing="0" style="background: #111827; border-radius: 10px; overflow: hidden;">
                    <tr>
                        <td style="padding: 6px 18px; border-bottom: 1px solid #1e2a3a; color: #4b5563; font-size: 9px; font-weight: 600; text-transform: uppercase;">Company</td>
                        <td style="padding: 6px 14px; border-bottom: 1px solid #1e2a3a; color: #4b5563; font-size: 9px; font-weight: 600; text-align: right; text-transform: uppercase;">Holdings</td>
                        <td style="padding: 6px 18px; border-bottom: 1px solid #1e2a3a; color: #4b5563; font-size: 9px; font-weight: 600; text-align: right; text-transform: uppercase;">vs You</td>
                    </tr>
                    {rows}
                </table>
            </td></tr>
        """

    # Sector peers
    sector_peers_html = ""
    sector_peers = personalization.get("sector_peers", [])
    if sector_peers and has_profile:
        peer_rows = ""
        for p in sector_peers[:5]:
            peer_rows += f"""
                <tr>
                    <td style="padding: 6px 18px; border-bottom: 1px solid #1e2a3a;">
                        <span style="color: #9ca3af; font-size: 11px;">#{p['rank']}</span>
                        <span style="color: #d1d5db; font-size: 12px; margin-left: 6px;">{p['company'][:30]}</span>
                    </td>
                    <td style="padding: 6px 18px; border-bottom: 1px solid #1e2a3a; text-align: right;">
                        <span style="color: #f0f0f0; font-family: 'Courier New', monospace; font-size: 11px;">{p['btc_holdings']:,} BTC</span>
                    </td>
                </tr>"""

        subscriber_sector = subscriber.get("sector", "Your Sector") if subscriber else "Your Sector"
        sector_peers_html = f"""
            <tr><td style="padding: 4px 36px 12px 36px;">
                <span style="color: #6b7280; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.12em;">🏢 Peers in {subscriber_sector}</span>
                <table width="100%" cellpadding="0" cellspacing="0" style="background: #111827; border-radius: 10px; overflow: hidden; margin-top: 6px;">
                    {peer_rows}
                </table>
            </td></tr>
        """

    # Watchlist activity (Phase 8)
    watchlist_html = ""
    watchlist_activity = personalization.get("watchlist_activity", [])
    if watchlist_activity and has_profile:
        watchlist_html = format_watchlist_email_html(watchlist_activity)

    # Historical pattern match (Phase 14)
    pattern_html = ""
    pm_score = pattern_match.get("score", 0)
    pm_patterns = pattern_match.get("matching_patterns", [])
    pm_narrative = pattern_match.get("narrative", "")
    if pm_score > 0 or pm_patterns:
        pm_color = "#EF4444" if pm_score >= 70 else "#F59E0B" if pm_score >= 40 else "#6B7280"
        pm_icon = "🔴" if pm_score >= 70 else "🟡" if pm_score >= 40 else "⚪"
        pm_rows = ""
        for p in pm_patterns[:4]:
            pm_rows += f"""<tr><td style="padding: 6px 18px; border-bottom: 1px solid #1e2a3a;"><span style="color: #10B981;">✅</span> <span style="color: #d1d5db; font-size: 12px;">{p['name']}</span><br><span style="color: #9ca3af; font-size: 11px;">{p['match_detail']}</span></td><td style="padding: 6px 14px; border-bottom: 1px solid #1e2a3a; text-align: right; vertical-align: top;"><span style="color: #6b7280; font-size: 10px;">{p['historical_frequency'][:40]}</span></td></tr>"""

        pattern_html = f"""
            <tr><td style="padding: 8px 36px 12px 36px;">
                <table width="100%" cellpadding="0" cellspacing="0"><tr>
                    <td><span style="color: #6b7280; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.12em;">🔮 Historical Pattern Match</span></td>
                    <td style="text-align: right;"><span style="color: {pm_color}; font-size: 18px; font-weight: 800; font-family: 'Courier New', monospace;">{pm_icon} {pm_score}/100</span></td>
                </tr></table>
                <p style="color: #9ca3af; font-size: 11px; margin: 4px 0 8px 0;">{pm_narrative[:200]}</p>
                {'<table width="100%" cellpadding="0" cellspacing="0" style="background: #111827; border-radius: 10px; overflow: hidden;">' + pm_rows + '</table>' if pm_rows else ''}
            </td></tr>
        """

    btc_price = market.get("btc_price", 0)
    btc_change = market.get("btc_change", 0)
    btc_color = "#10B981" if btc_change >= 0 else "#EF4444"
    btc_arrow = "▲" if btc_change >= 0 else "▼"
    mstr_color = "#10B981" if market.get("mstr_change", 0) >= 0 else "#EF4444"
    mstr_arrow = "▲" if market.get("mstr_change", 0) >= 0 else "▼"

    strc_ratio = market.get("strc_ratio", 0)
    if strc_ratio >= 2.0:
        strc_status = "VERY HIGH — Aggressive capital raise detected"
        strc_color = "#EF4444"
        strc_dot = "🔴"
    elif strc_ratio >= 1.5:
        strc_status = "HIGH — Elevated issuance activity"
        strc_color = "#F59E0B"
        strc_dot = "🟠"
    elif strc_ratio >= 1.2:
        strc_status = "ELEVATED — Above average"
        strc_color = "#FBBF24"
        strc_dot = "🟡"
    else:
        strc_status = "NORMAL — Baseline activity"
        strc_color = "#10B981"
        strc_dot = "🟢"

    cor_score = correlation.get("correlated_score", 0)
    cor_active = correlation.get("active_streams", 0)
    cor_narrative = correlation.get("narrative", "No significant signals.")
    if cor_score >= 70:
        cor_color = "#EF4444"
    elif cor_score >= 50:
        cor_color = "#F59E0B"
    elif cor_score >= 25:
        cor_color = "#3B82F6"
    else:
        cor_color = "#4b5563"

    # Executive summary bullets
    exec_bullets = []
    if len(signals) > 0:
        top_sig = max(signals, key=lambda x: x.get("confidence_score", 0))
        exec_bullets.append(f"<span style='color: #F59E0B;'>⚡</span> {len(signals)} purchase signal(s) detected — highest: {top_sig.get('confidence_score', 0)}/100 from @{top_sig.get('author_username', '')}")
    else:
        exec_bullets.append("<span style='color: #10B981;'>✅</span> No purchase signals in the last 24 hours — market is quiet")
    if strc_ratio >= 1.5:
        exec_bullets.append(f"<span style='color: #EF4444;'>🔴</span> STRC volume is {strc_ratio}x normal — capital raise activity elevated")
    else:
        exec_bullets.append(f"<span style='color: #10B981;'>🟢</span> STRC volume is {strc_ratio}x normal — no unusual capital raise activity")
    if cor_active >= 2:
        exec_bullets.append(f"<span style='color: #F59E0B;'>🔗</span> Correlation Engine: {cor_score}/100 — {cor_active}/4 streams active")
    else:
        exec_bullets.append(f"<span style='color: #4b5563;'>🔗</span> Correlation Engine: {cor_score}/100 — baseline, no multi-stream convergence")
    if purchases:
        latest = purchases[0]
        exec_bullets.append(f"<span style='color: #E67E22;'>💰</span> Last confirmed purchase: {latest['company'].replace(' (MicroStrategy)', '')} bought {latest['btc_amount']:,} BTC on {latest['filing_date']}")
    exec_bullets.append(f"<span style='color: #3B82F6;'>🏛️</span> Regulatory: {reg_stats['total_items']} items tracked across {reg_stats['regions_tracked']} regions — {reg_stats['bullish']} bullish for BTC")

    exec_tooltips = {
        0: "Our AI monitors 24+ executive accounts, scoring tweets 0-100 for purchase intent. Signals above 60 historically precede purchases within 24-72 hours.",
        1: "STRC is Strategy's preferred stock for raising Bitcoin purchase capital. Volume above 1.5x the 20-day average signals an imminent buy.",
        2: "4 data streams monitored simultaneously. Single stream = 35% confidence. Three streams converging = 99% confidence.",
        3: "Compares daily leaderboard snapshots across 148 companies. When holdings increase, a purchase is auto-detected.",
        4: "Tracks legislation, regulations, and policy across 6 global regions. Auto-scans news every hour for new developments.",
    }
    exec_summary_html = ""
    for i, b in enumerate(exec_bullets):
        tooltip_text = exec_tooltips.get(i, "")
        title_attr = f' title="{tooltip_text}"' if tooltip_text else ""
        exec_summary_html += f'<tr><td style="padding: 6px 18px; color: #d1d5db; font-size: 13px; line-height: 1.6; cursor: help;"{title_attr}>{b}</td></tr>'

    # Signals HTML
    if signals:
        signals_html = ""
        for sig in signals[:5]:
            score = sig.get("confidence_score", 0)
            author = sig.get("author_username", "")
            text = sig.get("tweet_text", "")[:140]
            company = sig.get("company", "")
            sig_color = "#EF4444" if score >= 60 else "#F59E0B" if score >= 40 else "#FBBF24"
            sig_bg = f"rgba({','.join(str(int(sig_color.lstrip('#')[i:i+2], 16)) for i in (0,2,4))},0.08)"
            signals_html += f"""
            <tr><td style="padding: 14px 18px; border-bottom: 1px solid #1e2a3a;">
                <table width="100%" cellpadding="0" cellspacing="0"><tr>
                    <td width="70" style="vertical-align: top;">
                        <div style="background: {sig_bg}; border: 1px solid {sig_color}; border-radius: 8px; padding: 6px 0; text-align: center; width: 64px;">
                            <span style="color: {sig_color}; font-size: 18px; font-weight: 800; font-family: 'Courier New', monospace;">{score}</span>
                            <br><span style="color: {sig_color}; font-size: 9px; font-weight: 700; letter-spacing: 0.05em;">/100</span>
                        </div>
                    </td>
                    <td style="padding-left: 14px; vertical-align: top;">
                        <span style="color: #e0e0e0; font-weight: 600; font-size: 14px;">@{author}</span>
                        <span style="color: #4b5563; font-size: 12px;"> — {company}</span>
                        <br><span style="color: #9ca3af; font-size: 13px; line-height: 1.5;">{text}...</span>
                    </td>
                </tr></table>
            </td></tr>"""
        signal_summary = f"<span style='color: #F59E0B; font-weight: 600;'>{len(signals)} signal(s)</span> detected"
    else:
        signals_html = """<tr><td style="padding: 20px 18px; text-align: center;">
            <span style="color: #10B981; font-size: 14px;">✅ All clear — no purchase signals in the last 24 hours</span>
        </td></tr>"""
        signal_summary = "<span style='color: #10B981;'>All clear</span>"

    # Correlation streams
    stream_check = lambda active: "✅" if active else "⬜"
    cor_streams_html = f"""
    <tr><td style="padding: 14px 18px; border-bottom: 1px solid #1e2a3a;">
        <table width="100%" cellpadding="0" cellspacing="0">
            <tr>
                <td width="50%" style="color: #d1d5db; font-size: 13px; padding: 3px 0;">{stream_check(correlation.get('has_tweet_signal', False))} Executive Tweet Signals</td>
                <td width="50%" style="color: #d1d5db; font-size: 13px; padding: 3px 0;">{stream_check(correlation.get('has_strc_signal', False))} STRC Volume Spike</td>
            </tr>
            <tr>
                <td style="color: #d1d5db; font-size: 13px; padding: 3px 0;">{stream_check(correlation.get('has_edgar_signal', False))} SEC EDGAR Filing</td>
                <td style="color: #d1d5db; font-size: 13px; padding: 3px 0;">{stream_check(correlation.get('has_timing_signal', False))} Timing Pattern</td>
            </tr>
        </table>
    </td></tr>
    <tr><td style="padding: 10px 18px;">
        <span style="color: #6b7280; font-size: 12px; font-style: italic;">{cor_narrative}</span>
    </td></tr>"""

    # Market dominance
    strategy_btc = 0
    other_btc = 0
    for c in leaderboard:
        if "strategy" in c.get("company", "").lower() or c.get("ticker", "") == "MSTR":
            strategy_btc = c.get("btc_holdings", 0)
        else:
            other_btc += c.get("btc_holdings", 0)
    total_lb_btc = strategy_btc + other_btc
    strategy_pct = round((strategy_btc / total_lb_btc) * 100, 1) if total_lb_btc > 0 else 0
    other_pct = round(100 - strategy_pct, 1)

    # Leaderboard table (Top 10)
    leaderboard_html = ""
    medals = ["🥇", "🥈", "🥉"]
    for c in leaderboard[:10]:
        if c["btc_holdings"] > 0:
            rank = c["rank"]
            medal = medals[rank - 1] if rank <= 3 else f"<span style='color: #4b5563; font-weight: 600;'>#{rank}</span>"
            name = c["company"].replace(" (MicroStrategy)", "").replace(" Digital (MARA)", "")
            pnl_cell = ""
            if c.get("unrealized_pnl_pct") and c["unrealized_pnl_pct"] != 0:
                pnl_color = "#10B981" if c["unrealized_pnl_pct"] > 0 else "#EF4444"
                pnl_arrow = "▲" if c["unrealized_pnl_pct"] > 0 else "▼"
                pnl_cell = f'<span style="color: {pnl_color}; font-size: 11px; font-family: Courier New, monospace;"> {pnl_arrow}{abs(c["unrealized_pnl_pct"]):.1f}%</span>'
            leaderboard_html += f"""
            <tr>
                <td style="padding: 10px 18px; border-bottom: 1px solid #1e2a3a; color: #e0e0e0; font-size: 13px;">{medal} <strong>{name}</strong> <span style="color: #4b5563;">({c['ticker']})</span></td>
                <td style="padding: 10px 14px; border-bottom: 1px solid #1e2a3a; color: #E67E22; font-size: 13px; text-align: right; font-weight: 700; font-family: 'Courier New', monospace;">{c['btc_holdings']:,}</td>
                <td style="padding: 10px 18px; border-bottom: 1px solid #1e2a3a; color: #9ca3af; font-size: 13px; text-align: right; font-family: 'Courier New', monospace;">${c['btc_value_b']:.2f}B{pnl_cell}</td>
            </tr>"""

    # Recent Purchases
    purchases_html = ""
    for p in purchases[:5]:
        usd_m = p["usd_amount"] / 1_000_000
        if usd_m >= 1000:
            size_color = "#EF4444"
            size_label = "MEGA"
        elif usd_m >= 500:
            size_color = "#F59E0B"
            size_label = "LARGE"
        elif usd_m >= 100:
            size_color = "#FBBF24"
            size_label = "MED"
        else:
            size_color = "#3B82F6"
            size_label = "SMALL"
        company_short = p["company"].replace(" (MicroStrategy)", "")
        purchases_html += f"""
        <tr><td style="padding: 10px 18px; border-bottom: 1px solid #1e2a3a;">
            <span style="background: {size_color}; color: white; padding: 1px 6px; border-radius: 4px; font-size: 9px; font-weight: 700; letter-spacing: 0.05em;">{size_label}</span>
            <strong style="color: #e0e0e0; font-size: 13px; margin-left: 6px;">{company_short}</strong>
            <span style="color: #4b5563; font-size: 12px;">({p['ticker']})</span>
            <span style="color: #6b7280; font-size: 11px; float: right;">{p['filing_date']}</span>
            <br><span style="color: #E67E22; font-size: 13px; font-weight: 700; font-family: 'Courier New', monospace;">₿ {p['btc_amount']:,}</span>
            <span style="color: #9ca3af; font-size: 12px;"> — ${usd_m:,.0f}M at ${p['price_per_btc']:,.0f}/BTC</span>
        </td></tr>"""

    # Regulatory
    active_regs = [r for r in reg_items if r.get("status_color") == "green"][:3]
    pending_regs = [r for r in reg_items if r.get("status_color") == "yellow"][:3]
    reg_html = ""
    for r in active_regs + pending_regs:
        status_color = "#10B981" if r["status_color"] == "green" else "#FBBF24"
        status_bg = "rgba(16,185,129,0.1)" if r["status_color"] == "green" else "rgba(251,191,36,0.1)"
        impact_color = "#EF4444" if "EXTREMELY" in r.get("btc_impact", "") or "VERY" in r.get("btc_impact", "") else "#F59E0B"
        reg_html += f"""
        <tr><td style="padding: 10px 18px; border-bottom: 1px solid #1e2a3a;">
            <span style="color: {status_color}; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; background: {status_bg}; padding: 2px 8px; border-radius: 4px;">{r['status']}</span>
            <span style="color: #4b5563; font-size: 10px; margin-left: 6px;">{r['category']}</span>
            <span style="color: {impact_color}; font-size: 10px; font-weight: 700; float: right;">{r['btc_impact']}</span>
            <br><span style="color: #e0e0e0; font-size: 13px; font-weight: 600;">{r['title']}</span>
        </td></tr>"""

    # Notable Statements
    statements_html = ""
    for s in statements[:5]:
        if "EXTREMELY" in s.get("impact", ""):
            s_color = "#EF4444"
        elif "VERY" in s.get("impact", ""):
            s_color = "#F59E0B"
        elif "BULLISH" in s.get("impact", ""):
            s_color = "#10B981"
        elif "BEARISH" in s.get("impact", ""):
            s_color = "#EF4444"
        else:
            s_color = "#6b7280"
        cat_emoji = "🏛️" if s.get("category") == "Government" else "💼"
        statements_html += f"""
        <tr><td style="padding: 12px 18px; border-bottom: 1px solid #1e2a3a;">
            <span style="color: #4b5563; font-size: 10px;">{cat_emoji} {s.get('category', '')} · {s.get('date', '')}</span>
            <span style="color: {s_color}; font-size: 10px; font-weight: 700; float: right;">{s.get('impact', '')}</span>
            <br><strong style="color: #e0e0e0; font-size: 13px;">{s.get('person', '')}</strong>
            <span style="color: #6b7280; font-size: 11px;"> — {s.get('title', '')}</span>
            <br><span style="color: #9ca3af; font-size: 12px; font-style: italic;">"{s.get('statement', '')[:120]}..."</span>
        </td></tr>"""

    # Overnight changes HTML
    changes_html = ""
    for c in (changes or [{"icon": "✅", "text": "No significant changes overnight"}]):
        changes_html += f"""<tr><td style="padding: 10px 18px; border-bottom: 1px solid #1e2a3a;">
            <span style="font-size: 14px; margin-right: 8px;">{c.get('icon', '📊')}</span>
            <span style="color: #d1d5db; font-size: 13px;">{c.get('text', '')}</span>
        </td></tr>"""

    # Peer activity HTML
    peers_html = ""
    for p in (peers or [{"icon": "✅", "company": "All Companies", "text": "No significant changes detected"}]):
        peers_html += f"""<tr><td style="padding: 10px 18px; border-bottom: 1px solid #1e2a3a;">
            <span style="font-size: 14px; margin-right: 8px;">{p.get('icon', '📊')}</span>
            <strong style="color: #e0e0e0; font-size: 13px;">{p.get('company', '')}</strong>
            <span style="color: #9ca3af; font-size: 12px;"> {p.get('text', '')}</span>
        </td></tr>"""

    # Week ahead HTML
    week_html = ""
    for e in (week_ahead or []):
        impact_color = "#EF4444" if e.get("impact") == "VERY HIGH" else "#F59E0B" if e.get("impact") == "HIGH" else "#3B82F6"
        week_html += f"""<tr><td style="padding: 12px 18px; border-bottom: 1px solid #1e2a3a;">
            <span style="background: {impact_color}; color: white; padding: 2px 8px; border-radius: 4px; font-size: 9px; font-weight: 700;">{e.get('timing', '')}</span>
            <span style="color: #4b5563; font-size: 10px; margin-left: 4px;">{e.get('category', '')}</span>
            <br><strong style="color: #e0e0e0; font-size: 13px;">{e.get('event', '')}</strong>
            <br><span style="color: #6b7280; font-size: 11px;">{e.get('description', '')[:150]}</span>
        </td></tr>"""

    # Risk values
    action_color = action.get("action_color", "#9CA3AF") if action else "#9CA3AF"
    action_text = action.get("action", "⚪ HOLD") if action else "⚪ HOLD"
    action_score = action.get("score", 0) if action else 0
    action_summary = action.get("summary", "No strong signals.") if action else "No strong signals."

    # Build confidence breakdown HTML for email
    _breakdown = action.get("confidence_breakdown", []) if action else []
    _breakdown_html = ""
    if _breakdown:
        _bd_rows = ""
        for stream in _breakdown:
            pct = (stream["contribution"] / stream["max"] * 100) if stream["max"] > 0 else 0
            bar_color = "#10B981" if pct >= 60 else "#F59E0B" if pct >= 30 else "#374151"
            bar_width = max(2, min(int(pct), 100))
            _bd_rows += f"""<tr>
                <td style="padding: 2px 0; color: #6b7280; font-size: 10px; width: 120px;">{stream['icon']} {stream['stream']}</td>
                <td style="padding: 2px 8px;"><div style="background: #1e2a3a; border-radius: 3px; height: 5px; width: 100%;"><div style="background: {bar_color}; border-radius: 3px; height: 5px; width: {bar_width}%;"></div></div></td>
                <td style="padding: 2px 0; color: #9ca3af; font-size: 10px; font-family: 'Courier New', monospace; text-align: right; width: 40px;">{stream['contribution']}/{stream['max']}</td>
            </tr>"""
        _breakdown_html = f'<table width="100%" cellpadding="0" cellspacing="0" style="margin-top: 12px; border-top: 1px solid #1e2a3a; padding-top: 8px;"><tr><td colspan="3" style="color: #4b5563; font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; padding-bottom: 4px;">Confidence Breakdown</td></tr>{_bd_rows}</table>'
    fg_value = risk.get("fear_greed_value", 50) if risk else 50
    fg_label = risk.get("fear_greed_label", "Neutral") if risk else "Neutral"
    vol_30d = risk.get("volatility_30d", 0) if risk else 0
    dd_ath = risk.get("drawdown_from_ath", 0) if risk else 0
    risk_level = risk.get("risk_level", "MODERATE") if risk else "MODERATE"
    risk_color = risk.get("risk_color", "#F59E0B") if risk else "#F59E0B"
    fg_color = "#EF4444" if fg_value <= 25 else "#F59E0B" if fg_value <= 40 else "#10B981" if fg_value <= 60 else "#F59E0B"
    vol_color = "#EF4444" if vol_30d >= 60 else "#F59E0B" if vol_30d >= 40 else "#10B981"

    total_signals = len(all_signals)
    high_signals = len([s for s in all_signals if s.get("confidence_score", 0) >= 60])

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="margin: 0; padding: 0; background-color: #060910; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif;">

        <div style="display:none;font-size:1px;color:#060910;line-height:1px;max-height:0px;max-width:0px;opacity:0;overflow:hidden;">
            BTC ${btc_price:,.0f} {btc_arrow}{abs(btc_change):.1f}% | {action_text} | {lb_summary['total_btc']:,} BTC held | Fear &amp; Greed: {fg_value}
        </div>

        <table width="100%" cellpadding="0" cellspacing="0" style="max-width: 680px; margin: 0 auto; background-color: #0a0e17;">

            <tr><td style="height: 4px; background: linear-gradient(90deg, #E67E22 0%, #F59E0B 50%, #E67E22 100%);"></td></tr>

            <!-- Header -->
            <tr><td style="padding: 28px 36px 20px 36px;">
                <table width="100%" cellpadding="0" cellspacing="0"><tr>
                    <td>
                        <span style="color: #E67E22; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.15em;">Treasury Signal Intelligence</span>
                        <br>{greeting_html}
                        <br><span style="color: #4b5563; font-size: 12px;">{today} · {time_now}</span>
                    </td>
                    <td style="text-align: right; vertical-align: top;">
                        <span style="color: #E67E22; font-size: 32px;">🔶</span>
                    </td>
                </tr></table>
            </td></tr>

            <tr><td style="padding: 0 36px;"><div style="border-top: 1px solid #1e2a3a;"></div></td></tr>

            {holdings_change_html}

            {your_position_html}

            {competitor_spotlight_html}

            {sector_peers_html}

            {watchlist_html}

            <!-- ⓪ ACTION SIGNAL -->
            <tr><td style="padding: 24px 36px 16px 36px;">
                <table width="100%" cellpadding="0" cellspacing="0" style="background: #111827; border-radius: 12px; border: 2px solid {action_color}; overflow: hidden;">
                    <tr><td style="padding: 20px 24px;">
                        <table width="100%" cellpadding="0" cellspacing="0"><tr>
                            <td>
                                <span style="color: #6b7280; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.12em;">Today's Action Signal</span>
                                <br><span style="color: {action_color}; font-size: 26px; font-weight: 800; letter-spacing: -0.02em;">{action_text}</span>
                            </td>
                            <td style="text-align: right; vertical-align: top;">
                                <span style="color: {action_color}; font-size: 34px; font-weight: 800; font-family: 'Courier New', monospace;">{action_score}</span>
                                <br><span style="color: #4b5563; font-size: 10px;">/100</span>
                            </td>
                        </tr></table>
                        <p style="color: #d1d5db; font-size: 13px; line-height: 1.6; margin: 12px 0 0 0;">{action_summary[:300]}</p>
                        {_breakdown_html}
                    </td></tr>
                </table>
            </td></tr>

            {personalized_context_html}

            {pattern_html}

            <!-- RISK DASHBOARD -->
            <tr><td style="padding: 0 36px 16px 36px;">
                <span style="color: #6b7280; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.12em;">Risk Dashboard</span>
                <table width="100%" cellpadding="0" cellspacing="0" style="margin-top: 10px;">
                    <tr>
                        <td width="24%" style="padding: 14px 8px; text-align: center; background: #111827; border-radius: 10px; cursor: help;" title="The Fear &amp; Greed Index measures market sentiment on a scale of 0-100. Extreme Fear (0-25) historically signals buying opportunities. Extreme Greed (75-100) signals caution. Data from alternative.me.">
                            <span style="color: {fg_color}; font-size: 24px; font-weight: 800; font-family: 'Courier New', monospace;">{fg_value}</span>
                            <br><span style="color: #4b5563; font-size: 9px; font-weight: 600; text-transform: uppercase;">Fear & Greed</span>
                            <span style="color: #E67E22; font-size: 9px;"> ℹ</span>
                            <br><span style="color: #6b7280; font-size: 9px;">{fg_label}</span>
                        </td>
                        <td width="2%"></td>
                        <td width="24%" style="padding: 14px 8px; text-align: center; background: #111827; border-radius: 10px; cursor: help;" title="30-Day Annualized Volatility measures price fluctuation. Below 40% is stable. 40-60% is moderate. Above 60% means rapid price swings and elevated risk.">
                            <span style="color: {vol_color}; font-size: 24px; font-weight: 800; font-family: 'Courier New', monospace;">{vol_30d}%</span>
                            <br><span style="color: #4b5563; font-size: 9px; font-weight: 600; text-transform: uppercase;">30D Volatility</span>
                            <span style="color: #E67E22; font-size: 9px;"> ℹ</span>
                        </td>
                        <td width="2%"></td>
                        <td width="24%" style="padding: 14px 8px; text-align: center; background: #111827; border-radius: 10px; cursor: help;" title="Drawdown from All-Time High shows how far Bitcoin has fallen from its peak. Larger drawdowns (30%+) can signal buying opportunities for long-term holders.">
                            <span style="color: #EF4444; font-size: 24px; font-weight: 800; font-family: 'Courier New', monospace;">{dd_ath}%</span>
                            <br><span style="color: #4b5563; font-size: 9px; font-weight: 600; text-transform: uppercase;">From ATH</span>
                            <span style="color: #E67E22; font-size: 9px;"> ℹ</span>
                        </td>
                        <td width="2%"></td>
                        <td width="24%" style="padding: 14px 8px; text-align: center; background: #111827; border-radius: 10px; border: 1px solid {risk_color}; cursor: help;" title="Overall Risk Level combines Fear &amp; Greed, Volatility, and Drawdown. MODERATE = favorable. ELEVATED = caution. HIGH = consider pausing new purchases.">
                            <span style="color: {risk_color}; font-size: 14px; font-weight: 800;">{risk_level}</span>
                            <br><span style="color: #4b5563; font-size: 9px; font-weight: 600; text-transform: uppercase;">Risk Level</span>
                            <span style="color: #E67E22; font-size: 9px;"> ℹ</span>
                        </td>
                    </tr>
                </table>
            </td></tr>

            <!-- WHAT CHANGED OVERNIGHT -->
            <tr><td style="padding: 0 36px 16px 36px;">
                <span style="color: #6b7280; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.12em;">What Changed Overnight</span>
                <table width="100%" cellpadding="0" cellspacing="0" style="background: #111827; border-radius: 12px; margin-top: 10px; overflow: hidden;">
                    {changes_html}
                </table>
            </td></tr>

            <!-- PEER ACTIVITY -->
            <tr><td style="padding: 0 36px 16px 36px;">
                <span style="color: #6b7280; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.12em;">Peer Activity (Since Yesterday)</span>
                <table width="100%" cellpadding="0" cellspacing="0" style="background: #111827; border-radius: 12px; margin-top: 10px; overflow: hidden;">
                    {peers_html}
                </table>
            </td></tr>

            <!-- WEEK AHEAD -->
            <tr><td style="padding: 0 36px 16px 36px;">
                <span style="color: #6b7280; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.12em;">Week Ahead</span>
                <table width="100%" cellpadding="0" cellspacing="0" style="background: #111827; border-radius: 12px; margin-top: 10px; overflow: hidden;">
                    {week_html}
                </table>
            </td></tr>

            <!-- ① EXECUTIVE SUMMARY -->
            <tr><td style="padding: 24px 36px 16px 36px;">
                <span style="color: #E67E22; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.12em;">① Executive Summary</span>
                <table width="100%" cellpadding="0" cellspacing="0" style="margin-top: 10px; background: #111827; border-radius: 12px; border-left: 4px solid #E67E22;">
                    {exec_summary_html}
                </table>
            </td></tr>

            <!-- ② MARKET SNAPSHOT -->
            <tr><td style="padding: 8px 36px 16px 36px;">
                <span style="color: #6b7280; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.12em;">② Market Snapshot</span>
                {freshness.format_provenance_html("btc_price")}
                <table width="100%" cellpadding="0" cellspacing="0" style="margin-top: 10px;">
                    <tr>
                        <td width="32%" style="padding: 16px; text-align: center; background: #111827; border-radius: 12px;">
                            <span style="color: #6b7280; font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.1em;">Bitcoin</span>
                            <br><span style="color: #f0f0f0; font-size: 24px; font-weight: 800; font-family: 'Courier New', monospace;">${btc_price:,.0f}</span>
                            <br><span style="color: {btc_color}; font-size: 13px; font-weight: 600;">{btc_arrow} {btc_change:+.2f}%</span>
                        </td>
                        <td width="2%"></td>
                        <td width="32%" style="padding: 16px; text-align: center; background: #111827; border-radius: 12px;">
                            <span style="color: #6b7280; font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.1em;">MSTR</span>
                            <br><span style="color: #f0f0f0; font-size: 24px; font-weight: 800; font-family: 'Courier New', monospace;">${market.get('mstr_price', 0):,.2f}</span>
                            <br><span style="color: {mstr_color}; font-size: 13px; font-weight: 600;">{mstr_arrow} {market.get('mstr_change', 0):+.2f}%</span>
                        </td>
                        <td width="2%"></td>
                        <td width="32%" style="padding: 16px; text-align: center; background: #111827; border-radius: 12px;">
                            <span style="color: #6b7280; font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.1em;">STRC</span>
                            <br><span style="color: #f0f0f0; font-size: 24px; font-weight: 800; font-family: 'Courier New', monospace;">${market.get('strc_price', 0):.2f}</span>
                            <br><span style="color: #6b7280; font-size: 13px;">Vol: ${market.get('strc_volume_m', 0)}M</span>
                        </td>
                    </tr>
                </table>
            </td></tr>

            <!-- STRC Alert -->
            <tr><td style="padding: 0 36px 16px 36px;">
                <div style="background: #111827; border-left: 4px solid {strc_color}; padding: 12px 18px; border-radius: 0 10px 10px 0;">
                    <span style="color: #e0e0e0; font-size: 13px; font-weight: 600;">{strc_dot} STRC Capital Raise: {strc_status}</span>
                    <br><span style="color: #4b5563; font-size: 11px;">Volume ratio: {strc_ratio}x · Dollar volume: ${market.get('strc_volume_m', 0)}M</span>
                </div>
            </td></tr>

            <!-- ③ CORRELATION ENGINE -->
            <tr><td style="padding: 0 36px 16px 36px;">
                <table width="100%" cellpadding="0" cellspacing="0">
                    <tr>
                        <td><span style="color: #6b7280; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.12em;">③ Multi-Signal Correlation Engine™</span></td>
                        <td style="text-align: right;"><span style="color: {cor_color}; font-size: 13px; font-weight: 700; font-family: 'Courier New', monospace;">{cor_score}/100 · {cor_active}/4 streams</span></td>
                    </tr>
                </table>
                <table width="100%" cellpadding="0" cellspacing="0" style="background: #111827; border-radius: 12px; margin-top: 10px; border-left: 4px solid {cor_color}; overflow: hidden;">
                    {cor_streams_html}
                </table>
            </td></tr>

            <!-- ④ PURCHASE SIGNALS -->
            <tr><td style="padding: 0 36px 16px 36px;">
                <table width="100%" cellpadding="0" cellspacing="0">
                    <tr>
                        <td><span style="color: #6b7280; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.12em;">④ Purchase Signals (24h)</span></td>
                        <td style="text-align: right;"><span style="color: #6b7280; font-size: 11px;">{signal_summary}</span></td>
                    </tr>
                </table>
                <table width="100%" cellpadding="0" cellspacing="0" style="background: #111827; border-radius: 12px; margin-top: 10px; overflow: hidden;">
                    {signals_html}
                </table>
            </td></tr>

            <!-- ⑤ RECENT CONFIRMED PURCHASES -->
            <tr><td style="padding: 0 36px 16px 36px;">
                <table width="100%" cellpadding="0" cellspacing="0">
                    <tr>
                        <td><span style="color: #6b7280; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.12em;">⑤ Recent BTC Purchases</span></td>
                        <td style="text-align: right;">
                            <a href="https://treasury-signals-jqyywcwr8l8pbtv66rvbbg.streamlit.app/" style="color: #E67E22; font-size: 10px; font-weight: 600; text-decoration: none;">History →</a>
                            <span style="color: #4b5563;"> · </span>
                            <a href="https://saylortracker.com" style="color: #E67E22; font-size: 10px; font-weight: 600; text-decoration: none;">Saylor Tracker →</a>
                            <span style="color: #4b5563;"> · </span>
                            <a href="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&type=8-K&dateb=&owner=include&count=40" style="color: #E67E22; font-size: 10px; font-weight: 600; text-decoration: none;">SEC EDGAR →</a>
                        </td>
                    </tr>
                </table>
                <table width="100%" cellpadding="0" cellspacing="0" style="background: #111827; border-radius: 12px; margin-top: 10px; overflow: hidden;">
                    {purchases_html}
                </table>
            </td></tr>

            <!-- ⑥ BTC TREASURY LEADERBOARD -->
            <tr><td style="padding: 0 36px 16px 36px;">
                <table width="100%" cellpadding="0" cellspacing="0">
                    <tr>
                        <td><span style="color: #6b7280; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.12em;">⑥ BTC Treasury Leaderboard</span>
                        {freshness.format_provenance_html("leaderboard_corporate")}
                        </td>
                        <td style="text-align: right;">
                            <a href="https://bitcointreasuries.net" style="color: #E67E22; font-size: 11px; font-weight: 600; text-decoration: none;">View all {lb_summary['total_companies']} companies →</a>
                        </td>
                    </tr>
                </table>
                <p style="color: #6b7280; font-size: 11px; margin: 4px 0 10px 0;">{lb_summary.get('corporate_count', 0)} companies + {lb_summary.get('sovereign_count', 0)} governments · {lb_summary['total_btc']:,} BTC · ${lb_summary['total_value_b']:.1f}B · Strategy dominance: {strategy_pct}%</p>

                <table width="100%" cellpadding="0" cellspacing="0" style="background: #111827; border-radius: 12px; overflow: hidden;">
                    <tr>
                        <td style="padding: 8px 18px; border-bottom: 1px solid #1e2a3a; color: #4b5563; font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em;">Company</td>
                        <td style="padding: 8px 14px; border-bottom: 1px solid #1e2a3a; color: #4b5563; font-size: 10px; font-weight: 600; text-align: right; text-transform: uppercase; letter-spacing: 0.08em;">BTC</td>
                        <td style="padding: 8px 18px; border-bottom: 1px solid #1e2a3a; color: #4b5563; font-size: 10px; font-weight: 600; text-align: right; text-transform: uppercase; letter-spacing: 0.08em;">Value</td>
                    </tr>
                    {leaderboard_html}
                    <tr style="background: rgba(230,126,34,0.05);">
                        <td style="padding: 12px 18px; color: #E67E22; font-weight: 700; font-size: 13px;">TOTAL</td>
                        <td style="padding: 12px 14px; color: #E67E22; font-weight: 700; font-size: 13px; text-align: right; font-family: 'Courier New', monospace;">{lb_summary['total_btc']:,}</td>
                        <td style="padding: 12px 18px; color: #E67E22; font-weight: 700; font-size: 13px; text-align: right; font-family: 'Courier New', monospace;">${lb_summary['total_value_b']:.1f}B</td>
                    </tr>
                    <tr>
                        <td colspan="3" style="padding: 10px 18px; text-align: center;">
                            <a href="https://bitcointreasuries.net" style="color: #E67E22; font-size: 12px; font-weight: 600; text-decoration: none;">View full leaderboard with all {lb_summary['total_companies']} companies on bitcointreasuries.net →</a>
                        </td>
                    </tr>
                </table>
            </td></tr>

            <!-- ⑦ REGULATORY -->
            <tr><td style="padding: 0 36px 16px 36px;">
                <table width="100%" cellpadding="0" cellspacing="0">
                    <tr>
                        <td><span style="color: #6b7280; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.12em;">⑦ Global Regulatory Landscape</span>
                        {freshness.format_provenance_html("regulatory")}
                        </td>
                        <td style="text-align: right;">
                            <a href="https://www.congress.gov/search?q=bitcoin+crypto&s=1" style="color: #E67E22; font-size: 11px; font-weight: 600; text-decoration: none;">Congress.gov →</a>
                            <span style="color: #4b5563; font-size: 11px;"> · </span>
                            <a href="https://www.coindesk.com/policy/" style="color: #E67E22; font-size: 11px; font-weight: 600; text-decoration: none;">CoinDesk Policy →</a>
                        </td>
                    </tr>
                </table>
                <table width="100%" cellpadding="0" cellspacing="0" style="background: #111827; border-radius: 12px; margin-top: 10px; overflow: hidden;">
                    {reg_html}
                </table>
            </td></tr>

            <!-- ⑧ NOTABLE STATEMENTS -->
            <tr><td style="padding: 0 36px 16px 36px;">
                <table width="100%" cellpadding="0" cellspacing="0">
                    <tr>
                        <td><span style="color: #6b7280; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.12em;">⑧ Notable Statements — Leaders & CEOs</span></td>
                        <td style="text-align: right;">
                            <a href="https://treasury-signals-jqyywcwr8l8pbtv66rvbbg.streamlit.app/" style="color: #E67E22; font-size: 10px; font-weight: 600; text-decoration: none;">History →</a>
                            <span style="color: #4b5563;"> · </span>
                            <a href="https://www.theblock.co/" style="color: #E67E22; font-size: 10px; font-weight: 600; text-decoration: none;">The Block →</a>
                            <span style="color: #4b5563;"> · </span>
                            <a href="https://www.bloomberg.com/crypto" style="color: #E67E22; font-size: 10px; font-weight: 600; text-decoration: none;">Bloomberg →</a>
                        </td>
                    </tr>
                </table>
                <table width="100%" cellpadding="0" cellspacing="0" style="background: #111827; border-radius: 12px; margin-top: 10px; overflow: hidden;">
                    {statements_html}
                </table>
            </td></tr>

            <!-- ⑨ INTELLIGENCE PERFORMANCE -->
            <tr><td style="padding: 0 36px 24px 36px;">
                <span style="color: #6b7280; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.12em;">⑨ Intelligence Performance</span>
                <table width="100%" cellpadding="0" cellspacing="0" style="margin-top: 10px;">
                    <tr>
                        <td width="19%" style="padding: 14px 6px; text-align: center; background: #111827; border-radius: 10px; cursor: help;" title="Total Signals: The total number of purchase signals detected since launch. A signal is any tweet scoring 40/100 or above on our classification engine.">
                            <span style="color: #E67E22; font-size: 22px; font-weight: 800; font-family: 'Courier New', monospace;">{total_signals}</span>
                            <br><span style="color: #4b5563; font-size: 9px; font-weight: 600; text-transform: uppercase;">Signals</span>
                            <span style="color: #E67E22; font-size: 9px;"> ℹ</span>
                        </td>
                        <td width="2%"></td>
                        <td width="19%" style="padding: 14px 6px; text-align: center; background: #111827; border-radius: 10px; cursor: help;" title="High Confidence: Signals scoring 60/100 or above. These historically precede confirmed purchases within 24-72 hours.">
                            <span style="color: #E67E22; font-size: 22px; font-weight: 800; font-family: 'Courier New', monospace;">{high_signals}</span>
                            <br><span style="color: #4b5563; font-size: 9px; font-weight: 600; text-transform: uppercase;">High Conf</span>
                            <span style="color: #E67E22; font-size: 9px;"> ℹ</span>
                        </td>
                        <td width="2%"></td>
                        <td width="19%" style="padding: 14px 6px; text-align: center; background: #111827; border-radius: 10px; cursor: help;" title="Predictions: Auto-logged when signals score 60+, STRC spikes, or correlation hits 50+. Later matched against confirmed purchases to calculate accuracy.">
                            <span style="color: #E67E22; font-size: 22px; font-weight: 800; font-family: 'Courier New', monospace;">{accuracy['total_predictions']}</span>
                            <br><span style="color: #4b5563; font-size: 9px; font-weight: 600; text-transform: uppercase;">Predictions</span>
                            <span style="color: #E67E22; font-size: 9px;"> ℹ</span>
                        </td>
                        <td width="2%"></td>
                        <td width="19%" style="padding: 14px 6px; text-align: center; background: #111827; border-radius: 10px; cursor: help;" title="Hit Rate: Percentage of confirmed purchases our system predicted in advance (within 72 hours before the 8-K filing).">
                            <span style="color: #E67E22; font-size: 22px; font-weight: 800; font-family: 'Courier New', monospace;">{accuracy['hit_rate']}%</span>
                            <br><span style="color: #4b5563; font-size: 9px; font-weight: 600; text-transform: uppercase;">Hit Rate</span>
                            <span style="color: #E67E22; font-size: 9px;"> ℹ</span>
                        </td>
                        <td width="2%"></td>
                        <td width="19%" style="padding: 14px 6px; text-align: center; background: #111827; border-radius: 10px; cursor: help;" title="Confirmed Purchases: Verified BTC purchases from SEC 8-K filings, press releases, and auto-detected via leaderboard snapshot comparison.">
                            <span style="color: #E67E22; font-size: 22px; font-weight: 800; font-family: 'Courier New', monospace;">{accuracy['total_purchases']}</span>
                            <br><span style="color: #4b5563; font-size: 9px; font-weight: 600; text-transform: uppercase;">Confirmed</span>
                            <span style="color: #E67E22; font-size: 9px;"> ℹ</span>
                        </td>
                    </tr>
                </table>
            </td></tr>

            <!-- CTA -->
            <tr><td style="padding: 28px 36px; text-align: center; background: #111827; border-top: 1px solid #1e2a3a;">
                <span style="color: #e0e0e0; font-size: 14px; font-weight: 600;">Explore the Full Intelligence Platform</span>
                <br><span style="color: #6b7280; font-size: 12px; margin-top: 4px; display: inline-block;">Interactive charts, live data, and deep-dive analysis across all 6 sections:</span>
                <br><br>
                <a href="https://treasury-signals-jqyywcwr8l8pbtv66rvbbg.streamlit.app/" style="background: linear-gradient(135deg, #E67E22, #d35400); color: white; padding: 14px 40px; border-radius: 8px; text-decoration: none; font-weight: 700; font-size: 15px; letter-spacing: 0.02em; display: inline-block;">Open Intelligence Platform →</a>
                <br><br>
                <table width="100%" cellpadding="0" cellspacing="0" style="margin-top: 8px;">
                    <tr>
                        <td width="33%" style="padding: 8px 4px; text-align: center;">
                            <span style="color: #E67E22; font-size: 16px;">📊</span>
                            <br><span style="color: #9ca3af; font-size: 10px; font-weight: 600;">Live Dashboard</span>
                            <br><span style="color: #4b5563; font-size: 9px;">Real-time signals & STRC</span>
                        </td>
                        <td width="33%" style="padding: 8px 4px; text-align: center;">
                            <span style="color: #E67E22; font-size: 16px;">🏆</span>
                            <br><span style="color: #9ca3af; font-size: 10px; font-weight: 600;">BTC Leaderboard</span>
                            <br><span style="color: #4b5563; font-size: 9px;">{lb_summary['total_companies']} companies ranked</span>
                        </td>
                        <td width="33%" style="padding: 8px 4px; text-align: center;">
                            <span style="color: #E67E22; font-size: 16px;">💰</span>
                            <br><span style="color: #9ca3af; font-size: 10px; font-weight: 600;">Recent Purchases</span>
                            <br><span style="color: #4b5563; font-size: 9px;">Auto-detected buys</span>
                        </td>
                    </tr>
                    <tr>
                        <td width="33%" style="padding: 8px 4px; text-align: center;">
                            <span style="color: #E67E22; font-size: 16px;">🏛️</span>
                            <br><span style="color: #9ca3af; font-size: 10px; font-weight: 600;">Regulatory Tracker</span>
                            <br><span style="color: #4b5563; font-size: 9px;">{reg_stats['total_items']}+ items, {reg_stats['regions_tracked']} regions</span>
                        </td>
                        <td width="33%" style="padding: 8px 4px; text-align: center;">
                            <span style="color: #E67E22; font-size: 16px;">📈</span>
                            <br><span style="color: #9ca3af; font-size: 10px; font-weight: 600;">Accuracy Tracking</span>
                            <br><span style="color: #4b5563; font-size: 9px;">Verified predictions</span>
                        </td>
                        <td width="33%" style="padding: 8px 4px; text-align: center;">
                            <span style="color: #E67E22; font-size: 16px;">🔗</span>
                            <br><span style="color: #9ca3af; font-size: 10px; font-weight: 600;">Correlation Engine</span>
                            <br><span style="color: #4b5563; font-size: 9px;">Multi-signal analysis</span>
                        </td>
                    </tr>
                </table>
            </td></tr>

            <!-- Data Freshness Status -->
            <tr><td style="padding: 0 36px;">
                {freshness.format_for_email()}
            </td></tr>

            <!-- AI Learning Insights (Phase 15) -->
            {_get_feedback_email_html()}

            <!-- Footer -->
            <tr><td style="padding: 24px 36px; border-top: 1px solid #1e2a3a;">
                <span style="color: #E67E22; font-size: 10px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase;">Treasury Signal Intelligence™</span>
                <br><span style="color: #374151; font-size: 10px;">Multi-Signal Correlation Engine™ · BTC Treasury Leaderboard™ · Global Regulatory Tracker™</span>
                <br><span style="color: #1f2937; font-size: 10px; margin-top: 8px; display: inline-block;">
                    Data: TwitterAPI.io · Yahoo Finance · SEC EDGAR · bitcointreasuries · Not financial advice.<br>
                    © {datetime.now().year} Treasury Signal Intelligence. All rights reserved.
                </span>
                <br><span style="color: #1f2937; font-size: 9px; margin-top: 12px; display: inline-block;">
                    You're receiving this because you subscribed to Treasury Signal Intelligence.
                    <br><a href="{DASHBOARD_URL}/?page=unsubscribe&email={subscriber.get('email', '') if subscriber else ''}" style="color: #4b5563; text-decoration: underline;">Unsubscribe</a>
                    · <a href="{DASHBOARD_URL}" style="color: #4b5563; text-decoration: underline;">Dashboard</a>
                    {f' · <a href="mailto:{EMAIL_REPLY_TO}" style="color: #4b5563; text-decoration: underline;">Contact Us</a>' if EMAIL_REPLY_TO else ''}
                </span>
            </td></tr>

            <tr><td style="height: 4px; background: linear-gradient(90deg, #E67E22 0%, #F59E0B 50%, #E67E22 100%);"></td></tr>
        </table>
    </body>
    </html>
    """

    return html


def send_briefing(to_email, html_content, subscriber=None):
    try:
        # Personalized subject line
        if subscriber and subscriber.get("company_name"):
            company_short = subscriber["company_name"][:30]
            subject = f"🔶 {company_short} — Daily Intelligence Briefing — {datetime.now().strftime('%b %d, %Y')}"
        else:
            subject = f"🔶 Daily Intelligence Briefing — {datetime.now().strftime('%b %d, %Y')}"

        params = {
            "from": f"{EMAIL_FROM_NAME} <{EMAIL_FROM_ADDRESS}>",
            "to": [to_email],
            "subject": subject,
            "html": html_content,
        }

        # Add reply-to if configured
        if EMAIL_REPLY_TO:
            params["reply_to"] = EMAIL_REPLY_TO

        # Add unsubscribe header for email client support
        unsubscribe_url = f"{DASHBOARD_URL}/?page=unsubscribe&email={to_email}"
        params["headers"] = {
            "List-Unsubscribe": f"<{unsubscribe_url}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        }

        email = resend.Emails.send(params)
        logger.info(f"Email sent to {to_email} from {EMAIL_FROM_ADDRESS}: {email.get('id', 'unknown')}")
        return True
    except Exception as e:
        logger.error(f"Email send failed for {to_email}: {e}", exc_info=True)
        return False


def generate_and_send_briefing(to_email, subscriber=None):
    logger.info("Generating executive briefing v5.0 (personalized CEO intelligence)...")

    market = get_market_data()
    signals = get_recent_signals(hours=24)
    all_signals = get_all_signals()
    btc_price = market.get("btc_price", 72000)
    leaderboard, lb_summary = get_leaderboard_with_live_price(btc_price)
    reg_stats = get_reg_stats()
    reg_items = get_all_regulatory_items()
    accuracy = get_accuracy_data()
    statements = get_all_statements()
    purchases = get_recent_purchases(5)
    purchase_stats = get_purchase_stats()

    engine = CorrelationEngine()
    for sig in signals:
        score = sig.get("confidence_score", 0)
        if score >= 60:
            engine.add_tweet_signal(sig.get("author_username", ""), score, sig.get("tweet_text", ""))
    correlation = engine.calculate_correlation()

    risk = get_risk_dashboard()

    # Historical pattern matching (Phase 14) — compute BEFORE action signal
    pattern_match = {"score": 0, "matched_count": 0, "total_patterns": 0, "matching_patterns": [], "narrative": ""}
    try:
        from pattern_analyzer import pattern_engine
        pattern_match = pattern_engine.match_current_conditions(
            recent_signals=signals,
            strc_ratio=market.get("strc_ratio", 0),
            fear_greed=risk.get("fear_greed_value", 50),
            btc_change_pct=market.get("btc_change", 0),
            recent_purchases=purchases,
        )
        logger.info(f"Pattern match for email: {pattern_match['score']}/100 ({pattern_match['matched_count']} patterns)")
    except Exception as e:
        logger.debug(f"Pattern analysis for email skipped: {e}")

    action = generate_action_signal(
        correlation_score=correlation["correlated_score"],
        active_streams=correlation["active_streams"],
        strc_ratio=market.get("strc_ratio", 0),
        signals_24h=signals,
        btc_change=market.get("btc_change", 0),
        fear_greed_value=risk["fear_greed_value"],
        pattern_match=pattern_match,
        subscriber=subscriber,
    )
    changes = get_overnight_changes(
        btc_price, market.get("mstr_price", 0), market.get("strc_ratio", 0),
        len(signals), lb_summary["total_btc"], reg_stats["total_items"],
    )
    peers = get_peer_activity()
    week_ahead = get_week_ahead()

    # Deep personalization (Phase 6 + Phase 8)
    personalization = {}
    if subscriber and subscriber.get("email"):
        try:
            sub_email = subscriber["email"]
            personalization["sector_peers"] = sub_mgr.get_sector_peers(sub_email, leaderboard)
            personalization["competitor_spotlight"] = sub_mgr.get_competitor_spotlight(sub_email, btc_price, leaderboard, purchases)
            personalization["context"] = sub_mgr.get_personalized_context(sub_email, btc_price, action, leaderboard)
            personalization["holdings_change"] = sub_mgr.track_holdings_change(sub_email)

            # Watchlist activity (Phase 8)
            watchlist = subscriber.get("watchlist", [])
            if isinstance(watchlist, str):
                import json as _json
                watchlist = _json.loads(watchlist) if watchlist else []
            if watchlist:
                personalization["watchlist_activity"] = get_watchlist_activity(
                    watchlist=watchlist, signals=signals,
                    purchases=purchases, leaderboard=leaderboard,
                )
                logger.info(f"Watchlist: {len(watchlist)} companies tracked, {len(personalization.get('watchlist_activity', []))} activities found")

            logger.info(f"Personalization: {len(personalization.get('sector_peers', []))} peers, {len(personalization.get('competitor_spotlight', []))} competitors")
        except Exception as e:
            logger.warning(f"Personalization data failed for {subscriber.get('email', '')}: {e}")

    html = build_briefing_html(
        market, signals, all_signals, leaderboard, lb_summary,
        reg_stats, reg_items, accuracy, statements, purchases,
        purchase_stats, correlation, action, risk, changes, peers, week_ahead,
        subscriber=subscriber, personalization=personalization,
        pattern_match=pattern_match
    )

    if subscriber:
        logger.info(f"Briefing personalized for {subscriber.get('name', '')} ({subscriber.get('company_name', '')})")
    logger.info(f"Briefing: BTC ${btc_price:,.0f} | Action: {action['action']} | Risk: {risk['risk_level']}")
    logger.info(f"Briefing: {lb_summary['total_companies']} companies | {reg_stats['total_items']} reg items | {accuracy['hit_rate']}% hit rate")

    success = send_briefing(to_email, html, subscriber=subscriber)
    return success, html


if __name__ == "__main__":
    print("Executive Email Briefing v4.0 — Full CEO Intelligence\n")
    print("=" * 60)

    market = get_market_data()
    signals = get_recent_signals(hours=24)
    all_signals = get_all_signals()
    btc_price = market.get("btc_price", 72000)
    leaderboard, lb_summary = get_leaderboard_with_live_price(btc_price)
    reg_stats = get_reg_stats()
    reg_items = get_all_regulatory_items()
    accuracy = get_accuracy_data()
    statements = get_all_statements()
    purchases = get_recent_purchases(5)
    purchase_stats = get_purchase_stats()

    engine = CorrelationEngine()
    for sig in signals:
        score = sig.get("confidence_score", 0)
        if score >= 60:
            engine.add_tweet_signal(sig.get("author_username", ""), score, sig.get("tweet_text", ""))
    correlation = engine.calculate_correlation()

    risk = get_risk_dashboard()
    action = generate_action_signal(
        correlation_score=correlation["correlated_score"],
        active_streams=correlation["active_streams"],
        strc_ratio=market.get("strc_ratio", 0),
        signals_24h=signals,
        btc_change=market.get("btc_change", 0),
        fear_greed_value=risk["fear_greed_value"],
    )
    changes = get_overnight_changes(
        btc_price, market.get("mstr_price", 0), market.get("strc_ratio", 0),
        len(signals), lb_summary["total_btc"], reg_stats["total_items"],
    )
    peers = get_peer_activity()
    week_ahead = get_week_ahead()

    html = build_briefing_html(
        market, signals, all_signals, leaderboard, lb_summary,
        reg_stats, reg_items, accuracy, statements, purchases,
        purchase_stats, correlation, action, risk, changes, peers, week_ahead
    )

    with open("briefing_preview.html", "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  Action: {action['action']} (score: {action['score']})")
    print(f"  Risk: {risk['risk_level']} | Fear & Greed: {risk['fear_greed_value']} ({risk['fear_greed_label']})")
    print(f"  Volatility: {risk['volatility_30d']}% | Drawdown: {risk['drawdown_from_ath']}%")
    print(f"  Changes: {len(changes)} | Peers: {len(peers)} | Events: {len(week_ahead)}")
    print(f"  Market: BTC ${btc_price:,.0f} | MSTR ${market.get('mstr_price', 0):,.2f}")
    print(f"  Leaderboard: {lb_summary['total_companies']} companies | {lb_summary['total_btc']:,} BTC")
    print(f"\n  Preview saved to: briefing_preview.html")
    print(f"  Open this file in your browser!\n")
    print("Briefing v4.0 is ready!")
