"""
exchange_flow_tracker.py — BTC Exchange Net Flow Monitor
----------------------------------------------------------
Tracks BTC flowing into and out of exchanges to detect
institutional accumulation or distribution patterns.

Key metrics:
  - Exchange inflows (BTC deposited to exchanges = potential selling)
  - Exchange outflows (BTC withdrawn from exchanges = accumulation)
  - Net flow (outflows - inflows: negative = accumulation, positive = selling)
  - Exchange reserves (total BTC held on exchanges — declining = bullish)

Data Sources (in priority order):
  1. CryptoQuant API (best exchange flow data — free tier available)
     Sign up: https://cryptoquant.com → free account → API key
     Free tier: 100 calls/day, daily resolution
     Pro tier ($29/mo): 1000 calls/day, hourly resolution
     
  2. Blockchain.com API (free, no key — basic network stats only)
     Limited: total volume and transaction counts, no exchange labeling
     Used as fallback for network health indicators

Environment variable needed:
  CRYPTOQUANT_API_KEY=your_key_here  (get from cryptoquant.com/account/api)
"""

import os
import json
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from logger import get_logger

logger = get_logger(__name__)
load_dotenv()

CRYPTOQUANT_API_KEY = os.getenv("CRYPTOQUANT_API_KEY", "")

# ============================================
# CRYPTOQUANT API (Primary Source)
# ============================================
CRYPTOQUANT_BASE = "https://api.cryptoquant.com/v1"

# Known exchange names for labeling
EXCHANGE_NAMES = {
    "binance": "Binance",
    "coinbase": "Coinbase",
    "kraken": "Kraken",
    "bitfinex": "Bitfinex",
    "okx": "OKX",
    "bybit": "Bybit",
    "huobi": "Huobi",
    "gemini": "Gemini",
    "bitstamp": "Bitstamp",
    "kucoin": "KuCoin",
}


def _cryptoquant_request(endpoint, params=None):
    """Make an authenticated request to CryptoQuant API."""
    if not CRYPTOQUANT_API_KEY:
        return None

    headers = {
        "Authorization": f"Bearer {CRYPTOQUANT_API_KEY}",
        "Accept": "application/json",
    }

    try:
        url = f"{CRYPTOQUANT_BASE}{endpoint}"
        response = requests.get(url, headers=headers, params=params, timeout=15)

        if response.status_code == 200:
            return response.json()
        elif response.status_code == 429:
            logger.warning("CryptoQuant: rate limited (429)")
            return None
        elif response.status_code == 401:
            logger.warning("CryptoQuant: invalid API key (401)")
            return None
        else:
            logger.debug(f"CryptoQuant: HTTP {response.status_code} for {endpoint}")
            return None
    except Exception as e:
        logger.debug(f"CryptoQuant request failed: {e}")
        return None


def get_exchange_netflow():
    """
    Get BTC exchange net flow (inflow - outflow).
    Negative = BTC leaving exchanges (accumulation/bullish)
    Positive = BTC entering exchanges (selling pressure/bearish)
    
    Returns dict or None.
    """
    # CryptoQuant: Exchange Netflow
    data = _cryptoquant_request("/btc/exchange-flows/netflow", params={
        "window": "day",
        "limit": 7,
    })

    if data and data.get("status", {}).get("code") == 200:
        result = data.get("result", {}).get("data", [])
        if result:
            latest = result[-1] if isinstance(result, list) else result
            netflow_btc = float(latest.get("netflow", latest.get("value", 0)))

            # Calculate 7-day trend
            if isinstance(result, list) and len(result) >= 3:
                recent_flows = [float(r.get("netflow", r.get("value", 0))) for r in result[-3:]]
                avg_recent = sum(recent_flows) / len(recent_flows)
                consecutive_outflows = sum(1 for f in recent_flows if f < 0)
            else:
                avg_recent = netflow_btc
                consecutive_outflows = 1 if netflow_btc < 0 else 0

            return {
                "netflow_btc": netflow_btc,
                "netflow_usd": 0,  # Will be calculated with BTC price
                "direction": "outflow" if netflow_btc < 0 else "inflow",
                "avg_3day_btc": avg_recent,
                "consecutive_outflow_days": consecutive_outflows,
                "source": "CryptoQuant",
                "timestamp": latest.get("date", datetime.now().isoformat()),
            }

    logger.debug("Exchange netflow: CryptoQuant data unavailable")
    return None


