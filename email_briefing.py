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
from regulatory_tracker import get_all_regulatory_items, get_summary_stats as get_reg_stats
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


def build_briefing_html(market, signals, all_signals, leaderboard, lb_summary, reg_stats, reg_items, accuracy):
    """Build the full executive briefing HTML email."""

    today = datetime.now().strftime("%A, %B %d, %Y")

    # Price change formatting
    btc_color = "#2ECC71" if market.get("btc_change", 0) >= 0 else "#E74C3C"
    btc_arrow = "▲" if market.get("btc_change", 0) >= 0 else "▼"
    mstr_color = "#2ECC71" if market.get("mstr_change", 0) >= 0 else "#E74C3C"
    mstr_arrow = "▲" if market.get("mstr_change", 0) >= 0 else "▼"

    # STRC status
    strc_ratio = market.get("strc_ratio", 0)
    if strc_ratio >= 2.0:
        strc_status = "🔴 VERY HIGH — Aggressive capital raise detected"
        strc_color = "#E74C3C"
    elif strc_ratio >= 1.5:
        strc_status = "🟠 HIGH — Elevated issuance activity"
        strc_color = "#F39C12"
    elif strc_ratio >= 1.2:
        strc_status = "🟡 ELEVATED — Above average"
        strc_color = "#F1C40F"
    else:
        strc_status = "✅ NORMAL — Baseline activity"
        strc_color = "#2ECC71"

    # Build signals section
    if signals:
        signals_html = ""
        for sig in signals[:5]:
            score = sig.get("confidence_score", 0)
            author = sig.get("author_username", "")
            text = sig.get("tweet_text", "")[:150]
            company = sig.get("company", "")
            if score >= 60:
                sig_color = "#E74C3C"
                sig_label = "HIGH"
            elif score >= 40:
                sig_color = "#F39C12"
                sig_label = "MEDIUM"
            else:
                sig_color = "#F1C40F"
                sig_label = "LOW"
            signals_html += f"""
            <tr>
                <td style="padding: 12px; border-bottom: 1px solid #2C3E50;">
                    <span style="background: {sig_color}; color: white; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 700;">{score}/100 {sig_label}</span>
                    <br><strong style="color: #ECF0F1;">@{author}</strong> <span style="color: #7F8C8D;">({company})</span>
                    <br><span style="color: #BDC3C7; font-size: 14px;">{text}...</span>
                </td>
            </tr>
            """
        signal_count_text = f"{len(signals)} signal(s) detected in the last 24 hours"
    else:
        signals_html = """
        <tr>
            <td style="padding: 12px; color: #7F8C8D;">
                ✅ No purchase signals detected in the last 24 hours. All quiet.
            </td>
        </tr>
        """
        signal_count_text = "No signals in the last 24 hours"

    # Build leaderboard section (Top 10)
    leaderboard_html = ""
    medals = ["🥇", "🥈", "🥉"]
    for c in leaderboard[:10]:
        if c["btc_holdings"] > 0:
            rank = c["rank"]
            medal = medals[rank - 1] if rank <= 3 else f"#{rank}"
            name = c["company"].replace(" (MicroStrategy)", "").replace(" Digital (MARA)", "")
            pnl_html = ""
            if c.get("unrealized_pnl_pct") and c["unrealized_pnl_pct"] != 0:
                pnl_color = "#2ECC71" if c["unrealized_pnl_pct"] > 0 else "#E74C3C"
                pnl_html = f'<span style="color: {pnl_color}; font-size: 12px;"> ({c["unrealized_pnl_pct"]:+.1f}%)</span>'

            leaderboard_html += f"""
            <tr>
                <td style="padding: 8px 12px; border-bottom: 1px solid #2C3E50; color: #ECF0F1; font-size: 14px;">
                    <strong>{medal}</strong> {name} <span style="color: #7F8C8D;">({c['ticker']})</span>
                </td>
                <td style="padding: 8px 12px; border-bottom: 1px solid #2C3E50; color: #E67E22; font-size: 14px; text-align: right; font-weight: 700;">
                    {c['btc_holdings']:,} BTC
                </td>
                <td style="padding: 8px 12px; border-bottom: 1px solid #2C3E50; color: #BDC3C7; font-size: 14px; text-align: right;">
                    ${c['btc_value_b']:.2f}B{pnl_html}
                </td>
            </tr>
            """

    # Build regulatory section
    active_regs = [r for r in reg_items if r["status_color"] == "green"]
    pending_regs = [r for r in reg_items if r["status_color"] == "yellow"]

    reg_html = ""
    # Show top 3 active + top 3 pending
    for r in active_regs[:3]:
        impact_color = "#E74C3C" if "EXTREMELY" in r["btc_impact"] or "VERY" in r["btc_impact"] else "#F39C12"
        reg_html += f"""
        <tr>
            <td style="padding: 8px 12px; border-bottom: 1px solid #2C3E50;">
                <span style="color: #2ECC71; font-size: 12px;">✅ {r['status']}</span>
                <br><strong style="color: #ECF0F1; font-size: 13px;">{r['title']}</strong>
                <br><span style="color: #7F8C8D; font-size: 12px;">{r['category']}</span>
                <span style="color: {impact_color}; font-size: 12px; float: right;">{r['btc_impact']}</span>
            </td>
        </tr>
        """

    for r in pending_regs[:3]:
        impact_color = "#E74C3C" if "EXTREMELY" in r["btc_impact"] or "VERY" in r["btc_impact"] else "#F39C12"
        reg_html += f"""
        <tr>
            <td style="padding: 8px 12px; border-bottom: 1px solid #2C3E50;">
                <span style="color: #F1C40F; font-size: 12px;">🟡 {r['status']}</span>
                <br><strong style="color: #ECF0F1; font-size: 13px;">{r['title']}</strong>
                <br><span style="color: #7F8C8D; font-size: 12px;">{r['category']}</span>
                <span style="color: {impact_color}; font-size: 12px; float: right;">{r['btc_impact']}</span>
            </td>
        </tr>
        """

    # Total stats
    total_signals = len(all_signals)
    high_signals = len([s for s in all_signals if s.get("confidence_score", 0) >= 60])

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="margin: 0; padding: 0; background-color: #0D1117; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">

        <table width="100%" cellpadding="0" cellspacing="0" style="max-width: 680px; margin: 0 auto; background-color: #161B22;">

            <!-- Header -->
            <tr>
                <td style="padding: 30px 40px; background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); border-bottom: 3px solid #E67E22;">
                    <h1 style="color: #E67E22; margin: 0; font-size: 22px; font-weight: 800;">🔶 Treasury Signal Intelligence</h1>
                    <p style="color: #7F8C8D; margin: 5px 0 0 0; font-size: 13px;">Executive Daily Briefing — {today}</p>
                </td>
            </tr>

            <!-- Market Snapshot -->
            <tr>
                <td style="padding: 25px 40px 15px 40px;">
                    <h2 style="color: #ECF0F1; font-size: 16px; margin: 0 0 15px 0; border-bottom: 1px solid #2C3E50; padding-bottom: 8px;">📊 MARKET SNAPSHOT</h2>
                    <table width="100%" cellpadding="0" cellspacing="0">
                        <tr>
                            <td width="33%" style="padding: 10px; text-align: center;">
                                <p style="color: #7F8C8D; margin: 0; font-size: 11px; text-transform: uppercase;">Bitcoin</p>
                                <p style="color: #ECF0F1; margin: 5px 0; font-size: 22px; font-weight: 800;">${market.get('btc_price', 0):,.0f}</p>
                                <p style="color: {btc_color}; margin: 0; font-size: 13px;">{btc_arrow} {market.get('btc_change', 0):+.2f}%</p>
                            </td>
                            <td width="33%" style="padding: 10px; text-align: center; border-left: 1px solid #2C3E50; border-right: 1px solid #2C3E50;">
                                <p style="color: #7F8C8D; margin: 0; font-size: 11px; text-transform: uppercase;">MSTR</p>
                                <p style="color: #ECF0F1; margin: 5px 0; font-size: 22px; font-weight: 800;">${market.get('mstr_price', 0):,.2f}</p>
                                <p style="color: {mstr_color}; margin: 0; font-size: 13px;">{mstr_arrow} {market.get('mstr_change', 0):+.2f}%</p>
                            </td>
                            <td width="33%" style="padding: 10px; text-align: center;">
                                <p style="color: #7F8C8D; margin: 0; font-size: 11px; text-transform: uppercase;">STRC</p>
                                <p style="color: #ECF0F1; margin: 5px 0; font-size: 22px; font-weight: 800;">${market.get('strc_price', 0):.2f}</p>
                                <p style="color: #7F8C8D; margin: 0; font-size: 13px;">Vol: ${market.get('strc_volume_m', 0)}M</p>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>

            <!-- STRC Status -->
            <tr>
                <td style="padding: 0 40px 20px 40px;">
                    <div style="background: #1a1a2e; border-left: 4px solid {strc_color}; padding: 12px 15px; border-radius: 0 8px 8px 0;">
                        <p style="color: #ECF0F1; margin: 0; font-size: 13px;">
                            <strong>STRC Capital Raise Status:</strong> {strc_status}
                            <br><span style="color: #7F8C8D; font-size: 12px;">Volume ratio: {strc_ratio}x normal | Dollar volume: ${market.get('strc_volume_m', 0)}M</span>
                        </p>
                    </div>
                </td>
            </tr>

            <!-- Purchase Signals -->
            <tr>
                <td style="padding: 0 40px 20px 40px;">
                    <h2 style="color: #ECF0F1; font-size: 16px; margin: 0 0 5px 0; border-bottom: 1px solid #2C3E50; padding-bottom: 8px;">🚨 PURCHASE SIGNALS (24H)</h2>
                    <p style="color: #7F8C8D; font-size: 12px; margin: 0 0 10px 0;">{signal_count_text}</p>
                    <table width="100%" cellpadding="0" cellspacing="0" style="background: #1a1a2e; border-radius: 8px;">
                        {signals_html}
                    </table>
                </td>
            </tr>

            <!-- BTC Treasury Leaderboard -->
            <tr>
                <td style="padding: 0 40px 20px 40px;">
                    <h2 style="color: #ECF0F1; font-size: 16px; margin: 0 0 5px 0; border-bottom: 1px solid #2C3E50; padding-bottom: 8px;">🏆 BTC TREASURY LEADERBOARD</h2>
                    <p style="color: #7F8C8D; font-size: 12px; margin: 0 0 10px 0;">
                        {lb_summary['total_companies']} companies | {lb_summary['total_btc']:,} BTC total (${lb_summary['total_value_b']:.1f}B)
                    </p>
                    <table width="100%" cellpadding="0" cellspacing="0" style="background: #1a1a2e; border-radius: 8px;">
                        <tr>
                            <td style="padding: 8px 12px; border-bottom: 1px solid #2C3E50; color: #7F8C8D; font-size: 11px; text-transform: uppercase;">Company</td>
                            <td style="padding: 8px 12px; border-bottom: 1px solid #2C3E50; color: #7F8C8D; font-size: 11px; text-align: right; text-transform: uppercase;">Holdings</td>
                            <td style="padding: 8px 12px; border-bottom: 1px solid #2C3E50; color: #7F8C8D; font-size: 11px; text-align: right; text-transform: uppercase;">Value</td>
                        </tr>
                        {leaderboard_html}
                        <tr>
                            <td style="padding: 10px 12px; color: #E67E22; font-weight: 700; font-size: 13px;">TOTAL</td>
                            <td style="padding: 10px 12px; color: #E67E22; font-weight: 700; font-size: 13px; text-align: right;">{lb_summary['total_btc']:,} BTC</td>
                            <td style="padding: 10px 12px; color: #E67E22; font-weight: 700; font-size: 13px; text-align: right;">${lb_summary['total_value_b']:.1f}B</td>
                        </tr>
                    </table>
                </td>
            </tr>

            <!-- Government & Regulatory -->
            <tr>
                <td style="padding: 0 40px 20px 40px;">
                    <h2 style="color: #ECF0F1; font-size: 16px; margin: 0 0 5px 0; border-bottom: 1px solid #2C3E50; padding-bottom: 8px;">🏛️ GOVERNMENT & REGULATORY</h2>
                    <p style="color: #7F8C8D; font-size: 12px; margin: 0 0 10px 0;">
                        {reg_stats['total_items']} items tracked | ✅ {reg_stats['active_passed']} active | 🟡 {reg_stats['pending']} pending | 📈 {reg_stats['bullish']} bullish for BTC
                    </p>
                    <table width="100%" cellpadding="0" cellspacing="0" style="background: #1a1a2e; border-radius: 8px;">
                        {reg_html}
                    </table>
                </td>
            </tr>

            <!-- Intelligence Summary -->
            <tr>
                <td style="padding: 0 40px 20px 40px;">
                    <h2 style="color: #ECF0F1; font-size: 16px; margin: 0 0 15px 0; border-bottom: 1px solid #2C3E50; padding-bottom: 8px;">📈 INTELLIGENCE SUMMARY</h2>
                    <table width="100%" cellpadding="0" cellspacing="0">
                        <tr>
                            <td width="20%" style="padding: 10px; text-align: center; background: #1a1a2e; border-radius: 8px;">
                                <p style="color: #E67E22; font-size: 24px; font-weight: 800; margin: 0;">{total_signals}</p>
                                <p style="color: #7F8C8D; font-size: 10px; margin: 0;">Total Signals</p>
                            </td>
                            <td width="4%"></td>
                            <td width="20%" style="padding: 10px; text-align: center; background: #1a1a2e; border-radius: 8px;">
                                <p style="color: #E67E22; font-size: 24px; font-weight: 800; margin: 0;">{high_signals}</p>
                                <p style="color: #7F8C8D; font-size: 10px; margin: 0;">High Confidence</p>
                            </td>
                            <td width="4%"></td>
                            <td width="20%" style="padding: 10px; text-align: center; background: #1a1a2e; border-radius: 8px;">
                                <p style="color: #E67E22; font-size: 24px; font-weight: 800; margin: 0;">{accuracy['total_predictions']}</p>
                                <p style="color: #7F8C8D; font-size: 10px; margin: 0;">Predictions Logged</p>
                            </td>
                            <td width="4%"></td>
                            <td width="20%" style="padding: 10px; text-align: center; background: #1a1a2e; border-radius: 8px;">
                                <p style="color: #E67E22; font-size: 24px; font-weight: 800; margin: 0;">{accuracy['hit_rate']}%</p>
                                <p style="color: #7F8C8D; font-size: 10px; margin: 0;">Hit Rate</p>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>

            <!-- CTA -->
            <tr>
                <td style="padding: 20px 40px; text-align: center; background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); border-top: 1px solid #2C3E50;">
                    <p style="color: #7F8C8D; font-size: 12px; margin: 0 0 12px 0;">Full live dashboard with interactive charts, real-time signals, and complete leaderboard:</p>
                    <a href="https://treasury-signals-jqyywcwr8l8pbtv66rvbbg.streamlit.app/" style="background: #E67E22; color: white; padding: 12px 30px; border-radius: 6px; text-decoration: none; font-weight: 700; font-size: 14px;">Open Live Dashboard →</a>
                </td>
            </tr>

            <!-- Footer -->
            <tr>
                <td style="padding: 20px 40px; border-top: 1px solid #2C3E50;">
                    <p style="color: #4A5568; font-size: 11px; margin: 0; text-align: center;">
                        Treasury Signal Intelligence™ — Multi-Signal Correlation Engine™<br>
                        BTC Treasury Leaderboard™ — Government & Regulatory Tracker™<br>
                        Data: TwitterAPI.io • Yahoo Finance • SEC EDGAR<br>
                        This is not financial advice. For informational purposes only.<br>
                        © 2026 Treasury Signal Intelligence. All rights reserved.
                    </p>
                </td>
            </tr>

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
    print("  Generating executive briefing v2.0...")

    market = get_market_data()
    signals = get_recent_signals(hours=24)
    all_signals = get_all_signals()
    btc_price = market.get("btc_price", 72000)
    leaderboard, lb_summary = get_leaderboard_with_live_price(btc_price)
    reg_stats = get_reg_stats()
    reg_items = get_all_regulatory_items()
    accuracy = get_accuracy_data()

    html = build_briefing_html(market, signals, all_signals, leaderboard, lb_summary, reg_stats, reg_items, accuracy)

    print(f"  Market: BTC ${market.get('btc_price', 0):,.0f} | MSTR ${market.get('mstr_price', 0):,.2f} | STRC ${market.get('strc_price', 0):.2f}")
    print(f"  Signals (24h): {len(signals)} | Total: {len(all_signals)}")
    print(f"  Leaderboard: {lb_summary['total_companies']} companies | {lb_summary['total_btc']:,} BTC")
    print(f"  Regulatory: {reg_stats['total_items']} items | {reg_stats['active_passed']} active")
    print(f"  Accuracy: {accuracy['total_predictions']} predictions | {accuracy['hit_rate']}% hit rate")

    success = send_briefing(to_email, html)
    return success, html


