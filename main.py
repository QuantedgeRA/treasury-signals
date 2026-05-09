"""
main.py — Treasury Signal Intelligence v2.2
Entry point: setup, scan loop, post-scan tasks, sleep.

The 10 numbered scan phases live in treasury_signals/scheduler/phases.py.
Cross-scan helpers (tweet fetching, classification, STRC, correlation,
email, leaderboard) and their cross-scan globals live in
treasury_signals/scheduler/helpers.py. The CorrelationEngine singleton
lives in treasury_signals/scheduler/__init__.py.

This file is the orchestrator only:
  1. Banner + auto-seed at startup
  2. Loop: build ScanState, run 10 phases in order, run post-scan tasks,
     sleep until the next scheduled scan time
  3. Post-scan tasks (entity sync, fixers, maintenance, primary source
     collection, watchlist alerts) — extracted in a separate PR
"""

import json
import time
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Initialize Sentry BEFORE any other imports so module-level exceptions are captured
load_dotenv()
from treasury_signals.observability import init_sentry
init_sentry()

import yfinance as yf

from treasury_signals.logger import get_logger
from treasury_signals.freshness_tracker import freshness
from treasury_signals.storage.subscriber_manager import subscribers
from treasury_signals.alerts.telegram_bot import send_scan_summary, send_to_paid
from treasury_signals.alerts.watchlist_manager import get_watchlist_activity, format_watchlist_telegram
from treasury_signals.pipelines.feedback_loop import feedback_engine
from treasury_signals.pipelines.price_predictor import predictor
from treasury_signals.pipelines.filing_parser import parse_and_update
from treasury_signals.sync.treasury_sync import sync as treasury_sync
from treasury_signals.sync.gov_entities import fix_government_entities
from treasury_signals.sync.shares_updater import update_shares
from treasury_signals.sync.entity_classifier import fix_entity_types
from treasury_signals.sync.entity_name_fixer import fix_entity_names
from treasury_signals.sync.sync_protector import snapshot_primary_data, protect_primary_data
from treasury_signals.sync.ticker_validator import validate_all_tickers
from treasury_signals.sync.shares_sync import sync_shares_outstanding
from treasury_signals.scanners.global_filing_scanner import scan_all_filings
from treasury_signals.scanners.etf_holdings_scraper import update_etf_holdings
from treasury_signals.scanners.defi_tracker import update_defi_holdings
from treasury_signals.scanners.whale_monitor import check_whale_transactions
from treasury_signals.scanners.exchange_flow_tracker import get_exchange_flow_report, format_flow_telegram

# Scheduler module — ScanState + phase functions + the engine singleton
from treasury_signals.scheduler import engine
from treasury_signals.scheduler.state import ScanState
from treasury_signals.scheduler.helpers import is_morning_scan
from treasury_signals.scheduler.phases import (
    phase_1_tweets, phase_2_classify, phase_3_strc, phase_4_edgar,
    phase_5_correlation, phase_6_email, phase_7_leaderboard,
    phase_8_purchase_detection, phase_9_regulatory, phase_10_dashboard_ping,
)

logger = get_logger(__name__)


def load_accounts():
    with open('accounts.json', 'r') as f:
        return json.load(f)['accounts']