def get_exchange_inflow():
    """Get total BTC flowing INTO exchanges (potential selling)."""
    data = _cryptoquant_request("/btc/exchange-flows/inflow", params={
        "window": "day",
        "limit": 3,
    })

    if data and data.get("status", {}).get("code") == 200:
        result = data.get("result", {}).get("data", [])
        if result:
            latest = result[-1] if isinstance(result, list) else result
            inflow = float(latest.get("inflow_total", latest.get("value", 0)))
            return {
                "btc": inflow,
                "timestamp": latest.get("date", ""),
                "source": "CryptoQuant",
            }
    return None


def get_exchange_outflow():
    """Get total BTC flowing OUT of exchanges (accumulation)."""
    data = _cryptoquant_request("/btc/exchange-flows/outflow", params={
        "window": "day",
        "limit": 3,
    })

    if data and data.get("status", {}).get("code") == 200:
        result = data.get("result", {}).get("data", [])
        if result:
            latest = result[-1] if isinstance(result, list) else result
            outflow = float(latest.get("outflow_total", latest.get("value", 0)))
            return {
                "btc": outflow,
                "timestamp": latest.get("date", ""),
                "source": "CryptoQuant",
            }
    return None


def get_exchange_reserve():
    """
    Get total BTC held on all exchanges.
    Declining reserves = supply squeeze = bullish.
    """
    data = _cryptoquant_request("/btc/exchange-flows/reserve", params={
        "window": "day",
        "limit": 30,
    })

    if data and data.get("status", {}).get("code") == 200:
        result = data.get("result", {}).get("data", [])
        if result and isinstance(result, list):
            latest = result[-1]
            reserve_btc = float(latest.get("reserve", latest.get("value", 0)))

            # Calculate 30-day change
            if len(result) >= 30:
                reserve_30d_ago = float(result[0].get("reserve", result[0].get("value", 0)))
                reserve_change_30d = reserve_btc - reserve_30d_ago
                reserve_change_pct = (reserve_change_30d / reserve_30d_ago * 100) if reserve_30d_ago > 0 else 0
            else:
                reserve_change_30d = 0
                reserve_change_pct = 0

            # Calculate 7-day change
            if len(result) >= 7:
                reserve_7d_ago = float(result[-7].get("reserve", result[-7].get("value", 0)))
                reserve_change_7d = reserve_btc - reserve_7d_ago
            else:
                reserve_change_7d = 0

            return {
                "reserve_btc": reserve_btc,
                "reserve_change_30d_btc": reserve_change_30d,
                "reserve_change_30d_pct": reserve_change_pct,
                "reserve_change_7d_btc": reserve_change_7d,
                "trend": "declining" if reserve_change_7d < 0 else "increasing",
                "source": "CryptoQuant",
                "timestamp": latest.get("date", ""),
            }
    return None


# ============================================
# BLOCKCHAIN.COM FALLBACK (Free, no key)
# ============================================
def get_network_stats_fallback():
    """
    Fallback: basic Bitcoin network stats from Blockchain.com.
    No exchange-specific data, but gives total network activity.
    """
    try:
        response = requests.get("https://api.blockchain.info/stats", timeout=10)
        if response.status_code == 200:
            data = response.json()
            return {
                "total_btc_sent_24h": data.get("estimated_btc_sent", 0) / 1e8,  # Convert satoshis
                "n_transactions_24h": data.get("n_tx", 0),
                "hash_rate": data.get("hash_rate", 0),
                "difficulty": data.get("difficulty", 0),
                "mempool_size": data.get("n_btc_mined", 0),
                "source": "Blockchain.com",
            }
    except Exception as e:
        logger.debug(f"Blockchain.com stats failed: {e}")
    return None


