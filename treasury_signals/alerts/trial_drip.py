"""
trial_drip.py — 7-day trial conversion email sequence.
-------------------------------------------------------

When a user starts a Pro trial via Stripe Checkout, we send them 5 emails
over the trial window to walk them into the value:

    Day 0 — welcome           : 3-step setup checklist
    Day 1 — first_brief        : prove daily value (yesterday's snapshot)
    Day 3 — calculator         : push the most-missed feature
    Day 5 — competitors        : real competitor activity since trial start
    Day 6 — endreminder        : honest "trial ends tomorrow" note

Industry baseline: a sequence like this lifts trial → paid conversion
25-40% over the do-nothing baseline. No dark patterns — the day-6 email
explicitly says "cancel anytime, we'd rather you stop than churn unhappy".

Cron pattern (matches send_daily_email):
    send_due_trial_emails() runs after the daily briefing once per day
    after 7am ET. It picks subscribers in their trial window AND today's
    day-code is not already in trial_emails_sent_json.

Trigger:
    Stripe webhook on checkout.session.completed sets trial_started_at
    when subscription has trial_period_days > 0. See
    treasury-dashboard/src/app/api/webhook/route.js.

Suppression rules (in addition to day-code dedupe):
    - email_briefing must be true (respects user's email preference)
    - is_active must be true (no canceled subs)
    - plan must be 'pro' (not yet upgraded to team/enterprise mid-trial)
    - trial_started_at must be in the last 7 days

Failure handling: per-subscriber try/except so one bad send doesn't
block the rest. We mark the day-code as sent ONLY on Resend success, so
a failed send retries on the next cron run (next day).
"""

from __future__ import annotations

import os
import json
from datetime import datetime, timedelta
from typing import Optional

import requests
from dotenv import load_dotenv
from supabase import create_client

from treasury_signals.logger import get_logger

logger = get_logger(__name__)

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
EMAIL_FROM_NAME = os.getenv("EMAIL_FROM_NAME", "Treasury Signal Intelligence")
EMAIL_FROM_ADDRESS = os.getenv("EMAIL_FROM_ADDRESS", "briefing@quantedgeriskadvisory.com")
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "https://app.quantedgeriskadvisory.com")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

# ── Schedule definition ──────────────────────────────────────────────────
# (day_offset, code) — day_offset is integer days since trial_started_at.
# Codes are stable identifiers stored in trial_emails_sent_json so we can
# rename templates / change subjects without losing dedupe.
SCHEDULE = [
    (0, "welcome"),
    (1, "day1_brief"),
    (3, "day3_calculator"),
    (5, "day5_competitors"),
    (6, "day6_endreminder"),
]

TRIAL_DAYS = 7  # matches the Stripe trial_period_days


# ─────────────────────────── shared HTML chrome ──────────────────────────


def _wrap(body_html: str, *, preheader: str = "") -> str:
    """Common email shell — brand strip, header, body, footer.

    Inline styles only (email clients strip <style>). Same brand alignment
    as email_briefing.py — #0EA5E9 primary, dark surface, TSI badge.
    """
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#04070d;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
  <div style="display:none;font-size:1px;color:#04070d;line-height:1px;max-height:0;max-width:0;opacity:0;overflow:hidden;">
    {preheader}
  </div>
  <table width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;margin:40px auto;background:#0a0e17;border:1px solid #1e2a3a;border-radius:16px;overflow:hidden;">
    <tr><td style="height:4px;background:linear-gradient(90deg,#0EA5E9 0%,#38BDF8 50%,#0EA5E9 100%);"></td></tr>
    <tr><td style="padding:32px 36px 16px;">
      <table cellpadding="0" cellspacing="0" style="display:inline-table;margin-bottom:18px;"><tr><td style="background:#0EA5E9;border-radius:8px;padding:6px 10px;">
        <span style="color:#ffffff;font-size:11px;font-weight:800;letter-spacing:0.18em;">TSI</span>
      </td></tr></table>
      {body_html}
    </td></tr>
    <tr><td style="background:#0c1220;border-top:1px solid #1e2a3a;padding:14px 36px;">
      <p style="color:#4b5563;font-size:10px;margin:0;line-height:1.5;">
        Treasury Signal Intelligence · Quantedge Risk Advisory · You're getting this as part of your 7-day Pro trial.
      </p>
    </td></tr>
  </table>
