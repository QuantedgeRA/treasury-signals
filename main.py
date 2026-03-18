"""
main.py — Treasury Signal Intelligence v2.0
Full automated pipeline with all features integrated.

Runs every 15 minutes:
  1. Scan tweets from 24+ executive accounts
  2. Classify signals + send Telegram alerts
  3. Check STRC issuance volume
  4. Check SEC EDGAR for 8-K filings
  5. Run Multi-Signal Correlation Engine
  6. Auto-log predictions when confidence is high
  7. Send daily email briefing at 7am ET
"""

import json
import time
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from twitter_client import get_user_tweets, extract_tweet_info
from database import save_tweet, get_new_tweets, mark_processed
from classifier import classify_tweet, get_signal_label
from telegram_bot import send_alert, send_scan_summary, send_strc_alert, send_edgar_alert, send_to_paid, send_to_free
from strc_tracker import get_strc_volume_data, analyze_strc_signal, format_strc_alert
from edgar_monitor import scan_edgar_filings, format_edgar_alert, TREASURY_COMPANIES
from correlation_engine import CorrelationEngine
from accuracy_tracker import log_prediction
from email_briefing import generate_and_send_briefing
from treasury_leaderboard import get_leaderboard_with_live_price, format_leaderboard_telegram
from regulatory_tracker import format_regulatory_briefing
import yfinance as yf

load_dotenv()

# Initialize persistent objects
engine = CorrelationEngine()
alerted_filings = set()
last_correlation_alert_score = 0
last_email_date = None
last_leaderboard_date = None
# Track what we've already sent to avoid duplicate notifications
sent_tweet_ids = set()
sent_strc_status = None
sent_edgar_ids = set()
sent_correlation_score = 0

# Email recipients (add more as customers sign up)
EMAIL_RECIPIENTS = [
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
        print(f'  Scanning @{username} ({company})...', end=' ')
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
            print(f'Got {len(tweets)} tweets, {account_new} new.')
        else:
            print('No tweets returned.')
    return new_count, skip_count


def process_and_alert():
    global sent_tweet_ids
    unprocessed = get_new_tweets()
    if not unprocessed:
        print('  No new tweets to classify.')
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
            }
            signals.append(signal)

            # Feed into correlation engine
            if result['score'] >= 60:
                engine.add_tweet_signal(tweet['author_username'], result['score'], tweet['tweet_text'])

                # Auto-log prediction
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
                    company=company_name,
                    ticker=ticker,
                    signal_type="tweet",
                    signal_score=result['score'],
                    signal_details=f"@{tweet['author_username']}: {tweet['tweet_text'][:200]}",
                )

            # Only send Telegram alert if we haven't already sent this tweet
            tweet_id = tweet.get('tweet_id', tweet['tweet_text'][:50])
            if tweet_id not in sent_tweet_ids:
                sent_tweet_ids.add(tweet_id)
                print(f'  >> SENDING ALERT: {signal["label"]} from @{signal["author"]}')
                success = send_alert(signal, delay_free=True)
                if success:
                    alerts_sent += 1
            else:
                print(f'  >> Already sent alert for this tweet, skipping.')

    print(f'  Classified {len(unprocessed)} tweets. Found {len(signals)} signals. Sent {alerts_sent} alerts.')
    return signals, alerts_sent


