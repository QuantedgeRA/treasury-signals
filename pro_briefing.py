"""
pro_briefing.py — Personalized Executive Briefing (Pro Only)
-------------------------------------------------------------
Generates and sends personalized daily briefings to Pro subscribers.

Includes 5 personalized sections:
  1. Purchase signals detected
  2. Competitor watchlist activity
  3. New entrants detected
  4. Your rank changed
  5. Daily market summary with your position

Usage:
    from pro_briefing import send_pro_briefings
    send_pro_briefings()  # Call after scan cycle completes
"""

import os
import json
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from supabase import create_client
from logger import get_logger

logger = get_logger(__name__)

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
EMAIL_FROM = os.getenv("EMAIL_FROM_ADDRESS", "briefing@quantedgeriskadvisory.com")
EMAIL_FROM_NAME = os.getenv("EMAIL_FROM_NAME", "Treasury Signal Intelligence")
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "https://app.quantedgeriskadvisory.com")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def get_pro_subscribers():
    """Get all Pro subscribers with email briefing enabled."""
    try:
        result = supabase.table("subscribers").select(
            "email, name, company_name, ticker, btc_holdings, watchlist_json, shares_outstanding"
        ).eq("plan", "pro").eq("email_briefing", True).eq("is_active", True).execute()
        return result.data or []
    except Exception as e:
        logger.error(f"Failed to fetch Pro subscribers: {e}")
        return []


def get_signals_24h():
    """Get purchase signals from last 24 hours."""
    try:
        cutoff = (datetime.utcnow() - timedelta(hours=24)).isoformat()
        result = supabase.table("signals").select("*").gte(
            "created_at", cutoff
        ).order("confidence_score", desc=True).limit(20).execute()
        return result.data or []
    except Exception:
        return []


def get_leaderboard():
    """Get current leaderboard sorted by holdings."""
    try:
        result = supabase.table("treasury_companies").select(
            "ticker, company, btc_holdings"
        ).eq("is_government", False).gt("btc_holdings", 0).order(
            "btc_holdings", desc=True
        ).execute()
        return result.data or []
    except Exception:
        return []


def get_new_entrants_24h():
    """Get new entrants from the last 24 hours."""
    try:
        cutoff = (datetime.utcnow() - timedelta(hours=24)).strftime("%Y-%m-%d")
        result = supabase.table("new_entrants").select("*").gte(
            "first_seen", cutoff
        ).execute()
        return result.data or []
    except Exception:
        return []


def get_btc_price():
    """Get latest BTC price from leaderboard snapshots."""
    try:
        result = supabase.table("leaderboard_snapshots").select(
            "btc_price"
        ).order("snapshot_date", desc=True).limit(1).execute()
        if result.data and result.data[0].get("btc_price"):
            return float(result.data[0]["btc_price"])
    except Exception:
        pass
    return 0


def find_subscriber_rank(leaderboard, ticker):
    """Find subscriber's rank on the leaderboard."""
    if not ticker:
        return 0, 0
    for i, c in enumerate(leaderboard):
        if c.get("ticker") == ticker:
            return i + 1, c.get("btc_holdings", 0)
    return 0, 0


def get_watchlist_activity(watchlist_tickers, signals):
    """Find signals related to watchlist companies."""
    if not watchlist_tickers:
        return []
    activity = []
    for sig in signals:
        sig_ticker = sig.get("ticker", "")
        sig_company = (sig.get("company", "") or "").lower()
        for wt in watchlist_tickers:
            if wt.upper() == sig_ticker.upper() or wt.lower() in sig_company:
                activity.append(sig)
                break
    return activity


