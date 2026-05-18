"""
fast_edgar.py — Fast filings cron entry point (US + international).

Runs SEC EDGAR FTS + non-USA regulatory adapters (Japan-EDINET, South Korea-
DART, etc.) + Claude excerpt extraction + Slack alert dispatch, then exits.
Designed to be invoked by Render's cron scheduler every 1–2 minutes so the
customer-visible alert latency on new BTC filings stays sub-60-seconds (median).

Why this exists:
    main.py sleeps until the next SCAN_HOURS slot (6/12/18 UTC) and only then
    runs phase_4_edgar (US) + phase_9_regulatory (international). That makes
    worst-case file-to-alert latency ~6 hours and median ~4 hours —
    incompatible with the trader-led value prop that the landing page, trial
    drip, and FAQ all promise ("sub-60 seconds").

    This script runs only the fast paths (filing scan → excerpt → alerts).
    The 3x/day full scan in main.py still does the heavy synthesis work
    (correlation engine, daily briefing, leaderboard, Google News in 15
    languages, crypto news wires).

Idempotency:
    check_edgar_filings() dedupes via edgar_filings.accession_number (UNIQUE).
    Concurrent runs of main.py and fast_edgar.py on the same filing are safe —
    second insert errors gracefully and the alert won't double-fire.

Render setup (one-time):
    Create a Cron Job service in the same workspace as the main worker.
    Schedule: `* * * * *` (every minute) or `*/2 * * * *` (every 2 min).
    Command: `python fast_edgar.py`
    Env: copy from main service (SUPABASE_*, ANTHROPIC_API_KEY, RESEND, etc.).
"""

import time
from dotenv import load_dotenv

# Sentry must initialize before other imports so module-level exceptions surface.
load_dotenv()
from treasury_signals.observability import init_sentry
init_sentry()

from treasury_signals.logger import get_logger
from treasury_signals.scanners.edgar_realtime import check_edgar_filings

logger = get_logger(__name__)


def main():
    start = time.time()

    # US SEC EDGAR — FTS scan via edgar_realtime.py. Dedupes via
    # edgar_filings.accession_number UNIQUE.
    us_result = check_edgar_filings(days_back=1)
    us_new = (us_result or {}).get("new_filings", 0)

    if us_new > 0:
        # Claude-score the just-stored US filings. Bounded to keep spend
        # predictable; no-ops when ANTHROPIC_API_KEY is unset. Currently
        # SEC-only — extractor reads from edgar_filings.
        try:
            from treasury_signals.pipelines.filing_excerpt_extractor import (
                extract_excerpts_for_recent_filings,
            )
            extract_excerpts_for_recent_filings(lookback_hours=2, max_filings=10)
        except Exception as e:
            logger.debug(f"fast_edgar excerpt extractor: {e}")

        # Push high-impact excerpts to teams' Slack channels. Per-team watchlist
        # filter + alerted_at dedupe applies.
        try:
            from treasury_signals.alerts.filing_excerpt_alerts import (
                dispatch_pending_excerpts,
            )
            dispatch_pending_excerpts(min_impact=70)
        except Exception as e:
            logger.debug(f"fast_edgar alert dispatcher: {e}")

    # International — Japan EDINET, South Korea DART, plus any other non-USA
    # regulatory adapters defined in REGULATORY_ADAPTERS. Each adapter
    # silently no-ops when its API key is unset. Alerts fire via
    # global_filing_scanner._send_alert (reconciler-routed).
    intl_new = 0
    try:
        from treasury_signals.scanners.global_filing_scanner import scan_intl_filings
        intl = scan_intl_filings(days_back=1) or {}
        intl_new = intl.get("new_filings", 0)
        if intl_new > 0:
            logger.info(f"fast_edgar intl: {intl_new} new — {intl.get('sources')}")
    except Exception as e:
        logger.debug(f"fast_edgar intl scan: {e}")

    elapsed = time.time() - start
    logger.info(f"fast_edgar: {us_new} US + {intl_new} intl filings, {elapsed:.1f}s")


if __name__ == "__main__":
    main()
