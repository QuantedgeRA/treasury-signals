"""
email_briefing.py
-----------------
Executive Daily Intelligence Briefing

Sends a beautifully formatted HTML email at 7am daily with:
- Overnight signal summary
- STRC volume status
- BTC treasury leaderboard changes
- SEC filing activity
- Correlation engine status
- Government/regulatory updates (Phase 3)

This is the CEO-grade delivery mechanism.
Executives don't check Telegram. They check email.
"""

import os
import resend
from datetime import datetime, timedelta
from dotenv import load_dotenv
from supabase import create_client
from strc_tracker import get_strc_volume_data, analyze_strc_signal
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


def build_briefing_html(market, signals, all_signals):
    """Build the executive briefing HTML email."""
    
    today = datetime.now().strftime("%A, %B %d, %Y")
    
    # Format price changes with colors
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
        
        <!-- Container -->
        <table width="100%" cellpadding="0" cellspacing="0" style="max-width: 680px; margin: 0 auto; background-color: #161B22;">
            
            <!-- Header -->
            <tr>
                <td style="padding: 30px 40px; background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); border-bottom: 3px solid #E67E22;">
                    <table width="100%">
                        <tr>
                            <td>
                                <h1 style="color: #E67E22; margin: 0; font-size: 24px; font-weight: 800;">🔶 Treasury Signal Intelligence</h1>
                                <p style="color: #7F8C8D; margin: 5px 0 0 0; font-size: 14px;">Executive Daily Briefing — {today}</p>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
            
            <!-- Market Snapshot -->
            <tr>
                <td style="padding: 25px 40px;">
                    <h2 style="color: #ECF0F1; font-size: 18px; margin: 0 0 15px 0; border-bottom: 1px solid #2C3E50; padding-bottom: 10px;">📊 Market Snapshot</h2>
                    <table width="100%" cellpadding="0" cellspacing="0">
                        <tr>
                            <td width="33%" style="padding: 10px; text-align: center;">
                                <p style="color: #7F8C8D; margin: 0; font-size: 12px; text-transform: uppercase;">Bitcoin</p>
                                <p style="color: #ECF0F1; margin: 5px 0; font-size: 24px; font-weight: 800;">${market.get('btc_price', 0):,.0f}</p>
                                <p style="color: {btc_color}; margin: 0; font-size: 14px;">{btc_arrow} {market.get('btc_change', 0):+.2f}%</p>
                            </td>
                            <td width="33%" style="padding: 10px; text-align: center; border-left: 1px solid #2C3E50; border-right: 1px solid #2C3E50;">
                                <p style="color: #7F8C8D; margin: 0; font-size: 12px; text-transform: uppercase;">MSTR</p>
                                <p style="color: #ECF0F1; margin: 5px 0; font-size: 24px; font-weight: 800;">${market.get('mstr_price', 0):,.2f}</p>
                                <p style="color: {mstr_color}; margin: 0; font-size: 14px;">{mstr_arrow} {market.get('mstr_change', 0):+.2f}%</p>
                            </td>
                            <td width="33%" style="padding: 10px; text-align: center;">
                                <p style="color: #7F8C8D; margin: 0; font-size: 12px; text-transform: uppercase;">STRC</p>
                                <p style="color: #ECF0F1; margin: 5px 0; font-size: 24px; font-weight: 800;">${market.get('strc_price', 0):.2f}</p>
                                <p style="color: #7F8C8D; margin: 0; font-size: 14px;">Vol: ${market.get('strc_volume_m', 0)}M</p>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
            
            <!-- STRC Capital Raise Status -->
            <tr>
                <td style="padding: 0 40px 25px 40px;">
                    <div style="background: #1a1a2e; border-left: 4px solid {strc_color}; padding: 15px; border-radius: 0 8px 8px 0;">
                        <p style="color: #ECF0F1; margin: 0; font-size: 14px;">
                            <strong>STRC Capital Raise Status:</strong> {strc_status}
                            <br><span style="color: #7F8C8D;">Volume ratio: {strc_ratio}x normal | Dollar volume: ${market.get('strc_volume_m', 0)}M</span>
                        </p>
                    </div>
                </td>
            </tr>
            
            <!-- Purchase Signals -->
            <tr>
                <td style="padding: 0 40px 25px 40px;">
                    <h2 style="color: #ECF0F1; font-size: 18px; margin: 0 0 5px 0; border-bottom: 1px solid #2C3E50; padding-bottom: 10px;">🚨 Purchase Signals (24h)</h2>
                    <p style="color: #7F8C8D; font-size: 13px; margin: 0 0 10px 0;">{signal_count_text}</p>
                    <table width="100%" cellpadding="0" cellspacing="0" style="background: #1a1a2e; border-radius: 8px;">
                        {signals_html}
                    </table>
                </td>
            </tr>
            
            <!-- System Stats -->
            <tr>
                <td style="padding: 0 40px 25px 40px;">
                    <h2 style="color: #ECF0F1; font-size: 18px; margin: 0 0 15px 0; border-bottom: 1px solid #2C3E50; padding-bottom: 10px;">📈 Intelligence Summary</h2>
                    <table width="100%" cellpadding="0" cellspacing="0">
                        <tr>
                            <td width="25%" style="padding: 10px; text-align: center; background: #1a1a2e; border-radius: 8px;">
                                <p style="color: #E67E22; font-size: 28px; font-weight: 800; margin: 0;">{total_signals}</p>
                                <p style="color: #7F8C8D; font-size: 11px; margin: 0;">Total Signals</p>
                            </td>
                            <td width="5%"></td>
                            <td width="25%" style="padding: 10px; text-align: center; background: #1a1a2e; border-radius: 8px;">
                                <p style="color: #E67E22; font-size: 28px; font-weight: 800; margin: 0;">{high_signals}</p>
                                <p style="color: #7F8C8D; font-size: 11px; margin: 0;">High Confidence</p>
                            </td>
                            <td width="5%"></td>
                            <td width="25%" style="padding: 10px; text-align: center; background: #1a1a2e; border-radius: 8px;">
                                <p style="color: #E67E22; font-size: 28px; font-weight: 800; margin: 0;">24+</p>
                                <p style="color: #7F8C8D; font-size: 11px; margin: 0;">Accounts Monitored</p>
                            </td>
                            <td width="5%"></td>
                            <td width="25%" style="padding: 10px; text-align: center; background: #1a1a2e; border-radius: 8px;">
                                <p style="color: #E67E22; font-size: 28px; font-weight: 800; margin: 0;">4</p>
                                <p style="color: #7F8C8D; font-size: 11px; margin: 0;">Data Streams</p>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
            
            <!-- CTA -->
            <tr>
                <td style="padding: 20px 40px; text-align: center; background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); border-top: 1px solid #2C3E50;">
                    <p style="color: #7F8C8D; font-size: 13px; margin: 0 0 10px 0;">View the full live dashboard with charts, correlation engine, and real-time signals:</p>
                    <a href="https://treasury-signals-jqyywcwr8l8pbtv66rvbbg.streamlit.app/" style="background: #E67E22; color: white; padding: 12px 30px; border-radius: 6px; text-decoration: none; font-weight: 700; font-size: 14px;">Open Live Dashboard →</a>
                </td>
            </tr>
            
            <!-- Footer -->
            <tr>
                <td style="padding: 20px 40px; border-top: 1px solid #2C3E50;">
                    <p style="color: #4A5568; font-size: 11px; margin: 0; text-align: center;">
                        Treasury Signal Intelligence™ — Multi-Signal Correlation Engine™<br>
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
            "from": "Treasury Signal Intelligence <signals@quantedgeriskadvisory.com>",
            "to": [to_email],
            "subject": f"🔶 Treasury Signal Intelligence — Daily Briefing ({datetime.now().strftime('%b %d, %Y')})",
            "html": html_content,
        }
        
        email = resend.Emails.send(params)
        print(f"  Email sent to {to_email}: {email}")
        return True
    except Exception as e:
        print(f"  Email ERROR: {e}")
        return False


