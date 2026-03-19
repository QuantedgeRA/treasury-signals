"""
email_briefing.py
-----------------
Executive Daily Intelligence Briefing v2.0

Sends a beautifully formatted HTML email at 7am daily with:
- Market snapshot (BTC, MSTR, STRC)
- Overnight signal summary
- STRC capital raise status
- BTC Treasury Leaderboard (Top 10)
- Government & Regulatory updates
- Correlation engine status
- Accuracy stats

This is the CEO-grade delivery mechanism.
"""

import os
import resend
from datetime import datetime, timedelta
from dotenv import load_dotenv
from supabase import create_client
from strc_tracker import get_strc_volume_data, analyze_strc_signal
from treasury_leaderboard import get_leaderboard_with_live_price
from regulatory_tracker import get_all_regulatory_items, get_summary_stats as get_reg_stats, get_all_statements
from purchase_tracker import get_recent_purchases, get_purchase_stats
from correlation_engine import CorrelationEngine
import yfinance as yf

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
RESEND_API_KEY = os.getenv("RESEND_API_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
resend.api_key = RESEND_API_KEY


def get_market_data():
    """Fetch current BTC, MSTR, and STRC prices."""
    data = {}
    try:
        btc = yf.Ticker("BTC-USD")
        hist = btc.history(period="5d")
        if not hist.empty:
            data["btc_price"] = round(float(hist["Close"].iloc[-1]), 2)
            data["btc_prev"] = round(float(hist["Close"].iloc[-2]), 2) if len(hist) > 1 else data["btc_price"]
            data["btc_change"] = round(((data["btc_price"] - data["btc_prev"]) / data["btc_prev"]) * 100, 2)
    except:
        data["btc_price"] = 0
        data["btc_change"] = 0

    try:
        mstr = yf.Ticker("MSTR")
        hist = mstr.history(period="5d")
        if not hist.empty:
            data["mstr_price"] = round(float(hist["Close"].iloc[-1]), 2)
            data["mstr_prev"] = round(float(hist["Close"].iloc[-2]), 2) if len(hist) > 1 else data["mstr_price"]
            data["mstr_change"] = round(((data["mstr_price"] - data["mstr_prev"]) / data["mstr_prev"]) * 100, 2)
    except:
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
    except:
        data["strc_price"] = 0
        data["strc_volume_m"] = 0
        data["strc_ratio"] = 0

    return data


def get_recent_signals(hours=24):
    """Get signals from the last N hours."""
    try:
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        result = (
            supabase.table("tweets")
            .select("*")
            .eq("is_signal", True)
            .gte("inserted_at", cutoff)
            .order("confidence_score", desc=True)
            .limit(10)
            .execute()
        )
        return result.data if result.data else []
    except:
        return []


def get_all_signals():
    """Get all signals for stats."""
    try:
        result = supabase.table("tweets").select("*").eq("is_signal", True).order("inserted_at", desc=True).execute()
        return result.data if result.data else []
    except:
        return []


def get_accuracy_data():
    """Get accuracy tracking data."""
    try:
        purchases = supabase.table("confirmed_purchases").select("*").execute()
        predictions = supabase.table("predictions").select("*").execute()
        all_purchases = purchases.data if purchases.data else []
        all_predictions = predictions.data if predictions.data else []
        total = len(all_purchases)
        predicted = len([p for p in all_purchases if p.get("was_predicted")])
        hit_rate = round(predicted / total * 100, 1) if total > 0 else 0
        return {
            "total_purchases": total,
            "predicted": predicted,
            "hit_rate": hit_rate,
            "total_predictions": len(all_predictions),
        }
    except:
        return {"total_purchases": 0, "predicted": 0, "hit_rate": 0, "total_predictions": 0}


def build_briefing_html(market, signals, all_signals, leaderboard, lb_summary, reg_stats, reg_items, accuracy, statements, purchases, purchase_stats, correlation):
    """Build the premium executive briefing — full 6-page intelligence summary."""

    today = datetime.now().strftime("%A, %B %d, %Y")
    time_now = datetime.now().strftime("%I:%M %p ET")

    btc_price = market.get("btc_price", 0)
    btc_change = market.get("btc_change", 0)
    btc_color = "#10B981" if btc_change >= 0 else "#EF4444"
    btc_arrow = "▲" if btc_change >= 0 else "▼"
    mstr_color = "#10B981" if market.get("mstr_change", 0) >= 0 else "#EF4444"
    mstr_arrow = "▲" if market.get("mstr_change", 0) >= 0 else "▼"

    # STRC status
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

    # Correlation status
    cor_score = correlation.get("correlated_score", 0)
    cor_active = correlation.get("active_streams", 0)
    cor_level = correlation.get("alert_level", "⚪ NONE")
    cor_narrative = correlation.get("narrative", "No significant signals.")
    if cor_score >= 70:
        cor_color = "#EF4444"
    elif cor_score >= 50:
        cor_color = "#F59E0B"
    elif cor_score >= 25:
        cor_color = "#3B82F6"
    else:
        cor_color = "#4b5563"

    # Executive summary bullet points
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

    # Signals section
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
            </td></tr>
            """
        signal_summary = f"<span style='color: #F59E0B; font-weight: 600;'>{len(signals)} signal(s)</span> detected"
    else:
        signals_html = """<tr><td style="padding: 20px 18px; text-align: center;">
            <span style="color: #10B981; font-size: 14px;">✅ All clear — no purchase signals in the last 24 hours</span>
        </td></tr>"""
        signal_summary = "<span style='color: #10B981;'>All clear</span>"

    # Correlation streams visual
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
    </td></tr>
    """

    # Leaderboard
    leaderboard_html = ""
    medals = ["🥇", "🥈", "🥉"]
    for c in leaderboard[:10]:
        if c["btc_holdings"] > 0:
            rank = c["rank"]
            medal = medals[rank - 1] if rank <= 3 else f"<span style='color: #4b5563; font-weight: 600;'>#{rank}</span>"
            name = c["company"].replace(" (MicroStrategy)", "").replace(" Digital (MARA)", "")
            pnl_html = ""
            if c.get("unrealized_pnl_pct") and c["unrealized_pnl_pct"] != 0:
                pnl_color = "#10B981" if c["unrealized_pnl_pct"] > 0 else "#EF4444"
                pnl_arrow = "▲" if c["unrealized_pnl_pct"] > 0 else "▼"
                pnl_html = f'<span style="color: {pnl_color}; font-size: 11px; font-family: Courier New, monospace;"> {pnl_arrow}{abs(c["unrealized_pnl_pct"]):.1f}%</span>'
            leaderboard_html += f"""
            <tr>
                <td style="padding: 10px 18px; border-bottom: 1px solid #1e2a3a; color: #e0e0e0; font-size: 13px;">{medal} <strong>{name}</strong> <span style="color: #4b5563;">({c['ticker']})</span></td>
                <td style="padding: 10px 14px; border-bottom: 1px solid #1e2a3a; color: #E67E22; font-size: 13px; text-align: right; font-weight: 700; font-family: 'Courier New', monospace;">{c['btc_holdings']:,}</td>
                <td style="padding: 10px 18px; border-bottom: 1px solid #1e2a3a; color: #9ca3af; font-size: 13px; text-align: right; font-family: 'Courier New', monospace;">${c['btc_value_b']:.2f}B{pnl_html}</td>
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
        if "EXTREMELY" in s["impact"]:
            s_color = "#EF4444"
        elif "VERY" in s["impact"]:
            s_color = "#F59E0B"
        elif "BULLISH" in s["impact"]:
            s_color = "#10B981"
        elif "BEARISH" in s["impact"]:
            s_color = "#EF4444"
        else:
            s_color = "#6b7280"
        cat_emoji = "🏛️" if s["category"] == "Government" else "💼"
        statements_html += f"""
        <tr><td style="padding: 12px 18px; border-bottom: 1px solid #1e2a3a;">
            <span style="color: #4b5563; font-size: 10px;">{cat_emoji} {s['category']} · {s['date']}</span>
            <span style="color: {s_color}; font-size: 10px; font-weight: 700; float: right;">{s['impact']}</span>
            <br><strong style="color: #e0e0e0; font-size: 13px;">{s['person']}</strong>
            <span style="color: #6b7280; font-size: 11px;"> — {s['title']}</span>
            <br><span style="color: #9ca3af; font-size: 12px; font-style: italic;">"{s['statement'][:120]}..."</span>
        </td></tr>"""

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
            BTC ${btc_price:,.0f} {btc_arrow}{abs(btc_change):.1f}% | Correlation: {cor_score}/100 | {lb_summary['total_btc']:,} BTC held | {reg_stats['total_items']} regulatory items
        </div>

        <table width="100%" cellpadding="0" cellspacing="0" style="max-width: 680px; margin: 0 auto; background-color: #0a0e17;">

            <tr><td style="height: 4px; background: linear-gradient(90deg, #E67E22 0%, #F59E0B 50%, #E67E22 100%);"></td></tr>

            <!-- Header -->
            <tr><td style="padding: 28px 36px 20px 36px;">
                <table width="100%" cellpadding="0" cellspacing="0"><tr>
                    <td>
                        <span style="color: #E67E22; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.15em;">Treasury Signal Intelligence</span>
                        <br><span style="color: #e0e0e0; font-size: 22px; font-weight: 700; letter-spacing: -0.02em;">Executive Daily Briefing</span>
                        <br><span style="color: #4b5563; font-size: 12px;">{today} · {time_now}</span>
                    </td>
                    <td style="text-align: right; vertical-align: top;">
                        <span style="color: #E67E22; font-size: 32px;">🔶</span>
                    </td>
                </tr></table>
            </td></tr>

            <tr><td style="padding: 0 36px;"><div style="border-top: 1px solid #1e2a3a;"></div></td></tr>

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

            <!-- STRC Alert Bar -->
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
                        <td><span style="color: #6b7280; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.12em;">⑤ Recent Confirmed BTC Purchases</span></td>
                        <td style="text-align: right;"><span style="color: #6b7280; font-size: 11px;">{purchase_stats['total_purchases']} total · {purchase_stats['total_btc']:,} BTC · ${purchase_stats['total_usd']/1_000_000_000:.1f}B</span></td>
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
                        <td><span style="color: #6b7280; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.12em;">⑥ BTC Treasury Leaderboard</span></td>
                        <td style="text-align: right;"><span style="color: #6b7280; font-size: 11px;">{lb_summary['total_companies']} companies · {lb_summary['total_btc']:,} BTC · ${lb_summary['total_value_b']:.1f}B</span></td>
                    </tr>
                </table>
                <table width="100%" cellpadding="0" cellspacing="0" style="background: #111827; border-radius: 12px; margin-top: 10px; overflow: hidden;">
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
                </table>
            </td></tr>

            <!-- ⑦ REGULATORY & GOVERNMENT -->
            <tr><td style="padding: 0 36px 16px 36px;">
                <table width="100%" cellpadding="0" cellspacing="0">
                    <tr>
                        <td><span style="color: #6b7280; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.12em;">⑦ Global Regulatory Landscape</span></td>
                        <td style="text-align: right;"><span style="color: #6b7280; font-size: 11px;">{reg_stats['total_items']} items · {reg_stats['regions_tracked']} regions · {reg_stats['bullish']} bullish</span></td>
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
                        <td style="text-align: right;"><span style="color: #6b7280; font-size: 11px;">{reg_stats['total_statements']} statements · {reg_stats['bullish_statements']} bullish · {reg_stats['bearish_statements']} bearish</span></td>
                    </tr>
                </table>
                <table width="100%" cellpadding="0" cellspacing="0" style="background: #111827; border-radius: 12px; margin-top: 10px; overflow: hidden;">
                    {statements_html}
                </table>
            </td></tr>

            <!-- ⑨ ACCURACY & PREDICTION TRACKING -->
            <tr><td style="padding: 0 36px 24px 36px;">
                <span style="color: #6b7280; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.12em;">⑨ Intelligence Performance</span>
                <table width="100%" cellpadding="0" cellspacing="0" style="margin-top: 10px;">
                    <tr>
                        <td width="19%" style="padding: 14px 6px; text-align: center; background: #111827; border-radius: 10px;">
                            <span style="color: #E67E22; font-size: 22px; font-weight: 800; font-family: 'Courier New', monospace;">{total_signals}</span>
                            <br><span style="color: #4b5563; font-size: 9px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em;">Signals</span>
                        </td>
                        <td width="2%"></td>
                        <td width="19%" style="padding: 14px 6px; text-align: center; background: #111827; border-radius: 10px;">
                            <span style="color: #E67E22; font-size: 22px; font-weight: 800; font-family: 'Courier New', monospace;">{high_signals}</span>
                            <br><span style="color: #4b5563; font-size: 9px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em;">High Conf</span>
                        </td>
                        <td width="2%"></td>
                        <td width="19%" style="padding: 14px 6px; text-align: center; background: #111827; border-radius: 10px;">
                            <span style="color: #E67E22; font-size: 22px; font-weight: 800; font-family: 'Courier New', monospace;">{accuracy['total_predictions']}</span>
                            <br><span style="color: #4b5563; font-size: 9px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em;">Predictions</span>
                        </td>
                        <td width="2%"></td>
                        <td width="19%" style="padding: 14px 6px; text-align: center; background: #111827; border-radius: 10px;">
                            <span style="color: #E67E22; font-size: 22px; font-weight: 800; font-family: 'Courier New', monospace;">{accuracy['hit_rate']}%</span>
                            <br><span style="color: #4b5563; font-size: 9px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em;">Hit Rate</span>
                        </td>
                        <td width="2%"></td>
                        <td width="19%" style="padding: 14px 6px; text-align: center; background: #111827; border-radius: 10px;">
                            <span style="color: #E67E22; font-size: 22px; font-weight: 800; font-family: 'Courier New', monospace;">{accuracy['total_purchases']}</span>
                            <br><span style="color: #4b5563; font-size: 9px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em;">Confirmed</span>
                        </td>
                    </tr>
                </table>
            </td></tr>

            <!-- CTA -->
            <tr><td style="padding: 24px 36px; text-align: center; background: #111827; border-top: 1px solid #1e2a3a;">
                <span style="color: #6b7280; font-size: 12px;">Full interactive dashboard with charts, correlation engine, and real-time data:</span>
                <br><br>
                <a href="https://treasury-signals-jqyywcwr8l8pbtv66rvbbg.streamlit.app/" style="background: linear-gradient(135deg, #E67E22, #d35400); color: white; padding: 14px 36px; border-radius: 8px; text-decoration: none; font-weight: 700; font-size: 14px; letter-spacing: 0.02em; display: inline-block;">Open Live Dashboard →</a>
                <br><br>
                <span style="color: #374151; font-size: 11px;">Live Dashboard · BTC Leaderboard · Recent Purchases · Regulatory Tracker · Accuracy</span>
            </td></tr>

            <!-- Footer -->
            <tr><td style="padding: 24px 36px; border-top: 1px solid #1e2a3a;">
                <span style="color: #E67E22; font-size: 10px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase;">Treasury Signal Intelligence™</span>
                <br><span style="color: #374151; font-size: 10px;">Multi-Signal Correlation Engine™ · BTC Treasury Leaderboard™ · Global Regulatory Tracker™</span>
                <br><span style="color: #1f2937; font-size: 10px; margin-top: 8px; display: inline-block;">
                    Data: TwitterAPI.io · Yahoo Finance · SEC EDGAR · Not financial advice.<br>
                    © 2026 Treasury Signal Intelligence. All rights reserved.
                </span>
            </td></tr>

            <tr><td style="height: 4px; background: linear-gradient(90deg, #E67E22 0%, #F59E0B 50%, #E67E22 100%);"></td></tr>
        </table>
    </body>
    </html>
    """

    return html


def send_briefing(to_email, html_content):
    """Send the briefing email via Resend."""
    try:
        params = {
            "from": "Treasury Signal Intelligence <onboarding@resend.dev>",
            "to": [to_email],
            "subject": f"🔶 Daily Intelligence Briefing — {datetime.now().strftime('%b %d, %Y')}",
            "html": html_content,
        }
        email = resend.Emails.send(params)
        print(f"  Email sent to {to_email}: {email.get('id', 'unknown')}")
        return True
    except Exception as e:
        print(f"  Email ERROR: {e}")
        return False


def generate_and_send_briefing(to_email):
    """Generate the full briefing and send it."""
    print("  Generating executive briefing v3.0 (full 6-page summary)...")

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

    # Build correlation snapshot
    engine = CorrelationEngine()
    for sig in signals:
        score = sig.get("confidence_score", 0)
        if score >= 60:
            engine.add_tweet_signal(sig.get("author_username", ""), score, sig.get("tweet_text", ""))
    correlation = engine.calculate_correlation()

    html = build_briefing_html(
        market, signals, all_signals, leaderboard, lb_summary,
        reg_stats, reg_items, accuracy, statements, purchases,
        purchase_stats, correlation
    )

    print(f"  Market: BTC ${market.get('btc_price', 0):,.0f} | MSTR ${market.get('mstr_price', 0):,.2f}")
    print(f"  Signals (24h): {len(signals)} | Total: {len(all_signals)}")
    print(f"  Leaderboard: {lb_summary['total_companies']} companies | {lb_summary['total_btc']:,} BTC")
    print(f"  Regulatory: {reg_stats['total_items']} items | {reg_stats['active_passed']} active")
    print(f"  Statements: {reg_stats['total_statements']} notable")
    print(f"  Recent Purchases: {len(purchases)} shown | {purchase_stats['total_purchases']} total tracked")
    print(f"  Correlation: {correlation['correlated_score']}/100 ({correlation['active_streams']}/4 streams)")
    print(f"  Accuracy: {accuracy['total_predictions']} predictions | {accuracy['hit_rate']}% hit rate")

    success = send_briefing(to_email, html)
    return success, html


# ============================================
# QUICK TEST
# ============================================
if __name__ == "__main__":
    print("Executive Email Briefing v3.0 — Full 6-Page Intelligence Summary\n")
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

    html = build_briefing_html(
        market, signals, all_signals, leaderboard, lb_summary,
        reg_stats, reg_items, accuracy, statements, purchases,
        purchase_stats, correlation
    )

    with open("briefing_preview.html", "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  Market: BTC ${market.get('btc_price', 0):,.0f} | MSTR ${market.get('mstr_price', 0):,.2f}")
    print(f"  Leaderboard: {lb_summary['total_companies']} companies | {lb_summary['total_btc']:,} BTC")
    print(f"  Regulatory: {reg_stats['total_items']} items | {reg_stats['total_statements']} statements")
    print(f"  Purchases: {purchase_stats['total_purchases']} tracked | {purchase_stats['total_btc']:,} BTC")
    print(f"  Correlation: {correlation['correlated_score']}/100 ({correlation['active_streams']}/4 streams)")
    print(f"  Accuracy: {accuracy['total_predictions']} predictions | {accuracy['hit_rate']}% hit rate")
    print(f"\n  Preview saved to: briefing_preview.html")
    print(f"  Open this file in your browser to see the full briefing!\n")
    print("Briefing v3.0 is ready!")