def main():
    logger.info("=" * 60)
    logger.info("TREASURY PURCHASE SIGNAL INTELLIGENCE v2.2")
    logger.info("=" * 60)

    # Auto-seed database if tables are empty (first run)
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
        logger.warning(f"Auto-seed check skipped: {e}. Run 'python seed_database.py' manually if needed.")

    accounts = load_accounts()
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

    scan_number = 0
    while True:
        scan_number += 1
        morning = is_morning_scan()
        scan_type = "FULL (maintenance + detection)" if morning else "DETECTION"
        logger.info(f"{'='*50} SCAN #{scan_number} [{scan_type}] {'='*50}")

        state = ScanState(scan_number=scan_number, morning=morning, accounts=accounts)

        # ─── 10-step scan cycle (each phase reads/mutates ScanState) ───
        phase_1_tweets(state)
        phase_2_classify(state)
        phase_3_strc(state)
        phase_4_edgar(state)
        phase_5_correlation(state)
        phase_6_email(state)
        phase_7_leaderboard(state)
        phase_8_purchase_detection(state)
        phase_9_regulatory(state)
        phase_10_dashboard_ping(state)

        logger.info(f"Scan #{scan_number} complete")

        # Save freshness snapshot to Supabase
        try:
            from treasury_signals.storage.database import supabase as db_client
            freshness.save_to_supabase(db_client)
        except Exception as e:
            logger.debug(f"Freshness save: {e}")

        # Log system health
        health = freshness.get_overall_health()
        logger.info(f"System Health: {health['emoji']} {health['health'].upper()} — {health['message']}")

        # ═══ DAILY-ONLY TASKS (morning scan) ═══

        # Accuracy feedback loop — learn once per day
        if morning:
            try:
                feedback_engine.learn()
                feedback_engine.load_from_db()
                report = feedback_engine.get_learning_report()
                if "No learning data" not in report:
                    logger.info("Feedback loop: learning cycle complete")
            except Exception as e:
                logger.debug(f"Feedback loop: {e}")

        # Price prediction model (once per day)
        if morning:
            try:
                predictor.analyze()
            except Exception as e:
                logger.debug(f"Price predictor: {e}")

        # ═══ ENTITY SYNC (every scan) ═══

        # SNAPSHOT primary source data before aggregator sync
        try:
            snapshot_primary_data()
        except Exception as e:
            logger.debug(f"Sync snapshot: {e}")

        # Sync entities from CoinGecko + BitcoinTreasuries.net (aggregator)
        try:
            treasury_sync.run()
        except Exception as e:
            logger.debug(f"Treasury sync: {e}")

        # PROTECT: restore primary source data that aggregator may have overwritten
        try:
            protect_primary_data()
        except Exception as e:
            logger.debug(f"Sync protector: {e}")

        # ═══ NAME/TYPE FIXERS (every scan — must run before velocity tracker) ═══
        # Fix garbled emoji names from BitcoinTreasuries.net scraping.

        try:
            fix_government_entities()
        except Exception as e:
            logger.debug(f"Gov fix: {e}")

        try:
            fix_entity_types()
        except Exception as e:
            logger.debug(f"Entity fix: {e}")

        try:
            fix_entity_names()
        except Exception as e:
            logger.debug(f"Name fix: {e}")

        # Record daily snapshots + detect new entrants (AFTER fixers so names are clean)
        try:
            from treasury_signals.sync.velocity_tracker import velocity
            velocity.run()
        except Exception as e:
            logger.debug(f"Velocity tracker: {e}")

        # ═══ HEAVY MAINTENANCE TASKS (6am only) ═══

        if morning:
            try:
                update_shares()
            except Exception as e:
                logger.debug(f"Shares update: {e}")

            try:
                validate_all_tickers()
            except Exception as e:
                logger.debug(f"Ticker validator: {e}")

            try:
                shares_result = sync_shares_outstanding(limit=50)
                if shares_result['updated'] > 0:
                    logger.info(f"Shares sync: {shares_result['updated']} companies updated with shares outstanding")
            except Exception as e:
                logger.debug(f"Shares sync: {e}")
        else:
            logger.debug("Heavy maintenance tasks skipped (6am only)")

        # ═══ PRIMARY SOURCE DATA COLLECTION ═══

        # Global filing scanner: SEC EDGAR + Google News (15 langs) + crypto wires
        try:
            filing_result = scan_all_filings(days_back=1)
            if filing_result and isinstance(filing_result, dict):
                alerts = filing_result.get("alerts", [])
                if isinstance(alerts, list):
                    for alert in alerts[:10]:
                        engine.add_global_filing(
                            company=alert.get("company", "Unknown"),
                            ticker=alert.get("ticker", ""),
                            country=alert.get("country", ""),
                            filing_type=alert.get("source", "Global"),
                            detail_text=alert.get("title", alert.get("description", ""))[:150],
                        )
        except Exception as e:
            logger.debug(f"Global filing scanner: {e}")

        # AI filing parser: extract structured BTC data from detected filings
        try:
            parse_and_update(max_filings=15)
        except Exception as e:
            logger.debug(f"Filing parser: {e}")

        # Whale monitor: large BTC transactions on-chain → feeds correlation engine
        try:
            whale_result = check_whale_transactions()
            if whale_result and hasattr(whale_result, '__iter__'):
                for w in (whale_result if isinstance(whale_result, list) else []):
                    btc_amt = w.get("btc_amount", w.get("amount", 0))
                    if btc_amt >= 500:
                        engine.add_whale_movement(
                            btc_amount=btc_amt,
                            from_entity=w.get("from_entity"),
                            to_entity=w.get("to_entity"),
                            from_ticker=w.get("from_ticker"),
                            to_ticker=w.get("to_ticker"),
                        )
        except Exception as e:
            logger.debug(f"Whale monitor: {e}")

        # Exchange flow tracker: BTC exchange inflows/outflows/reserves
        try:
            try:
                btc = yf.Ticker("BTC-USD")
                hist = btc.history(period="2d")
                current_btc_price = float(hist["Close"].iloc[-1]) if not hist.empty else 67000
            except Exception:
                current_btc_price = 67000

            flow_report = get_exchange_flow_report(btc_price=current_btc_price)
            if flow_report and flow_report.get("has_exchange_data"):
                signal = flow_report.get("signal", "NEUTRAL")
                netflow = flow_report.get("netflow_btc", 0)
                logger.info(f"Exchange Flow: {signal} | Net: {netflow:+,.0f} BTC | Reserve trend: {flow_report.get('reserve_trend', 'unknown')}")

                if signal in ("STRONG_ACCUMULATION", "STRONG_DISTRIBUTION", "ACCUMULATION", "DISTRIBUTION"):
                    tg_msg = format_flow_telegram(flow_report)
                    if tg_msg:
                        send_to_paid(tg_msg)
                        logger.info(f"Exchange flow alert sent to PAID channel ({signal})")
            elif flow_report and flow_report.get("has_network_data"):
                logger.info(f"Exchange Flow: No exchange data (add CRYPTOQUANT_API_KEY) | Network: {flow_report.get('network_transactions_24h', 0):,} txns")
            else:
                logger.debug("Exchange Flow: No data available")
        except Exception as e:
            logger.debug(f"Exchange flow tracker: {e}")

        # ETF holdings: direct from issuer websites (morning only)
        if morning:
            try:
                update_etf_holdings()
            except Exception as e:
                logger.debug(f"ETF scraper: {e}")

        # DeFi holdings: DeFi Llama on-chain data (morning only)
        if morning:
            try:
                update_defi_holdings()
            except Exception as e:
                logger.debug(f"DeFi tracker: {e}")

        # ═══ WATCHLIST ALERTS (uses state.signals + state.detected) ═══

        try:
            all_subscribers = subscribers.get_active_subscribers()
            for sub in all_subscribers:
                watchlist = sub.get("watchlist", [])
                if isinstance(watchlist, str):
                    watchlist = json.loads(watchlist) if watchlist else []
                if not watchlist:
                    continue

                w_activity = get_watchlist_activity(
                    watchlist=watchlist,
                    signals=state.signals,
                    purchases=state.detected,
                )
                high_priority = [a for a in w_activity if a["priority"] == "high"]
                if high_priority:
                    tg_msg = format_watchlist_telegram(high_priority, sub.get("name", ""))
                    if tg_msg and sub.get("telegram_chat_id"):
                        from treasury_signals.alerts.telegram_bot import send_to_channel
                        send_to_channel(sub["telegram_chat_id"], tg_msg)
                        logger.info(f"Watchlist alert sent to {sub['name']} ({len(high_priority)} items)")
                    elif tg_msg:
                        send_to_paid(tg_msg)
                        logger.info(f"Watchlist alert for {sub['name']} sent to PAID channel ({len(high_priority)} items)")
        except Exception as e:
            logger.debug(f"Watchlist alert check: {e}")

        # ═══ SCAN SUMMARY ═══

        cor_score = state.correlation.get("market_score", 0) if state.correlation else 0
        cor_streams = state.correlation.get("total_streams", 0) if state.correlation else 0
        cor_level = state.correlation.get("alert_level", "NONE") if state.correlation else "NONE"

        send_scan_summary(scan_number, len(accounts), state.tweets_new, len(state.signals))
        logger.info(f"Tweets: {state.tweets_new} | Signals: {len(state.signals)} | Correlation v2: Market {cor_score}/100 ({cor_streams}/6 streams, {cor_level})")

        # ═══ SCHEDULED SCAN TIMING — sleep until next 6am/12pm/6pm ═══

        SCAN_HOURS = [6, 12, 18]
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
        except KeyboardInterrupt:
            logger.info("Stopped by user. Goodbye!")
            break


if __name__ == '__main__':
    main()
