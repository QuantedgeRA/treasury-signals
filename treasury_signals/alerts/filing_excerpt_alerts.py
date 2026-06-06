"""
filing_excerpt_alerts.py — push high-impact filing excerpts to team Slack channels.

The delivery half of the filing-intelligence moat. Reads filing_excerpts
rows that haven't been alerted yet, finds teams with a slack_webhook_url
configured, applies per-team watchlist filtering, posts to Slack, and
stamps alerted_at on the excerpt so it's never re-sent.

Per-team filter logic:
    - Team has watchlist tickers → only send excerpts matching one of them
    - Team has empty watchlist → send all high-impact excerpts

Dedupe semantics:
    alerted_at IS NULL  → not yet attempted delivery to any team
    alerted_at SET     → delivery attempted at least once globally
                          (further teams who later add the company to
                          their watchlist do NOT get historical excerpts)

This V1 trade-off keeps the schema simple. A future migration could add
a per-team excerpt_alerts table for granular dedupe + retry, but the
loss case (a team adding a ticker mid-cycle) is rare and graceful.

Designed to be called from the scheduler's phase_4_edgar AFTER
extract_excerpts_for_recent_filings has populated filing_excerpts.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from dotenv import load_dotenv
from supabase import create_client

from treasury_signals.alerts.slack_sender import send_filing_excerpt_to_slack
from treasury_signals.logger import get_logger
from treasury_signals.observability import capture_exception

logger = get_logger(__name__)
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Default minimum impact to fire a Slack alert. Teams may want per-team
# thresholds eventually — for V1 this is a single global gate.
DEFAULT_MIN_IMPACT = 70

# Hard cap per scheduler tick. Prevents a backlog from blasting Slack if
# the scheduler was paused for a day and 200 excerpts piled up.
MAX_EXCERPTS_PER_RUN = 30


def _normalize_ticker(t: Any) -> str:
    """Strip exchange suffix + uppercase. 'MSTR.US' → 'MSTR'."""
    if not t:
        return ""
    s = str(t).strip().upper()
    if "." in s:
        s = s.split(".", 1)[0]
    return s


def _team_watchlist_tickers(team: dict) -> set[str]:
    """Pull tickers out of teams.watchlist_json (JSONB array). Empty set
    when the team hasn't configured a watchlist — caller treats that as
    'send everything'."""
    raw = team.get("watchlist_json") or []
    if isinstance(raw, str):
        # Defensive — should be parsed by the supabase client already
        try:
            import json
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return set()
    if not isinstance(raw, list):
        return set()
    return {_normalize_ticker(t) for t in raw if t}


def _pull_pending_excerpts(min_impact: int) -> list[dict]:
    try:
        res = (
            supabase.table("filing_excerpts")
            .select(
                "id, accession_number, company_name, ticker, filing_date, filing_url, "
                "form_type, excerpt_text, claude_summary, impact_score, category, "
                "btc_amount, usd_amount"
            )
            .is_("alerted_at", "null")
            .gte("impact_score", min_impact)
            .order("impact_score", desc=True)
            .order("created_at", desc=True)
            .limit(MAX_EXCERPTS_PER_RUN)
            .execute()
        )
        return res.data or []
    except Exception as e:
        # filing_excerpts may not exist yet on a fresh DB without the migration.
        # Surface that loudly — operators need to run migration 0011.
        logger.warning(f"  Filing alert dispatcher: filing_excerpts read error (run migration 0011?): {e}")
        return []


def _pull_teams_with_slack() -> list[dict]:
    try:
        res = (
            supabase.table("teams")
            .select("id, name, slack_webhook_url, watchlist_json")
            .not_.is_("slack_webhook_url", "null")
            .execute()
        )
        teams = res.data or []
        # Final filter — null vs empty string vs malformed
        return [t for t in teams if t.get("slack_webhook_url") and "hooks.slack.com" in t["slack_webhook_url"]]
    except Exception as e:
        logger.debug(f"  Filing alert dispatcher: teams fetch error: {e}")
        return []


def _mark_alerted(excerpt_id: int) -> None:
    try:
        supabase.table("filing_excerpts").update(
            {"alerted_at": datetime.utcnow().isoformat()}
        ).eq("id", excerpt_id).execute()
    except Exception as e:
        logger.warning(f"  Filing alert dispatcher: alerted_at write error for excerpt={excerpt_id}: {e}")
        capture_exception(e, context={"where": "filing_excerpt_alerts._mark_alerted", "excerpt_id": excerpt_id})


def _claim_excerpt(excerpt_id: int) -> bool:
    """Atomically claim an excerpt for Slack dispatch — flip alerted_at NULL->now
    only if still unclaimed. Returns True for the winning process. Stops the
    worker (phase_4) and the fast_edgar cron from double-posting the same excerpt
    to a paying team's Slack. Fail-OPEN: post anyway on query error."""
    try:
        res = (
            supabase.table("filing_excerpts")
            .update({"alerted_at": datetime.utcnow().isoformat()})
            .eq("id", excerpt_id)
            .is_("alerted_at", "null")
            .execute()
        )
        return bool(res.data)
    except Exception as e:
        logger.warning(f"  Filing alert dispatcher: claim error for excerpt={excerpt_id} (posting anyway): {e}")
        return True


