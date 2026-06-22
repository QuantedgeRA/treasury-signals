"""
main.py — Treasury Signal Intelligence v2.2
Entry point: setup, scan loop, sleep. Everything else lives in
treasury_signals/scheduler/.

Layout:
  - 10 numbered scan phases    → treasury_signals/scheduler/phases.py
  - Post-scan tasks (sync/     → treasury_signals/scheduler/post_scan.py
    fixers/maintenance/etc.)
  - Cross-scan helpers + state → treasury_signals/scheduler/helpers.py
  - ScanState dataclass        → treasury_signals/scheduler/state.py
  - CorrelationEngine singleton → treasury_signals/scheduler/__init__.py

This file's only job is the loop and the sleep.
"""

import json
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Initialize Sentry BEFORE any other imports so module-level exceptions are captured
load_dotenv()
from treasury_signals.observability import init_sentry, capture_exception
init_sentry()

from treasury_signals.logger import get_logger
from treasury_signals.config import SCAN_HOURS
from treasury_signals.scheduler.state import ScanState
from treasury_signals.scheduler.helpers import is_morning_scan
from treasury_signals.scheduler.phases import (
    phase_1_tweets, phase_2_classify, phase_3_strc, phase_4_edgar,
    phase_5_correlation, phase_6_email, phase_7_leaderboard,
    phase_8_purchase_detection, phase_9_regulatory,
)
from treasury_signals.scheduler import post_scan

logger = get_logger(__name__)


def _safe(step, fn, *args):
    """Run one scan step in isolation.

    A single step's unhandled exception must NEVER kill the long-lived worker or
    abort the rest of the cycle. Without this, one failing phase (e.g. an EDGAR
    500, a bad row, or an error introduced by a deploy) propagated out of the
    `while True` loop, killed the process, and froze EVERY downstream table at
    once (leaderboard, purchases, mNAV, signals). Log + report to Sentry and
    keep going so the remaining phases and post-scan maintenance still run.
    """
    try:
        fn(*args)
    except Exception as e:
        logger.error(f"Scan step '{step}' failed: {e}", exc_info=True)
        try:
            capture_exception(e, context={"where": f"main.scan.{step}"})
        except Exception:
            pass


def load_accounts():
    with open('accounts.json', 'r') as f:
        return json.load(f)['accounts']


def _log_startup_banner(accounts):
    """One-time process-startup banner. Cheap; runs once before the loop."""
    import os
    logger.info("=" * 60)
    logger.info("TREASURY PURCHASE SIGNAL INTELLIGENCE v2.2")
    logger.info("=" * 60)
    logger.info(f"Monitoring {len(accounts)} X accounts")
    logger.info(f"EDGAR Realtime: monitoring ALL bitcoin-related 8-K filings")
    logger.info(f"STRC volume tracking: ACTIVE")
    logger.info(f"Correlation Engine v2: ACTIVE (6-stream, per-company + market-wide)")
    logger.info(f"Auto-Prediction Logging: ACTIVE")
    logger.info(f"Daily Email Briefing: ACTIVE (subscriber-based)")
    logger.info(f"Daily Leaderboard: ACTIVE")
    logger.info(f"EDGAR Realtime Bridge: ACTIVE (purchases → confirmed_purchases)")
    logger.info(f"Purchase Reconciler: ACTIVE (dedup + source hierarchy + pending verification)")
    logger.info(f"Exchange Flow Tracker: {'ACTIVE (CryptoQuant)' if os.getenv('CRYPTOQUANT_API_KEY') else 'LIMITED (add CRYPTOQUANT_API_KEY for full data)'}")
    logger.info(f"Scan schedule: 6am (full), 12pm (detection), 6pm (detection)")


def _auto_seed_if_empty():
    """First-run convenience: seed the DB if treasury_companies is empty."""
    try:
        from treasury_signals.sync.seed_database import run_full_seed
        from treasury_signals.storage.database import supabase as db
        check = db.table("treasury_companies").select("ticker").limit(1).execute()
        if not check.data:
            logger.info("Database appears empty — running auto-seed...")
            run_full_seed()
        else:
            logger.info("Database already seeded")
    except Exception as e:
        logger.warning(f"Auto-seed check skipped: {e}. Run 'python -m treasury_signals.sync.seed_database' manually if needed.")


def _sleep_until_next_scan():
    """Sleep until the next scheduled scan hour (from config.SCAN_HOURS).
    Returns True normally, False on Ctrl+C."""
    now = datetime.now()
    next_times = []
    for h in SCAN_HOURS:
        candidate = now.replace(hour=h, minute=0, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        next_times.append(candidate)
    next_scan = min(next_times)
    wait_seconds = (next_scan - now).total_seconds()
    wait_minutes = int(wait_seconds / 60)
    logger.info(f"Next scan at {next_scan.strftime('%Y-%m-%d %H:%M')} ({wait_minutes} minutes). Press Ctrl+C to stop.")
    try:
        time.sleep(wait_seconds)
        return True
    except KeyboardInterrupt:
        logger.info("Stopped by user. Goodbye!")
        return False


def main():
    _auto_seed_if_empty()
    accounts = load_accounts()
    _log_startup_banner(accounts)

    scan_number = 0
    while True:
        scan_number += 1
        # Outer backstop: even if something OUTSIDE a _safe step throws (e.g.
        # ScanState construction), the loop must survive to the next scan rather
        # than killing the worker. Each step below is ALSO individually isolated
        # so one failure never aborts the rest of the cycle.
        try:
            morning = is_morning_scan()
            scan_type = "FULL (maintenance + detection)" if morning else "DETECTION"
            logger.info(f"{'='*50} SCAN #{scan_number} [{scan_type}] {'='*50}")

            state = ScanState(scan_number=scan_number, morning=morning, accounts=accounts)

            # ─── 10-step scan cycle (each step isolated) ───
            _safe("phase_1_tweets", phase_1_tweets, state)
            _safe("phase_2_classify", phase_2_classify, state)
            _safe("phase_3_strc", phase_3_strc, state)
            _safe("phase_4_edgar", phase_4_edgar, state)
            _safe("phase_5_correlation", phase_5_correlation, state)
            _safe("phase_6_email", phase_6_email, state)
            _safe("phase_7_leaderboard", phase_7_leaderboard, state)
            _safe("phase_8_purchase_detection", phase_8_purchase_detection, state)
            _safe("phase_9_regulatory", phase_9_regulatory, state)

            logger.info(f"Scan #{scan_number} complete")

            # ─── Post-scan: freshness, sync, fixers, maintenance, primary source
            # collection, watchlist, scan summary (each isolated) ───
            _safe("save_freshness_snapshot", post_scan.save_freshness_snapshot)
            _safe("run_entity_sync", post_scan.run_entity_sync)
            _safe("run_name_type_fixers", post_scan.run_name_type_fixers)
            _safe("run_heavy_maintenance", post_scan.run_heavy_maintenance, state)
            _safe("run_primary_source_collection", post_scan.run_primary_source_collection, state)
            _safe("run_watchlist_alerts", post_scan.run_watchlist_alerts, state)
            _safe("send_scan_summary_log", post_scan.send_scan_summary_log, state, accounts)
        except Exception as e:
            logger.error(f"Scan #{scan_number} aborted by unexpected error: {e}", exc_info=True)
            try:
                capture_exception(e, context={"where": "main.scan_cycle", "scan_number": scan_number})
            except Exception:
                pass

        if not _sleep_until_next_scan():
            break


if __name__ == '__main__':
    main()
