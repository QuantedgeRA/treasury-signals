"""scheduler/post_scan — work that runs after the 10 numbered phases.

Each function corresponds to one section of the previous post-scan inline
block in main.py. Functions take ScanState only when they actually need
per-cycle data (state.morning gating, state.signals/detected for the
watchlist, state.correlation/tweets_new/signals for the summary).

Order matters: callers should invoke these in the sequence laid out by
the comment headers below — entity sync MUST run before name/type
fixers, fixers MUST run before velocity tracker, and the watchlist
alert MUST run after the primary source collection so its data is
fresh.

Verbatim behavior preservation from the previous inline code: same
try/except patterns, same logger.debug swallow, same morning-only
gates. No logic changes.
"""

import json

import yfinance as yf

from treasury_signals.logger import get_logger
from treasury_signals.freshness_tracker import freshness
from treasury_signals.scheduler import engine
from treasury_signals.scheduler.state import ScanState

# Imports per section — kept inline rather than top-of-file to mirror the
# original inline-block structure. Could be hoisted later.
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
from treasury_signals.alerts.telegram_bot import send_scan_summary, send_to_paid, send_to_channel
from treasury_signals.alerts.watchlist_manager import get_watchlist_activity, format_watchlist_telegram
from treasury_signals.storage.subscriber_manager import subscribers

logger = get_logger(__name__)


# ─── Freshness + system health ─────────────────────────────────────────────

def save_freshness_snapshot():
    """Persist the in-memory freshness tracker to Supabase + log health."""
    try:
        from treasury_signals.storage.database import supabase as db_client
        freshness.save_to_supabase(db_client)
    except Exception as e:
        logger.debug(f"Freshness save: {e}")

    health = freshness.get_overall_health()
    logger.info(f"System Health: {health['emoji']} {health['health'].upper()} — {health['message']}")


# ─── Daily-only learning tasks (morning gate) ──────────────────────────────

def run_daily_only_tasks(state: ScanState):
    """Morning-only learning loop: classifier feedback + price predictor.

    SOFT-HIDDEN 2026-05-11 — predictions feature deprecated pending strategic
    pivot to filings-based signals (see memory/product_strategy_2026_05.md).
    Code preserved for 30-day reversibility; uncomment block below to restore.
    """
    return

    # try:
    #     feedback_engine.learn()
    #     feedback_engine.load_from_db()
    #     report = feedback_engine.get_learning_report()
    #     if "No learning data" not in report:
    #         logger.info("Feedback loop: learning cycle complete")
    # except Exception as e:
    #     logger.debug(f"Feedback loop: {e}")
    #
    # try:
    #     predictor.analyze()
    # except Exception as e:
    #     logger.debug(f"Price predictor: {e}")


# ─── Entity sync (every scan): snapshot → CoinGecko/BT pull → protect ──────

def run_entity_sync():
    """Three-step pattern: snapshot primary data, run aggregator sync,
    then restore primary data the aggregator may have downgraded."""
    try:
        snapshot_primary_data()
    except Exception as e:
        logger.debug(f"Sync snapshot: {e}")

    try:
        treasury_sync.run()
    except Exception as e:
        logger.debug(f"Treasury sync: {e}")

    try:
        protect_primary_data()
    except Exception as e:
        logger.debug(f"Sync protector: {e}")


# ─── Name/type fixers + velocity (every scan, must run after entity_sync) ──

def run_name_type_fixers():
    """Fix garbled emoji names from BitcoinTreasuries.net + run velocity
    tracker. Must run after entity_sync so the fixers see fresh data;
    velocity must run after fixers so its snapshots use clean names."""
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

    try:
        from treasury_signals.sync.velocity_tracker import velocity
        velocity.run()
    except Exception as e:
        logger.debug(f"Velocity tracker: {e}")


# ─── Heavy maintenance (morning only) — Yahoo-heavy work ───────────────────