def check_strc_volume():
    global sent_strc_status
    strc_data = get_strc_volume_data()
    if strc_data:
        strc_analysis = analyze_strc_signal(strc_data)
        print(f'  STRC: ${strc_data["dollar_volume_m"]}M volume, {strc_data["volume_ratio"]}x average -- {strc_analysis["level"]}')

        # Only send alert if status changed
        current_status = strc_analysis["level"]
        if strc_analysis['is_signal'] and current_status != sent_strc_status:
            engine.add_strc_spike(strc_data['volume_ratio'], strc_data['dollar_volume_m'])

            log_prediction(
                company="Strategy (MSTR)",
                ticker="MSTR",
                signal_type="strc_volume",
                signal_score=min(int(strc_data['volume_ratio'] * 30), 90),
                signal_details=f"STRC volume spike: {strc_data['volume_ratio']}x normal, ${strc_data['dollar_volume_m']}M",
            )

            strc_message = format_strc_alert(strc_data, strc_analysis)
            is_very_high = strc_data['volume_ratio'] >= 2.0
            send_strc_alert(strc_message, is_high=is_very_high)
            sent_strc_status = current_status
        elif current_status == sent_strc_status:
            print(f'  STRC status unchanged ({current_status}), no notification sent.')

        return strc_data, strc_analysis
    else:
        print('  STRC: Could not fetch data.')
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
                    company=filing['company'],
                    ticker=filing['ticker'],
                    signal_type="edgar_8k",
                    signal_score=70 if filing['is_btc_related'] else 40,
                    signal_details=f"8-K filing on {filing['date']}: {filing.get('description', '')}",
                )

                label = "BTC-RELATED" if filing['is_btc_related'] else "HIGH-PRIORITY"
                print(f'  >> {label}: {filing["company"]} filed 8-K on {filing["date"]}')
                alert_message = format_edgar_alert(filing)
                send_edgar_alert(alert_message)
            else:
                print(f'  Already alerted: {filing["company"]} 8-K from {filing["date"]}')
    print(f'  {len(noteworthy)} noteworthy filing(s) found, {new_filings} new alert(s) sent.')
    return noteworthy


def check_correlation():
    """Run correlation engine and send alert only if score changed significantly."""
    global last_correlation_alert_score, sent_correlation_score

    result = engine.calculate_correlation()
    score = result['correlated_score']
    active = result['active_streams']
    level = result['alert_level']

    print(f'  Correlation: {score}/100 | {active}/4 streams | {level}')

    if active >= 1:
        for reason in result['reasons']:
            print(f'    {reason}')

    # Auto-log correlation prediction
    if score >= 50 and active >= 2:
        log_prediction(
            company="Multi-Signal",
            ticker="MSTR",
            signal_type="correlation",
            signal_score=score,
            signal_details=f"{active}/4 streams active. Multiplier: {result['multiplier']}x. {'; '.join(result['reasons'][:3])}",
        )

    # Only send if score increased significantly AND is different from last sent
    if score >= 50 and (score - last_correlation_alert_score) >= 15 and score != sent_correlation_score:
        alert_message = engine.format_correlation_alert(result)
        send_to_paid(alert_message)
        print(f'  >> Correlation alert sent to PAID channel!')
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
            print(f'  >> Critical alert sent to FREE channel!')

        last_correlation_alert_score = score
    elif score == sent_correlation_score:
        print(f'  Correlation unchanged ({score}/100), no notification sent.')

    if score < 30:
        last_correlation_alert_score = 0
        sent_correlation_score = 0

    return result


def send_daily_email():
    """Send the daily email briefing at 7am ET (once per day)."""
    global last_email_date
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    # Send at 7am or later, but only once per day
    if now.hour >= 7 and last_email_date != today:
        print(f'  Sending daily email briefing to {len(EMAIL_RECIPIENTS)} recipient(s)...')
        for email in EMAIL_RECIPIENTS:
            try:
                success, _ = generate_and_send_briefing(email)
                if success:
                    print(f'  ✅ Briefing sent to {email}')
                else:
                    print(f'  ❌ Failed to send to {email}')
            except Exception as e:
                print(f'  ❌ Email error for {email}: {e}')
        last_email_date = today
    else:
        if last_email_date == today:
            print(f'  Daily briefing already sent today.')
        else:
            print(f'  Daily briefing scheduled for 7am (current hour: {now.hour}).')