def build_personalized_briefing(subscriber, signals, leaderboard, new_entrants, btc_price):
    """Build HTML email for one Pro subscriber."""
    name = subscriber.get("name", "").split(" ")[0] or "there"
    company = subscriber.get("company_name", "")
    ticker = subscriber.get("ticker", "")
    holdings = subscriber.get("btc_holdings", 0) or 0
    shares = subscriber.get("shares_outstanding", 0) or 0

    # Parse watchlist
    wl_raw = subscriber.get("watchlist_json", "[]")
    watchlist = json.loads(wl_raw) if isinstance(wl_raw, str) else (wl_raw or [])

    # Calculate personalized data
    rank, _ = find_subscriber_rank(leaderboard, ticker)
    total_entities = len(leaderboard)
    btc_yield = (holdings / shares) if shares > 0 else 0
    btc_value = holdings * btc_price if btc_price else 0
    pct_21m = (holdings / 21_000_000 * 100) if holdings > 0 else 0

    # Watchlist activity
    watchlist_activity = get_watchlist_activity(watchlist, signals)

    # High-confidence signals
    high_signals = [s for s in signals if (s.get("confidence_score", 0) or 0) >= 60]

    # Gap analysis
    gap_above = ""
    if rank > 1 and rank <= len(leaderboard):
        above = leaderboard[rank - 2]
        gap = (above.get("btc_holdings", 0) or 0) - holdings
        if gap > 0:
            gap_above = f"{gap:,} BTC behind #{rank - 1} ({above.get('company', 'N/A')})"

    date_str = datetime.now().strftime("%B %d, %Y")
    greeting = "Good morning" if datetime.now().hour < 12 else "Good afternoon"

    html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
    <body style="margin:0;padding:0;background:#04070d;font-family:'Helvetica Neue',Arial,sans-serif;">
    <div style="max-width:640px;margin:0 auto;padding:32px 20px;">

    <!-- Header -->
    <div style="text-align:center;margin-bottom:32px;">
      <div style="display:inline-block;background:linear-gradient(135deg,#E67E22,#d35400);width:48px;height:48px;border-radius:14px;line-height:48px;font-size:24px;color:white;font-weight:bold;">⬡</div>
      <h1 style="color:#ffffff;font-size:22px;margin:12px 0 4px 0;">Daily Intelligence Briefing</h1>
      <p style="color:#666;font-size:13px;margin:0;">{date_str} · Pro Subscriber</p>
    </div>

    <!-- Greeting -->
    <div style="background:#111827;border:1px solid #1e2a3a;border-radius:12px;padding:20px;margin-bottom:16px;">
      <p style="color:#e0e0e0;font-size:15px;margin:0;">{greeting}, {name}.</p>
      <p style="color:#888;font-size:13px;margin:8px 0 0 0;">Here's your personalized treasury intelligence for <strong style="color:#E67E22;">{company or 'your company'}</strong>.</p>
    </div>

    <!-- Section 5: Your Position Summary -->
    <div style="background:#111827;border:1px solid #1e2a3a;border-radius:12px;padding:20px;margin-bottom:16px;">
      <h2 style="color:#E67E22;font-size:14px;text-transform:uppercase;letter-spacing:2px;margin:0 0 16px 0;">📊 Your Position</h2>
      <table style="width:100%;border-collapse:collapse;">
        <tr>
          <td style="padding:8px 0;color:#888;font-size:13px;border-bottom:1px solid #1e2a3a;">Leaderboard Rank</td>
          <td style="padding:8px 0;color:#fff;font-size:15px;font-weight:700;text-align:right;border-bottom:1px solid #1e2a3a;">{'#' + str(rank) if rank > 0 else 'Not ranked'} <span style="color:#555;font-size:11px;">of {total_entities}</span></td>
        </tr>
        <tr>
          <td style="padding:8px 0;color:#888;font-size:13px;border-bottom:1px solid #1e2a3a;">BTC Holdings</td>
          <td style="padding:8px 0;color:#fff;font-size:15px;font-weight:700;text-align:right;border-bottom:1px solid #1e2a3a;">{holdings:,} BTC</td>
        </tr>
        <tr>
          <td style="padding:8px 0;color:#888;font-size:13px;border-bottom:1px solid #1e2a3a;">Portfolio Value</td>
          <td style="padding:8px 0;color:#fff;font-size:15px;font-weight:700;text-align:right;border-bottom:1px solid #1e2a3a;">${btc_value:,.0f}</td>
        </tr>
        {'<tr><td style="padding:8px 0;color:#888;font-size:13px;border-bottom:1px solid #1e2a3a;">BTC/Share (Yield)</td><td style="padding:8px 0;color:#E67E22;font-size:15px;font-weight:700;text-align:right;border-bottom:1px solid #1e2a3a;">' + f'{btc_yield:.6f}' + '</td></tr>' if btc_yield > 0 else ''}
        <tr>
          <td style="padding:8px 0;color:#888;font-size:13px;">% of 21M Supply</td>
          <td style="padding:8px 0;color:#fff;font-size:15px;font-weight:700;text-align:right;">{pct_21m:.4f}%</td>
        </tr>
      </table>
      {'<p style="color:#E67E22;font-size:12px;margin:12px 0 0 0;">⬆ Gap to next rank: ' + gap_above + '</p>' if gap_above else ''}
    </div>

    <!-- Section 1: Purchase Signals -->
    <div style="background:#111827;border:1px solid #1e2a3a;border-radius:12px;padding:20px;margin-bottom:16px;">
      <h2 style="color:#E67E22;font-size:14px;text-transform:uppercase;letter-spacing:2px;margin:0 0 16px 0;">🔮 Purchase Signals ({len(high_signals)} high-confidence)</h2>
    """

    if high_signals:
        for sig in high_signals[:5]:
            score = sig.get("confidence_score", 0) or 0
            color = "#10B981" if score >= 80 else "#E67E22" if score >= 60 else "#888"
            html += f"""
      <div style="border-bottom:1px solid #1e2a3a;padding:10px 0;">
        <div style="display:flex;justify-content:space-between;">
          <span style="color:#e0e0e0;font-size:13px;">{(sig.get('tweet_text', '') or '')[:100]}</span>
        </div>
        <div style="margin-top:4px;">
          <span style="color:{color};font-size:12px;font-weight:700;">{score}% confidence</span>
          <span style="color:#555;font-size:11px;margin-left:8px;">@{sig.get('author_username', 'unknown')}</span>
        </div>
      </div>"""
    else:
        html += '<p style="color:#555;font-size:13px;margin:0;">No high-confidence signals in the last 24 hours. All quiet.</p>'

    html += "</div>"

    # Section 2: Watchlist Activity
    html += f"""
    <div style="background:#111827;border:1px solid #1e2a3a;border-radius:12px;padding:20px;margin-bottom:16px;">
      <h2 style="color:#3B82F6;font-size:14px;text-transform:uppercase;letter-spacing:2px;margin:0 0 16px 0;">👁️ Watchlist Activity ({len(watchlist_activity)} alerts)</h2>
    """

    if watchlist_activity:
        for wa in watchlist_activity[:5]:
            html += f"""
      <div style="border-bottom:1px solid #1e2a3a;padding:8px 0;">
        <span style="color:#3B82F6;font-size:12px;font-weight:700;">{wa.get('ticker', '')}</span>
        <span style="color:#e0e0e0;font-size:12px;margin-left:8px;">{(wa.get('tweet_text', '') or '')[:80]}</span>
        <span style="color:#555;font-size:11px;display:block;margin-top:2px;">{wa.get('confidence_score', 0)}% confidence</span>
      </div>"""
    elif watchlist:
        html += f'<p style="color:#555;font-size:13px;margin:0;">No activity detected for your {len(watchlist)} watchlisted companies in the last 24 hours.</p>'
    else:
        html += '<p style="color:#555;font-size:13px;margin:0;">No watchlist set. <a href="' + DASHBOARD_URL + '/company" style="color:#E67E22;">Add companies to track →</a></p>'

    html += "</div>"

    # Section 3: New Entrants
    html += f"""
    <div style="background:#111827;border:1px solid #1e2a3a;border-radius:12px;padding:20px;margin-bottom:16px;">
      <h2 style="color:#10B981;font-size:14px;text-transform:uppercase;letter-spacing:2px;margin:0 0 16px 0;">🆕 New Treasury Entrants ({len(new_entrants)})</h2>
    """

    if new_entrants:
        for ne in new_entrants[:5]:
            html += f"""
      <div style="border-bottom:1px solid #1e2a3a;padding:8px 0;">
        <span style="color:#10B981;font-size:13px;font-weight:700;">{ne.get('company', ne.get('ticker', ''))}</span>
        <span style="color:#e0e0e0;font-size:12px;margin-left:8px;">{ne.get('ticker', '')} · {(ne.get('btc_holdings', 0) or 0):,} BTC</span>
        <span style="color:#555;font-size:11px;display:block;margin-top:2px;">First seen: {ne.get('first_seen', 'today')}</span>
      </div>"""
        if len(new_entrants) > 5:
            html += f'<p style="color:#555;font-size:12px;margin:8px 0 0 0;">+ {len(new_entrants) - 5} more new entrants</p>'
    else:
        html += '<p style="color:#555;font-size:13px;margin:0;">No new entrants detected in the last 24 hours.</p>'

    html += "</div>"

    # Section 4: Market Summary
    html += f"""
    <div style="background:#111827;border:1px solid #1e2a3a;border-radius:12px;padding:20px;margin-bottom:16px;">
      <h2 style="color:#F59E0B;font-size:14px;text-transform:uppercase;letter-spacing:2px;margin:0 0 16px 0;">📈 Market Summary</h2>
      <table style="width:100%;border-collapse:collapse;">
        <tr>
          <td style="padding:6px 0;color:#888;font-size:13px;">BTC Price</td>
          <td style="padding:6px 0;color:#fff;font-size:14px;font-weight:700;text-align:right;">${btc_price:,.0f}</td>
        </tr>
        <tr>
          <td style="padding:6px 0;color:#888;font-size:13px;">Total Entities Tracked</td>
          <td style="padding:6px 0;color:#fff;font-size:14px;font-weight:700;text-align:right;">{total_entities}</td>
        </tr>
        <tr>
          <td style="padding:6px 0;color:#888;font-size:13px;">Signals (24h)</td>
          <td style="padding:6px 0;color:#fff;font-size:14px;font-weight:700;text-align:right;">{len(signals)} total, {len(high_signals)} high-confidence</td>
        </tr>
        <tr>
          <td style="padding:6px 0;color:#888;font-size:13px;">New Entrants (24h)</td>
          <td style="padding:6px 0;color:#fff;font-size:14px;font-weight:700;text-align:right;">{len(new_entrants)}</td>
        </tr>
      </table>
    </div>
    """

    # CTA + Footer
    html += f"""
    <div style="text-align:center;margin:24px 0;">
      <a href="{DASHBOARD_URL}/dashboard" style="display:inline-block;background:linear-gradient(135deg,#E67E22,#d35400);color:white;font-weight:600;padding:12px 32px;border-radius:12px;text-decoration:none;font-size:14px;">Open Your Dashboard →</a>
    </div>

    <div style="text-align:center;margin-top:32px;padding-top:20px;border-top:1px solid #1e2a3a;">
      <p style="color:#444;font-size:11px;margin:0;">{EMAIL_FROM_NAME} · QuantEdge Risk Advisory</p>
      <p style="color:#333;font-size:10px;margin:4px 0 0 0;">You're receiving this because you're a Pro subscriber with email briefings enabled.</p>
      <p style="color:#333;font-size:10px;margin:4px 0 0 0;">Manage your preferences at <a href="{DASHBOARD_URL}/company" style="color:#E67E22;">your account settings</a>.</p>
    </div>

    </div>
    </body>
    </html>
    """

    return html


def send_email(to_email, subject, html):
    """Send email via Resend."""
    if not RESEND_API_KEY:
        logger.error("RESEND_API_KEY not configured")
        return False

    try:
        res = requests.post("https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
            json={
                "from": f"{EMAIL_FROM_NAME} <{EMAIL_FROM}>",
                "to": [to_email],
                "subject": subject,
                "html": html,
            }, timeout=15)

        if res.ok:
            return True
        else:
            logger.error(f"Resend error for {to_email}: {res.status_code} {res.text[:100]}")
            return False
    except Exception as e:
        logger.error(f"Email send error for {to_email}: {e}")
        return False


def send_pro_briefings():
    """Send personalized briefings to all Pro subscribers. Call after scan cycle."""
    logger.info("Pro Briefing: starting...")

    subscribers = get_pro_subscribers()
    if not subscribers:
        logger.info("Pro Briefing: no eligible subscribers (plan=pro, email_briefing=true)")
        return {"sent": 0, "failed": 0}

    # Fetch shared data once
    signals = get_signals_24h()
    leaderboard = get_leaderboard()
    new_entrants = get_new_entrants_24h()
    btc_price = get_btc_price()

    logger.info(f"Pro Briefing: {len(subscribers)} subscriber(s), {len(signals)} signals, {len(new_entrants)} new entrants")

    sent = 0
    failed = 0
    date_str = datetime.now().strftime("%b %d, %Y")

    for sub in subscribers:
        try:
            html = build_personalized_briefing(sub, signals, leaderboard, new_entrants, btc_price)
            subject = f"🔶 Your Daily Intelligence — {date_str}"

            # Add personalized subject if they have rank
            ticker = sub.get("ticker", "")
            if ticker:
                rank, _ = find_subscriber_rank(leaderboard, ticker)
                if rank > 0:
                    subject = f"🔶 #{rank} — Your Daily Intelligence — {date_str}"

            if send_email(sub["email"], subject, html):
                sent += 1
                logger.info(f"  ✅ Sent to {sub.get('name', sub['email'])}")
            else:
                failed += 1
                logger.error(f"  ❌ Failed for {sub.get('name', sub['email'])}")
        except Exception as e:
            failed += 1
            logger.error(f"  ❌ Error for {sub.get('name', sub['email'])}: {e}")

    logger.info(f"Pro Briefing: {sent} sent, {failed} failed")
    return {"sent": sent, "failed": failed}


if __name__ == "__main__":
    logger.info("Pro Briefing — manual run...")
    result = send_pro_briefings()
    print(f"\nSent: {result['sent']}, Failed: {result['failed']}")
