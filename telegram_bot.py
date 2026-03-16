"""
telegram_bot.py
---------------
Sends purchase signal alerts to a Telegram channel.
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"


def send_alert(signal):
    """
    Send a formatted purchase signal alert to the Telegram channel.
    
    Args:
        signal: dict with keys: author, company, text, url, created_at, score, label, reasons
    """
    
    # Build the message
    reasons_text = "\n".join([f"  • {r}" for r in signal["reasons"]])
    
    message = f"""
⚠️ PURCHASE SIGNAL DETECTED

{signal['label']}  Score: {signal['score']}/100

👤 Author: @{signal['author']} ({signal['company']})
📅 Date: {signal['created_at']}

💬 Tweet:
{signal['text'][:500]}

🔗 {signal.get('url', '')}

📊 Signal Reasons:
{reasons_text}

---
Treasury Purchase Signal Intelligence
"""
    
    try:
        response = requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={
                "chat_id": CHANNEL_ID,
                "text": message,
                "disable_web_page_preview": False,
            }
        )
        
        if response.status_code == 200:
            return True
        else:
            print(f"  Telegram ERROR: {response.status_code} - {response.text[:200]}")
            return False
            
    except Exception as e:
        print(f"  Telegram ERROR: {e}")
        return False


def send_scan_summary(scan_number, accounts_scanned, new_tweets, signals_found):
    """Send a brief scan summary to the channel."""
    
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
    
    try:
        requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={
                "chat_id": CHANNEL_ID,
                "text": message,
            }
        )
    except:
        pass


# ============================================
# QUICK TEST
# ============================================
if __name__ == "__main__":
    print("Testing Telegram bot...\n")
    
    if not BOT_TOKEN or "paste" in str(BOT_TOKEN):
        print("ERROR: Set TELEGRAM_BOT_TOKEN in .env")
        exit()
    
    if not CHANNEL_ID or "paste" in str(CHANNEL_ID):
        print("ERROR: Set TELEGRAM_CHANNEL_ID in .env")
        exit()
    
    print(f"Bot Token: {BOT_TOKEN[:10]}...")
    print(f"Channel ID: {CHANNEL_ID}\n")
    
    # Send a test signal
    test_signal = {
        "author": "saylor",
        "company": "Strategy (MSTR)",
        "text": "Stretch the Orange Dots. https://t.co/WMVPUxlIcx",
        "url": "https://x.com/saylor/status/2033148137678704725",
        "created_at": "Sun Mar 15 11:47:44 +0000 2026",
        "score": 90,
        "label": "🔴 VERY HIGH",
        "reasons": [
            "High-priority author: @saylor (+25)",
            "Strong keywords: ['orange dots', 'stretch the orange'] (+40)",
            "Short/cryptic post (5 words) from key author (+15)",
            "Posted on weekend (Sunday) (+10)",
        ],
    }
    
    print("Sending test alert to Telegram channel...")
    success = send_alert(test_signal)
    
    if success:
        print("SUCCESS! Check your Telegram channel — you should see the alert!")
    else:
        print("Failed to send. Check your bot token and channel ID.")