</body></html>"""


def _button(label: str, href: str) -> str:
    return (
        f'<a href="{href}" style="display:inline-block;background:#0EA5E9;color:#ffffff;'
        f'text-decoration:none;font-weight:600;font-size:14px;padding:12px 28px;'
        f'border-radius:12px;">{label}</a>'
    )


def _h1(text: str) -> str:
    return (
        f'<h1 style="color:#f9fafb;font-size:22px;font-weight:700;letter-spacing:-0.02em;'
        f'margin:0 0 12px;">{text}</h1>'
    )


def _p(text: str, *, color: str = "#9ca3af") -> str:
    return f'<p style="color:{color};font-size:14px;line-height:1.6;margin:0 0 16px;">{text}</p>'


def _kicker(text: str) -> str:
    return (
        f'<p style="color:#0EA5E9;font-size:10px;font-weight:700;letter-spacing:0.18em;'
        f'text-transform:uppercase;margin:0 0 8px;">{text}</p>'
    )


def _first_name(sub: dict) -> str:
    name = (sub.get("name") or "").strip()
    if name:
        return name.split(" ")[0]
    email = (sub.get("email") or "").strip()
    return email.split("@")[0] if email else "there"


# ─────────────────────────── individual templates ────────────────────────


def _render_welcome(sub: dict) -> tuple[str, str]:
    """Day 0 — Welcome + 3-step setup checklist."""
    first = _first_name(sub)
    has_company = bool((sub.get("company_name") or "").strip())
    has_ticker = bool((sub.get("ticker") or "").strip())

    body = f"""
    {_kicker("Welcome to Pro · Day 1 of 7")}
    {_h1(f"Welcome to TSI Pro, {first}.")}
    {_p("You've unlocked daily personalized briefings, real-time competitor alerts, board-ready reports, and the full leaderboard. To get the most out of your 7-day trial, do these three things now — each takes under a minute:")}

    <table width="100%" cellpadding="0" cellspacing="0" style="background:#111827;border:1px solid #1e2a3a;border-radius:12px;padding:8px 0;margin-bottom:24px;">
      <tr><td style="padding:10px 18px;border-bottom:1px solid #1e2a3a;">
        <p style="color:#e5e7eb;font-size:13px;margin:0;line-height:1.5;">
          <strong style="color:#0EA5E9;">1.</strong>
          {"<span style='color:#10b981;'>✓</span> " if has_ticker else ""}
          Set your company's ticker so the dashboard ranks you against peers.
        </p>
      </td></tr>
      <tr><td style="padding:10px 18px;border-bottom:1px solid #1e2a3a;">
        <p style="color:#e5e7eb;font-size:13px;margin:0;line-height:1.5;">
          <strong style="color:#0EA5E9;">2.</strong>
          {"<span style='color:#10b981;'>✓</span> " if has_company else ""}
          Add 5 entities to your watchlist — they'll show up in tomorrow's briefing.
        </p>
      </td></tr>
      <tr><td style="padding:10px 18px;">
        <p style="color:#e5e7eb;font-size:13px;margin:0;line-height:1.5;">
          <strong style="color:#0EA5E9;">3.</strong> Open the dashboard and read your verdict — it's the synthesized "what to do today" from all the data we ingested overnight.
        </p>
      </td></tr>
    </table>

    {_button("Open dashboard", f"{DASHBOARD_URL}/dashboard")}
    """
    return ("Welcome to TSI Pro — your 5-minute setup", _wrap(body, preheader="Set your ticker, add a watchlist, and open today's brief."))


def _render_day1_brief(sub: dict) -> tuple[str, str]:
    """Day 1 — prove the daily value with a snapshot of what your dashboard caught."""
    first = _first_name(sub)
    body = f"""
    {_kicker("Day 2 of 7")}
    {_h1(f"Your first brief landed this morning, {first}.")}
    {_p("Every Pro user gets a personalized intelligence brief at 7am ET — synthesized from regulatory filings, on-chain data, and competitor activity ingested overnight.")}
    {_p("Today's brief covers: <strong style=\"color:#e5e7eb;\">action signal, risk dashboard, what changed overnight, peer activity, week ahead</strong> — and the watchlist activity for any entities you're tracking.")}
    {_p("Don't see it in your inbox? Check spam — and add briefing@quantedgeriskadvisory.com to your contacts so it never gets caught again.")}

    {_button("View today's brief", f"{DASHBOARD_URL}/dashboard")}

    <p style="color:#4b5563;font-size:11px;margin:20px 0 0;line-height:1.5;">
      <em>Tomorrow's email walks you through the most-missed Pro feature.</em>
    </p>
    """
    return (
        f"Your first daily brief is ready, {first}",
        _wrap(body, preheader="Synthesized intel — action signal, risk, peer activity, watchlist."),
    )


def _render_day3_calculator(sub: dict) -> tuple[str, str]:
    """Day 3 — surface the What-If Calculator (most-missed Pro tool)."""
    first = _first_name(sub)
    holdings = float(sub.get("btc_holdings") or 0)
    suggested_buy = max(100, round(holdings * 0.5)) if holdings > 0 else 1000
    company = (sub.get("company_name") or "your company").strip()

    body = f"""
    {_kicker("Day 4 of 7 · Most users discover this on day 3")}
    {_h1(f"What if {company} bought {suggested_buy:,} BTC tomorrow?")}
    {_p(f"The What-If Calculator models a hypothetical purchase against your current position and the live leaderboard. Most CFOs run their first scenario by day 3 of trial — usually right before a board meeting.")}
    {_p("In one click you'll see:")}

    <ul style="color:#9ca3af;font-size:14px;line-height:1.8;margin:0 0 24px 0;padding-left:18px;">
      <li>Your new leaderboard rank after the purchase</li>
      <li>Companies you'd overtake</li>
      <li>How many BTC to reach the next position above you</li>
      <li>P&amp;L scenarios across bear / current / bull / moon prices</li>
      <li>Break-even price post-purchase</li>
    </ul>

    {_button(f"Model {suggested_buy:,} BTC scenario", f"{DASHBOARD_URL}/calculator")}

    <p style="color:#4b5563;font-size:11px;margin:20px 0 0;line-height:1.5;">
      <em>Not the right number? Open the calculator and try your own.</em>
    </p>
    """
    return (
        "Most Pro users discover this on day 3",
        _wrap(body, preheader="Model a hypothetical purchase and see your new rank in one click."),
    )


def _render_day5_competitors(sub: dict, recent_purchases: list[dict]) -> tuple[str, str]:
    """Day 5 — real competitor activity recap, value demonstration."""
    first = _first_name(sub)

    if recent_purchases:
        rows = []
        for p in recent_purchases[:3]:
            company = (p.get("company") or "").replace(" (MicroStrategy)", "")
            ticker = p.get("ticker") or ""
            btc = int(p.get("btc_amount") or 0)
            usd = float(p.get("usd_amount") or 0)
            usd_str = f" · ${usd / 1_000_000:,.0f}M" if usd > 0 else ""
            date = p.get("filing_date") or ""
            rows.append(
                f'<tr><td style="padding:10px 18px;border-bottom:1px solid #1e2a3a;">'
                f'<p style="color:#e5e7eb;font-size:13px;margin:0;line-height:1.5;">'
                f'<strong>{company}</strong> bought {btc:,} BTC{usd_str}'
                f'<br><span style="color:#6b7280;font-size:11px;">{ticker} · {date}</span>'
                f'</p></td></tr>'
            )
        # Strip the trailing border on the last row
        rows[-1] = rows[-1].replace("border-bottom:1px solid #1e2a3a;", "")
        activity_block = (
            '<table width="100%" cellpadding="0" cellspacing="0" '
            'style="background:#111827;border:1px solid #1e2a3a;border-radius:12px;'
            'padding:8px 0;margin-bottom:24px;">'
            + "".join(rows)
            + "</table>"
        )
    else:
        activity_block = _p(
            "It was a quiet week for new purchases — but the dashboard still tracked "
            "regulatory activity, signal updates, and price movement. The next purchase "
            "wave is usually within 5 trading days of any major BTC price swing.",
            color="#9ca3af",
        )

    body = f"""
    {_kicker("Day 6 of 7")}
    {_h1("Competitor activity since you started your trial")}
    {_p("Here's what real corporate Bitcoin treasuries did over the last few days — every one of these would have triggered a real-time alert in your inbox / Telegram / Slack on Pro:")}

    {activity_block}

    {_p("Want this for your team? Pro stays at $19/mo after your trial ends tomorrow. Team adds 5 seats + Slack integration at $99/mo.")}

    {_button("Open competitive intel", f"{DASHBOARD_URL}/competitive")}
    """
    return (
        "Your competitors made these moves this week",
        _wrap(body, preheader="Real purchases. Pro alerts you within 15 minutes of each filing."),
    )


def _render_day6_endreminder(sub: dict) -> tuple[str, str]:
    """Day 6 — honest trial-end reminder, no dark patterns."""
    first = _first_name(sub)

    body = f"""
    {_kicker("Day 7 of 7 · Honest reminder")}
    {_h1("Your TSI Pro trial ends tomorrow.")}
    {_p(f"Heads up, {first} — your 7-day Pro trial expires in roughly 24 hours. If you don't want to continue, cancel via the link below — we'd rather you stop than churn unhappy.")}
    {_p("If you stay on Pro, Stripe will charge $19/month tomorrow. You can cancel anytime from the Company page.")}

    <p style="color:#e5e7eb;font-size:13px;font-weight:600;margin:24px 0 8px;">What you keep on Pro:</p>
    <ul style="color:#9ca3af;font-size:13px;line-height:1.8;margin:0 0 24px 0;padding-left:18px;">
      <li>Daily personalized briefings (instead of weekly summary)</li>
      <li>Real-time alerts via email + Telegram</li>
      <li>Board reports & shareholder comms templates</li>
      <li>Competitive intel + NAV premium analysis</li>
      <li>What-If calculator + Peer benchmark</li>
      <li>Full leaderboard (not delayed top 10)</li>
      <li>API access</li>
    </ul>

    {_button("Manage subscription", f"{DASHBOARD_URL}/company")}

    <p style="color:#4b5563;font-size:11px;margin:20px 0 0;line-height:1.5;">
      Questions? Reply to this email or hit the support widget bottom-right.
    </p>
    """
    return (
        "Your TSI Pro trial ends tomorrow",
        _wrap(body, preheader="Cancel via Company page if you don't want to continue. No dark patterns."),
    )


# ─────────────────────────── send + dispatch ─────────────────────────────


def _send_email(to_email: str, subject: str, html: str) -> bool:
    """POST to Resend. Returns True on success, False on any failure."""
    if not RESEND_API_KEY:
        logger.warning(f"trial_drip: RESEND_API_KEY unset, skipping send to {to_email}")
        return False
    if not to_email:
        return False
    try:
        unsubscribe_url = f"{DASHBOARD_URL}/?page=unsubscribe&email={to_email}"
        res = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
            json={
                "from": f"{EMAIL_FROM_NAME} <{EMAIL_FROM_ADDRESS}>",
                "to": [to_email],
                "subject": subject,
                "html": html,
                "headers": {
                    "List-Unsubscribe": f"<{unsubscribe_url}>",
                    "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
                },
            },
            timeout=15,
        )
        if res.status_code >= 400:
            logger.warning(f"trial_drip: Resend {res.status_code} for {to_email}: {res.text[:200]}")
            return False
        return True
    except Exception as e:
        logger.warning(f"trial_drip: send threw for {to_email}: {e}")
        return False


def _due_code_for(trial_started_at: datetime, sent: list[str]) -> Optional[str]:
    """Compute which day-code (if any) is due today and not yet sent."""
    if not trial_started_at:
        return None
    days_in = (datetime.now(trial_started_at.tzinfo or None) - trial_started_at).days
    # Walk the schedule in order — return the highest day_offset that
    # has elapsed AND hasn't already been sent. (Highest, not lowest, so a
    # subscriber who somehow misses day 0 + day 1 still gets caught up to
    # the most recent eligible email rather than receiving a stale day-0
    # welcome on day 4.)
    eligible = [(off, code) for off, code in SCHEDULE if off <= days_in and code not in sent]
    if not eligible:
        return None
    eligible.sort(key=lambda x: x[0], reverse=True)
    return eligible[0][1]


def _parse_sent(raw) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw]
    if isinstance(raw, str):
        try:
            v = json.loads(raw)
            return [str(x) for x in v] if isinstance(v, list) else []
        except Exception:
            return []
    return []


def _fetch_recent_purchases_for_day5() -> list[dict]:
    """Top 3 purchases in the last 7 days — used by the day-5 competitors email."""
    if not supabase:
        return []
    try:
        cutoff = (datetime.now() - timedelta(days=7)).date().isoformat()
        res = (
            supabase.table("confirmed_purchases")
            .select("company, ticker, btc_amount, usd_amount, filing_date")
            .gte("filing_date", cutoff)
            .order("usd_amount", desc=True)
            .limit(3)
            .execute()
        )
        return res.data or []
    except Exception as e:
        logger.debug(f"trial_drip: recent purchases lookup failed: {e}")
        return []


def send_due_trial_emails() -> int:
    """Cron entry point. Returns count of emails sent."""
    if not supabase:
        logger.warning("trial_drip: supabase client unconfigured, skipping")
        return 0

    try:
        # Filter to trial-eligible subscribers — index on trial_started_at
        # makes this fast even at scale.
        cutoff = (datetime.now() - timedelta(days=TRIAL_DAYS + 1)).isoformat()
        res = (
            supabase.table("subscribers")
            .select(
                "subscriber_id, email, name, company_name, ticker, "
                "btc_holdings, plan, is_active, email_briefing, "
                "trial_started_at, trial_emails_sent_json"
            )
            .gte("trial_started_at", cutoff)
            .execute()
        )
        candidates = res.data or []
    except Exception as e:
        logger.error(f"trial_drip: candidate fetch failed: {e}")
        return 0

    if not candidates:
        return 0

    sent_count = 0
    recent_purchases_cache = None  # lazy — only fetch if we have a day-5 candidate

    for sub in candidates:
        # Suppression rules
        if not sub.get("email_briefing"):
            continue
        if not sub.get("is_active"):
            continue
        if sub.get("plan") != "pro":
            # User upgraded to team/enterprise mid-trial, or downgraded — skip
            continue
        if not sub.get("email"):
            continue

        # Parse trial_started_at (Supabase returns ISO string)
        raw_started = sub.get("trial_started_at")
        if not raw_started:
            continue
        try:
            started_at = datetime.fromisoformat(raw_started.replace("Z", "+00:00"))
        except Exception:
            logger.debug(f"trial_drip: bad trial_started_at for {sub.get('email')}: {raw_started}")
            continue

        sent = _parse_sent(sub.get("trial_emails_sent_json"))
        code = _due_code_for(started_at, sent)
        if not code:
            continue

        # Render template based on the day-code
        try:
            if code == "welcome":
                subject, html = _render_welcome(sub)
            elif code == "day1_brief":
                subject, html = _render_day1_brief(sub)
            elif code == "day3_calculator":
                subject, html = _render_day3_calculator(sub)
            elif code == "day5_competitors":
                if recent_purchases_cache is None:
                    recent_purchases_cache = _fetch_recent_purchases_for_day5()
                subject, html = _render_day5_competitors(sub, recent_purchases_cache)
            elif code == "day6_endreminder":
                subject, html = _render_day6_endreminder(sub)
            else:
                logger.warning(f"trial_drip: unknown day code {code}, skipping")
                continue
        except Exception as e:
            logger.error(f"trial_drip: render failed for {sub.get('email')} / {code}: {e}", exc_info=True)
            continue

        # Send + record on success only (failed sends retry tomorrow)
        ok = _send_email(sub["email"], subject, html)
        if not ok:
            continue

        try:
            new_sent = sent + [code]
            supabase.table("subscribers").update(
                {"trial_emails_sent_json": new_sent}
            ).eq("subscriber_id", sub["subscriber_id"]).execute()
            logger.info(f"trial_drip: sent {code} to {sub['email']}")
            sent_count += 1
        except Exception as e:
            # If the DB update fails after a successful send, we'd risk
            # double-sending tomorrow. Log loudly so it surfaces in Sentry.
            logger.error(
                f"trial_drip: SENT but failed to mark sent for {sub['email']} / {code}: {e}",
                exc_info=True,
            )

    if sent_count > 0:
        logger.info(f"trial_drip: {sent_count} email(s) sent this run")
    return sent_count


if __name__ == "__main__":
    print(f"trial_drip: dispatching due emails")
    n = send_due_trial_emails()
    print(f"trial_drip: {n} sent")