def run_heavy_maintenance(state: ScanState):
    """Morning-only Yahoo-Finance-heavy work: ~225 shares calls, ticker
    validation against SEC + Yahoo, shares_outstanding sync. No-op outside
    the morning window."""
    if not state.morning:
        logger.debug("Heavy maintenance tasks skipped (6am only)")
        return

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

    # mNAV daily snapshot — depends on freshly synced shares_outstanding above.
    # Persists one row per public treasury company per day into mnav_history
    # (migration 0014). Defensive: never let mNAV errors block the rest of
    # the heavy-maintenance phase.
    try:
        from treasury_signals.pipelines.mnav_calculator import compute_and_persist_all_mnav
        mnav_stats = compute_and_persist_all_mnav()
        if mnav_stats.get("persisted", 0) > 0:
            logger.info(
                f"mNAV daily snapshot: {mnav_stats['persisted']} persisted, "
                f"{mnav_stats['skipped']} skipped, {mnav_stats['errors']} errors"
            )
    except Exception as e:
        logger.debug(f"mNAV daily snapshot: {e}")

    # mNAV alerts — compare today's snapshot to 7-day-prior to detect
    # premium compression, premium expansion, and new-discount crossings.
    # Must run AFTER compute_and_persist_all_mnav so today's row exists.
    try:
        from treasury_signals.alerts.mnav_alerts import check_mnav_alerts
        alert_stats = check_mnav_alerts()
        if alert_stats.get("alerts_fired", 0) > 0:
            logger.info(
                f"mNAV alerts: {alert_stats['alerts_fired']} fired, "
                f"types={alert_stats.get('by_type', {})}"
            )
    except Exception as e:
        logger.debug(f"mNAV alerts: {e}")

    # ATM-filing detector — scans S-3 / S-3/A / 424B5 / 424B7 across every
    # public treasury issuer. Funds-side complement to the 8-K purchase
    # detector: an ATM takedown filing is the leading indicator before the
    # BTC buy lands in the next 8-K. Migration 0015 + scanners/atm_filing_detector.
    # Morning-only because EDGAR submissions are batched daily by the SEC.
    try:
        from treasury_signals.scanners.atm_filing_detector import scan_atm_filings
        atm_stats = scan_atm_filings()
        if atm_stats.get("new_detections", 0) > 0:
            logger.info(
                f"ATM scanner: {atm_stats['new_detections']} new "
                f"({atm_stats.get('takedowns', 0)} takedowns, "
                f"{atm_stats.get('active', 0)} active, "
                f"{atm_stats.get('shelves', 0)} shelves)"
            )
    except Exception as e:
        logger.debug(f"ATM scanner: {e}")

    # Treasury-equity volume tracker — joins yfinance volume spikes against
    # atm_filings to emit "issuance underway, BTC buy imminent" signals for
    # any treasury equity (generalization of MSTR-only strc_tracker).
    # Must run AFTER atm scanner so the join sees same-day filings.
    try:
        from treasury_signals.scanners.equity_volume_tracker import scan_treasury_equity_volume
        ev_stats = scan_treasury_equity_volume()
        if ev_stats.get("signals", 0) > 0:
            logger.info(
                f"Equity volume: {ev_stats['signals']} signals, "
                f"{ev_stats.get('suppressed', 0)} suppressed (no ATM), "
                f"scanned {ev_stats.get('scanned', 0)}"
            )
    except Exception as e:
        logger.debug(f"Equity volume tracker: {e}")

    # Weekly Pro-tier digest: per-subscriber filtered list of open
    # btc_holdings_divergence_alerts on their watchlist tickers. Mondays
    # UTC only — once per week. The alerts table is populated continuously
    # by the reconciler; this just opens the per-week emit window.
    from datetime import datetime as _dt
    if _dt.utcnow().weekday() == 0:  # Monday
        try:
            from treasury_signals.alerts.divergence_digest import send_weekly_digest_to_all
            dg_stats = send_weekly_digest_to_all()
            if dg_stats.get("sent", 0) > 0:
                logger.info(
                    f"Divergence digest (weekly): {dg_stats['sent']} sent, "
                    f"{dg_stats.get('skipped_no_divergence', 0)} skipped (no divergences)"
                )
        except Exception as e:
            logger.debug(f"Divergence digest weekly: {e}")

    # Wallet movement monitor (Tier 3 of [[wallet_attribution_design]]).
    # Scans every is_active entity_wallets row for new outgoing/incoming
    # transactions, classifies counterparties, persists into
    # wallet_movements, and dispatches alerts on customer-relevant
    # flows (exchange_inflow / exchange_outflow / custody_change).
    # Dormant when entity_wallets is empty — no-op cost.
    try:
        from treasury_signals.pipelines.wallet_monitor import scan_tracked_wallets
        wm_stats = scan_tracked_wallets(send_alerts=True)
        if wm_stats.get("new_movements", 0) > 0 or wm_stats.get("alerts", 0) > 0:
            logger.info(
                f"Wallet monitor: {wm_stats['wallets_scanned']} wallets, "
                f"{wm_stats['new_movements']} new movements, "
                f"{wm_stats.get('alerts', 0)} alerts. "
                f"By class: {wm_stats.get('by_classification', {})}"
            )
    except Exception as e:
        logger.debug(f"Wallet monitor: {e}")

    # Backtest reactions backfill — compute equity reactions on new
    # confirmed_purchases that don't have a backtest_reactions row yet.
    # Powers the public /backtest landing-page asset. yfinance is slow +
    # rate-limited, so this runs once per morning (heavy_maintenance).
    # Idempotent: upserts on (ticker, filing_date); re-running same day
    # is a no-op.
    try:
        import subprocess
        # Use the script as a one-shot so its argument parsing + sys.path
        # setup work identically to a manual invocation. The script itself
        # exits cleanly on success/failure and writes to the same logger.
        from pathlib import Path as _Path
        script_path = _Path(__file__).resolve().parent.parent.parent / "scripts" / "backfill_backtest_reactions.py"
        if script_path.exists():
            result = subprocess.run(
                ["python", str(script_path), "--apply"],
                capture_output=True,
                text=True,
                timeout=600,  # 10 min cap — yfinance can be slow
            )
            if result.returncode == 0:
                # Print stats from the script's stdout summary
                for line in result.stdout.splitlines()[-6:]:
                    if line.strip():
                        logger.info(f"  backtest: {line.strip()}")
            else:
                logger.debug(f"Backtest backfill returned {result.returncode}: {result.stderr[:200]}")
    except Exception as e:
        logger.debug(f"Backtest backfill: {e}")


