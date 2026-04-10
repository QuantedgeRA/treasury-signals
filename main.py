"""
main.py — Treasury Signal Intelligence v2.2
Full automated pipeline with all features integrated.

Scans at 6am, 12pm, 6pm:
  1. Scan tweets from 24+ executive accounts
  2. Classify signals + send Telegram alerts
  3. Check STRC issuance volume
  4. SEC EDGAR realtime 8-K scanner (all bitcoin filings)
  5. Correlation Engine v2 (6-stream, per-company + market-wide)
  6. Send daily email briefing at 7am ET
  7. Send daily leaderboard at 8am
  8. Detect new BTC purchases (with reconciler)
  9. Scan regulatory news & statements
  10. Ping dashboard to keep alive

6am scan also runs: shares_updater, entity fixers, ticker validator

Correlation Engine v2 streams:
  - Tweet signals (mapped to companies)
  - STRC volume spikes (Strategy-specific)
  - EDGAR realtime 8-K filings
  - Global filing scanner (international)
  - Whale on-chain detection
  - News scanner (purchase headlines)
"""

import json
import time
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from twitter_client import get_user_tweets, extract_tweet_info
from database import save_tweet, get_new_tweets, mark_processed
from classifier import classify_tweet, get_signal_label, get_dimension_breakdown
from telegram_bot import send_alert, send_scan_summary, send_strc_alert, send_edgar_alert, send_to_paid, send_to_free
from strc_tracker import get_strc_volume_data, analyze_strc_signal, format_strc_alert
from correlation_engine import CorrelationEngineV2
from pattern_analyzer import pattern_engine
from feedback_loop import feedback_engine
from narrative_engine import narrator
from accuracy_tracker import log_prediction
from email_briefing import generate_and_send_briefing
from treasury_leaderboard import get_leaderboard_with_live_price, format_leaderboard_telegram
from purchase_tracker import detect_new_purchases, log_detected_purchases, format_purchase_telegram, scan_news_for_purchases
from regulatory_scanner import run_full_scan as scan_regulatory
from regulatory_tracker import format_regulatory_briefing
from logger import get_logger, ScanContext
from freshness_tracker import freshness
from subscriber_manager import subscribers
from watchlist_manager import get_watchlist_activity, format_watchlist_telegram
import yfinance as yf
import requests as req
from price_predictor import predictor
from treasury_sync import sync as treasury_sync
from competitor_alerts import check_competitor_purchase
from pro_briefing import send_pro_briefings
from telegram_alerts import alerts as telegram_alerts
from gov_entities import fix_government_entities
from shares_updater import update_shares
from entity_classifier import fix_entity_types
from entity_name_fixer import fix_entity_names
from edgar_realtime import check_edgar_filings as check_edgar_realtime
from purchase_reconciler import promote_pending_purchases, expire_stale_pending, get_reconciler_stats
from global_filing_scanner import scan_all_filings
from etf_holdings_scraper import update_etf_holdings
from defi_tracker import update_defi_holdings
from whale_monitor import check_whale_transactions
from exchange_flow_tracker import get_exchange_flow_report, format_flow_telegram
from filing_parser import parse_and_update
from sync_protector import snapshot_primary_data, protect_primary_data
from ticker_validator import validate_all_tickers

logger = get_logger(__name__)

load_dotenv()

# Initialize persistent objects
engine = CorrelationEngineV2()
last_correlation_alert_score = 0
last_email_date = None
last_leaderboard_date = None
sent_tweet_ids = set()
sent_strc_status = None
sent_correlation_score = 0

# Fallback email list — used only if subscribers table is empty
FALLBACK_EMAIL_RECIPIENTS = [
    "contact@quantedgeriskadvisory.com",
]


def load_accounts():
    with open('accounts.json', 'r') as f:
        return json.load(f)['accounts']


