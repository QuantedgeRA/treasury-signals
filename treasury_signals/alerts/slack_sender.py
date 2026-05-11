"""
slack_sender.py — Slack Incoming Webhook delivery for daily briefings + alerts.

Posts to the team's `slack_webhook_url` using Slack's Block Kit JSON. No OAuth,
no tokens, no SDK — just `requests.post(url, json=blocks)`. The webhook URL is
the only secret; we treat it as such (never log the full URL, redact in
exception messages).

Two entry points:
    send_briefing_to_slack(webhook_url, briefing)
        Daily intelligence briefing — abbreviated for Slack (people don't read
        full briefings inside Slack; the goal is a hook + click-through to
        the dashboard).

    send_alert_to_slack(webhook_url, alert)
        Standalone alert (competitor purchase, large filing, etc). Full
        detail since it's a single event.

Both functions return {"ok": True} or {"ok": False, "error": "..."}. They
NEVER raise — Slack failures should not block the email send.
"""

from __future__ import annotations

import os
import re
from typing import Any

import requests

from treasury_signals.logger import get_logger

logger = get_logger(__name__)

DASHBOARD_URL = os.getenv("DASHBOARD_URL", "https://app.quantedgeriskadvisory.com")
SLACK_WEBHOOK_PREFIX = "https://hooks.slack.com/services/"
HTTP_TIMEOUT = 10  # seconds — Slack should respond fast or fail

# ─────────────────────────── helpers ─────────────────────────────────────


def _redact_url(url: str) -> str:
    """Last 6 chars only — enough to disambiguate in logs without leaking the secret."""
    if not url:
        return "<empty>"
    return f"…{url[-6:]}"


def is_valid_slack_webhook(url: str) -> bool:
    """Cheap validator — must look like a Slack incoming webhook URL."""
    if not isinstance(url, str):
        return False
    return url.startswith(SLACK_WEBHOOK_PREFIX) and len(url) > len(SLACK_WEBHOOK_PREFIX) + 10


def _post(webhook_url: str, payload: dict) -> dict:
    """POST JSON to the webhook. Swallow exceptions; return shape signaling success."""
    if not is_valid_slack_webhook(webhook_url):
        return {"ok": False, "error": "invalid_webhook_url"}
    try:
        res = requests.post(webhook_url, json=payload, timeout=HTTP_TIMEOUT)
        if res.status_code >= 400:
            # Slack returns "invalid_token", "channel_not_found", etc as plain text
            body = (res.text or "").strip()[:200]
            logger.warning(
                f"Slack webhook {_redact_url(webhook_url)} returned {res.status_code}: {body}"
            )
            return {"ok": False, "error": f"slack_{res.status_code}", "body": body}
        return {"ok": True}
    except requests.RequestException as e:
        logger.warning(f"Slack webhook {_redact_url(webhook_url)} raised: {e}")
        return {"ok": False, "error": "network_error"}


# ─────────────────────────── briefing payload ────────────────────────────


def _action_emoji(action_text: str) -> str:
    """Map BUY / HOLD / WAIT to a colored circle for visual triage in Slack."""
    if not action_text:
        return ":small_blue_diamond:"
    a = action_text.upper()
    if "BUY" in a:
        return ":large_green_circle:"
    if "HOLD" in a:
        return ":large_yellow_circle:"
    if "WAIT" in a or "PAUSE" in a:
        return ":large_orange_circle:"
    return ":small_blue_diamond:"


def _format_usd(n: float) -> str:
    if not n:
        return "$0"
    n = float(n)
    if n >= 1e9:
        return f"${n / 1e9:.1f}B"
    if n >= 1e6:
        return f"${n / 1e6:.1f}M"
    if n >= 1e3:
        return f"${n / 1e3:.0f}K"
    return f"${n:,.0f}"