# ============================================
# COMBINED FLOW REPORT
# ============================================
def get_exchange_flow_report(btc_price=0):
    """
    Generate a complete exchange flow report combining all available data.
    
    Args:
        btc_price: Current BTC price for USD calculations
        
    Returns:
        dict with complete flow analysis, or None if no data available
    """
    report = {
        "timestamp": datetime.now().isoformat(),
        "btc_price": btc_price,
        "has_exchange_data": False,
        "has_network_data": False,
    }

    # Try CryptoQuant data first
    if CRYPTOQUANT_API_KEY:
        netflow = get_exchange_netflow()
        inflow = get_exchange_inflow()
        outflow = get_exchange_outflow()
        reserve = get_exchange_reserve()

        if netflow:
            report["has_exchange_data"] = True
            report["netflow_btc"] = netflow["netflow_btc"]
            report["netflow_usd"] = netflow["netflow_btc"] * btc_price if btc_price else 0
            report["netflow_direction"] = netflow["direction"]
            report["avg_3day_netflow_btc"] = netflow["avg_3day_btc"]
            report["consecutive_outflow_days"] = netflow["consecutive_outflow_days"]

        if inflow:
            report["inflow_btc"] = inflow["btc"]
            report["inflow_usd"] = inflow["btc"] * btc_price if btc_price else 0

        if outflow:
            report["outflow_btc"] = outflow["btc"]
            report["outflow_usd"] = outflow["btc"] * btc_price if btc_price else 0

        if reserve:
            report["reserve_btc"] = reserve["reserve_btc"]
            report["reserve_change_7d_btc"] = reserve["reserve_change_7d_btc"]
            report["reserve_change_30d_btc"] = reserve["reserve_change_30d_btc"]
            report["reserve_change_30d_pct"] = reserve["reserve_change_30d_pct"]
            report["reserve_trend"] = reserve["trend"]

        # Generate interpretation
        report["interpretation"] = _interpret_flow(report)
        report["signal"] = _flow_signal(report)
        report["data_source"] = "CryptoQuant"
    else:
        logger.info("Exchange flow: No CryptoQuant API key — using network stats fallback")
        report["data_source"] = "None (add CRYPTOQUANT_API_KEY for exchange flow data)"

    # Always try blockchain.com for basic network stats
    network = get_network_stats_fallback()
    if network:
        report["has_network_data"] = True
        report["network_btc_sent_24h"] = network["total_btc_sent_24h"]
        report["network_transactions_24h"] = network["n_transactions_24h"]
        report["network_hash_rate"] = network["hash_rate"]

    return report


def _interpret_flow(report):
    """Generate human-readable interpretation of exchange flows."""
    parts = []

    netflow = report.get("netflow_btc", 0)
    consecutive = report.get("consecutive_outflow_days", 0)
    reserve_trend = report.get("reserve_trend", "unknown")
    reserve_change_7d = report.get("reserve_change_7d_btc", 0)

    if netflow < -5000:
        parts.append("Heavy institutional accumulation — large BTC outflows from exchanges.")
    elif netflow < -1000:
        parts.append("Moderate accumulation — BTC flowing out of exchanges.")
    elif netflow < 0:
        parts.append("Slight accumulation — minor net outflows from exchanges.")
    elif netflow > 5000:
        parts.append("Heavy selling pressure — large BTC inflows to exchanges.")
    elif netflow > 1000:
        parts.append("Moderate selling pressure — BTC flowing into exchanges.")
    elif netflow > 0:
        parts.append("Slight selling pressure — minor net inflows to exchanges.")
    else:
        parts.append("Exchange flows neutral.")

    if consecutive >= 3:
        parts.append(f"Sustained trend: {consecutive} consecutive days of net outflows.")

    if reserve_trend == "declining" and reserve_change_7d < -5000:
        parts.append("Exchange reserves declining sharply — supply squeeze developing.")
    elif reserve_trend == "declining":
        parts.append("Exchange reserves declining — less BTC available for immediate sale.")
    elif reserve_trend == "increasing" and reserve_change_7d > 5000:
        parts.append("Exchange reserves increasing sharply — more BTC available for sale.")

    return " ".join(parts) if parts else "Insufficient data for interpretation."


