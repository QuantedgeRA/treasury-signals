"""
divergence_digest.py — weekly Pro-tier alert surfacing source-disagreement
on subscribers' watchlist tickers.

Why this is a paid feature, not internal plumbing:
  The reconciler ([[btc_holdings_reconciler_architecture]]) silently picks
  the highest-trust source value and the customer-facing dashboard always
  shows the resolved number. But for sophisticated subscribers — hedge-fund
  analysts, treasury operators auditing their own thesis — knowing that
  sources DISAGREE about a position they care about is itself a signal.
  Source-disagreement on a treasury equity often precedes:
    • A 10-Q correction (aggregator was stale)
    • An undisclosed sale (aggregators haven't picked up the divestiture)
    • A merger/rename event (entity has multiple identities in flight)

This module sends one weekly digest per Pro+ subscriber with a watchlist,
filtered to only their tickers. Subscribers without a watchlist get
nothing — the digest is opt-in via watchlist configuration. Free-tier
subscribers are excluded.

Designed to be invoked from a weekly cron OR from the existing morning
scan once per week. Idempotent — re-running on the same day re-sends
(intentional: the cron should run once weekly, not multiple times daily).

Delivery: email via Resend (matches the daily-briefing pattern in
alerts/email_briefing.py). Could be extended to Telegram for subscribers
with a chat_id, but email is the right primary channel for a weekly digest.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests
from dotenv import load_dotenv
from supabase import create_client

from treasury_signals.logger import get_logger
from treasury_signals.observability import capture_exception

logger = get_logger(__name__)
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
EMAIL_FROM = os.getenv("EMAIL_FROM_ADDRESS", "briefing@quantedgeriskadvisory.com")
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "https://treasurysignal.io")

DIGEST_LOOKBACK_DAYS = 7
ELIGIBLE_PLANS = {"pro", "team", "enterprise"}


def _fetch_eligible_subscribers() -> list[dict]:
    """Pro+ subscribers with a non-empty watchlist."""
    if not supabase:
        return []
    try:
        res = (
            supabase.table("subscribers")
            .select("id, email, name, plan, watchlist, telegram_chat_id")
            .in_("plan", list(ELIGIBLE_PLANS))
            .execute()
        )
    except Exception as e:
        logger.warning(f"divergence_digest: subscriber fetch failed: {e}")
        return []

    out = []
    for row in (res.data or []):
        wl = row.get("watchlist") or []
        # watchlist may be stored as JSON string in some legacy rows
        if isinstance(wl, str):
            try:
                import json
                wl = json.loads(wl)
            except Exception:
                wl = []
        if isinstance(wl, list) and any((t or "").strip() for t in wl):
            row["watchlist_clean"] = sorted({(t or "").strip().upper() for t in wl if t})
            out.append(row)
    return out


def _fetch_divergences_for_watchlist(watchlist: list[str], lookback_days: int = DIGEST_LOOKBACK_DAYS) -> list[dict]:
    """Open divergence alerts whose ticker is in the subscriber's watchlist."""
    if not supabase or not watchlist:
        return []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
    try:
        res = (
            supabase.table("btc_holdings_divergence_alerts")
            .select("ticker, detected_at, source_values, spread_btc, spread_pct, resolved_value, resolved_source, status")
            .in_("ticker", watchlist)
            .eq("status", "open")
            .gte("detected_at", cutoff)
            .order("spread_pct", desc=True)
            .execute()
        )
    except Exception as e:
        logger.warning(f"divergence_digest: alerts fetch failed: {e}")
        return []
    return res.data or []


def _fetch_company_names(tickers: list[str]) -> dict[str, str]:
    if not supabase or not tickers:
        return {}
    try:
        res = (
            supabase.table("treasury_companies")
            .select("ticker, company")
            .in_("ticker", tickers)
            .execute()
        )
        return {(r.get("ticker") or "").upper(): r.get("company") or r.get("ticker")
                for r in (res.data or [])}
    except Exception:
        return {}


# ─── Email rendering ──────────────────────────────────────────────────────


