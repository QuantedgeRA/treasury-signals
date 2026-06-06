"""scheduler/helpers — moved from main.py.

Cross-scan state (sent_tweet_ids, last_email_date, etc.) lives here as
module-level globals because it has to persist across the while-True loop
in main(). Phases mutate these globals through the helper functions.

Future cleanup (separate PR): these globals are the last meaningful piece
of "global mutable state" in the codebase. They could move into a small
DeliveryTracker class so phases inject it explicitly. For now, module
globals match the pre-refactor pattern with no behavior change.
"""

from datetime import datetime

import yfinance as yf

from treasury_signals.logger import get_logger
from treasury_signals.config import FALLBACK_EMAIL_RECIPIENTS
from treasury_signals.scheduler import engine
from treasury_signals.scanners.twitter_client import get_user_tweets, extract_tweet_info
from treasury_signals.storage.database import save_tweet, get_new_tweets, mark_processed, claim_tweet
from treasury_signals.pipelines.classifier import classify_tweet, get_signal_label, get_dimension_breakdown
from treasury_signals.alerts.telegram_bot import send_alert, send_strc_alert, send_to_paid, send_to_free
from treasury_signals.scanners.strc_tracker import get_strc_volume_data, analyze_strc_signal, format_strc_alert
from treasury_signals.alerts.email_briefing import generate_and_send_briefing
from treasury_signals.alerts.treasury_leaderboard import get_leaderboard_with_live_price, format_leaderboard_telegram
from treasury_signals.storage.subscriber_manager import subscribers
from treasury_signals.alerts.pro_briefing import send_pro_briefings
from treasury_signals.alerts.telegram_alerts import alerts as telegram_alerts

logger = get_logger(__name__)


# ─── Cross-scan state (persists across loop iterations) ────────────────────

last_correlation_alert_score = 0
last_email_date = None
last_leaderboard_date = None
sent_tweet_ids = set()
sent_strc_status = None
sent_correlation_score = 0

# FALLBACK_EMAIL_RECIPIENTS is now sourced from treasury_signals.config
# (single source of truth — change there, not here).


# ─── is-morning helper (used by phases AND main loop for the scan-type log) ─

def is_morning_scan():
    """True if the current scan should run heavy 6am maintenance tasks."""
    return datetime.now().hour < 9


# ─── Tweet fetching ────────────────────────────────────────────────────────

def scan_all_accounts(accounts):
    """Fetch tweets from each monitored X account, save new ones to DB."""
    import time as _time
    new_count = 0
    skip_count = 0
    for account in accounts:
        username = account['username']
        company = account.get('company', '')
        logger.debug(f"Scanning @{username} ({company})...")
        _time.sleep(6)
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


# ─── Tweet classification + alerting ───────────────────────────────────────

def process_and_alert():
    """Classify all unprocessed tweets, alert on signals, return (signals, alerts_sent)."""
    global sent_tweet_ids
    unprocessed = get_new_tweets()
    if not unprocessed:
        logger.info("No new tweets to classify")
        return [], 0
    signals = []
    alerts_sent = 0
    from treasury_signals.pipelines.exec_signal_detector import detect_exec_signal

    for tweet in unprocessed:
        # Atomic claim before doing any work: only the process that flips this
        # tweet's processed False->True classifies + alerts it. Stops duplicate
        # signal alerts when the worker and a fast_tweets cron (or two cron
        # ticks) pull the same unprocessed tweet concurrently.
        if not claim_tweet(tweet['tweet_id']):
            continue

        result = classify_tweet(
            tweet_text=tweet['tweet_text'],
            author_username=tweet['author_username'],
            created_at=tweet['created_at'],
            is_reply=tweet.get('is_reply', False),
        )

        # CEO pattern detector — overrides the generic classifier when a
        # known executive's tweet matches a registered pre-announcement
        # pattern (Saylor tracker, Mallers acquisition, etc.). Boosts the
        # score to detector confidence so high-conviction patterns cross
        # the 60 alert threshold even when the classifier underweights them.
        exec_signal = detect_exec_signal(tweet['author_username'], tweet['tweet_text'])
        if exec_signal.fired and exec_signal.confidence > result['score']:
            result['score'] = exec_signal.confidence
            result['is_signal'] = True
            result['pattern'] = exec_signal.pattern
            result.setdefault('reasons', []).insert(
                0, f"PATTERN [{exec_signal.pattern}]: {exec_signal.reasoning}"
            )
            logger.info(
                f"Exec pattern fired: @{tweet['author_username']} → "
                f"{exec_signal.pattern} (conf {exec_signal.confidence})"
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
                'pattern': result.get('pattern', ''),
            }
            signals.append(signal)
            logger.info(f"Signal: @{tweet['author_username']} {result['score']}/100 — {get_dimension_breakdown(result.get('dimensions', {}))}")

            if result['score'] >= 60:
                company_name = tweet.get('company', 'Unknown')
                ticker = ""
                # TODO (architectural review item): replace this hardcoded ticker
                # chain with a database lookup against treasury_companies.
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


