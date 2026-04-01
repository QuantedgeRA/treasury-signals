"""
pro_briefing.py — Bloomberg-Quality Daily Email Briefing
=========================================================
Sends personalized daily intelligence to Pro subscribers.
Styled to match the TSI steel blue brand (#0EA5E9).

Usage:
    from pro_briefing import send_pro_briefings
    send_pro_briefings()  # Called daily at 7am ET from main.py
"""

import os
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from supabase import create_client
from logger import get_logger

logger = get_logger(__name__)
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "https://app.quantedgeriskadvisory.com")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def _get_market_data():
    """Fetch all data needed for the briefing."""
    try:
        # Companies
        comp_res = supabase.table("treasury_companies").select(
            "company, ticker, btc_holdings, entity_type, is_government, sector, data_source, source_updated_at"
        ).gt("btc_holdings", 0).order("btc_holdings", ascending=False).execute()
        companies = comp_res.data or []

        # BTC price from latest snapshot
        snap_res = supabase.table("leaderboard_snapshots").select(
            "btc_price, snapshot_date"
        ).order("snapshot_date", ascending=False).limit(1).execute()
        btc_price = float(snap_res.data[0]["btc_price"]) if snap_res.data else 0

        # Recent purchases (last 48h)
        cutoff = (datetime.now() - timedelta(hours=48)).isoformat()
        purch_res = supabase.table("confirmed_purchases").select("*").gte(
            "filing_date", cutoff[:10]
        ).order("filing_date", ascending=False).limit(10).execute()
        purchases = purch_res.data or []

        # Recent signals (last 24h, score >= 60)
        sig_cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
        sig_res = supabase.table("tweets").select(
            "author_username, company, confidence_score, tweet_text, created_at"
        ).gte("created_at", sig_cutoff).gte("confidence_score", 60).order(
            "confidence_score", ascending=False
        ).limit(5).execute()
        signals = sig_res.data or []

        # Narrative
        nar_res = supabase.table("narratives").select("content").eq(
            "narrative_type", "daily"
        ).order("generated_at", ascending=False).limit(1).execute()
        narrative = nar_res.data[0]["content"] if nar_res.data else ""

        # Velocity data (new entrants last 7 days)
        vel_cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        # Check if velocity snapshots exist for new entrant detection
        new_entrants = []

        return {
            "companies": companies,
            "btc_price": btc_price,
            "purchases": purchases,
            "signals": signals,
            "narrative": narrative,
            "new_entrants": new_entrants,
        }
    except Exception as e:
        logger.debug(f"Market data fetch error: {e}")
        return None


def _get_subscriber_position(subscriber, companies, btc_price):
    """Calculate subscriber's position metrics."""
    ticker = (subscriber.get("ticker") or "").upper().strip()
    btc = float(subscriber.get("btc_holdings") or 0)
    cost = float(subscriber.get("total_invested_usd") or 0)
    avg_price = float(subscriber.get("avg_purchase_price") or 0)

    # Find in leaderboard
    corporate = [c for c in companies if not c.get("is_government")]
    rank = 0
    for i, c in enumerate(corporate):
        if c.get("ticker", "").upper() == ticker:
            rank = i + 1
            btc = max(btc, float(c.get("btc_holdings") or 0))
            break

    value = btc * btc_price
    pnl_pct = ((btc_price - avg_price) / avg_price * 100) if avg_price > 0 else 0
    total_btc = sum(float(c.get("btc_holdings") or 0) for c in corporate)
    market_share = (btc / total_btc * 100) if total_btc > 0 else 0

    # Gap to next rank
    gap_above = 0
    if rank > 1:
        above = corporate[rank - 2]
        gap_above = float(above.get("btc_holdings") or 0) - btc

    return {
        "rank": rank,
        "btc": btc,
        "value": value,
        "pnl_pct": pnl_pct,
        "market_share": market_share,
        "gap_above": gap_above,
        "total_entities": len(companies),
        "total_corporate": len(corporate),
    }