def _format_divergence_row_html(d: dict, company_map: dict[str, str]) -> str:
    ticker = (d.get("ticker") or "").upper()
    company = company_map.get(ticker, ticker)
    spread_pct = float(d.get("spread_pct") or 0)
    spread_btc = float(d.get("spread_btc") or 0)
    resolved_val = float(d.get("resolved_value") or 0)
    resolved_src = d.get("resolved_source") or "?"
    sv = d.get("source_values") or {}

    # Sources line: "BT: 2,469 | CG: 1,558"
    src_pairs = []
    for src, info in sv.items():
        if not isinstance(info, dict):
            continue
        try:
            val = float(info.get("value") or 0)
        except (TypeError, ValueError):
            continue
        label = {
            "bitcointreasuries": "BT",
            "coingecko": "CG",
            "edgar_8k": "8-K",
            "press_release": "Press",
            "company_irpage": "IR",
            "defillama": "DL",
            "backfill_initial": "—",
            "manual_override": "Override",
        }.get(src, src[:6])
        src_pairs.append(f"{label}: {val:,.0f}")
    sources_str = " | ".join(src_pairs)

    return (
        f'<tr>'
        f'<td style="padding:10px 12px;border-top:1px solid rgba(255,255,255,0.06);font-family:monospace;font-size:13px;color:#38bdf8;">{ticker}</td>'
        f'<td style="padding:10px 12px;border-top:1px solid rgba(255,255,255,0.06);font-size:13px;color:#cdd6e1;">{company[:38]}</td>'
        f'<td style="padding:10px 12px;border-top:1px solid rgba(255,255,255,0.06);text-align:right;font-family:monospace;font-size:13px;color:#ef4444;font-weight:600;">{spread_pct:.1f}%</td>'
        f'<td style="padding:10px 12px;border-top:1px solid rgba(255,255,255,0.06);text-align:right;font-family:monospace;font-size:12px;color:#94a3b8;">{spread_btc:,.0f} BTC</td>'
        f'<td style="padding:10px 12px;border-top:1px solid rgba(255,255,255,0.06);font-size:12px;color:#94a3b8;font-family:monospace;">{sources_str}</td>'
        f'</tr>'
    )


def _format_digest_email_html(name: str, divergences: list[dict], company_map: dict[str, str]) -> str:
    rows_html = "\n".join(_format_divergence_row_html(d, company_map) for d in divergences)
    n = len(divergences)
    headline = (
        f"{n} watchlist company showed source-disagreement this week"
        if n == 1
        else f"{n} watchlist companies showed source-disagreement this week"
    )

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Watchlist data-quality digest</title>
</head>
<body style="margin:0;padding:32px 16px;background:#0a0e1a;color:#e2e8f0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
  <div style="max-width:640px;margin:0 auto;">

    <div style="margin-bottom:24px;">
      <span style="display:inline-block;background:rgba(56,189,248,0.08);color:#38bdf8;border:1px solid rgba(56,189,248,0.15);border-radius:999px;padding:4px 12px;font-size:11px;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;">
        Watchlist · Data Quality
      </span>
    </div>

    <h1 style="font-size:24px;line-height:1.3;font-weight:700;color:#f1f5f9;margin:0 0 8px 0;">
      {headline}.
    </h1>
    <p style="font-size:14px;color:#94a3b8;line-height:1.55;margin:0 0 24px 0;">
      {("Hi " + name + ", ") if name else ""}our reconciler detected disagreement between data sources on these tickers in your watchlist
      over the last {DIGEST_LOOKBACK_DAYS} days. Source-disagreement on a treasury equity is often a leading signal of an
      undisclosed event — an aggregator going stale, a divestiture not yet propagated, or a corporate-action mid-flight.
    </p>

    <div style="background:#0f172a;border:1px solid rgba(255,255,255,0.06);border-radius:12px;overflow:hidden;margin-bottom:24px;">
      <table style="width:100%;border-collapse:collapse;">
        <thead>
          <tr style="background:rgba(255,255,255,0.02);">
            <th style="padding:10px 12px;text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:0.08em;color:#64748b;font-weight:600;">Ticker</th>
            <th style="padding:10px 12px;text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:0.08em;color:#64748b;font-weight:600;">Company</th>
            <th style="padding:10px 12px;text-align:right;font-size:10px;text-transform:uppercase;letter-spacing:0.08em;color:#64748b;font-weight:600;">Disagreement</th>
            <th style="padding:10px 12px;text-align:right;font-size:10px;text-transform:uppercase;letter-spacing:0.08em;color:#64748b;font-weight:600;">Spread</th>
            <th style="padding:10px 12px;text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:0.08em;color:#64748b;font-weight:600;">Sources</th>
          </tr>
        </thead>
        <tbody>
{rows_html}
        </tbody>
      </table>
    </div>

    <p style="font-size:13px;color:#94a3b8;line-height:1.55;margin:0 0 24px 0;">
      We resolve each disputed value to the highest-trust source automatically. The numbers you see in the dashboard are
      already reconciled — this digest exists to give you visibility into the underlying uncertainty so you can
      cross-check against your own sources when an audit matters.
    </p>

    <a href="{DASHBOARD_URL}/insights" style="display:inline-block;background:#38bdf8;color:#0a0e1a;padding:12px 24px;border-radius:10px;font-weight:600;text-decoration:none;font-size:14px;">
      Open dashboard →
    </a>

    <p style="font-size:11px;color:#475569;margin:32px 0 0 0;line-height:1.5;">
      You're receiving this because you have a watchlist configured on a Pro/Team plan.<br>
      Manage your watchlist in the dashboard settings.
    </p>

  </div>