# ─── STRC volume tracker ───────────────────────────────────────────────────

def check_strc_volume():
    """Check Strategy STRC issuance volume; alert on level changes."""
    global sent_strc_status
    strc_data = get_strc_volume_data()
    if strc_data:
        strc_analysis = analyze_strc_signal(strc_data)
        logger.info(f"STRC: ${strc_data['dollar_volume_m']}M volume, {strc_data['volume_ratio']}x avg — {strc_analysis['level']}")

        current_status = strc_analysis["level"]
        if strc_analysis['is_signal'] and current_status != sent_strc_status:
            engine.add_strc_spike(strc_data['volume_ratio'], strc_data['dollar_volume_m'])

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


# ─── Correlation Engine v2 calculation + alerting ──────────────────────────

def check_correlation():
    """Calculate v2 correlation, alert on score jumps, persist snapshot,
    return result dict.

    Order matters:
      1. Feed Claude-scored filing excerpts into the engine (Week 5
         stream — same data flow as tweets/EDGAR/whale/news).
      2. engine.calculate_correlation() rolls everything up.
      3. Persist a snapshot to pre_announcement_signals so the
         frontend feed + Slack dispatcher can read the same numbers.
      4. Telegram alert flow runs unchanged.
    """
    global last_correlation_alert_score, sent_correlation_score

    # Stream 7 feeder — Week 5 pre-announcement signals
    try:
        from treasury_signals.pipelines.pre_announcement_persister import feed_filing_excerpts_to_engine
        feed_filing_excerpts_to_engine(engine)
    except Exception as e:
        logger.debug(f"Pre-announce feeder: {e}")

    result = engine.calculate_correlation()
    market_score = result['market_score']
    total_streams = result['total_streams']
    level = result['alert_level']

    logger.info(f"Correlation v2: Market {market_score}/100 | {total_streams}/6 streams | {level}")

    # Persist snapshot for the frontend + Slack dispatcher
    try:
        from treasury_signals.pipelines.pre_announcement_persister import persist_correlation_snapshot
        persist_correlation_snapshot(result)
    except Exception as e:
        logger.debug(f"Pre-announce persister: {e}")

    # Dispatch high-score pre-announcement signals to team Slack channels.
    # 24h per-ticker cooldown + per-team watchlist filter inside the dispatcher.
    try:
        from treasury_signals.alerts.pre_announcement_alerts import dispatch_pending_signals
        dispatch_pending_signals()
    except Exception as e:
        logger.debug(f"Pre-announce dispatcher: {e}")

    for c in result['top_companies'][:3]:
        if c['score'] >= 30:
            logger.info(f"  📊 {c['company']}: {c['score']}/100 ({' + '.join(c['streams'])})")

    if result['reasons']:
        for reason in result['reasons']:
            logger.info(f"  {reason}")

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


# ─── Daily email briefing (sends only when due — 7am+, once per day) ───────

def send_daily_email():
    """Send daily briefing email if it's after 7am and not yet sent today."""
    global last_email_date
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    if now.hour >= 7 and last_email_date != today:
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
            try:
                from treasury_signals.scanners.market_intelligence import get_risk_dashboard
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

        # 7-day trial conversion drip — runs once per day after the daily
        # briefing, since both share the same "after 7am, once per day"
        # gate. Failures are swallowed so a drip outage never blocks the
        # main briefing path.
        try:
            from treasury_signals.alerts.trial_drip import send_due_trial_emails
            send_due_trial_emails()
        except Exception as e:
            logger.debug(f"Trial drip: {e}")
    else:
        if last_email_date == today:
            logger.debug("Daily briefing already sent today")
        else:
            logger.debug(f"Daily briefing scheduled for 7am (current hour: {now.hour})")


# ─── Daily leaderboard Telegram (sends only when due — 8am+, once per day) ─

def send_daily_leaderboard():
    """Send daily leaderboard to PAID Telegram channel if 8am+ and not sent today."""
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
