import json
import time
import os
from dotenv import load_dotenv
from twitter_client import get_user_tweets, extract_tweet_info
from database import save_tweet, get_new_tweets, mark_processed
from classifier import classify_tweet, get_signal_label
from telegram_bot import send_alert, send_scan_summary, send_strc_alert, send_edgar_alert, send_to_paid, send_to_free
from strc_tracker import get_strc_volume_data, analyze_strc_signal, format_strc_alert
from edgar_monitor import scan_edgar_filings, format_edgar_alert, TREASURY_COMPANIES
from correlation_engine import CorrelationEngine

load_dotenv()

# Initialize the correlation engine (persists across scans)
engine = CorrelationEngine()

# Track already-alerted filings
alerted_filings = set()
last_correlation_alert_score = 0


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
            
            # Feed into correlation engine
            if result['score'] >= 60:
                engine.add_tweet_signal(tweet['author_username'], result['score'], tweet['tweet_text'])
                print(f'  >> SENDING ALERT: {signal["label"]} from @{signal["author"]}')
                success = send_alert(signal, delay_free=True)
                if success:
                    alerts_sent += 1
    print(f'  Classified {len(unprocessed)} tweets. Found {len(signals)} signals. Sent {alerts_sent} alerts.')
    return signals, alerts_sent


def check_strc_volume():
    strc_data = get_strc_volume_data()
    if strc_data:
        strc_analysis = analyze_strc_signal(strc_data)
        print(f'  STRC: ${strc_data["dollar_volume_m"]}M volume, {strc_data["volume_ratio"]}x average -- {strc_analysis["level"]}')
        if strc_analysis['is_signal']:
            # Feed into correlation engine
            engine.add_strc_spike(strc_data['volume_ratio'], strc_data['dollar_volume_m'])
            strc_message = format_strc_alert(strc_data, strc_analysis)
            is_very_high = strc_data['volume_ratio'] >= 2.0
            send_strc_alert(strc_message, is_high=is_very_high)
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
            filing_id = f"{filing['ticker']}_{filing['date']}_{filing.get('url', '')[:50]}"
            if filing_id not in alerted_filings:
                alerted_filings.add(filing_id)
                new_filings += 1
                # Feed into correlation engine
                engine.add_edgar_filing(filing['company'], filing['ticker'], filing['is_btc_related'], filing['date'])
                label = "BTC-RELATED" if filing['is_btc_related'] else "HIGH-PRIORITY"
                print(f'  >> {label}: {filing["company"]} filed 8-K on {filing["date"]}')
                alert_message = format_edgar_alert(filing)
                send_edgar_alert(alert_message)
            else:
                print(f'  Already alerted: {filing["company"]} 8-K from {filing["date"]}')
    print(f'  {len(noteworthy)} noteworthy filing(s) found, {new_filings} new alert(s) sent.')
    return noteworthy


def check_correlation():
    """Run the correlation engine and send alert if score is significant."""
    global last_correlation_alert_score
    
    result = engine.calculate_correlation()
    score = result['correlated_score']
    active = result['active_streams']
    level = result['alert_level']
    
    print(f'  Correlation: {score}/100 | {active}/4 streams | {level}')
    
    if active >= 1:
        for reason in result['reasons']:
            print(f'    {reason}')
    
    # Send correlation alert if score is HIGH+ and has increased significantly
    if score >= 50 and (score - last_correlation_alert_score) >= 15:
        alert_message = engine.format_correlation_alert(result)
        send_to_paid(alert_message)
        print(f'  >> Correlation alert sent to PAID channel!')
        
        # Also send to free if CRITICAL
        if score >= 90:
            free_message = f"""
🔗 CRITICAL MULTI-SIGNAL ALERT

Correlated Score: {score}/100
Active Streams: {active}/4

{result['narrative']}

🔓 Full details available in PRO channel.
Subscribe for instant multi-source correlation alerts.
"""
            send_to_free(free_message)
            print(f'  >> Critical correlation alert sent to FREE channel!')
        
        last_correlation_alert_score = score
    
    # Reset if score drops back down
    if score < 30:
        last_correlation_alert_score = 0
    
    return result


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
    print('  Full Pipeline + Multi-Signal Correlation Engine')
    print('=' * 60)
    print()
    accounts = load_accounts()
    print(f'Monitoring {len(accounts)} X accounts.')
    print(f'Monitoring {len(TREASURY_COMPANIES)} companies on SEC EDGAR.')
    print(f'Tracking STRC issuance volume.')
    print(f'Multi-Signal Correlation Engine: ACTIVE')
    print(f'FREE channel: Saylor-only, delayed.')
    print(f'PAID channel: Full access, instant, correlated alerts.')
    scan_number = 0
    while True:
        scan_number += 1
        current_time = time.strftime('%Y-%m-%d %H:%M:%S')
        print(f'\n{"="*60}')
        print(f'  SCAN #{scan_number} at {current_time}')
        print(f'{"="*60}\n')

        print('[1/5] Fetching tweets...\n')
        new_count, skip_count = scan_all_accounts(accounts)
        print(f'\n  {new_count} new, {skip_count} duplicates.\n')

        print('[2/5] Classifying + sending alerts...\n')
        signals, alerts_sent = process_and_alert()
        display_signals(signals)
        if not signals:
            print('\n  No purchase signals this scan.')

        print('\n[3/5] Checking STRC issuance volume...\n')
        check_strc_volume()

        print('\n[4/5] Checking SEC EDGAR for 8-K filings...\n')
        check_edgar_filings()

        print('\n[5/5] Running Multi-Signal Correlation Engine...\n')
        correlation = check_correlation()

        send_scan_summary(scan_number, len(accounts), new_count, len(signals))
        print(f'\n  Scan #{scan_number} done. {alerts_sent} tweet alerts sent.')
        print(f'  Correlation: {correlation["correlated_score"]}/100 ({correlation["active_streams"]}/4 streams)')

        wait_minutes = 15
        print(f'  Next scan in {wait_minutes} minutes. Press Ctrl+C to stop.\n')
        try:
            time.sleep(wait_minutes * 60)
        except KeyboardInterrupt:
            print('\n\nStopped by user. Goodbye!')
            break


if __name__ == '__main__':
    main()
