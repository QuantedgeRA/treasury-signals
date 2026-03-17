import json
import time
import os
import requests as req
from dotenv import load_dotenv
from twitter_client import get_user_tweets, extract_tweet_info
from database import save_tweet, get_new_tweets, mark_processed
from classifier import classify_tweet, get_signal_label
from telegram_bot import send_alert, send_scan_summary
from strc_tracker import get_strc_volume_data, analyze_strc_signal, format_strc_alert
from edgar_monitor import scan_edgar_filings, format_edgar_alert

load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")

# Track already-alerted filings so we don't send duplicates
alerted_filings = set()


def send_telegram(message):
    try:
        req.post(
            f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage',
            json={'chat_id': CHANNEL_ID, 'text': message}
        )
        return True
    except:
        return False


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
            if result['score'] >= 60:
                print(f'  >> SENDING ALERT: {signal["label"]} from @{signal["author"]}')
                success = send_alert(signal)
                if success:
                    alerts_sent += 1
                    print('  >> Alert sent to Telegram!')
    print(f'  Classified {len(unprocessed)} tweets. Found {len(signals)} signals. Sent {alerts_sent} alerts.')
    return signals, alerts_sent


def check_strc_volume():
    strc_data = get_strc_volume_data()
    if strc_data:
        strc_analysis = analyze_strc_signal(strc_data)
        print(f'  STRC: ${strc_data["dollar_volume_m"]}M volume, {strc_data["volume_ratio"]}x average -- {strc_analysis["level"]}')
        if strc_analysis['is_signal']:
            strc_message = format_strc_alert(strc_data, strc_analysis)
            if send_telegram(strc_message):
                print('  >> STRC alert sent to Telegram!')
            else:
                print('  >> Failed to send STRC alert.')
        return strc_data, strc_analysis
    else:
        print('  STRC: Could not fetch data.')
        return None, None


def check_edgar_filings():
    global alerted_filings
    noteworthy = scan_edgar_filings(days_back=3)
    new_filings = 0
    
    if noteworthy:
        for filing in noteworthy:
            # Create unique ID to avoid duplicate alerts
            filing_id = f"{filing['ticker']}_{filing['date']}_{filing.get('url', '')[:50]}"
            
            if filing_id not in alerted_filings:
                alerted_filings.add(filing_id)
                new_filings += 1
                
                label = "BTC-RELATED" if filing['is_btc_related'] else "HIGH-PRIORITY"
                print(f'  >> {label}: {filing["company"]} filed 8-K on {filing["date"]}')
                
                alert_message = format_edgar_alert(filing)
                if send_telegram(alert_message):
                    print(f'  >> EDGAR alert sent to Telegram!')
                else:
                    print(f'  >> Failed to send EDGAR alert.')
            else:
                print(f'  Already alerted: {filing["company"]} 8-K from {filing["date"]}')
    
    print(f'  {len(noteworthy)} noteworthy filing(s) found, {new_filings} new alert(s) sent.')
    return noteworthy


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
    print('  TREASURY PURCHASE SIGNAL INTELLIGENCE')
    print('  Full Pipeline: Tweets + Classifier + STRC + EDGAR + Telegram')
    print('=' * 60)
    print()
    accounts = load_accounts()
    print(f'Monitoring {len(accounts)} X accounts.')
    print(f'Monitoring {len(TREASURY_COMPANIES)} companies on SEC EDGAR.')
    print(f'Tracking STRC issuance volume.')
    print(f'Alerts sent to Telegram for HIGH+ signals.')
    scan_number = 0
    while True:
        scan_number += 1
        current_time = time.strftime('%Y-%m-%d %H:%M:%S')
        print(f'\n{"="*60}')
        print(f'  SCAN #{scan_number} at {current_time}')
        print(f'{"="*60}\n')

        # Step 1: Fetch tweets
        print('[1/4] Fetching tweets...\n')
        new_count, skip_count = scan_all_accounts(accounts)
        print(f'\n  {new_count} new, {skip_count} duplicates.\n')

        # Step 2: Classify + Alert
        print('[2/4] Classifying + sending alerts...\n')
        signals, alerts_sent = process_and_alert()
        display_signals(signals)
        if not signals:
            print('\n  No purchase signals this scan.')

        # Step 3: Check STRC volume
        print('\n[3/4] Checking STRC issuance volume...\n')
        check_strc_volume()

        # Step 4: Check SEC EDGAR filings
        print('\n[4/4] Checking SEC EDGAR for 8-K filings...\n')
        check_edgar_filings()

        # Send scan summary to Telegram
        send_scan_summary(scan_number, len(accounts), new_count, len(signals))
        print(f'\n  Scan #{scan_number} done. {alerts_sent} tweet alerts sent.')

        # Wait
        wait_minutes = 15
        print(f'  Next scan in {wait_minutes} minutes. Press Ctrl+C to stop.\n')
        try:
            time.sleep(wait_minutes * 60)
        except KeyboardInterrupt:
            print('\n\nStopped by user. Goodbye!')
            break


# Need this for the EDGAR company list reference
from edgar_monitor import TREASURY_COMPANIES

if __name__ == '__main__':
    main()
