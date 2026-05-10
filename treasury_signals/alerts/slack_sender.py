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