def build_briefing_blocks(briefing: dict) -> list[dict]:
    """
    Convert briefing data into Slack Block Kit blocks.

    Expected (all optional) keys in `briefing`:
        date_str, company_name, btc_price, btc_change_pct,
        action_text, action_score, action_summary,
        risk_level, fg_value,
        watchlist_activity (list of {company, ticker, headline}),
        peer_activity (list of {text}),
        dashboard_url
    """
    company = briefing.get("company_name") or "Treasury Signal Intelligence"
    date_str = briefing.get("date_str") or ""
    btc_price = briefing.get("btc_price")
    btc_change = briefing.get("btc_change_pct")
    action_text = briefing.get("action_text") or "—"
    action_score = briefing.get("action_score")
    action_summary = (briefing.get("action_summary") or "").strip()
    risk_level = briefing.get("risk_level") or "—"
    fg_value = briefing.get("fg_value")
    watchlist = (briefing.get("watchlist_activity") or [])[:3]
    peers = (briefing.get("peer_activity") or [])[:3]
    dashboard = briefing.get("dashboard_url") or DASHBOARD_URL

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"Daily Intelligence Briefing · {date_str}", "emoji": True},
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"*{company}* · BTC " + (
                    f"*{_format_usd(btc_price)}* ({btc_change:+.1f}%)" if btc_price and btc_change is not None
                    else _format_usd(btc_price) if btc_price else "—"
                )},
            ],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"{_action_emoji(action_text)} *Today's signal:* *{action_text}*"
                    + (f"  ·  *{action_score}/100*" if action_score is not None else "")
                ),
            },
        },
    ]

    if action_summary:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": action_summary[:600]},
        })

    blocks.append({
        "type": "context",
        "elements": [
            {"type": "mrkdwn", "text": f"*Risk:* {risk_level}" + (f"  ·  *F&G:* {fg_value}" if fg_value is not None else "")},
        ],
    })

    if watchlist:
        wl_lines = []
        for item in watchlist:
            ticker = item.get("ticker") or ""
            headline = item.get("headline") or item.get("text") or ""
            wl_lines.append(f"• *{ticker}* — {headline}")
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Watchlist activity*\n" + "\n".join(wl_lines)},
        })

    if peers:
        peer_lines = [f"• {(p.get('text') or '').strip()[:160]}" for p in peers if (p.get("text") or "").strip()]
        if peer_lines:
            blocks.append({"type": "divider"})
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Peer activity*\n" + "\n".join(peer_lines)},
            })

    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Open dashboard", "emoji": True},
                "url": dashboard,
                "style": "primary",
            },
        ],
    })

    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": "_Treasury Signal Intelligence · brief delivered to this channel daily_"}],
    })

    return blocks


def send_briefing_to_slack(webhook_url: str, briefing: dict) -> dict:
    """High-level entry. Builds blocks + posts. Returns {ok, error?}."""
    if not is_valid_slack_webhook(webhook_url):
        return {"ok": False, "error": "invalid_webhook_url"}
    blocks = build_briefing_blocks(briefing)
    fallback = (
        f"Daily Intelligence Briefing · {briefing.get('date_str') or ''} · "
        f"{briefing.get('action_text') or '—'}"
    )
    return _post(webhook_url, {"text": fallback, "blocks": blocks})


# ─────────────────────────── alert payload ───────────────────────────────


def build_competitor_alert_blocks(alert: dict) -> list[dict]:
    """Block Kit for a single competitor purchase alert."""
    company = alert.get("company") or "A competitor"
    btc_amount = alert.get("btc_amount") or 0
    usd_amount = alert.get("usd_amount") or 0
    filing_date = alert.get("filing_date") or ""
    reasons = alert.get("reasons") or []
    dashboard = alert.get("dashboard_url") or f"{DASHBOARD_URL}/competitive"

    headline = f"*{company}* bought *{btc_amount:,} BTC*"
    if usd_amount:
        headline += f"  ·  {_format_usd(usd_amount)}"
    if filing_date:
        headline += f"  ·  _{filing_date}_"

    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": "Competitor alert", "emoji": True}},
        {"type": "section", "text": {"type": "mrkdwn", "text": headline}},
    ]

    if reasons:
        body = "\n".join(f"• {r}" for r in reasons[:4])
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*Why this matters*\n{body}"}})

    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "View competitive intel", "emoji": True},
                "url": dashboard,
                "style": "primary",
            },
        ],
    })
    return blocks


def send_competitor_alert_to_slack(webhook_url: str, alert: dict) -> dict:
    if not is_valid_slack_webhook(webhook_url):
        return {"ok": False, "error": "invalid_webhook_url"}
    blocks = build_competitor_alert_blocks(alert)
    fallback = f"Competitor alert: {alert.get('company', 'Unknown')} bought {alert.get('btc_amount', 0):,} BTC"
    return _post(webhook_url, {"text": fallback, "blocks": blocks})


