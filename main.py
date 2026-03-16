"""
main.py - Treasury Purchase Signal Intelligence
Week 4: Full pipeline with Telegram alerts
"""

import json
import time
from twitter_client import get_user_tweets, extract_tweet_info
from database import save_tweet, get_new_tweets, mark_processed
from classifier import classify_tweet, get_signal_label
from telegram_bot import send_alert, send_scan_summary


def load_accounts():
    try:
        with open("accounts.json", "r") as f:
            data = json.load(f)
            return data["accounts"]
    except FileNotFoundError:
        print("ERROR: accounts.json not found!")
        exit()


def scan_all_accounts(accounts):
    new_count = 0
    skip_count = 0

    for account in accounts:
        username = account["username"]
        company = account.get("company", "")

        print(f"  Scanning @{username} ({company})...", end=" ")

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
            print(f"Got {len(tweets)} tweets, {account_new} new.")
        else:
            print("No tweets returned.")

    return new_count, skip_count


def process_and_alert():
    """Classify new tweets and send Telegram alerts for signals."""
    unprocessed = get_new_tweets()

    if not unprocessed:
        print("  No new tweets to classify.")
        return [], 0

    signals = []
    alerts_sent = 0

    for tweet in unprocessed:
        result = classify_tweet(
            tweet_text=tweet["tweet_text"],
            author_username=tweet["author_username"],
            created_at=tweet["created_at"],
            is_reply=tweet.get("is_reply", False),
        )

        mark_processed(
            tweet_id=tweet["tweet_id"],
            is_signal=result["is_signal"],
            confidence_score=result["score"],
        )

        if result["is_signal"]:
            signal = {
                "author": tweet["author_username"],
                "company": tweet.get("company", ""),
                "text": tweet["tweet_text"],
                "url": tweet.get("tweet_url", ""),
                "created_at": tweet["created_at"],
                "score": result["score"],
                "label": get_signal_label(result["score"]),
                "reasons": result["reasons"],
            }
            signals.append(signal)

            # Send Telegram alert for HIGH and VERY HIGH signals
            if result["score"] >= 60:
                print(f"\n  >> SENDING ALERT: {signal['label']} from @{signal['author']}")
                success = send_alert(signal)
                if success:
                    alerts_sent += 1
                    print(f"  >> Alert sent to Telegram!")
                else:
                    print(f"  >> Failed to send alert.")

    print(f"  Classified {len(unprocessed)} tweets. Found {len(signals)} signals. Sent {alerts_sent} alerts.")
    return signals, alerts_sent


def display_signals(signals):
    if not signals:
        return

    signals.sort(key=lambda x: x["score"], reverse=True)

    print()
    print("!" * 60)
    print("  PURCHASE SIGNALS DETECTED")
    print("!" * 60)

    for sig in signals:
        print()
        print(f"  {sig['label']}  Score: {sig['score']}/100")
        print(f"  Author:  @{sig['author']} ({sig['company']})")
        print(f"  Tweet:   {sig['text'][:200]}")
        if sig['url']:
            print(f"  Link:    {sig['url']}")
        print("-" * 60)


def main():
    print()
    print("=" * 60)
    print("  TREASURY PURCHASE SIGNAL INTELLIGENCE")
    print("  Week 4: Full pipeline with Telegram alerts")
    print("=" * 60)
    print()

    accounts = load_accounts()
    print(f"Monitoring {len(accounts)} accounts.")
    print(f"Alerts will be sent to Telegram for HIGH+ signals.\n")

    scan_number = 0

    while True:
        scan_number += 1
        current_time = time.strftime("%Y-%m-%d %H:%M:%S")

        print(f"\n{'='*60}")
        print(f"  SCAN #{scan_number} at {current_time}")
        print(f"{'='*60}\n")

        # Step 1: Fetch
        print("[1/2] Fetching tweets...\n")
        new_count, skip_count = scan_all_accounts(accounts)
        print(f"\n  {new_count} new, {skip_count} duplicates.\n")

        # Step 2: Classify + Alert
        print("[2/2] Classifying + sending alerts...\n")
        signals, alerts_sent = process_and_alert()

        # Show signals in terminal
        display_signals(signals)

        if not signals:
            print("\n  No purchase signals this scan.")

        # Send scan summary to Telegram
        send_scan_summary(scan_number, len(accounts), new_count, len(signals))

        print(f"\n  Scan #{scan_number} done. {alerts_sent} Telegram alerts sent.")

        # Wait
        wait_minutes = 10
        print(f"  Next scan in {wait_minutes} minutes. Press Ctrl+C to stop.\n")

        try:
            time.sleep(wait_minutes * 60)
        except KeyboardInterrupt:
            print("\n\nStopped by user. Goodbye!")
            break


if __name__ == "__main__":
    main()