"""
strc_tracker.py
---------------
Tracks STRC issuance volume to detect when Strategy
is raising capital to buy Bitcoin.

Logic: When STRC daily volume spikes significantly above
its 20-day average, it means Strategy is aggressively
selling STRC shares via their ATM program. The proceeds
go directly to buying BTC — usually within days.
"""

import yfinance as yf
from datetime import datetime, timedelta
from logger import get_logger
from freshness_tracker import freshness

logger = get_logger(__name__)


def get_strc_volume_data():
    """
    Fetch STRC's recent trading data from Yahoo Finance.
    Returns a dict with today's volume, average volume, and ratio.
    """
    try:
        strc = yf.Ticker("STRC")
        hist = strc.history(period="1mo")

        if hist.empty:
            logger.warning("STRC: No data returned from Yahoo Finance")
            return None

        latest = hist.iloc[-1]
        latest_date = hist.index[-1].strftime("%Y-%m-%d")
        latest_volume = int(latest["Volume"])
        latest_close = round(float(latest["Close"]), 2)

        latest_dollar_volume = latest_volume * latest_close

        avg_period = min(20, len(hist) - 1)
        if avg_period > 0:
            avg_volume = int(hist["Volume"].iloc[:-1].tail(avg_period).mean())
            avg_dollar_volume = avg_volume * latest_close
        else:
            avg_volume = latest_volume
            avg_dollar_volume = latest_dollar_volume

        if avg_volume > 0:
            volume_ratio = round(latest_volume / avg_volume, 2)
        else:
            volume_ratio = 0

        dollar_vol_m = round(latest_dollar_volume / 1_000_000, 1)
        avg_dollar_vol_m = round(avg_dollar_volume / 1_000_000, 1)

        logger.debug(f"STRC: ${latest_close} | Vol: {latest_volume:,} ({dollar_vol_m}M) | Ratio: {volume_ratio}x")
        freshness.record_success("strc_yfinance", detail=f"${latest_close} | {dollar_vol_m}M vol | {volume_ratio}x")

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
        logger.error(f"STRC data fetch failed: {e}", exc_info=True)
        freshness.record_failure("strc_yfinance", error=str(e))
        return None


def analyze_strc_signal(data):
    """
    Analyze STRC volume data and return a signal assessment.
    """
    if not data:
        return {"is_signal": False, "level": "NONE", "message": "No data available"}

    ratio = data["volume_ratio"]
    dollar_vol = data["dollar_volume_m"]

    # Use ratio as primary signal (adjusts for price changes over time)
    # Dollar volume is a secondary confirmation, not a standalone trigger
    if ratio >= 3.0 and dollar_vol >= 200:
        level = "🔴 VERY HIGH"
        is_signal = True
        message = f"STRC volume is {ratio}x normal (${dollar_vol}M). Strategy likely raising massive capital for BTC purchase."
    elif ratio >= 2.0 and dollar_vol >= 100:
        level = "🟠 HIGH"
        is_signal = True
        message = f"STRC volume is {ratio}x normal (${dollar_vol}M). Significant capital raise — BTC purchase likely within days."
    elif ratio >= 1.5:
        level = "🟡 ELEVATED"
        is_signal = True
        message = f"STRC volume is {ratio}x normal (${dollar_vol}M). Above-average issuance activity."
    else:
        level = "✅ NORMAL"
        is_signal = False
        message = f"STRC volume is {ratio}x average (${dollar_vol}M). Normal trading activity."

    if is_signal:
        logger.info(f"STRC signal: {level} — {ratio}x normal (${dollar_vol}M)")

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
    logger.info("STRC Volume Tracker — fetching data...")

    data = get_strc_volume_data()

    if data:
        logger.info(f"Date: {data['date']} | Price: ${data['price']} | Vol: {data['volume']:,} (${data['dollar_volume_m']}M) | Ratio: {data['volume_ratio']}x")
        analysis = analyze_strc_signal(data)
        logger.info(f"Signal: {analysis['level']} | Is Signal: {analysis['is_signal']}")
    else:
        logger.error("Failed to fetch STRC data")

    logger.info("STRC Tracker test complete")
