"""scheduler/phases — the 10 numbered scan phases.

Each phase takes a ScanState, mutates it, and returns nothing. State flows
forward: phase_2 fills state.signals; phase_5 reads state.signals; phase_8
fills state.detected; etc. The orchestrator (main.py) constructs the state
once per scan and threads it through.

Phases preserve the verbatim behavior of the previous inline code, including
the same ScanContext labels, the same error-swallowing patterns, and the
same correlation-engine glue. This module is a pure structural move from
main.py — no logic changes.
"""

from treasury_signals.logger import get_logger, ScanContext
from treasury_signals.scheduler import engine
from treasury_signals.scheduler.state import ScanState
from treasury_signals.scheduler.helpers import (
    scan_all_accounts,
    process_and_alert,
    check_strc_volume,
    check_correlation,
    send_daily_email,
    send_daily_leaderboard,
)
from treasury_signals.scanners.edgar_realtime import check_edgar_filings as check_edgar_realtime
from treasury_signals.scanners.strc_tracker import get_strc_volume_data
from treasury_signals.pipelines.pattern_analyzer import pattern_engine
from treasury_signals.pipelines.narrative_engine import narrator
from treasury_signals.pipelines.purchase_tracker import (
    detect_new_purchases,
    log_detected_purchases,
    format_purchase_telegram,
    scan_news_for_purchases,
)
from treasury_signals.pipelines.purchase_reconciler import (
    promote_pending_purchases,
    expire_stale_pending,
    get_reconciler_stats,
    promote_pending_sales,
)
from treasury_signals.scanners.regulatory_scanner import run_full_scan as scan_regulatory
from treasury_signals.alerts.telegram_bot import send_to_paid, send_to_free

import requests as req

logger = get_logger(__name__)


def phase_1_tweets(state: ScanState):
    """[1/10] Fetch tweets from monitored accounts."""
    with ScanContext(logger, state.scan_number, "[1/10] Fetching tweets"):
        state.tweets_new, state.tweets_skipped = scan_all_accounts(state.accounts)
        logger.info(f"Tweets: {state.tweets_new} new, {state.tweets_skipped} duplicates")


def phase_2_classify(state: ScanState):
    """[2/10] Classify tweets and send signal alerts."""
    with ScanContext(logger, state.scan_number, "[2/10] Classifying + alerting"):
        state.signals, state.alerts_sent = process_and_alert()


def phase_3_strc(state: ScanState):
    """[3/10] STRC issuance volume tracker (Strategy-specific)."""
    with ScanContext(logger, state.scan_number, "[3/10] STRC issuance volume"):
        check_strc_volume()


def phase_4_edgar(state: ScanState):
    """[4/10] SEC EDGAR realtime 8-K scanner + correlation feed +
    Claude-scored excerpt extraction (the filing-intelligence moat).
    """
    with ScanContext(logger, state.scan_number, "[4/10] SEC EDGAR realtime"):
        try:
            edgar_result = check_edgar_realtime(days_back=1)
            if edgar_result and edgar_result.get("new_filings", 0) > 0:
                # Extract BTC-relevant sentences + Claude-score them.
                # Bounded run (max 10 filings/scan) keeps Claude spend predictable.
                # No-ops when ANTHROPIC_API_KEY is unset.
                try:
                    from treasury_signals.pipelines.filing_excerpt_extractor import (
                        extract_excerpts_for_recent_filings,
                    )
                    extract_excerpts_for_recent_filings(lookback_hours=24, max_filings=10)
                except Exception as e:
                    logger.debug(f"Excerpt extractor: {e}")

                # Push high-impact excerpts to teams' Slack channels.
                # Per-team watchlist filter applies; alerted_at marks each
                # excerpt as processed so we never re-send.
                try:
                    from treasury_signals.alerts.filing_excerpt_alerts import (
                        dispatch_pending_excerpts,
                    )
                    dispatch_pending_excerpts(min_impact=70)
                except Exception as e:
                    logger.debug(f"Filing alert dispatcher: {e}")

                # Pull the most recent stored filings and feed them to the
                # correlation engine (kept here, not in edgar_realtime, so
                # the engine instance stays a scheduler concern).
                try:
                    from treasury_signals.storage.database import supabase as db
                    # SEC-only — exclude the Google-News rows that dominate edgar_filings.
                    recent_filings = db.table("edgar_filings").select("*").like("source", "SEC EDGAR%").order("processed_at", desc=True).limit(5).execute()
                    if recent_filings.data:
                        for f in recent_filings.data:
                            if f.get("event_type") == "purchase" and f.get("btc_amount", 0) > 0:
                                engine.add_edgar_filing(
                                    company=f.get("company_name", ""),
                                    ticker=f.get("ticker_cik", ""),
                                    is_btc_related=True,
                                    filing_date=f.get("filing_date", ""),
                                    btc_amount=f.get("btc_amount", 0),
                                )
                            elif f.get("event_type") in ("purchase", "holding"):
                                engine.add_edgar_filing(
                                    company=f.get("company_name", ""),
                                    ticker=f.get("ticker_cik", ""),
                                    is_btc_related=True,
                                    filing_date=f.get("filing_date", ""),
                                )
                except Exception as e:
                    logger.debug(f"EDGAR → correlation feed: {e}")
        except Exception as e:
            logger.debug(f"EDGAR realtime: {e}")