# ─────────────────────────── filing excerpt payload ─────────────────────


# Categories from filing_excerpts table — used to pick the emoji + label.
# Kept in sync with the CHECK constraint in migration 0011.
_FILING_CATEGORY_EMOJI = {
    "acquisition":     ":large_green_circle:",
    "sale":            ":red_circle:",
    "financing":       ":large_blue_circle:",
    "policy_change":   ":large_purple_circle:",
    "risk_factor":     ":warning:",
    "forward_looking": ":crystal_ball:",
    "general":         ":small_blue_diamond:",
}

_FILING_CATEGORY_LABEL = {
    "acquisition":     "Acquisition",
    "sale":            "Sale",
    "financing":       "Financing",
    "policy_change":   "Policy change",
    "risk_factor":     "Risk factor",
    "forward_looking": "Forward-looking",
    "general":         "General",
}


def build_filing_excerpt_blocks(excerpt: dict) -> list[dict]:
    """Block Kit payload for a single filing excerpt alert.

    Expected keys in `excerpt`:
        company_name, ticker, form_type, filing_date, filing_url,
        category, impact_score, claude_summary, excerpt_text,
        btc_amount, usd_amount
    """
    company = excerpt.get("company_name") or "Unknown entity"
    ticker = excerpt.get("ticker") or ""
    form_type = excerpt.get("form_type") or "8-K"
    filing_date = excerpt.get("filing_date") or ""
    filing_url = excerpt.get("filing_url") or ""
    category = excerpt.get("category") or "general"
    impact = excerpt.get("impact_score") or 0
    summary = (excerpt.get("claude_summary") or "").strip()
    verbatim = (excerpt.get("excerpt_text") or "").strip()
    btc_amount = excerpt.get("btc_amount")
    usd_amount = excerpt.get("usd_amount")

    emoji = _FILING_CATEGORY_EMOJI.get(category, ":small_blue_diamond:")
    cat_label = _FILING_CATEGORY_LABEL.get(category, "General")

    # Header line: company + ticker + form
    header_text = f"*{company}*"
    if ticker:
        header_text += f" ({ticker})"
    header_text += f" filed a {form_type}"

    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": f"Filing alert · {cat_label}", "emoji": True}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"{emoji} {header_text}"}},
    ]

    # The Claude summary is the primary "what happened" line
    if summary:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Summary*\n{summary[:600]}"},
        })

    # Verbatim excerpt — limited to 800 chars so it doesn't dominate the message
    if verbatim:
        clipped = verbatim[:800] + ("…" if len(verbatim) > 800 else "")
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*From the filing*\n> {clipped}"},
        })

    # Context line: impact + amounts + date
    context_parts = [f"*Impact:* {impact}/100"]
    if btc_amount:
        try:
            context_parts.append(f"*BTC:* {float(btc_amount):,.0f}")
        except (TypeError, ValueError):
            pass
    if usd_amount:
        try:
            context_parts.append(f"*USD:* {_format_usd(float(usd_amount))}")
        except (TypeError, ValueError):
            pass
    if filing_date:
        context_parts.append(f"*Filed:* {filing_date}")

    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": "  ·  ".join(context_parts)}],
    })

    # CTAs: view filing on SEC + open dashboard /filings page
    cta_elements = []
    if filing_url:
        cta_elements.append({
            "type": "button",
            "text": {"type": "plain_text", "text": "Open on SEC EDGAR", "emoji": True},
            "url": filing_url,
        })
    cta_elements.append({
        "type": "button",
        "text": {"type": "plain_text", "text": "Open in TSI", "emoji": True},
        "url": f"{DASHBOARD_URL}/filings",
        "style": "primary",
    })
    blocks.append({"type": "actions", "elements": cta_elements})

    return blocks


def send_filing_excerpt_to_slack(webhook_url: str, excerpt: dict) -> dict:
    """High-level entry. Builds blocks + posts. Returns {ok, error?}."""
    if not is_valid_slack_webhook(webhook_url):
        return {"ok": False, "error": "invalid_webhook_url"}
    blocks = build_filing_excerpt_blocks(excerpt)
    company = excerpt.get("company_name") or "Unknown"
    ticker = excerpt.get("ticker") or ""
    cat = excerpt.get("category") or "general"
    fallback = f"Filing alert · {company}{f' ({ticker})' if ticker else ''} · {cat} · impact {excerpt.get('impact_score') or 0}/100"
    return _post(webhook_url, {"text": fallback, "blocks": blocks})