# ============================================
# QUICK TEST
# ============================================
if __name__ == "__main__":
    print("Executive Email Briefing v2.0\n")
    print("=" * 60)

    market = get_market_data()
    signals = get_recent_signals(hours=24)
    all_signals = get_all_signals()
    btc_price = market.get("btc_price", 72000)
    leaderboard, lb_summary = get_leaderboard_with_live_price(btc_price)
    reg_stats = get_reg_stats()
    reg_items = get_all_regulatory_items()
    accuracy = get_accuracy_data()

    html = build_briefing_html(market, signals, all_signals, leaderboard, lb_summary, reg_stats, reg_items, accuracy)

    with open("briefing_preview.html", "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  Market: BTC ${market.get('btc_price', 0):,.0f} | MSTR ${market.get('mstr_price', 0):,.2f}")
    print(f"  Leaderboard: {lb_summary['total_companies']} companies | {lb_summary['total_btc']:,} BTC (${lb_summary['total_value_b']:.1f}B)")
    print(f"  Regulatory: {reg_stats['total_items']} items tracked")
    print(f"  Accuracy: {accuracy['total_predictions']} predictions | {accuracy['hit_rate']}% hit rate")
    print(f"\n  Preview saved to: briefing_preview.html")
    print(f"  Open this file in your browser to see the email!\n")
    print("Briefing v2.0 is ready!")
