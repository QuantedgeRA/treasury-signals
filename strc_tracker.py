"""
strc_tracker.py
---------------
Tracks STRC issuance volume to detect when Strategy
is raising capital to buy Bitcoin.

Logic: When STRC daily volume spikes significantly above
its 20-day average, it means Strategy is aggressively
selling STRC shares via their ATM program. The proceeds
go directly to buying BTC — usually within days.

Key facts:
- Strategy's record was $300M STRC sold in one day
- That funded ~1,420 BTC purchase
- Normal daily volume: ~$50-100M
- Spike day: $200M+ = high probability of BTC purchase
"""

import yfinance as yf
from datetime import datetime, timedelta


def get_strc_volume_data():
    """
    Fetch STRC's recent trading data from Yahoo Finance.
    Returns a dict with today's volume, average volume, and ratio.
    """
    try:
        strc = yf.Ticker("STRC")
        
        # Get last 30 days of data
        hist = strc.history(period="1mo")
        
        if hist.empty:
            print("  STRC: No data returned from Yahoo Finance")
            return None
        
        # Today's (or most recent) data
        latest = hist.iloc[-1]
        latest_date = hist.index[-1].strftime("%Y-%m-%d")
        latest_volume = int(latest["Volume"])
        latest_close = round(float(latest["Close"]), 2)
        
        # Calculate dollar volume (shares * price)
        latest_dollar_volume = latest_volume * latest_close
        
        # 20-day average volume (or however many days we have)
        avg_period = min(20, len(hist) - 1)  # Don't include today
        if avg_period > 0:
            avg_volume = int(hist["Volume"].iloc[:-1].tail(avg_period).mean())
            avg_dollar_volume = avg_volume * latest_close
        else:
            avg_volume = latest_volume
            avg_dollar_volume = latest_dollar_volume
        
        # Volume ratio (how many times above average)
        if avg_volume > 0:
            volume_ratio = round(latest_volume / avg_volume, 2)
        else:
            volume_ratio = 0
        
        # Dollar volume in millions for readability
        dollar_vol_m = round(latest_dollar_volume / 1_000_000, 1)
        avg_dollar_vol_m = round(avg_dollar_volume / 1_000_000, 1)
        
        return {
            "date": latest_date,
            "price": latest_close,
            "volume": latest_volume,
            "dollar_volume": latest_dollar_volume,
            "dollar_volume_m": dollar_vol_m,
            "avg_volume": avg_volume,
            "avg_dollar_volume_m": avg_dollar_vol_m,
            "volume_ratio": volume_ratio,
        }
        
    except Exception as e:
        print(f"  STRC TRACKER ERROR: {e}")
        return None


def analyze_strc_signal(data):
    """
    Analyze STRC volume data and return a signal assessment.
    """
    if not data:
        return {"is_signal": False, "level": "NONE", "message": "No data available"}
    
    ratio = data["volume_ratio"]
    dollar_vol = data["dollar_volume_m"]
    
    if ratio >= 3.0 or dollar_vol >= 250:
        level = "🔴 VERY HIGH"
        is_signal = True
        message = f"STRC volume is {ratio}x normal (${dollar_vol}M). Strategy likely raising massive capital for BTC purchase."
    elif ratio >= 2.0 or dollar_vol >= 150:
        level = "🟠 HIGH"
        is_signal = True
        message = f"STRC volume is {ratio}x normal (${dollar_vol}M). Significant capital raise — BTC purchase likely within days."
    elif ratio >= 1.5 or dollar_vol >= 100:
        level = "🟡 ELEVATED"
        is_signal = True
        message = f"STRC volume is {ratio}x normal (${dollar_vol}M). Above-average issuance activity."
    else:
        level = "✅ NORMAL"
        is_signal = False
        message = f"STRC volume is {ratio}x average (${dollar_vol}M). Normal trading activity."
    
    return {
        "is_signal": is_signal,
        "level": level,
        "message": message,
        "ratio": ratio,
        "dollar_volume_m": dollar_vol,
    }


def format_strc_alert(data, analysis):
    """Format a Telegram alert message for STRC volume."""
    
    return f"""
📊 STRC VOLUME ALERT

{analysis['level']}

💰 Today's STRC Volume: ${data['dollar_volume_m']}M ({data['volume']:,} shares)
📈 20-Day Average: ${data['avg_dollar_volume_m']}M ({data['avg_volume']:,} shares)
🔢 Volume Ratio: {data['volume_ratio']}x normal
💵 STRC Price: ${data['price']}

📋 {analysis['message']}

Why this matters:
STRC proceeds fund Bitcoin purchases directly.
Strategy's record $300M STRC day preceded a 1,420 BTC buy.

---
Treasury Purchase Signal Intelligence
"""


# ============================================
# QUICK TEST
# ============================================
if __name__ == "__main__":
    print("STRC Volume Tracker\n")
    print("Fetching STRC data from Yahoo Finance...\n")
    
    data = get_strc_volume_data()
    
    if data:
        print(f"  Date:           {data['date']}")
        print(f"  STRC Price:     ${data['price']}")
        print(f"  Today Volume:   {data['volume']:,} shares (${data['dollar_volume_m']}M)")
        print(f"  20-Day Avg:     {data['avg_volume']:,} shares (${data['avg_dollar_volume_m']}M)")
        print(f"  Volume Ratio:   {data['volume_ratio']}x")
        print()
        
        analysis = analyze_strc_signal(data)
        print(f"  Signal Level:   {analysis['level']}")
        print(f"  Is Signal:      {analysis['is_signal']}")
        print(f"  Assessment:     {analysis['message']}")
        
        if analysis['is_signal']:
            print(f"\n  ALERT WOULD BE SENT:")
            print(format_strc_alert(data, analysis))
    else:
        print("  Failed to fetch STRC data.")
    
    print("\nSTRC Tracker is working!")