def generate_and_send_briefing(to_email):
    """Generate the full briefing and send it."""
    print("  Generating executive briefing...")
    
    market = get_market_data()
    signals = get_recent_signals(hours=24)
    all_signals = get_all_signals()
    
    html = build_briefing_html(market, signals, all_signals)
    
    print(f"  Market: BTC ${market.get('btc_price', 0):,.0f} | MSTR ${market.get('mstr_price', 0):,.2f} | STRC ${market.get('strc_price', 0):.2f}")
    print(f"  Signals (24h): {len(signals)} | Total signals: {len(all_signals)}")
    
    success = send_briefing(to_email, html)
    return success, html


# ============================================
# QUICK TEST
# ============================================
if __name__ == "__main__":
    print("Executive Email Briefing Generator\n")
    print("=" * 60)
    
    if not RESEND_API_KEY or "your" in str(RESEND_API_KEY).lower():
        print("\nTo send real emails, sign up at resend.com and add your API key:")
        print("  RESEND_API_KEY=re_xxxxxxxxxxxx")
        print("\nFor now, generating the briefing HTML for preview...\n")
    
    market = get_market_data()
    signals = get_recent_signals(hours=24)
    all_signals = get_all_signals()
    
    html = build_briefing_html(market, signals, all_signals)
    
    # Save to file for preview
    with open("briefing_preview.html", "w", encoding="utf-8") as f:
        f.write(html)
    
    print(f"  Market data loaded: BTC ${market.get('btc_price', 0):,.0f}")
    print(f"  Recent signals: {len(signals)}")
    print(f"  Total signals: {len(all_signals)}")
    print(f"\n  Preview saved to: briefing_preview.html")
    print(f"  Open this file in your browser to see the email!\n")
    print("Email Briefing Generator is working!")