def _flow_signal(report):
    """
    Generate a trading signal from flow data.
    Returns: "STRONG_ACCUMULATION", "ACCUMULATION", "NEUTRAL", "DISTRIBUTION", "STRONG_DISTRIBUTION"
    """
    score = 0
    netflow = report.get("netflow_btc", 0)
    consecutive = report.get("consecutive_outflow_days", 0)
    reserve_trend = report.get("reserve_trend", "unknown")

    # Net flow scoring
    if netflow < -5000:
        score += 3
    elif netflow < -1000:
        score += 2
    elif netflow < 0:
        score += 1
    elif netflow > 5000:
        score -= 3
    elif netflow > 1000:
        score -= 2
    elif netflow > 0:
        score -= 1

    # Consecutive outflow days
    if consecutive >= 5:
        score += 2
    elif consecutive >= 3:
        score += 1

    # Reserve trend
    if reserve_trend == "declining":
        score += 1
    elif reserve_trend == "increasing":
        score -= 1

    if score >= 4:
        return "STRONG_ACCUMULATION"
    elif score >= 2:
        return "ACCUMULATION"
    elif score <= -4:
        return "STRONG_DISTRIBUTION"
    elif score <= -2:
        return "DISTRIBUTION"
    return "NEUTRAL"


# ============================================
# TELEGRAM FORMATTING
# ============================================
def format_flow_telegram(report):
    """Format exchange flow report for Telegram."""
    if not report or not report.get("has_exchange_data"):
        # Minimal report with network data only
        if report and report.get("has_network_data"):
            return f"""
📊 ON-CHAIN NETWORK REPORT

🔗 24h Network Activity:
  Transactions: {report.get('network_transactions_24h', 0):,}
  BTC Transferred: {report.get('network_btc_sent_24h', 0):,.0f} BTC

⚠️ Exchange flow data requires CryptoQuant API key.
Set CRYPTOQUANT_API_KEY in Render environment variables.
Sign up free: cryptoquant.com

---
Treasury Signal Intelligence
"""
        return None

    btc_price = report.get("btc_price", 70000)
    netflow = report.get("netflow_btc", 0)
    inflow = report.get("inflow_btc", 0)
    outflow = report.get("outflow_btc", 0)
    reserve = report.get("reserve_btc", 0)
    signal = report.get("signal", "NEUTRAL")

    # Signal emoji
    signal_map = {
        "STRONG_ACCUMULATION": "🟢🟢 STRONG ACCUMULATION",
        "ACCUMULATION": "🟢 ACCUMULATION",
        "NEUTRAL": "⚪ NEUTRAL",
        "DISTRIBUTION": "🔴 DISTRIBUTION",
        "STRONG_DISTRIBUTION": "🔴🔴 STRONG DISTRIBUTION",
    }
    signal_text = signal_map.get(signal, "⚪ NEUTRAL")

    # Net flow direction
    if netflow < 0:
        flow_emoji = "📤"
        flow_dir = f"{abs(netflow):,.0f} BTC leaving exchanges"
    else:
        flow_emoji = "📥"
        flow_dir = f"{abs(netflow):,.0f} BTC entering exchanges"

    lines = []
    lines.append(f"📊 EXCHANGE FLOW REPORT\n")
    lines.append(f"Signal: {signal_text}\n")

    lines.append(f"Exchange Flows (24h):")
    if inflow:
        lines.append(f"  📥 Inflows:  {inflow:,.0f} BTC (${inflow * btc_price / 1e6:,.0f}M)")
    if outflow:
        lines.append(f"  📤 Outflows: {outflow:,.0f} BTC (${outflow * btc_price / 1e6:,.0f}M)")
    lines.append(f"  {flow_emoji} Net Flow: {flow_dir}")

    if report.get("consecutive_outflow_days", 0) >= 2:
        lines.append(f"  📈 Trend: {report['consecutive_outflow_days']} consecutive days of net outflows")

    lines.append("")

    if reserve > 0:
        lines.append(f"Exchange Reserves:")
        lines.append(f"  💰 Total: {reserve:,.0f} BTC")
        change_7d = report.get("reserve_change_7d_btc", 0)
        if change_7d != 0:
            emoji = "📉" if change_7d < 0 else "📈"
            lines.append(f"  {emoji} 7d Change: {change_7d:+,.0f} BTC")
        change_30d = report.get("reserve_change_30d_pct", 0)
        if change_30d != 0:
            lines.append(f"  30d Change: {change_30d:+.1f}%")
        lines.append("")

    lines.append(f"💡 {report.get('interpretation', 'No interpretation available.')}")

    lines.append(f"\n---")
    lines.append(f"Treasury Signal Intelligence")
    lines.append(f"On-Chain Flow Monitor™")

    return "\n".join(lines)


