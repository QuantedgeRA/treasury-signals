"""
competitor_alerts.py — Competitor Purchase Alert System
--------------------------------------------------------
When a new purchase is detected, checks if it affects any subscriber:
  1. Is the purchasing company on the subscriber's watchlist?
  2. Is the purchaser within ±3 ranks of the subscriber?
  3. Is it a mega purchase (>$500M) that shifts the landscape?
  4. Is the gap between subscriber and nearest competitor closing?

Sends alerts via Telegram and email (Resend).

Integration: In main.py, after purchase detection:
    from competitor_alerts import check_competitor_purchase
    check_competitor_purchase(purchase_dict)
"""

import os
import requests
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client
from logger import get_logger

logger = get_logger(__name__)

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_PAID_CHANNEL_ID = os.getenv("TELEGRAM_PAID_CHANNEL_ID", "")
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
EMAIL_FROM = os.getenv("EMAIL_FROM_ADDRESS", "briefing@quantedgeriskadvisory.com")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def check_competitor_purchase(purchase_data):
    """Called after a new purchase is detected."""
    company = purchase_data.get("company", "")
    ticker = purchase_data.get("ticker", "").upper()
    btc_amount = int(purchase_data.get("btc_amount", 0))
    usd_amount = float(purchase_data.get("usd_amount", 0))

    if btc_amount <= 0:
        return

    logger.info(f"Competitor alert check: {company} ({ticker}) bought {btc_amount} BTC")

    try:
        res = supabase.table("subscribers").select("*").eq("plan", "pro").execute()
        subscribers = res.data or []
    except Exception as e:
        logger.warning(f"Competitor alerts: could not fetch subscribers: {e}")
        return

    try:
        res = supabase.table("treasury_companies").select("ticker, company, btc_holdings").gt("btc_holdings", 0).order("btc_holdings", ascending=False).execute()
        leaderboard = res.data or []
    except Exception as e:
        logger.warning(f"Competitor alerts: could not fetch leaderboard: {e}")
        return

    rank_by_ticker = {row["ticker"]: i + 1 for i, row in enumerate(leaderboard)}
    holdings_by_ticker = {row["ticker"]: row.get("btc_holdings", 0) for row in leaderboard}
    purchasing_rank = rank_by_ticker.get(ticker, 999)
    usd_m = usd_amount / 1_000_000
    is_mega = usd_m >= 500
    size_label = "MEGA" if usd_m >= 1000 else "LARGE" if usd_m >= 500 else "MEDIUM" if usd_m >= 100 else ""

    alerts_sent = 0

    for sub in subscribers:
        sub_ticker = (sub.get("ticker") or "").upper()
        sub_email = sub.get("email", "")
        sub_name = sub.get("name", "Subscriber")
        sub_company = sub.get("company_name", "")
        watchlist = sub.get("watchlist", []) or []

        if not sub_ticker or sub_ticker == ticker:
            continue

        sub_rank = rank_by_ticker.get(sub_ticker, 999)
        sub_holdings = holdings_by_ticker.get(sub_ticker, 0)
        reasons = []

        # Check 1: Watchlist
        if ticker in watchlist or company.lower() in [w.lower() for w in watchlist]:
            reasons.append(f"🎯 {company} is on your watchlist")

        # Check 2: Rank proximity (±3)
        if abs(purchasing_rank - sub_rank) <= 3 and sub_rank < 500:
            diff = abs(purchasing_rank - sub_rank)
            direction = "above" if purchasing_rank < sub_rank else "below"
            reasons.append(f"📊 {company} (#{purchasing_rank}) is {diff} spot{'s' if diff > 1 else ''} {direction} you (#{sub_rank})")

        # Check 3: Mega purchase
        if is_mega:
            reasons.append(f"🚨 {size_label} purchase: ${usd_m:,.0f}M — shifts the competitive landscape")

        # Check 4: Gap closing
        if sub_rank < 500 and purchasing_rank > sub_rank and sub_holdings > 0:
            purchaser_old = holdings_by_ticker.get(ticker, 0)
            purchaser_new = purchaser_old + btc_amount
            was_outside = purchaser_old < sub_holdings * 0.8
            now_inside = purchaser_new >= sub_holdings * 0.8
            if was_outside and now_inside:
                reasons.append(f"⚠️ {company} closing the gap — now within 20% of your {sub_holdings:,} BTC")

        if not reasons:
            continue

        alert_title = f"🔔 Competitor Alert: {company} bought {btc_amount:,} BTC"
        alert_body = f"{alert_title}\n\n{company} ({ticker}) purchased {btc_amount:,} BTC"
        if usd_m > 0:
            alert_body += f" (${usd_m:,.0f}M)"
        alert_body += f".\n\nWhy this matters to {sub_company or 'you'}:"
        for r in reasons:
            alert_body += f"\n  {r}"
        alert_body += f"\n\nFiled: {purchase_data.get('filing_date', 'Today')}\n— Treasury Signal Intelligence"

        _send_telegram(alert_body)
        _send_email_alert(sub_email, sub_name, company, ticker, btc_amount, usd_m, reasons, purchase_data)
        alerts_sent += 1
        logger.info(f"  Alert sent to {sub_email} ({len(reasons)} reasons)")

    if alerts_sent > 0:
        logger.info(f"Competitor alerts: {alerts_sent} alerts sent for {company} purchase")


