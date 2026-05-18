"""
fast_edgar.py — Fast EDGAR cron entry point.

Runs a single SEC EDGAR FTS scan + Claude excerpt extraction + Slack alert
dispatch, then exits. Designed to be invoked by Render's cron scheduler every
1–2 minutes so the customer-visible alert latency on new BTC 8-Ks stays
sub-60-seconds (median).

Why this exists:
    main.py sleeps until the next SCAN_HOURS slot (6/12/18 UTC) and only then
    runs phase_4_edgar. That makes worst-case file-to-alert latency ~6 hours
    and median ~4 hours — incompatible with the trader-led value prop that the
    landing page, trial drip, and FAQ all promise ("sub-60 seconds").

    This script runs only the fast path (EDGAR scan → Claude excerpt → alerts).
    The 3x/day full scan in main.py still does the heavy synthesis work
    (correlation engine, daily briefing, leaderboard, etc.).

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
    result = check_edgar_filings(days_back=1)
    new_filings = (result or {}).get("new_filings", 0)

    if new_filings > 0:
        # Claude-score the just-stored filings. Bounded to keep spend predictable;
        # no-ops when ANTHROPIC_API_KEY is unset.
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

    elapsed = time.time() - start
    logger.info(f"fast_edgar: {new_filings} new filings, {elapsed:.1f}s")


if __name__ == "__main__":
    main()