# ============================================
# EMAIL BRIEFING DATA
# ============================================
def get_flow_for_email(btc_price=0):
    """
    Get exchange flow data formatted for the email briefing.
    Returns a dict with all the fields the email template needs.
    """
    report = get_exchange_flow_report(btc_price)
    if not report:
        return None

    return {
        "has_data": report.get("has_exchange_data", False),
        "signal": report.get("signal", "NEUTRAL"),
        "netflow_btc": report.get("netflow_btc", 0),
        "netflow_usd": report.get("netflow_usd", 0),
        "inflow_btc": report.get("inflow_btc", 0),
        "outflow_btc": report.get("outflow_btc", 0),
        "reserve_btc": report.get("reserve_btc", 0),
        "reserve_change_7d_btc": report.get("reserve_change_7d_btc", 0),
        "reserve_change_30d_pct": report.get("reserve_change_30d_pct", 0),
        "reserve_trend": report.get("reserve_trend", "unknown"),
        "consecutive_outflow_days": report.get("consecutive_outflow_days", 0),
        "interpretation": report.get("interpretation", ""),
        "network_transactions_24h": report.get("network_transactions_24h", 0),
        "network_btc_sent_24h": report.get("network_btc_sent_24h", 0),
        "data_source": report.get("data_source", "None"),
    }


# ============================================
# QUICK TEST
# ============================================
if __name__ == "__main__":
    logger.info("Exchange Flow Tracker — self-test")
    logger.info("=" * 60)

    if not CRYPTOQUANT_API_KEY:
        logger.warning("No CRYPTOQUANT_API_KEY set. Exchange flow data will be unavailable.")
        logger.info("Sign up free at: https://cryptoquant.com")
        logger.info("Then add CRYPTOQUANT_API_KEY to your .env file")

    report = get_exchange_flow_report(btc_price=67000)

    if report:
        logger.info(f"Data source: {report.get('data_source', 'None')}")
        logger.info(f"Has exchange data: {report.get('has_exchange_data', False)}")
        logger.info(f"Has network data: {report.get('has_network_data', False)}")

        if report.get("has_exchange_data"):
            logger.info(f"Net flow: {report.get('netflow_btc', 0):+,.0f} BTC")
            logger.info(f"Signal: {report.get('signal', 'NEUTRAL')}")
            logger.info(f"Interpretation: {report.get('interpretation', '')}")

        if report.get("has_network_data"):
            logger.info(f"Network: {report.get('network_transactions_24h', 0):,} transactions, {report.get('network_btc_sent_24h', 0):,.0f} BTC sent")

        tg = format_flow_telegram(report)
        if tg:
            logger.info(f"\nTelegram Format:\n{tg}")
    else:
        logger.warning("No data available")

    logger.info("\nExchange Flow Tracker self-test complete")