def scan_all_accounts(accounts):
    new_count = 0
    skip_count = 0
    for account in accounts:
        username = account['username']
        company = account.get('company', '')
        logger.debug(f"Scanning @{username} ({company})...")
        time.sleep(6)
        tweets = get_user_tweets(username)
        if tweets:
            account_new = 0
            for tweet in tweets:
                info = extract_tweet_info(tweet)
                saved = save_tweet(info, company=company)
                if saved:
                    account_new += 1
                    new_count += 1
                else:
                    skip_count += 1
            if account_new > 0:
                logger.debug(f"@{username}: {len(tweets)} tweets, {account_new} new")
        else:
            logger.debug(f"@{username}: no tweets returned")
    return new_count, skip_count


def process_and_alert():
    global sent_tweet_ids
    unprocessed = get_new_tweets()
    if not unprocessed:
        logger.info("No new tweets to classify")
        return [], 0
    signals = []
    alerts_sent = 0
    for tweet in unprocessed:
        result = classify_tweet(
            tweet_text=tweet['tweet_text'],
            author_username=tweet['author_username'],
            created_at=tweet['created_at'],
            is_reply=tweet.get('is_reply', False),
        )
        mark_processed(
            tweet_id=tweet['tweet_id'],
            is_signal=result['is_signal'],
            confidence_score=result['score'],
        )
        if result['is_signal']:
            signal = {
                'author': tweet['author_username'],
                'company': tweet.get('company', ''),
                'text': tweet['tweet_text'],
                'url': tweet.get('tweet_url', ''),
                'created_at': tweet['created_at'],
                'score': result['score'],
                'label': get_signal_label(result['score']),
                'reasons': result['reasons'],
                'dimensions': result.get('dimensions', {}),
            }
            signals.append(signal)
            logger.info(f"Signal: @{tweet['author_username']} {result['score']}/100 — {get_dimension_breakdown(result.get('dimensions', {}))}")

            if result['score'] >= 60:
                company_name = tweet.get('company', 'Unknown')
                ticker = ""
                if "mstr" in company_name.lower() or "strategy" in company_name.lower():
                    ticker = "MSTR"
                elif "mara" in company_name.lower():
                    ticker = "MARA"
                elif "riot" in company_name.lower():
                    ticker = "RIOT"
                elif "tesla" in company_name.lower():
                    ticker = "TSLA"
                elif "gamestop" in company_name.lower():
                    ticker = "GME"
                elif "coinbase" in company_name.lower():
                    ticker = "COIN"

                engine.add_tweet_signal(tweet['author_username'], company_name, ticker, result['score'], tweet['tweet_text'])

                log_prediction(
                    company=company_name, ticker=ticker,
                    signal_type="tweet", signal_score=result['score'],
                    signal_details=f"@{tweet['author_username']}: {tweet['tweet_text'][:200]}",
                )

            tweet_id = tweet.get('tweet_id', tweet['tweet_text'][:50])
            if tweet_id not in sent_tweet_ids:
                sent_tweet_ids.add(tweet_id)
                logger.info(f"SIGNAL: {signal['label']} from @{signal['author']} (score: {signal['score']})")
                success = send_alert(signal, delay_free=True)
                if success:
                    alerts_sent += 1
            else:
                logger.debug(f"Already sent alert for tweet {tweet_id}, skipping")

    logger.info(f"Classified {len(unprocessed)} tweets: {len(signals)} signals, {alerts_sent} alerts sent")
    return signals, alerts_sent


def check_strc_volume():
    global sent_strc_status
    strc_data = get_strc_volume_data()
    if strc_data:
        strc_analysis = analyze_strc_signal(strc_data)
        logger.info(f"STRC: ${strc_data['dollar_volume_m']}M volume, {strc_data['volume_ratio']}x avg — {strc_analysis['level']}")

        current_status = strc_analysis["level"]
        if strc_analysis['is_signal'] and current_status != sent_strc_status:
            engine.add_strc_spike(strc_data['volume_ratio'], strc_data['dollar_volume_m'])

            log_prediction(
                company="Strategy (MSTR)", ticker="MSTR",
                signal_type="strc_volume",
                signal_score=min(int(strc_data['volume_ratio'] * 30), 90),
                signal_details=f"STRC volume spike: {strc_data['volume_ratio']}x normal, ${strc_data['dollar_volume_m']}M",
            )

            strc_message = format_strc_alert(strc_data, strc_analysis)
            is_very_high = strc_data['volume_ratio'] >= 2.0
            send_strc_alert(strc_message, is_high=is_very_high)
            sent_strc_status = current_status
        elif current_status == sent_strc_status:
            logger.debug(f"STRC status unchanged ({current_status}), no notification")

        return strc_data, strc_analysis
    else:
        logger.warning("STRC: Could not fetch data")
        return None, None