# ─────────────────────────── pre-announcement signal payload ────────────


_STREAM_EMOJI = {
    "tweet":          ":bird:",
    "strc":           ":bar_chart:",
    "edgar":          ":classical_building:",
    "global_filing":  ":globe_with_meridians:",
    "whale":          ":whale:",
    "news":           ":newspaper:",
    "filing_excerpt": ":mag:",
}


def build_pre_announcement_blocks(signal: dict) -> list[dict]:
    """Block Kit payload for a high-score pre-announcement signal.

    Expected keys (matches pre_announcement_signals row + the components
    JSON field):
        ticker, company, score, num_streams, alert_level, components
        components.streams (list), components.reasons (list)
    """
    company = signal.get("company") or "Unknown entity"
    ticker = signal.get("ticker") or ""
    score = signal.get("score") or 0
    num_streams = signal.get("num_streams") or 0
    alert_level = signal.get("alert_level") or "HIGH"
    components = signal.get("components") or {}
    streams = components.get("streams") or []
    reasons = components.get("reasons") or []

    stream_pills = " ".join(
        _STREAM_EMOJI.get(s, ":small_blue_diamond:") + " " + s.replace("_", " ")
        for s in streams[:6]
    )

    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": f"Pre-announcement signal · {alert_level}", "emoji": True}},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":radio_button: *{company}*{f' ({ticker})' if ticker else ''} — score *{score}/100* across *{num_streams} stream{'s' if num_streams != 1 else ''}*",
            },
        },
    ]

    if stream_pills:
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"*Streams firing:* {stream_pills}"}],
        })

    if reasons:
        body = "\n".join(f"• {(r or '').strip()[:180]}" for r in reasons[:4])
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*Reasons*\n{body}"}})

    # Market context line
    fg = components.get("fear_greed")
    btc_weekly = components.get("btc_weekly_change")
    ctx_parts = []
    if fg is not None:
        ctx_parts.append(f"*F&G:* {fg}")
    if btc_weekly is not None:
        try:
            ctx_parts.append(f"*BTC 7d:* {float(btc_weekly):+.1f}%")
        except (TypeError, ValueError):
            pass
    if ctx_parts:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "  ·  ".join(ctx_parts)}]})

    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Investigate in TSI", "emoji": True},
                "url": f"{DASHBOARD_URL}/signals",
                "style": "primary",
            },
        ],
    })

    # Explicit experimental disclaimer — false positives are by design
    blocks.append({
        "type": "context",
        "elements": [{
            "type": "mrkdwn",
            "text": "_Experimental signal — correlation across 7 streams, not a confirmed transaction. Calibration improves with each verified purchase._",
        }],
    })

    return blocks


def send_pre_announcement_to_slack(webhook_url: str, signal: dict) -> dict:
    if not is_valid_slack_webhook(webhook_url):
        return {"ok": False, "error": "invalid_webhook_url"}
    blocks = build_pre_announcement_blocks(signal)
    company = signal.get("company") or "Unknown"
    ticker = signal.get("ticker") or ""
    score = signal.get("score") or 0
    fallback = f"Pre-announcement signal · {company}{f' ({ticker})' if ticker else ''} · score {score}/100"
    return _post(webhook_url, {"text": fallback, "blocks": blocks})


# ─────────────────────────── test message ────────────────────────────────


def send_test_message(webhook_url: str) -> dict:
    """Used by the 'Send test message' button on /team. Verifies the webhook
    works without committing the team to a real briefing."""
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    ":wave: *Treasury Signal Intelligence* is now connected to this channel.\n\n"
                    "Daily briefings and competitor alerts will appear here automatically. "
                    "If you ever want to disconnect, head to the Team settings page."
                ),
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Open dashboard", "emoji": True},
                    "url": DASHBOARD_URL,
                    "style": "primary",
                },
            ],
        },
    ]
    return _post(webhook_url, {"text": "TSI Slack integration is connected.", "blocks": blocks})
