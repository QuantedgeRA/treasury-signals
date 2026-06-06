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

    # Heartbeat. fast_edgar previously emitted NO signal of its own, so whether
    # the Render */2 cron was actually deployed/running was unobservable from
    # data — the same blind spot that left the fast-tweets cron silently dead
    # for weeks. We upsert one row in cron_heartbeats; main.py's freshness phase
    # reads it and folds 'fast_edgar_cron' into the normal freshness snapshot +
    # admin-escalation path (stale > 30m). We deliberately do NOT write the
    # freshness snapshot from here — that table is a write-all-sources-once model
    # owned by post_scan, and a partial beat would blank every other source.
    # Best-effort: a heartbeat failure must never fail the scan.
    #
    # The heartbeat ALSO drives a cross-process EDGAR-down alarm. The freshness
    # tracker's 3-consecutive-failure escalator can't fire from a cron — each run
    # is a fresh process, so the in-memory streak resets every time, leaving the
    # latency-critical EDGAR path effectively unmonitored (the exact silent-outage
    # class that hid the original 2-week EDGAR breakage). So we run a tiny state
    # machine off the PERSISTED cron_heartbeats.last_status: a run where every
    # EFTS request errored arms 'edgar_down'; the 2nd consecutive such run
    # (~4 min) pages admin once and latches 'edgar_down_notified'; recovery pages
    # once. Transient single-run blips never page.
    try:
        from datetime import datetime, timezone
        from treasury_signals.scanners.edgar_realtime import supabase as _sb
        from treasury_signals.observability import notify_admin

        reqs = (us_result or {}).get("requests", 0)
        errs = (us_result or {}).get("request_errors", 0)
        edgar_down = reqs > 0 and errs >= reqs  # every EFTS request this run errored

        prior = ""
        try:
            _row = _sb.table("cron_heartbeats").select("last_status").eq(
                "cron_name", "fast_edgar"
            ).limit(1).execute().data
            prior = (_row[0]["last_status"] if _row else "") or ""
        except Exception:
            pass

        if edgar_down:
            if prior in ("edgar_down", "edgar_down_notified"):
                status = "edgar_down_notified"
                if prior == "edgar_down":  # 2nd consecutive failure — page once
                    notify_admin(
                        f"❌ fast_edgar: SEC EDGAR FTS errored on every request for 2+ "
                        f"consecutive runs (~4 min+). The real-time 8-K alert path is "
                        f"down ({errs}/{reqs} requests failed)."
                    )
            else:
                status = "edgar_down"  # 1st failure — arm, don't page yet
        else:
            status = "ok"
            if prior == "edgar_down_notified":
                notify_admin("✅ RECOVERED: fast_edgar SEC EDGAR FTS is returning results again.")

        _sb.table("cron_heartbeats").upsert({
            "cron_name": "fast_edgar",
            "last_run_at": datetime.now(timezone.utc).isoformat(),
            "last_status": status,
            "detail": f"{us_new} US + {intl_new} intl filings, {elapsed:.1f}s, edgar {errs}/{reqs} req errors",
        }, on_conflict="cron_name").execute()
    except Exception as e:
        logger.warning(f"fast_edgar heartbeat failed: {e}")


if __name__ == "__main__":
    main()