def check_correlation():
    global last_correlation_alert_score, sent_correlation_score

    result = engine.calculate_correlation()
    market_score = result['market_score']
    total_streams = result['total_streams']
    level = result['alert_level']

    logger.info(f"Correlation v2: Market {market_score}/100 | {total_streams}/6 streams | {level}")

    # Log top signaling companies
    for c in result['top_companies'][:3]:
        if c['score'] >= 30:
            logger.info(f"  📊 {c['company']}: {c['score']}/100 ({' + '.join(c['streams'])})")

    if result['reasons']:
        for reason in result['reasons']:
            logger.info(f"  {reason}")

    # Log predictions for high scores
    if market_score >= 50:
        signaling = [c for c in result['top_companies'] if c['score'] >= 40]
        log_prediction(
            company="Market-Wide", ticker="MULTI",
            signal_type="correlation_v2", signal_score=market_score,
            signal_details=f"{len(signaling)} companies signaling. Streams: {', '.join(result['active_streams'])}",
        )

    # Send alerts based on market-wide score
    if market_score >= 50 and (market_score - last_correlation_alert_score) >= 15 and market_score != sent_correlation_score:
        alert_message = engine.format_correlation_alert(result)
        send_to_paid(alert_message)
        logger.info(f"Correlation v2 alert sent to PAID channel (market score: {market_score})")
        sent_correlation_score = market_score

        if market_score >= 70:
            free_message = f"""
🔗 INSTITUTIONAL WAVE DETECTED

Market-Wide Score: {market_score}/100
Active Streams: {total_streams}/6

{result['narrative'][:300]}

🔓 Full company breakdown in PRO channel.
"""
            send_to_free(free_message)
            logger.info(f"Critical correlation alert sent to FREE channel (market score: {market_score})")

        last_correlation_alert_score = market_score
    elif market_score == sent_correlation_score:
        logger.debug(f"Correlation unchanged ({market_score}/100), no notification")

    if market_score < 30:
        last_correlation_alert_score = 0
        sent_correlation_score = 0

    return result


def send_daily_email():
    global last_email_date
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    if now.hour >= 7 and last_email_date != today:
        # Get subscribers from database
        email_subscribers = subscribers.get_email_recipients()

        if not email_subscribers:
            logger.info(f"No subscribers in DB — using fallback list ({len(FALLBACK_EMAIL_RECIPIENTS)} recipients)")
            for email in FALLBACK_EMAIL_RECIPIENTS:
                try:
                    success, _ = generate_and_send_briefing(email)
                    if success:
                        logger.info(f"Briefing sent to {email}")
                    else:
                        logger.error(f"Failed to send briefing to {email}")
                except Exception as e:
                    logger.error(f"Email error for {email}: {e}", exc_info=True)
        else:
            logger.info(f"Sending personalized briefings to {len(email_subscribers)} subscriber(s)...")
            for sub in email_subscribers:
                email = sub["email"]
                try:
                    success, _ = generate_and_send_briefing(email, subscriber=sub)
                    if success:
                        logger.info(f"Personalized briefing sent to {sub['name']} ({email})")
                    else:
                        logger.error(f"Failed to send briefing to {sub['name']} ({email})")
                except Exception as e:
                    logger.error(f"Email error for {sub['name']} ({email}): {e}", exc_info=True)

        last_email_date = today

        # Send personalized Pro briefings
        try:
            # Reuse BTC price from market intelligence to avoid redundant API calls
            try:
                from market_intelligence import get_risk_dashboard
                _risk = get_risk_dashboard()
                _btc_price = _risk.get("btc_price", 0)
            except Exception:
                _btc_price = None
            send_pro_briefings(btc_price=_btc_price)
        except Exception as e:
            logger.debug(f"Pro briefing: {e}")

        # Free channel: weekly summary on Mondays only
        try:
            if datetime.now().weekday() == 0:
                telegram_alerts.send_weekly_summary()
        except Exception as e:
            logger.debug(f"Weekly summary: {e}")
    else:
        if last_email_date == today:
            logger.debug("Daily briefing already sent today")
        else:
            logger.debug(f"Daily briefing scheduled for 7am (current hour: {now.hour})")


