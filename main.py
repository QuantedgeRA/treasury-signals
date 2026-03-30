"""
main.py — Treasury Signal Intelligence v2.0
Full automated pipeline with all features integrated.

Runs every 60 minutes:
  1. Scan tweets from 24+ executive accounts
  2. Classify signals + send Telegram alerts
  3. Check STRC issuance volume
  4. Check SEC EDGAR for 8-K filings
  5. Run Multi-Signal Correlation Engine
  6. Auto-log predictions when confidence is high
  7. Send daily email briefing at 7am ET
  8. Send daily leaderboard at 8am
  9. Detect new BTC purchases
  10. Scan regulatory news & statements
  11. Ping dashboard to keep alive
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
from edgar_monitor import scan_edgar_filings, format_edgar_alert, TREASURY_COMPANIES
from correlation_engine import CorrelationEngine
from pattern_analyzer import pattern_engine
from feedback_loop import feedback_engine
from narrative_engine import narrator
from accuracy_tracker import log_prediction
from email_briefing import generate_and_send_briefing
from treasury_leaderboard import get_leaderboard_with_live_price, format_leaderboard_telegram
from purchase_tracker import detect_new_purchases, log_detected_purchases, format_purchase_telegram
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
#from velocity_tracker import velocity
#velocity.run()

logger = get_logger(__name__)

load_dotenv()

# Initialize persistent objects
engine = CorrelationEngine()
alerted_filings = set()
last_correlation_alert_score = 0
last_email_date = None
last_leaderboard_date = None
sent_tweet_ids = set()
sent_strc_status = None
sent_edgar_ids = set()
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
                engine.add_tweet_signal(tweet['author_username'], result['score'], tweet['tweet_text'])

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


def check_edgar_filings():
    global alerted_filings, sent_edgar_ids
    noteworthy = scan_edgar_filings(days_back=3)
    new_filings = 0
    if noteworthy:
        for filing in noteworthy:
            filing_id = f"{filing['ticker']}_{filing['date']}_{filing.get('url', '')[:50]}"
            if filing_id not in alerted_filings and filing_id not in sent_edgar_ids:
                alerted_filings.add(filing_id)
                sent_edgar_ids.add(filing_id)
                new_filings += 1
                engine.add_edgar_filing(filing['company'], filing['ticker'], filing['is_btc_related'], filing['date'])

                log_prediction(
                    company=filing['company'], ticker=filing['ticker'],
                    signal_type="edgar_8k",
                    signal_score=70 if filing['is_btc_related'] else 40,
                    signal_details=f"8-K filing on {filing['date']}: {filing.get('description', '')}",
                )

                label = "BTC-RELATED" if filing['is_btc_related'] else "HIGH-PRIORITY"
                logger.info(f"EDGAR: {label} — {filing['company']} filed 8-K on {filing['date']}")
                alert_message = format_edgar_alert(filing)
                send_edgar_alert(alert_message)
            else:
                logger.debug(f"Already alerted: {filing['company']} 8-K from {filing['date']}")
    logger.info(f"EDGAR: {len(noteworthy)} noteworthy filing(s), {new_filings} new alert(s)")
    return noteworthy


def check_correlation():
    global last_correlation_alert_score, sent_correlation_score

    result = engine.calculate_correlation()
    score = result['correlated_score']
    active = result['active_streams']
    level = result['alert_level']

    logger.info(f"Correlation: {score}/100 | {active}/4 streams | {level}")

    if active >= 1:
        for reason in result['reasons']:
            logger.debug(f"  {reason}")

    if score >= 50 and active >= 2:
        log_prediction(
            company="Multi-Signal", ticker="MSTR",
            signal_type="correlation", signal_score=score,
            signal_details=f"{active}/4 streams active. Multiplier: {result['multiplier']}x. {'; '.join(result['reasons'][:3])}",
        )

    if score >= 50 and (score - last_correlation_alert_score) >= 15 and score != sent_correlation_score:
        alert_message = engine.format_correlation_alert(result)
        send_to_paid(alert_message)
        logger.info(f"Correlation alert sent to PAID channel (score: {score})")
        sent_correlation_score = score

        if score >= 90:
            free_message = f"""
🔗 CRITICAL MULTI-SIGNAL ALERT

Correlated Score: {score}/100
Active Streams: {active}/4

{result['narrative']}