def _build_email_html(subscriber, market, position):
    """Build the Bloomberg-quality HTML email."""
    name = subscriber.get("name", "").split(" ")[0] or "there"
    company = subscriber.get("company_name") or ""
    ticker = subscriber.get("ticker") or ""
    user_type = subscriber.get("user_type") or "entity"
    btc_price = market["btc_price"]
    today = datetime.now().strftime("%A, %B %d, %Y")
    purchases = market["purchases"]
    signals = market["signals"]
    narrative = market["narrative"]

    # Format helpers
    def fmt_btc(v):
        return f"{v:,.0f}" if v >= 1 else f"{v:.4f}"

    def fmt_usd(v):
        if v >= 1e9:
            return f"${v/1e9:.1f}B"
        if v >= 1e6:
            return f"${v/1e6:.1f}M"
        return f"${v:,.0f}"

    # Position section (entity users only)
    position_html = ""
    if user_type == "entity" and position["rank"] > 0:
        pnl_color = "#10B981" if position["pnl_pct"] >= 0 else "#EF4444"
        pnl_sign = "+" if position["pnl_pct"] >= 0 else ""
        position_html = f"""
        <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:24px;">
          <tr>
            <td style="background:#0a0e17;border:1px solid rgba(14,165,233,0.15);border-radius:12px;padding:20px;">
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr><td style="color:rgba(255,255,255,0.25);font-size:10px;text-transform:uppercase;letter-spacing:0.1em;font-weight:600;padding-bottom:12px;">Your Position — {company}</td></tr>
                <tr>
                  <td>
                    <table width="100%" cellpadding="0" cellspacing="0">
                      <tr>
                        <td width="25%" style="text-align:center;padding:8px 0;">
                          <div style="color:rgba(255,255,255,0.2);font-size:10px;text-transform:uppercase;letter-spacing:0.05em;">Rank</div>
                          <div style="color:#0EA5E9;font-size:24px;font-weight:700;font-family:'JetBrains Mono',monospace;">#{position['rank']}</div>
                          <div style="color:rgba(255,255,255,0.15);font-size:10px;">of {position['total_corporate']}</div>
                        </td>
                        <td width="25%" style="text-align:center;padding:8px 0;">
                          <div style="color:rgba(255,255,255,0.2);font-size:10px;text-transform:uppercase;letter-spacing:0.05em;">Holdings</div>
                          <div style="color:white;font-size:24px;font-weight:700;font-family:'JetBrains Mono',monospace;">{fmt_btc(position['btc'])}</div>
                          <div style="color:rgba(255,255,255,0.15);font-size:10px;">BTC</div>
                        </td>
                        <td width="25%" style="text-align:center;padding:8px 0;">
                          <div style="color:rgba(255,255,255,0.2);font-size:10px;text-transform:uppercase;letter-spacing:0.05em;">Value</div>
                          <div style="color:white;font-size:24px;font-weight:700;font-family:'JetBrains Mono',monospace;">{fmt_usd(position['value'])}</div>
                        </td>
                        <td width="25%" style="text-align:center;padding:8px 0;">
                          <div style="color:rgba(255,255,255,0.2);font-size:10px;text-transform:uppercase;letter-spacing:0.05em;">P&L</div>
                          <div style="color:{pnl_color};font-size:24px;font-weight:700;font-family:'JetBrains Mono',monospace;">{pnl_sign}{position['pnl_pct']:.1f}%</div>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
                {"<tr><td style='padding-top:12px;border-top:1px solid rgba(255,255,255,0.04);'><span style='color:rgba(255,255,255,0.2);font-size:11px;'>Gap to #" + str(position['rank']-1) + ": </span><span style='color:#0EA5E9;font-family:monospace;font-size:11px;font-weight:600;'>" + fmt_btc(position['gap_above']) + " BTC (" + fmt_usd(position['gap_above'] * btc_price) + ")</span></td></tr>" if position['gap_above'] > 0 and position['rank'] > 1 else ""}
              </table>
            </td>
          </tr>
        </table>"""

    # Purchases section
    purchases_html = ""
    if purchases:
        rows = ""
        for p in purchases[:5]:
            amt = float(p.get("btc_amount") or 0)
            usd = float(p.get("usd_amount") or 0)
            rows += f"""
            <tr style="border-bottom:1px solid rgba(255,255,255,0.03);">
              <td style="padding:10px 0;color:white;font-size:13px;">{(p.get('company') or '').replace(' (MicroStrategy)', '')[:25]}</td>
              <td style="padding:10px 0;color:white;font-family:'JetBrains Mono',monospace;font-size:13px;text-align:right;">{amt:,.0f} BTC</td>
              <td style="padding:10px 0;color:rgba(255,255,255,0.25);font-family:'JetBrains Mono',monospace;font-size:11px;text-align:right;">{fmt_usd(usd) if usd > 0 else '—'}</td>
              <td style="padding:10px 0;color:rgba(255,255,255,0.15);font-size:11px;text-align:right;">{p.get('filing_date', '')[:10]}</td>
            </tr>"""

        purchases_html = f"""
        <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:24px;">
          <tr><td style="color:rgba(255,255,255,0.25);font-size:10px;text-transform:uppercase;letter-spacing:0.1em;font-weight:600;padding-bottom:8px;">Recent Confirmed Purchases</td></tr>
          <tr><td>
            <table width="100%" cellpadding="0" cellspacing="0" style="background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);border-radius:10px;padding:4px 16px;">
              <tr style="border-bottom:1px solid rgba(255,255,255,0.06);">
                <td style="padding:8px 0;color:rgba(255,255,255,0.15);font-size:9px;text-transform:uppercase;letter-spacing:0.1em;">Company</td>
                <td style="padding:8px 0;color:rgba(255,255,255,0.15);font-size:9px;text-transform:uppercase;letter-spacing:0.1em;text-align:right;">Amount</td>
                <td style="padding:8px 0;color:rgba(255,255,255,0.15);font-size:9px;text-transform:uppercase;letter-spacing:0.1em;text-align:right;">USD</td>
                <td style="padding:8px 0;color:rgba(255,255,255,0.15);font-size:9px;text-transform:uppercase;letter-spacing:0.1em;text-align:right;">Date</td>
              </tr>
              {rows}
            </table>
          </td></tr>
        </table>"""

    # Signals section
    signals_html = ""
    if signals:
        sig_rows = ""
        for s in signals[:4]:
            score = s.get("confidence_score") or 0
            score_color = "#0EA5E9" if score >= 70 else "rgba(255,255,255,0.3)"
            sig_rows += f"""
            <tr style="border-bottom:1px solid rgba(255,255,255,0.03);">
              <td style="padding:8px 0;"><span style="background:{'rgba(14,165,233,0.1)' if score >= 70 else 'rgba(255,255,255,0.03)'};color:{score_color};font-family:'JetBrains Mono',monospace;font-size:10px;font-weight:700;padding:3px 8px;border-radius:6px;">{score}</span></td>
              <td style="padding:8px 0;color:white;font-size:12px;">@{s.get('author_username', '?')}</td>
              <td style="padding:8px 0;color:rgba(255,255,255,0.25);font-size:11px;max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{(s.get('tweet_text') or '')[:80]}</td>
            </tr>"""

        signals_html = f"""
        <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:24px;">
          <tr><td style="color:rgba(255,255,255,0.25);font-size:10px;text-transform:uppercase;letter-spacing:0.1em;font-weight:600;padding-bottom:8px;">Active Signals (24h)</td></tr>
          <tr><td>
            <table width="100%" cellpadding="0" cellspacing="0" style="background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);border-radius:10px;padding:4px 16px;">
              {sig_rows}
            </table>
          </td></tr>
        </table>"""

    # Narrative
    narrative_html = ""
    if narrative:
        narrative_html = f"""
        <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:24px;">
          <tr><td style="color:rgba(255,255,255,0.25);font-size:10px;text-transform:uppercase;letter-spacing:0.1em;font-weight:600;padding-bottom:8px;">AI Market Intelligence</td></tr>
          <tr><td style="background:rgba(14,165,233,0.04);border:1px solid rgba(14,165,233,0.1);border-radius:10px;padding:16px;">
            <p style="color:rgba(255,255,255,0.45);font-size:13px;line-height:1.7;margin:0;">{narrative[:500]}</p>
            <p style="color:rgba(255,255,255,0.1);font-size:10px;margin:8px 0 0;"><span style="display:inline-block;width:6px;height:6px;background:#0EA5E9;border-radius:50%;margin-right:4px;"></span> AI-generated from multi-signal correlation</p>
          </td></tr>
        </table>"""

    # Full email
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{{margin:0;padding:0;background:#04070d;font-family:'Segoe UI','Helvetica Neue',Arial,sans-serif;-webkit-text-size-adjust:100%;}}table{{border-collapse:collapse;}}td{{vertical-align:top;}}</style>
</head><body style="background:#04070d;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#04070d;">
<tr><td align="center" style="padding:0 16px;">
<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">

  <!-- Header -->
  <tr><td style="padding:32px 0 24px;">
    <table width="100%" cellpadding="0" cellspacing="0">
      <tr>
        <td>
          <table cellpadding="0" cellspacing="0"><tr>
            <td style="background:linear-gradient(135deg,#0EA5E9,#0284C7);border-radius:8px;width:32px;height:32px;text-align:center;vertical-align:middle;">
              <span style="color:white;font-weight:700;font-size:14px;">TSI</span>
            </td>
            <td style="padding-left:10px;">
              <span style="color:white;font-weight:700;font-size:14px;">Treasury Signal Intelligence</span>
            </td>
          </tr></table>
        </td>
        <td style="text-align:right;">
          <span style="color:rgba(255,255,255,0.15);font-size:11px;">{today}</span>
        </td>
      </tr>
    </table>
  </td></tr>

  <!-- Divider -->
  <tr><td style="height:1px;background:rgba(255,255,255,0.04);"></td></tr>

  <!-- BTC Price Bar -->
  <tr><td style="padding:16px 0 24px;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);border-radius:10px;padding:12px 20px;">
      <tr>
        <td><span style="color:rgba(255,255,255,0.2);font-size:10px;text-transform:uppercase;letter-spacing:0.1em;">Bitcoin</span></td>
        <td style="text-align:right;">
          <span style="color:white;font-family:'JetBrains Mono',monospace;font-size:18px;font-weight:700;">${btc_price:,.0f}</span>
          <span style="display:inline-block;width:6px;height:6px;background:#10B981;border-radius:50%;margin-left:6px;"></span>
        </td>
      </tr>
      <tr>
        <td colspan="2" style="padding-top:8px;">
          <span style="color:rgba(255,255,255,0.15);font-size:11px;">{position['total_entities']} entities tracked · {position['total_corporate']} corporate · 17 regulators scanned</span>
        </td>
      </tr>
    </table>
  </td></tr>

  <!-- Greeting -->
  <tr><td style="padding-bottom:24px;">
    <h1 style="color:white;font-size:20px;font-weight:700;margin:0 0 4px;">Good morning, {name}</h1>
    <p style="color:rgba(255,255,255,0.25);font-size:13px;margin:0;">Here's your personalized Bitcoin treasury intelligence for today.</p>
  </td></tr>

  {position_html}
  {narrative_html}
  {purchases_html}
  {signals_html}

  <!-- CTA -->
  <tr><td style="padding:8px 0 32px;text-align:center;">
    <a href="{DASHBOARD_URL}/dashboard" style="display:inline-block;background:linear-gradient(135deg,#0EA5E9,#0284C7);color:white;font-weight:600;padding:12px 32px;border-radius:10px;text-decoration:none;font-size:14px;">Open Dashboard</a>
  </td></tr>

  <!-- Divider -->
  <tr><td style="height:1px;background:rgba(255,255,255,0.04);"></td></tr>

  <!-- Footer -->
  <tr><td style="padding:24px 0;">
    <table width="100%" cellpadding="0" cellspacing="0">
      <tr>
        <td><span style="color:rgba(255,255,255,0.1);font-size:10px;">Treasury Signal Intelligence by QuantEdge Risk Advisory</span></td>
        <td style="text-align:right;"><span style="color:rgba(255,255,255,0.1);font-size:10px;">Data sourced from SEC EDGAR, 17+ regulators, blockchain</span></td>
      </tr>
      <tr>
        <td colspan="2" style="padding-top:8px;">
          <span style="color:rgba(255,255,255,0.08);font-size:10px;">You're receiving this because you're a Pro subscriber. <a href="{DASHBOARD_URL}/company" style="color:rgba(14,165,233,0.3);text-decoration:none;">Manage preferences</a></span>
        </td>
      </tr>
    </table>
  </td></tr>

</table>
</td></tr></table>
</body></html>"""

    return html


def send_pro_briefings():
    """Send personalized daily briefing to all Pro subscribers with email_briefing enabled."""
    logger.info("Pro briefing: generating daily intelligence...")

    # Fetch market data
    market = _get_market_data()
    if not market:
        logger.warning("Pro briefing: could not fetch market data")
        return

    # Fetch Pro subscribers with briefing enabled
    try:
        res = supabase.table("subscribers").select("*").eq("plan", "pro").eq(
            "email_briefing", True
        ).eq("is_active", True).execute()
        subscribers = res.data or []
    except Exception as e:
        logger.debug(f"Pro briefing: subscriber fetch error: {e}")
        return

    if not subscribers:
        logger.info("Pro briefing: no subscribers with email_briefing enabled")
        return

    sent = 0
    for sub in subscribers:
        try:
            position = _get_subscriber_position(sub, market["companies"], market["btc_price"])
            html = _build_email_html(sub, market, position)

            # Send via Resend
            import requests
            resp = requests.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": "Treasury Signal Intelligence <briefing@quantedgeriskadvisory.com>",
                    "to": [sub["email"]],
                    "subject": f"TSI Daily Brief — BTC ${market['btc_price']:,.0f} | {len(market['purchases'])} purchases | {len(market['signals'])} signals",
                    "html": html,
                },
                timeout=15,
            )
            if resp.status_code in (200, 201):
                sent += 1
                logger.debug(f"  Briefing sent to {sub['email']}")
            else:
                logger.debug(f"  Briefing failed for {sub['email']}: {resp.status_code} {resp.text[:100]}")
        except Exception as e:
            logger.debug(f"  Briefing error for {sub.get('email', '?')}: {e}")

    logger.info(f"Pro briefing: {sent}/{len(subscribers)} emails sent")
    return {"sent": sent, "total": len(subscribers)}


if __name__ == "__main__":
    # Test: generate HTML for first Pro subscriber and save to file
    market = _get_market_data()
    if market:
        res = supabase.table("subscribers").select("*").eq("plan", "pro").limit(1).execute()
        if res.data:
            sub = res.data[0]
            pos = _get_subscriber_position(sub, market["companies"], market["btc_price"])
            html = _build_email_html(sub, market, pos)
            with open("test_briefing.html", "w") as f:
                f.write(html)
            print(f"Test briefing saved to test_briefing.html ({len(html)} bytes)")
        else:
            print("No Pro subscribers found")
    else:
        print("Could not fetch market data")