</body>
</html>
"""


def _send_digest_email(to_email: str, name: str, divergences: list[dict], company_map: dict[str, str]) -> bool:
    if not RESEND_API_KEY:
        logger.debug("divergence_digest: RESEND_API_KEY unset, skipping email")
        return False
    if not to_email or not divergences:
        return False
    n = len(divergences)
    subject = (
        f"⚠️ {n} watchlist company shows data divergence this week"
        if n == 1
        else f"⚠️ {n} watchlist companies show data divergence this week"
    )
    try:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "from": EMAIL_FROM,
                "to": [to_email],
                "subject": subject,
                "html": _format_digest_email_html(name or "", divergences, company_map),
            },
            timeout=15,
        )
        if resp.ok:
            return True
        logger.warning(f"divergence_digest: Resend HTTP {resp.status_code}: {resp.text[:200]}")
        return False
    except Exception as e:
        logger.warning(f"divergence_digest: send failed to {to_email}: {e}")
        capture_exception(e, context={"where": "divergence_digest._send_digest_email", "to": to_email})
        return False


# ─── Public entry points ──────────────────────────────────────────────────


def send_weekly_digest_to_subscriber(subscriber: dict) -> dict:
    """Build + send digest for one subscriber. Returns stats dict.

    Skips silently when the subscriber has no qualifying divergences.
    """
    email = subscriber.get("email")
    name = subscriber.get("name") or ""
    watchlist = subscriber.get("watchlist_clean") or []
    divergences = _fetch_divergences_for_watchlist(watchlist)
    if not divergences:
        return {"email": email, "divergences": 0, "sent": False, "reason": "no_divergences"}

    company_map = _fetch_company_names([(d.get("ticker") or "").upper() for d in divergences])
    sent = _send_digest_email(email, name, divergences, company_map)
    if sent:
        logger.info(
            f"divergence_digest: sent to {email} ({len(divergences)} divergences in watchlist)"
        )
    return {"email": email, "divergences": len(divergences), "sent": sent}


def send_weekly_digest_to_all() -> dict:
    """Send the weekly digest to every eligible Pro+ subscriber.

    Designed to be called from a weekly cron (or once per week from the
    morning scan). Returns aggregate stats.
    """
    subs = _fetch_eligible_subscribers()
    if not subs:
        logger.info("divergence_digest: no eligible subscribers")
        return {"eligible": 0, "sent": 0, "skipped_no_divergence": 0, "errors": 0}

    sent = 0
    skipped = 0
    errors = 0
    for s in subs:
        try:
            r = send_weekly_digest_to_subscriber(s)
            if r.get("sent"):
                sent += 1
            elif r.get("reason") == "no_divergences":
                skipped += 1
        except Exception as e:
            errors += 1
            logger.warning(f"divergence_digest: subscriber {s.get('email')} failed: {e}")
            capture_exception(e, context={
                "where": "divergence_digest.send_weekly_digest_to_all",
                "subscriber_email": s.get("email"),
            })
    logger.info(
        f"divergence_digest weekly: {sent} sent, {skipped} skipped (no divergences), "
        f"{errors} errors across {len(subs)} eligible subscribers"
    )
    return {"eligible": len(subs), "sent": sent, "skipped_no_divergence": skipped, "errors": errors}


# ─── Manual smoke test ────────────────────────────────────────────────────


if __name__ == "__main__":
    print("Running divergence_digest manual smoke test (DRY-RUN — Resend may send if key is set)...")
    stats = send_weekly_digest_to_all()
    print(stats)
