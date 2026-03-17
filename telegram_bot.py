"""
telegram_bot.py
---------------
Sends alerts to FREE and PAID Telegram channels.

FREE channel: Saylor-only signals, delayed, limited STRC/EDGAR alerts
PAID channel: All accounts, instant, full STRC + EDGAR alerts
"""

import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
FREE_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
PAID_CHANNEL_ID = os.getenv("TELEGRAM_PAID_CHANNEL_ID")

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"


def send_to_channel(channel_id, message):
    """Send a message to a specific Telegram channel."""
    try:
        response = requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={
                "chat_id": channel_id,
                "text": message,
                "disable_web_page_preview": False,
            }
        )
        return response.status_code == 200
    except Exception as e:
        print(f"  Telegram ERROR: {e}")
        return False


def send_to_free(message):
    """Send to the free public channel."""
    if FREE_CHANNEL_ID:
        return send_to_channel(FREE_CHANNEL_ID, message)
    return False


def send_to_paid(message):
    """Send to the paid private channel."""
    if PAID_CHANNEL_ID:
        return send_to_channel(PAID_CHANNEL_ID, message)
    return False


def send_alert(signal, delay_free=True):
    """
    Send a purchase signal alert.
    
    PAID channel: gets ALL signals instantly
    FREE channel: gets only Saylor signals, with 1 hour delay
    """
    
    message = f"""
⚠️ PURCHASE SIGNAL DETECTED

{signal['label']}  Score: {signal['score']}/100

👤 Author: @{signal['author']} ({signal['company']})
📅 Date: {signal['created_at']}

💬 Tweet:
{signal['text'][:500]}

🔗 {signal.get('url', '')}

📊 Signal Reasons:
""" + "\n".join([f"  • {r}" for r in signal["reasons"]]) + """

---
Treasury Purchase Signal Intelligence
"""
    
    # PAID channel: always gets full alert instantly
    paid_sent = send_to_paid(message)
    if paid_sent:
        print("  >> Alert sent to PAID channel!")
    
    # FREE channel: only Saylor, with delay
    author_lower = signal.get('author', '').lower()
    is_saylor = author_lower in ['saylor', 'michael_saylor']
    
    if is_saylor and signal['score'] >= 60:
        if delay_free:
            # Add delay notice to free version
            free_message = f"""
⚠️ PURCHASE SIGNAL DETECTED (Delayed)

{signal['label']}  Score: {signal['score']}/100

👤 Author: @{signal['author']} ({signal['company']})

💬 Tweet:
{signal['text'][:200]}...

🔗 {signal.get('url', '')}

⏰ This alert was delayed by 1 hour.
🔓 Get instant alerts for ALL 24+ accounts → upgrade to PRO

---
Treasury Purchase Signal Intelligence (Free Tier)
"""
            # Delay 1 hour for free channel
            def delayed_send():
                time.sleep(3600)  # 1 hour
                send_to_free(free_message)
            
            import threading
            thread = threading.Thread(target=delayed_send, daemon=True)
            thread.start()
            print("  >> Free channel alert scheduled (1hr delay, Saylor only)")
        else:
            send_to_free(message)
    
    return paid_sent


def send_strc_alert(message, is_high=False):
    """
    Send STRC volume alert.
    
    PAID: gets all STRC alerts
    FREE: only gets alerts when volume is 2x+ normal
    """
    # Always send to paid
    send_to_paid(message)
    print("  >> STRC alert sent to PAID channel!")
    
    # Only send to free if really high volume (2x+)
    if is_high:
        free_message = message + "\n🔓 Get all STRC alerts → upgrade to PRO"
        send_to_free(free_message)
        print("  >> STRC alert sent to FREE channel (high volume)!")


def send_edgar_alert(message):
    """
    Send EDGAR filing alert.
    
    PAID: gets all filing alerts
    FREE: does not get EDGAR alerts
    """
    send_to_paid(message)
    print("  >> EDGAR alert sent to PAID channel!")
    
    # Free channel does NOT get EDGAR alerts
    # This is a paid-only feature


def send_scan_summary(scan_number, accounts_scanned, new_tweets, signals_found):
    """Send scan summary to PAID channel only."""
    
    if signals_found == 0:
        emoji = "✅"
        status = "No purchase signals detected"
    else:
        emoji = "🚨"
        status = f"{signals_found} purchase signal(s) detected!"
    
    message = f"""
{emoji} Scan #{scan_number} Complete

📊 Accounts scanned: {accounts_scanned}
🆕 New tweets: {new_tweets}
🔍 Signals found: {signals_found}

Status: {status}
"""
    
    # Only paid channel gets scan summaries
    send_to_paid(message)


# ============================================
# QUICK TEST
# ============================================
if __name__ == "__main__":
    print("Testing Telegram bot (dual channel)...\n")
    
    print(f"Free Channel:  {FREE_CHANNEL_ID}")
    print(f"Paid Channel:  {PAID_CHANNEL_ID}\n")
    
    if not PAID_CHANNEL_ID:
        print("ERROR: Set TELEGRAM_PAID_CHANNEL_ID in .env")
        exit()
    
    # Test paid channel
    print("Sending test to PAID channel...")
    success = send_to_paid("🔒 PRO TEST: This is a test alert for the paid channel. Full access enabled.")
    print(f"  Paid channel: {'SUCCESS' if success else 'FAILED'}")
    
    # Test free channel
    print("Sending test to FREE channel...")
    success = send_to_free("📢 FREE TEST: This is a test alert for the free channel.")
    print(f"  Free channel: {'SUCCESS' if success else 'FAILED'}")
    
    print("\nDual channel bot is working!")