def send_daily_leaderboard():
    """Send leaderboard update to Telegram once per day at 8am."""
    global last_leaderboard_date
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    if now.hour >= 8 and last_leaderboard_date != today:
        print(f'  Sending daily leaderboard to Telegram...')
        try:
            btc = yf.Ticker("BTC-USD")
            hist = btc.history(period="5d")
            btc_price = float(hist["Close"].iloc[-1]) if not hist.empty else 72000
            companies, summary = get_leaderboard_with_live_price(btc_price)
            message = format_leaderboard_telegram(companies, summary)
            send_to_paid(message)
            print(f'  ✅ Leaderboard sent to PAID channel')
            last_leaderboard_date = today
        except Exception as e:
            print(f'  ❌ Leaderboard error: {e}')
    else:
        if last_leaderboard_date == today:
            print(f'  Daily leaderboard already sent today.')
        else:
            print(f'  Daily leaderboard scheduled for 8am (current hour: {now.hour}).')


def display_signals(signals):
    if not signals:
        return
    signals.sort(key=lambda x: x['score'], reverse=True)
    print()
    print('!' * 60)
    print('  PURCHASE SIGNALS DETECTED')
    print('!' * 60)
    for sig in signals:
        print()
        print(f'  {sig["label"]}  Score: {sig["score"]}/100')
        print(f'  Author:  @{sig["author"]} ({sig["company"]})')
        print(f'  Tweet:   {sig["text"][:200]}')
        if sig['url']:
            print(f'  Link:    {sig["url"]}')
        print('-' * 60)


def main():
    print()
    print('=' * 60)
    print('  TREASURY PURCHASE SIGNAL INTELLIGENCE v2.0')
    print('  Full Automated Pipeline')
    print('=' * 60)
    print()
    accounts = load_accounts()
    print(f'  Monitoring {len(accounts)} X accounts')
    print(f'  Monitoring {len(TREASURY_COMPANIES)} companies on SEC EDGAR')
    print(f'  Tracking STRC issuance volume')
    print(f'  Multi-Signal Correlation Engine: ACTIVE')
    print(f'  Auto-Prediction Logging: ACTIVE')
    print(f'  Daily Email Briefing: ACTIVE ({len(EMAIL_RECIPIENTS)} recipients)')
    print(f'  Daily Leaderboard: ACTIVE')
    print(f'  FREE channel: Saylor-only, delayed')
    print(f'  PAID channel: Full access, instant, correlated alerts')

    scan_number = 0
    while True:
        scan_number += 1
        current_time = time.strftime('%Y-%m-%d %H:%M:%S')
        print(f'\n{"="*60}')
        print(f'  SCAN #{scan_number} at {current_time}')
        print(f'{"="*60}\n')

        print('[1/8] Fetching tweets...\n')
        new_count, skip_count = scan_all_accounts(accounts)
        print(f'\n  {new_count} new, {skip_count} duplicates.\n')

        print('[2/8] Classifying + sending alerts...\n')
        signals, alerts_sent = process_and_alert()
        display_signals(signals)
        if not signals:
            print('\n  No purchase signals this scan.')

        print('\n[3/8] Checking STRC issuance volume...\n')
        check_strc_volume()

        print('\n[4/8] Checking SEC EDGAR for 8-K filings...\n')
        check_edgar_filings()

        print('\n[5/8] Running Multi-Signal Correlation Engine...\n')
        correlation = check_correlation()

        print('\n[6/8] Checking daily email briefing...\n')
        send_daily_email()

        print('\n[7/8] Checking daily leaderboard...\n')
        send_daily_leaderboard()

        print('\n[8/8] Scan complete.\n')
        send_scan_summary(scan_number, len(accounts), new_count, len(signals))
        print(f'  Scan #{scan_number} done.')
        print(f'  Tweets: {new_count} new | Signals: {len(signals)} | Alerts: {alerts_sent}')
        print(f'  Correlation: {correlation["correlated_score"]}/100 ({correlation["active_streams"]}/4 streams)')

        wait_minutes = 60
        print(f'\n  Next scan in {wait_minutes} minutes. Press Ctrl+C to stop.\n')
        try:
            time.sleep(wait_minutes * 60)
        except KeyboardInterrupt:
            print('\n\nStopped by user. Goodbye!')
            break


if __name__ == '__main__':
    main()