"""
pre_announcement_alerts.py — push high-score pre-announcement signals to Slack.

The delivery half of the Week 5 build. Reads pre_announcement_signals
rows where score >= 60 (HIGH threshold), filters by per-team watchlist,
posts to each team's slack_webhook_url, stamps alerted_at.

Dedup semantics (intentional — pre-announcement scores are noisy):
  - Max ONE alert per ticker per 24 hours, even if score keeps climbing.
    Otherwise a single signaling company would spam Slack every cycle.
  - The cooldown is checked against alerted_at on ANY prior row for the
    same ticker. So once a company has been alerted, we wait 24h before
    re-alerting even if a fresh higher-scoring snapshot comes in.

This V1 trade-off keeps the noise floor low for the EXPERIMENTAL tier.
Future iterations can add a "score upgrade" rule (re-alert if score
crosses 80 after a 60-tier alert) when calibration data justifies it.

Designed to be called from helpers.check_correlation() AFTER
persist_correlation_snapshot.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any

from dotenv import load_dotenv
from supabase import create_client

from treasury_signals.alerts.slack_sender import send_pre_announcement_to_slack
from treasury_signals.logger import get_logger
from treasury_signals.observability import capture_exception

logger = get_logger(__name__)
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Per-ticker cooldown window. Even if score keeps climbing, no re-alert
# for the same ticker within this window. Tunable.
ALERT_COOLDOWN_HOURS = 24

# Min score to trigger an alert. Matches the engine's HIGH alert level.
MIN_SCORE = 60

# Hard cap per scheduler tick.
MAX_ALERTS_PER_RUN = 10


def _normalize_ticker(t: Any) -> str:
    if not t:
        return ""
    s = str(t).strip().upper()
    if "." in s:
        s = s.split(".", 1)[0]
    return s


def _team_watchlist_tickers(team: dict) -> set[str]:
    raw = team.get("watchlist_json") or []
    if isinstance(raw, str):
        try:
            import json
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return set()
    if not isinstance(raw, list):
        return set()
    return {_normalize_ticker(t) for t in raw if t}


def _ticker_was_recently_alerted(ticker: str) -> bool:
    """Check if any row for this ticker has alerted_at within the cooldown.
    Returns True → skip this ticker; False → safe to alert."""
    if not ticker:
        return False
    cutoff = (datetime.utcnow() - timedelta(hours=ALERT_COOLDOWN_HOURS)).isoformat()
    try:
        res = (
            supabase.table("pre_announcement_signals")
            .select("id")
            .eq("ticker", ticker)
            .gte("alerted_at", cutoff)
            .limit(1)
            .execute()
        )
        return bool(res.data)
    except Exception as e:
        logger.debug(f"  Pre-announce alerts: cooldown lookup error for {ticker}: {e}")
        # Fail-safe: if we can't check, don't alert (better silent than spammy)
        return True


def _pull_pending_signals() -> list[dict]:
    """Pull the most-recent unalerted snapshot per ticker, score >= MIN_SCORE."""
    cutoff = (datetime.utcnow() - timedelta(hours=2)).isoformat()  # only recent
    try:
        res = (
            supabase.table("pre_announcement_signals")
            .select(
                "id, ticker, company, score, num_streams, multiplier, components, "
                "market_score, alert_level, snapshot_at, threshold_at, alerted_at"
            )
            .gte("snapshot_at", cutoff)
            .gte("score", MIN_SCORE)
            .is_("alerted_at", "null")
            .order("score", desc=True)
            .order("snapshot_at", desc=True)
            .limit(MAX_ALERTS_PER_RUN * 4)  # over-fetch — we'll dedup by ticker
            .execute()
        )
        rows = res.data or []
    except Exception as e:
        logger.warning(f"  Pre-announce alerts: read error (run migration 0012?): {e}")
        return []

    # Dedup to latest snapshot per ticker
    seen = set()
    latest_per_ticker = []
    for row in rows:
        t = _normalize_ticker(row.get("ticker"))
        if not t or t in seen:
            continue
        seen.add(t)
        latest_per_ticker.append(row)
        if len(latest_per_ticker) >= MAX_ALERTS_PER_RUN:
            break

    return latest_per_ticker


def _pull_teams_with_slack() -> list[dict]:
    try:
        res = (
            supabase.table("teams")
            .select("id, name, slack_webhook_url, watchlist_json")
            .not_.is_("slack_webhook_url", "null")
            .execute()
        )
        teams = res.data or []
        return [t for t in teams if t.get("slack_webhook_url") and "hooks.slack.com" in t["slack_webhook_url"]]
    except Exception as e:
        logger.debug(f"  Pre-announce alerts: teams fetch error: {e}")
        return []


def _mark_alerted(signal_id: int) -> None:
    try:
        supabase.table("pre_announcement_signals").update(
            {"alerted_at": datetime.utcnow().isoformat()}
        ).eq("id", signal_id).execute()
    except Exception as e:
        logger.warning(f"  Pre-announce alerts: alerted_at write error for id={signal_id}: {e}")


def dispatch_pending_signals() -> dict:
    """Main entry. Find high-score unalerted signals, dedup by ticker +
    cooldown, post to each subscribed team's Slack channel.

    Returns:
        {"signals_considered": int, "slack_posts": int, "skipped_cooldown": int}
    """
    logger.info(f"Pre-announce alerts: scanning signals (min_score={MIN_SCORE}, cooldown={ALERT_COOLDOWN_HOURS}h)...")

    candidates = _pull_pending_signals()
    if not candidates:
        logger.info("  Pre-announce alerts: no pending signals above threshold")
        return {"signals_considered": 0, "slack_posts": 0, "skipped_cooldown": 0}

    teams = _pull_teams_with_slack()

    slack_posts = 0
    skipped_cooldown = 0

    for signal in candidates:
        ticker = _normalize_ticker(signal.get("ticker"))

        # Cooldown check (regardless of teams — applies to whole signal)
        if _ticker_was_recently_alerted(ticker):
            skipped_cooldown += 1
            # Still mark this snapshot's alerted_at so we don't re-evaluate it
            _mark_alerted(signal["id"])
            continue

        # If no teams subscribed, still mark alerted (prevents infinite re-evaluation)
        if not teams:
            _mark_alerted(signal["id"])
            continue

        any_team_posted = False
        for team in teams:
            watchlist = _team_watchlist_tickers(team)
            if watchlist and ticker not in watchlist:
                continue

            result = send_pre_announcement_to_slack(team["slack_webhook_url"], signal)
            if result.get("ok"):
                slack_posts += 1
                any_team_posted = True
                logger.info(
                    f"  Pre-announce alert → Slack: team={team.get('name', '?')[:30]} "
                    f"ticker={ticker} score={signal.get('score')}"
                )
            else:
                logger.debug(
                    f"  Pre-announce alert → Slack failed: team={team.get('name', '?')[:30]} "
                    f"err={result.get('error', '?')}"
                )

        # Mark alerted (even if no teams matched — prevents re-evaluation each cycle)
        _mark_alerted(signal["id"])

    logger.info(
        f"Pre-announce alerts: {len(candidates)} signals considered, "
        f"{slack_posts} Slack posts, {skipped_cooldown} skipped (cooldown)"
    )
    return {
        "signals_considered": len(candidates),
        "slack_posts": slack_posts,
        "skipped_cooldown": skipped_cooldown,
    }


if __name__ == "__main__":
    logger.info("Pre-announce alerts — manual run...")
    result = dispatch_pending_signals()
    print(
        f"Considered: {result['signals_considered']}, "
        f"Posts: {result['slack_posts']}, Cooldown skips: {result['skipped_cooldown']}"
    )