def send_daily_leaderboard():
    global last_leaderboard_date
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    if now.hour >= 8 and last_leaderboard_date != today:
        logger.info("Sending daily leaderboard to Telegram...")
        try:
            btc = yf.Ticker("BTC-USD")
            hist = btc.history(period="5d")
            btc_price = float(hist["Close"].iloc[-1]) if not hist.empty else 72000
            companies, summary = get_leaderboard_with_live_price(btc_price)
            message = format_leaderboard_telegram(companies, summary)
            send_to_paid(message)
            logger.info(f"Leaderboard sent: {summary['total_companies']} entities, {summary['total_btc']:,} BTC")
            last_leaderboard_date = today
        except Exception as e:
            logger.error(f"Leaderboard send failed: {e}", exc_info=True)
    else:
        if last_leaderboard_date == today:
            logger.debug("Daily leaderboard already sent today")
        else:
            logger.debug(f"Daily leaderboard scheduled for 8am (current hour: {now.hour})")


def is_morning_scan():
    """Check if current scan is the 6am morning maintenance scan."""
    return datetime.now().hour < 9


def main():
    logger.info("=" * 60)
    logger.info("TREASURY PURCHASE SIGNAL INTELLIGENCE v2.2")
    logger.info("=" * 60)

    # Auto-seed database if tables are empty (first run)
    try:
        from seed_database import run_full_seed
        from database import supabase as db
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
    scan_count = 0
    while True:
        scan_number += 1
        morning = is_morning_scan()
        scan_type = "FULL (maintenance + detection)" if morning else "DETECTION"
        logger.info(f"{'='*50} SCAN #{scan_number} [{scan_type}] {'='*50}")

        with ScanContext(logger, scan_number, "[1/10] Fetching tweets"):
            new_count, skip_count = scan_all_accounts(accounts)
            logger.info(f"Tweets: {new_count} new, {skip_count} duplicates")

        with ScanContext(logger, scan_number, "[2/10] Classifying + alerting"):
            signals, alerts_sent = process_and_alert()

        with ScanContext(logger, scan_number, "[3/10] STRC issuance volume"):
            check_strc_volume()

        with ScanContext(logger, scan_number, "[4/10] SEC EDGAR realtime"):
            # Searches ALL 8-K filings for bitcoin keywords, extracts BTC/USD amounts,
            # bridges purchases to confirmed_purchases, sends Telegram alerts
            try:
                edgar_result = check_edgar_realtime(days_back=1)
                # Feed EDGAR findings into correlation engine
                if edgar_result and edgar_result.get("new_filings", 0) > 0:
                    # Query recent edgar_filings from DB to get details
                    try:
                        from database import supabase as db
                        recent_filings = db.table("edgar_filings").select("*").order("processed_at", desc=True).limit(5).execute()
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

        with ScanContext(logger, scan_number, "[5/10] Correlation Engine v2"):
            # Feed market context into the engine before calculating
            try:
                from market_intelligence import get_risk_dashboard
                risk_data = get_risk_dashboard()
                fg_value = risk_data.get("fear_greed_value", 50)
                btc_weekly = risk_data.get("btc_7d_change", 0)
                engine.update_market_context(
                    fear_greed=fg_value,
                    btc_weekly_change=btc_weekly,
                    btc_price=risk_data.get("btc_price", 0)
                )
            except Exception as e:
                logger.debug(f"Market context update: {e}")
                fg_value = 50
                btc_weekly = 0

            correlation = check_correlation()

            # Historical pattern matching
            try:
                strc_data = get_strc_volume_data()
                strc_r = strc_data.get("volume_ratio", 0) if strc_data else 0

                pattern_match = pattern_engine.match_current_conditions(
                    recent_signals=signals if 'signals' in dir() else [],
                    strc_ratio=strc_r,
                    fear_greed=fg_value,
                    btc_change_pct=btc_weekly,
                )
                logger.info(f"Pattern Match: {pattern_match['score']}/100 ({pattern_match['matched_count']}/{pattern_match['total_patterns']} patterns)")
                if pattern_match['matching_patterns']:
                    for p in pattern_match['matching_patterns'][:3]:
                        logger.info(f"  ✅ {p['name']}: {p['match_detail']}")
            except Exception as e:
                logger.debug(f"Pattern analysis skipped: {e}")
                pattern_match = {"score": 0, "matched_count": 0, "total_patterns": 0, "matching_patterns": [], "narrative": ""}

        with ScanContext(logger, scan_number, "[6/10] Daily email briefing"):
            send_daily_email()

        with ScanContext(logger, scan_number, "[7/10] Daily leaderboard"):
            send_daily_leaderboard()

        with ScanContext(logger, scan_number, "[8/10] Purchase detection"):
            # Step 1: Scan news for real purchase announcements (feeds into reconciler)
            # This runs FIRST so news-confirmed purchases are in the DB before
            # snapshot comparison, allowing snapshot deltas to be deduped against them.
            try:
                news_purchases = scan_news_for_purchases()
                if news_purchases:
                    logger.info(f"News scanner: {len(news_purchases)} purchase(s) found in headlines")
            except Exception as e:
                logger.debug(f"News purchase scan: {e}")

            # Step 2: Snapshot comparison (all deltas go to pending, never auto-confirmed)
            detected = detect_new_purchases()
            if detected:
                log_detected_purchases(detected)
                for d in detected[:3]:
                    msg = format_purchase_telegram(d)
                    send_to_paid(msg)
                    if d["btc_amount"] >= 1000:
                        send_to_free(msg)
                logger.info(f"{len(detected)} purchase(s) detected and logged")

                # Feed detected purchases into correlation engine as news signals
                for d in detected[:10]:
                    engine.add_news_signal(
                        company=d.get("company", ""),
                        ticker=d.get("ticker", ""),
                        is_confirmed_purchase=True,
                        headline=f"{d.get('company', '')} acquired {d.get('btc_amount', 0):,} BTC",
                    )

                # LLM purchase analysis
                try:
                    for d in detected[:2]:
                        analysis = narrator.analyze_purchase(d, market_context={
                            "btc_price": btc_price if 'btc_price' in dir() else 70000,
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

            # Reconciler: expire stale pending entries (once per day, morning only)
            if morning:
                try:
                    expired = expire_stale_pending()
                    if expired:
                        logger.info(f"Reconciler: {expired} stale pending purchase(s) discarded")
                except Exception as e:
                    logger.debug(f"Reconciler expire: {e}")

            # Log reconciler stats
            try:
                rstats = get_reconciler_stats()
                logger.info(f"Reconciler: {rstats['confirmed_total']} confirmed | {rstats['pending_count']} pending | {rstats['promoted_count']} promoted | {rstats['discarded_count']} discarded")
            except Exception as e:
                logger.debug(f"Reconciler stats: {e}")

        with ScanContext(logger, scan_number, "[9/10] Regulatory scan"):
            scan_regulatory()

        with ScanContext(logger, scan_number, "[10/10] Dashboard ping"):
            try:
                response = req.get("https://treasury-signals-jqyywcwr8l8pbtv66rvbbg.streamlit.app/", timeout=30)
                logger.debug(f"Dashboard ping: {response.status_code}")
            except Exception as e:
                logger.debug(f"Dashboard ping failed: {e}")

        logger.info(f"Scan #{scan_number} complete")

        # Save freshness snapshot to Supabase
        try:
            from database import supabase as db_client
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
        # These fix garbled emoji names from BitcoinTreasuries.net scraping.
        # Lightweight: just DB updates + BT page scraping, no Yahoo calls.

        # Fix government entity names after sync
        try:
            fix_government_entities()
        except Exception as e:
            logger.debug(f"Gov fix: {e}")

        # Fix DeFi/ETF entity types after sync
        try:
            fix_entity_types()
        except Exception as e:
            logger.debug(f"Entity fix: {e}")

        # Fix garbled ETF/private company names
        try:
            fix_entity_names()
        except Exception as e:
            logger.debug(f"Name fix: {e}")

        # Record daily snapshots + detect new entrants (AFTER fixers so names are clean)
        try:
            from velocity_tracker import velocity
            velocity.run()
        except Exception as e:
            logger.debug(f"Velocity tracker: {e}")

        # ═══ HEAVY MAINTENANCE TASKS (6am only) ═══

        if morning:
            # Auto-update shares outstanding from Yahoo Finance (225 API calls)
            try:
                update_shares()
            except Exception as e:
                logger.debug(f"Shares update: {e}")

            # Validate and auto-correct tickers (SEC + Yahoo lookups)
            try:
                validate_all_tickers()
            except Exception as e:
                logger.debug(f"Ticker validator: {e}")
        else:
            logger.debug("Heavy maintenance tasks skipped (6am only)")

        # ═══ PRIMARY SOURCE DATA COLLECTION ═══

        # Global filing scanner: SEC EDGAR + SEDAR + TDnet + DART + RNS + HKEX + ASX + more
        try:
            filing_result = scan_all_filings(days_back=1)
            # Feed global filing alerts into correlation engine
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

        # Whale monitor: Large BTC transactions on-chain → feeds into correlation engine
        try:
            whale_result = check_whale_transactions()
            # Feed whale movements into correlation engine
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
            # Get current BTC price for USD calculations
            try:
                btc = yf.Ticker("BTC-USD")
                hist = btc.history(period="2d")
                current_btc_price = float(hist["Close"].iloc[-1]) if not hist.empty else 67000
            except:
                current_btc_price = 67000

            flow_report = get_exchange_flow_report(btc_price=current_btc_price)
            if flow_report and flow_report.get("has_exchange_data"):
                signal = flow_report.get("signal", "NEUTRAL")
                netflow = flow_report.get("netflow_btc", 0)
                logger.info(f"Exchange Flow: {signal} | Net: {netflow:+,.0f} BTC | Reserve trend: {flow_report.get('reserve_trend', 'unknown')}")

                # Send to Telegram (only significant signals — not NEUTRAL)
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

        # ETF holdings: Direct from issuer websites (morning only)
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

        scan_count += 1

        # Watchlist alerts
        try:
            all_subscribers = subscribers.get_active_subscribers()
            for sub in all_subscribers:
                watchlist = sub.get("watchlist", [])
                if isinstance(watchlist, str):
                    import json as _json
                    watchlist = _json.loads(watchlist) if watchlist else []
                if not watchlist:
                    continue

                w_activity = get_watchlist_activity(
                    watchlist=watchlist,
                    signals=signals if 'signals' in dir() else [],
                    purchases=detected if 'detected' in dir() and detected else [],
                )
                high_priority = [a for a in w_activity if a["priority"] == "high"]
                if high_priority:
                    tg_msg = format_watchlist_telegram(high_priority, sub.get("name", ""))
                    if tg_msg and sub.get("telegram_chat_id"):
                        from telegram_bot import send_to_channel
                        send_to_channel(sub["telegram_chat_id"], tg_msg)
                        logger.info(f"Watchlist alert sent to {sub['name']} ({len(high_priority)} items)")
                    elif tg_msg:
                        send_to_paid(tg_msg)
                        logger.info(f"Watchlist alert for {sub['name']} sent to PAID channel ({len(high_priority)} items)")
        except Exception as e:
            logger.debug(f"Watchlist alert check: {e}")

        # Handle correlation result safely
        try:
            cor_score = correlation["market_score"]
            cor_streams = correlation["total_streams"]
            cor_level = correlation["alert_level"]
        except (NameError, TypeError):
            cor_score = 0
            cor_streams = 0
            cor_level = "NONE"

        send_scan_summary(scan_number, len(accounts), new_count if 'new_count' in dir() else 0, len(signals) if 'signals' in dir() else 0)

        logger.info(f"Tweets: {new_count if 'new_count' in dir() else '?'} | Signals: {len(signals) if 'signals' in dir() else '?'} | Correlation v2: Market {cor_score}/100 ({cor_streams}/6 streams, {cor_level})")

        # ═══ SCHEDULED SCAN TIMING ═══
        # Scans at 6am, 12pm, 6pm
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