def _send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_PAID_CHANNEL_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_PAID_CHANNEL_ID, "text": message},
            timeout=10,
        )
    except Exception:
        pass


def _send_email_alert(email, name, company, ticker, btc_amount, usd_m, reasons, purchase_data):
    if not RESEND_API_KEY or not email:
        return
    reasons_html = "".join(f"<li style='margin-bottom:8px;'>{r}</li>" for r in reasons)
    html = f"""
<div style="font-family:-apple-system,system-ui,sans-serif;max-width:560px;margin:0 auto;background:#0a0e17;color:#e0e0e0;padding:32px;border-radius:16px;">
  <div style="border-bottom:1px solid rgba(255,255,255,0.06);padding-bottom:16px;margin-bottom:24px;">
    <span style="color:#E67E22;font-weight:700;font-size:13px;letter-spacing:0.1em;">COMPETITOR ALERT</span>
  </div>
  <h1 style="color:white;font-size:20px;margin:0 0 8px;">{company} bought {btc_amount:,} BTC</h1>
  <p style="color:rgba(255,255,255,0.3);font-size:14px;margin:0 0 24px;">
    {f'${usd_m:,.0f}M purchase' if usd_m > 0 else 'Purchase confirmed'} · {purchase_data.get('filing_date','Today')}
  </p>
  <div style="background:rgba(230,126,34,0.05);border:1px solid rgba(230,126,34,0.15);border-radius:12px;padding:20px;margin-bottom:24px;">
    <p style="color:rgba(255,255,255,0.5);font-size:13px;margin:0 0 12px;font-weight:600;">Why this matters:</p>
    <ul style="color:rgba(255,255,255,0.4);font-size:13px;padding-left:20px;margin:0;">{reasons_html}</ul>
  </div>
  <a href="https://app.quantedgeriskadvisory.com/competitive" style="display:inline-block;background:#E67E22;color:white;text-decoration:none;padding:10px 24px;border-radius:8px;font-weight:600;font-size:14px;">View Competitive Intel →</a>
  <p style="color:rgba(255,255,255,0.15);font-size:11px;margin-top:32px;">Treasury Signal Intelligence</p>
</div>"""
    try:
        requests.post("https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
            json={"from": f"TSI Alerts <{EMAIL_FROM}>", "to": [email],
                  "subject": f"🔔 {company} just bought {btc_amount:,} BTC", "html": html},
            timeout=10)
    except Exception:
        pass
