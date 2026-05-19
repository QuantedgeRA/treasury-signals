"""
fast_tweets.py — Fast tweet cron entry point for priority=high accounts.

Polls priority=high X accounts (Saylor, Mallers, MARA, Metaplanet, Twenty
One, Strategy, etc.) every 1-2 minutes via Render's cron scheduler, runs
them through the classifier + exec_signal_detector + alert dispatch
pipeline. Designed to deliver sub-60s detection of the Saylor-tracker and
analogous CEO patterns that historically precede 8-K announcements
(Saylor's tracker tweet → MSTR 8-K, 107/107 historical hits, 5-7d lead).

Why this exists:
    main.py's phase_1_tweets only fires at SCAN_HOURS (6/12/18 UTC) → a
    Saylor tracker tweet at 12:01 UTC would wait until 18:00 UTC to alert.
    That's a ~6h gap vs the trader value-prop ("sub-60 seconds"). The
    exec_signal_detector (commit 92b0a9f) does no good if it only runs
    three times a day.

Why priority=high only:
    TwitterAPI.io charges per call. All 64 tracked accounts × every minute
    = ~92k calls/day. Polling only the ~10 priority=high accounts is
    ~14k/day — the highest-conviction CEO patterns get fast detection
    while the broader account universe stays on the 3x/day cycle.

Idempotency:
    scan_all_accounts() saves new tweets via save_tweet() which dedupes by
    tweet_id (UNIQUE on the tweets table). process_and_alert() reads
    unprocessed tweets and marks them processed atomically. Safe to run
    every minute alongside the 3x/day cycle — no double-processing.

Cost when no new tweets (most runs):
    ~10 API calls (one per account), ~60s end-to-end due to the 6s
    inter-account sleep in scan_all_accounts (TwitterAPI.io rate-limit
    compliance). Schedule `*/2 * * * *` recommended for safety margin;
    `* * * * *` works if all 10 polls finish in under 60s reliably.

Render setup (one-time):
    Create a Cron Job service alongside fast_edgar and the main worker.
    Schedule: `*/2 * * * *` (every 2 min).
    Command: `python fast_tweets.py`.
    Env: needs TWITTER_API_KEY, SUPABASE_*, ANTHROPIC_API_KEY,
    TELEGRAM_*, RESEND_API_KEY, EMAIL_FROM_*, SENTRY_DSN, DASHBOARD_URL.
    Branch: master (not main — see commit afe1186 context).
"""

import json
import time
from dotenv import load_dotenv

# Sentry first so module-level errors during imports surface.
load_dotenv()
from treasury_signals.observability import init_sentry
init_sentry()

from treasury_signals.logger import get_logger
from treasury_signals.scanners.twitter_client import reset_circuit_breaker

logger = get_logger(__name__)

ACCOUNTS_FILE = "accounts.json"


def load_priority_accounts() -> list[dict]:
    """Returns only priority=high accounts from accounts.json."""
    with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
        all_accounts = json.load(f)["accounts"]
    return [a for a in all_accounts if a.get("priority") == "high"]


def main():
    start = time.time()
    reset_circuit_breaker()

    accounts = load_priority_accounts()
    if not accounts:
        logger.warning("fast_tweets: no priority=high accounts in accounts.json — exiting")
        return

    # Defer imports so init_sentry runs first (matches main.py pattern).
    from treasury_signals.scheduler.helpers import scan_all_accounts, process_and_alert

    new_count, skip_count = scan_all_accounts(accounts)

    # process_and_alert reads ANY unprocessed tweet (not just from the
    # priority list above) — that's intentional. If the 3x/day cycle ever
    # misses a tweet, the next fast_tweets run catches up; if priority
    # accounts have already been classified there's nothing to do.
    signals, alerts_sent = process_and_alert()

    elapsed = time.time() - start
    logger.info(
        f"fast_tweets: {new_count} new tweets ({len(accounts)} priority accounts polled), "
        f"{len(signals)} signals, {alerts_sent} alerts, {elapsed:.1f}s"
    )


if __name__ == "__main__":
    main()