# ─── Primary source data collection ────────────────────────────────────────

def run_primary_source_collection(state: ScanState):
    """Global filings (US EDGAR + news in 15 langs + crypto wires), AI
    filing parser, whale monitor, exchange flow tracker. ETF + DeFi
    holdings only on morning scans."""

    # Global filing scanner — feeds correlation engine
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
    if state.morning:
        try:
            update_etf_holdings()
        except Exception as e:
            logger.debug(f"ETF scraper: {e}")

    # DeFi holdings: DeFi Llama on-chain data (morning only)
    if state.morning:
        try:
            update_defi_holdings()
        except Exception as e:
            logger.debug(f"DeFi tracker: {e}")


# ─── Watchlist alerts (per-subscriber, uses state.signals + state.detected) ─

def run_watchlist_alerts(state: ScanState):
    """For each subscriber with a configured watchlist, find high-priority
    activity in this scan's signals + detected purchases. Send to the
    subscriber's personal channel if set, else fall back to the paid channel."""
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
                    send_to_channel(sub["telegram_chat_id"], tg_msg)
                    logger.info(f"Watchlist alert sent to {sub['name']} ({len(high_priority)} items)")
                elif tg_msg:
                    send_to_paid(tg_msg)
                    logger.info(f"Watchlist alert for {sub['name']} sent to PAID channel ({len(high_priority)} items)")
    except Exception as e:
        logger.debug(f"Watchlist alert check: {e}")


# ─── Scan summary (final log line + Telegram summary) ──────────────────────

def send_scan_summary_log(state: ScanState, accounts):
    """Send the cycle's summary to Telegram + log the final scan stats."""
    cor_score = state.correlation.get("market_score", 0) if state.correlation else 0
    cor_streams = state.correlation.get("total_streams", 0) if state.correlation else 0
    cor_level = state.correlation.get("alert_level", "NONE") if state.correlation else "NONE"

    send_scan_summary(state.scan_number, len(accounts), state.tweets_new, len(state.signals))
    logger.info(
        f"Tweets: {state.tweets_new} | Signals: {len(state.signals)} | "
        f"Correlation v2: Market {cor_score}/100 ({cor_streams}/6 streams, {cor_level})"
    )