def phase_5_correlation(state: ScanState):
    """[5/10] Correlation engine v2 + historical pattern matching.
    Reads state.signals; fills state.correlation, state.pattern_match,
    state.fg_value, state.btc_weekly."""
    with ScanContext(logger, state.scan_number, "[5/10] Correlation Engine v2"):
        try:
            from treasury_signals.scanners.market_intelligence import get_risk_dashboard
            risk_data = get_risk_dashboard()
            state.fg_value = risk_data.get("fear_greed_value", 50)
            state.btc_weekly = risk_data.get("btc_7d_change", 0)
            engine.update_market_context(
                fear_greed=state.fg_value,
                btc_weekly_change=state.btc_weekly,
                btc_price=risk_data.get("btc_price", 0),
            )
        except Exception as e:
            logger.debug(f"Market context update: {e}")
            # state.fg_value / btc_weekly already have defaults from ScanState

        state.correlation = check_correlation()

        try:
            strc_data = get_strc_volume_data()
            strc_r = strc_data.get("volume_ratio", 0) if strc_data else 0

            state.pattern_match = pattern_engine.match_current_conditions(
                recent_signals=state.signals or [],
                strc_ratio=strc_r,
                fear_greed=state.fg_value,
                btc_change_pct=state.btc_weekly,
            )
            logger.info(f"Pattern Match: {state.pattern_match['score']}/100 ({state.pattern_match['matched_count']}/{state.pattern_match['total_patterns']} patterns)")
            if state.pattern_match['matching_patterns']:
                for p in state.pattern_match['matching_patterns'][:3]:
                    logger.info(f"  ✅ {p['name']}: {p['match_detail']}")
        except Exception as e:
            logger.debug(f"Pattern analysis skipped: {e}")
            # state.pattern_match keeps its default-empty value from ScanState


def phase_6_email(state: ScanState):
    """[6/10] Daily email briefing (sends only when due)."""
    with ScanContext(logger, state.scan_number, "[6/10] Daily email briefing"):
        send_daily_email()


def phase_7_leaderboard(state: ScanState):
    """[7/10] Daily leaderboard Telegram (sends only when due)."""
    with ScanContext(logger, state.scan_number, "[7/10] Daily leaderboard"):
        send_daily_leaderboard()


def phase_8_purchase_detection(state: ScanState):
    """[8/10] Purchase + sale detection: news scan, snapshot diffs,
    reconciler promotions/expiry, stats. Fills state.detected."""
    with ScanContext(logger, state.scan_number, "[8/10] Purchase & sale detection"):
        try:
            news_purchases = scan_news_for_purchases()
            if news_purchases:
                logger.info(f"News scanner: {len(news_purchases)} purchase(s) found in headlines")
        except Exception as e:
            logger.debug(f"News purchase scan: {e}")

        state.detected = detect_new_purchases() or []
        if state.detected:
            log_detected_purchases(state.detected)
            for d in state.detected[:3]:
                msg = format_purchase_telegram(d)
                send_to_paid(msg)
                if d["btc_amount"] >= 1000:
                    send_to_free(msg)
            logger.info(f"{len(state.detected)} purchase(s) detected and logged")

            # Feed detected purchases into correlation engine as news signals
            for d in state.detected[:10]:
                engine.add_news_signal(
                    company=d.get("company", ""),
                    ticker=d.get("ticker", ""),
                    is_confirmed_purchase=True,
                    headline=f"{d.get('company', '')} acquired {d.get('btc_amount', 0):,} BTC",
                )

            # LLM purchase analysis
            try:
                for d in state.detected[:2]:
                    analysis = narrator.analyze_purchase(d, market_context={
                        "btc_price": 70000,
                        "fear_greed": 50,
                    }, was_predicted=d.get("was_predicted", False))
                    if analysis:
                        logger.info(f"LLM Purchase Analysis: {analysis[:100]}...")
            except Exception as e:
                logger.debug(f"LLM purchase analysis skipped: {e}")
        else:
            logger.info("No new purchases detected")

        # Reconciler: promote pending purchases confirmed by other scanners
        try:
            promoted = promote_pending_purchases()
            if promoted:
                logger.info(f"Reconciler: {promoted} pending purchase(s) promoted to confirmed")
        except Exception as e:
            logger.debug(f"Reconciler promote: {e}")

        # Reconciler: promote pending sales confirmed by other scanners
        try:
            promoted_sales = promote_pending_sales()
            if promoted_sales:
                logger.info(f"Reconciler: {promoted_sales} pending sale(s) promoted to confirmed")
        except Exception as e:
            logger.debug(f"Reconciler promote sales: {e}")

        # Reconciler: expire stale pending entries (once per day, morning only)
        if state.morning:
            try:
                expired = expire_stale_pending()
                if expired:
                    logger.info(f"Reconciler: {expired} stale pending entries discarded")
            except Exception as e:
                logger.debug(f"Reconciler expire: {e}")

        # Log reconciler stats
        try:
            rstats = get_reconciler_stats()
            logger.info(f"Reconciler: {rstats['confirmed_total']} confirmed purchases | {rstats.get('confirmed_sales', 0)} confirmed sales | {rstats.get('pending_buys', 0)} pending buys | {rstats.get('pending_sales', 0)} pending sales | {rstats['promoted_count']} promoted | {rstats['discarded_count']} discarded")
        except Exception as e:
            logger.debug(f"Reconciler stats: {e}")


def phase_9_regulatory(state: ScanState):
    """[9/10] Regulatory news + statements scan."""
    with ScanContext(logger, state.scan_number, "[9/10] Regulatory scan"):
        scan_regulatory()