🔓 Full details in PRO channel.
Subscribe for instant multi-source correlation alerts.
"""
            send_to_free(free_message)
            logger.info(f"Critical correlation alert sent to FREE channel (score: {score})")

        last_correlation_alert_score = score
    elif score == sent_correlation_score:
        logger.debug(f"Correlation unchanged ({score}/100), no notification")

    if score < 30:
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
            # Fallback to hardcoded list if no subscribers exist yet
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
    else:
        if last_email_date == today:
            logger.debug("Daily briefing already sent today")
        else:
            logger.debug(f"Daily briefing scheduled for 7am (current hour: {now.hour})")

# Send personalized Pro briefings
        try:
            send_pro_briefings()
        except Exception as e:
            logger.debug(f"Pro briefing: {e}")

        # Free channel: weekly summary on Mondays only
        try:
            if datetime.now().weekday() == 0:
                telegram_alerts.send_weekly_summary()
        except Exception as e:
            logger.debug(f"Weekly summary: {e}")

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


def main():
    logger.info("=" * 60)
    logger.info("TREASURY PURCHASE SIGNAL INTELLIGENCE v2.0")
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
    logger.info(f"Monitoring {len(TREASURY_COMPANIES)} companies on SEC EDGAR")
    logger.info(f"STRC volume tracking: ACTIVE")
    logger.info(f"Correlation Engine: ACTIVE")
    logger.info(f"Auto-Prediction Logging: ACTIVE")
    logger.info(f"Daily Email Briefing: ACTIVE (subscriber-based)")
    logger.info(f"Daily Leaderboard: ACTIVE")

    scan_number = 0
    while True:
        scan_number += 1
        logger.info(f"{'='*50} SCAN #{scan_number} {'='*50}")

        with ScanContext(logger, scan_number, "[1/11] Fetching tweets"):
            new_count, skip_count = scan_all_accounts(accounts)
            logger.info(f"Tweets: {new_count} new, {skip_count} duplicates")

        with ScanContext(logger, scan_number, "[2/11] Classifying + alerting"):
            signals, alerts_sent = process_and_alert()

        with ScanContext(logger, scan_number, "[3/11] STRC issuance volume"):
            check_strc_volume()

        with ScanContext(logger, scan_number, "[4/11] SEC EDGAR 8-K filings"):
            check_edgar_filings()

        with ScanContext(logger, scan_number, "[5/11] Correlation Engine"):
            correlation = check_correlation()

            # Historical pattern matching (Phase 14)
            try:
                from market_intelligence import get_risk_dashboard
                risk_data = get_risk_dashboard()
                fg_value = risk_data.get("fear_greed_value", 50)
                btc_weekly = risk_data.get("btc_7d_change", 0)
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

        with ScanContext(logger, scan_number, "[6/11] Daily email briefing"):
            send_daily_email()

        with ScanContext(logger, scan_number, "[7/11] Daily leaderboard"):
            send_daily_leaderboard()

        with ScanContext(logger, scan_number, "[8/11] Purchase detection"):
            detected = detect_new_purchases()
            if detected:
                log_detected_purchases(detected)
                for d in detected[:3]:
                    msg = format_purchase_telegram(d)
                    send_to_paid(msg)
                    if d["btc_amount"] >= 1000:
                        send_to_free(msg)
                logger.info(f"{len(detected)} purchase(s) detected and logged")

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

        with ScanContext(logger, scan_number, "[9/11] Regulatory scan"):
            scan_regulatory()

        with ScanContext(logger, scan_number, "[10/11] Dashboard ping"):
            response = req.get("https://treasury-signals-jqyywcwr8l8pbtv66rvbbg.streamlit.app/", timeout=30)
            logger.debug(f"Dashboard ping: {response.status_code}")

        logger.info(f"[11/11] Scan #{scan_number} complete")

        # Save freshness snapshot to Supabase
        from database import supabase as db_client
        freshness.save_to_supabase(db_client)

        # Log system health
        health = freshness.get_overall_health()
        logger.info(f"System Health: {health['emoji']} {health['health'].upper()} — {health['message']}")

        # Accuracy feedback loop (Phase 15) — learn once per day
        try:
            if scan_number == 1 or (scan_number % 24 == 0):
                feedback_engine.learn()
                feedback_engine.load_from_db()
                report = feedback_engine.get_learning_report()
                if "No learning data" not in report:
                    logger.info("Feedback loop: learning cycle complete")
        except Exception as e:
            logger.debug(f"Feedback loop: {e}")

        # Price prediction model (runs once per day)
        try:
            if scan_number == 1 or (scan_number % 24 == 0):
                predictor.analyze()
        except Exception as e:
            logger.debug(f"Price predictor: {e}")

        # Sync ALL entities from BitcoinTreasuries.net to Supabase
        try:
            treasury_sync.run()
        except Exception as e:
            logger.debug(f"Treasury sync: {e}")

        # Record daily snapshots + detect new entrants
        try:
            from velocity_tracker import velocity
            velocity.run()
        except Exception as e:
            logger.debug(f"Velocity tracker: {e}")

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

        # Auto-update shares outstanding from Yahoo Finance
        try:
            update_shares()
        except Exception as e:
            logger.debug(f"Shares update: {e}")

        # Watchlist alerts (Phase 8)
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

        # Handle correlation result safely (may not exist if step 5 failed)
        try:
            cor_score = correlation["correlated_score"]
            cor_active = correlation["active_streams"]
        except (NameError, TypeError):
            cor_score = 0
            cor_active = 0

        send_scan_summary(scan_number, len(accounts), new_count if 'new_count' in dir() else 0, len(signals) if 'signals' in dir() else 0)

        logger.info(f"Tweets: {new_count if 'new_count' in dir() else '?'} | Signals: {len(signals) if 'signals' in dir() else '?'} | Correlation: {cor_score}/100 ({cor_active}/4)")

        wait_minutes = 60
        logger.info(f"Next scan in {wait_minutes} minutes. Press Ctrl+C to stop.")
        try:
            time.sleep(wait_minutes * 60)
        except KeyboardInterrupt:
            logger.info("Stopped by user. Goodbye!")
            break


if __name__ == '__main__':
    main()