def dispatch_pending_excerpts(min_impact: int = DEFAULT_MIN_IMPACT) -> dict:
    """Main entry. Walk pending excerpts × teams, post to Slack, mark alerted.

    Args:
        min_impact: minimum impact_score to alert on. Below this, excerpts
            stay in filing_excerpts (visible in /filings feed) but never
            push to Slack.

    Returns:
        {"excerpts_considered": int, "slack_posts": int, "errors": int}
    """
    logger.info(f"Filing alert dispatcher: scanning pending excerpts (min_impact={min_impact})...")

    excerpts = _pull_pending_excerpts(min_impact)
    if not excerpts:
        logger.info("  Filing alert dispatcher: no pending excerpts")
        return {"excerpts_considered": 0, "slack_posts": 0, "errors": 0}

    teams = _pull_teams_with_slack()
    if not teams:
        # No teams subscribed to Slack delivery. Still mark excerpts as
        # alerted so they don't pile up forever — once a team configures
        # a webhook later, they'll start receiving NEW excerpts as they
        # arrive, but won't replay historical ones.
        for e in excerpts:
            _mark_alerted(e["id"])
        logger.info(f"  Filing alert dispatcher: no Slack-enabled teams; marked {len(excerpts)} excerpts as processed")
        return {"excerpts_considered": len(excerpts), "slack_posts": 0, "errors": 0}

    slack_posts = 0
    errors = 0

    for excerpt in excerpts:
        # Atomic claim BEFORE posting — only the process that flips this
        # excerpt's alerted_at NULL->now delivers it, so two concurrent dispatch
        # runs (worker + fast_edgar cron) can't double-post to a team's Slack.
        if not _claim_excerpt(excerpt["id"]):
            continue

        excerpt_ticker = _normalize_ticker(excerpt.get("ticker"))

        for team in teams:
            watchlist = _team_watchlist_tickers(team)
            # Watchlist filter: empty → send all; non-empty → must match
            if watchlist and (not excerpt_ticker or excerpt_ticker not in watchlist):
                continue

            result = send_filing_excerpt_to_slack(team["slack_webhook_url"], excerpt)
            if result.get("ok"):
                slack_posts += 1
                logger.info(
                    f"  Filing alert → Slack: team={team.get('name', '?')[:30]} "
                    f"company={excerpt.get('company_name', '?')[:30]} "
                    f"impact={excerpt.get('impact_score')}"
                )
            else:
                errors += 1
                logger.debug(
                    f"  Filing alert → Slack failed: team={team.get('name', '?')[:30]} "
                    f"err={result.get('error', '?')}"
                )

        # alerted_at was already set by _claim_excerpt() above (one global flag,
        # not per-team) — so even if every team's filter rejected it, the row is
        # marked processed and the dispatcher won't re-evaluate it next cycle.

    logger.info(
        f"Filing alert dispatcher: {len(excerpts)} excerpts considered, "
        f"{slack_posts} Slack posts, {errors} errors"
    )
    return {"excerpts_considered": len(excerpts), "slack_posts": slack_posts, "errors": errors}


if __name__ == "__main__":
    logger.info("Filing alert dispatcher — manual run (min_impact=70)...")
    result = dispatch_pending_excerpts(min_impact=70)
    print(
        f"Considered: {result['excerpts_considered']}, "
        f"Posts: {result['slack_posts']}, Errors: {result['errors']}"
    )
