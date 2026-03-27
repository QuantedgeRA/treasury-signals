"""
telegram_alerts.py — Tiered Telegram Alert System
---------------------------------------------------
Pro (Paid Channel): Real-time alerts for signals, purchases, new entrants
Free Channel: Weekly summary only (sent on Mondays)

Usage:
    from telegram_alerts import alerts
    
    # Real-time alert (Pro only) — call when signal detected
    alerts.send_signal_alert(signal_data)
    
    # Real-time alert (Pro only) — call when new entrant detected
    alerts.send_new_entrant_alert(entrant_data)
    
    # Weekly summary (Free channel) — call on Mondays
    alerts.send_weekly_summary()
"""

import os
import json
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from supabase import create_client
from logger import get_logger

logger = get_logger(__name__)

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_PAID_CHANNEL_ID = os.getenv("TELEGRAM_PAID_CHANNEL_ID", "")
TELEGRAM_FREE_CHANNEL_ID = os.getenv("TELEGRAM_FREE_CHANNEL_ID", "")
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "https://app.quantedgeriskadvisory.com")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


class TelegramAlerts:

    def _send(self, channel_id, message):
        """Send a message to a Telegram channel."""
        if not TELEGRAM_BOT_TOKEN or not channel_id:
            return False
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            res = requests.post(url, json={
                "chat_id": channel_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }, timeout=10)
            if res.ok:
                return True
            else:
                data = res.json()
                logger.warning(f"Telegram API returned {res.status_code}: {data.get('description', '')}")
                return False
        except Exception as e:
            logger.warning(f"Telegram send error: {e}")
            return False

    def send_to_pro(self, message):
        """Send alert to Pro/Paid channel only."""
        return self._send(TELEGRAM_PAID_CHANNEL_ID, message)

    def send_to_free(self, message):
        """Send alert to Free channel only."""
        return self._send(TELEGRAM_FREE_CHANNEL_ID, message)

    # ─── PRO-ONLY REAL-TIME ALERTS ───────────────────────────

    def send_signal_alert(self, signal):
        """Send real-time purchase signal alert to Pro channel."""
        score = signal.get("confidence_score", 0) or 0
        if score < 60:
            return  # Only alert on high-confidence signals

        level = "🔴 STRONG" if score >= 80 else "🟡 ELEVATED"
        author = signal.get("author_username", "unknown")
        text = (signal.get("tweet_text", "") or "")[:200]

        msg = (
            f"{level} PURCHASE SIGNAL\n\n"
            f"📊 Confidence: {score}%\n"
            f"👤 Source: @{author}\n"
            f"💬 \"{text}\"\n\n"
            f"🔗 {DASHBOARD_URL}/dashboard\n\n"
            f"—\n⚡ Treasury Signal Intelligence (Pro)"
        )
        self.send_to_pro(msg)

    def send_new_entrant_alert(self, entrant):
        """Send new entrant alert to Pro channel."""
        company = entrant.get("company", entrant.get("ticker", "Unknown"))
        ticker = entrant.get("ticker", "")
        btc = entrant.get("btc_holdings", 0) or 0

        msg = (
            f"🆕 NEW BITCOIN TREASURY ENTRANT\n\n"
            f"🏢 {company}"
            f"{' (' + ticker + ')' if ticker else ''}\n"
            f"₿ {btc:,} BTC\n"
            f"📅 First detected: {datetime.now().strftime('%Y-%m-%d')}\n\n"
            f"Corporate Bitcoin adoption continues to grow.\n\n"
            f"🔗 {DASHBOARD_URL}/leaderboard\n\n"
            f"—\n⚡ Treasury Signal Intelligence (Pro)"
        )
        self.send_to_pro(msg)

    def send_competitor_alert(self, alert_data):
        """Send competitor activity alert to Pro channel."""
        company = alert_data.get("company", "")
        ticker = alert_data.get("ticker", "")
        alert_type = alert_data.get("type", "activity")
        detail = alert_data.get("detail", "")

        msg = (
            f"👁️ WATCHLIST ALERT — {alert_type.upper()}\n\n"
            f"🏢 {company}"
            f"{' (' + ticker + ')' if ticker else ''}\n"
            f"📋 {detail}\n\n"
            f"🔗 {DASHBOARD_URL}/competitive\n\n"
            f"—\n⚡ Treasury Signal Intelligence (Pro)"
        )
        self.send_to_pro(msg)

    def send_rank_change_alert(self, subscriber_name, old_rank, new_rank, ticker):
        """Send rank change alert to Pro channel."""
        direction = "⬆️ MOVED UP" if new_rank < old_rank else "⬇️ MOVED DOWN"

        msg = (
            f"{direction} — RANK CHANGE\n\n"
            f"🏢 {subscriber_name} ({ticker})\n"
            f"📊 #{old_rank} → #{new_rank}\n\n"
            f"🔗 {DASHBOARD_URL}/leaderboard\n\n"
            f"—\n⚡ Treasury Signal Intelligence (Pro)"
        )
        self.send_to_pro(msg)

    # ─── FREE CHANNEL — WEEKLY SUMMARY ONLY ──────────────────

    def send_weekly_summary(self):
        """Send weekly market summary to Free channel. Call on Mondays."""
        logger.info("Telegram: generating weekly summary for free channel...")

        try:
            # Get leaderboard stats
            result = supabase.table("treasury_companies").select(
                "btc_holdings"
            ).eq("is_government", False).gt("btc_holdings", 0).execute()
            companies = result.data or []

            total_entities = len(companies)
            total_btc = sum(c.get("btc_holdings", 0) or 0 for c in companies)

            # Get new entrants from last 7 days
            week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            ne_result = supabase.table("new_entrants").select("*").gte(
                "first_seen", week_ago
            ).execute()
            new_entrants = ne_result.data or []

            # Get signal count from last 7 days
            week_cutoff = (datetime.utcnow() - timedelta(days=7)).isoformat()
            sig_result = supabase.table("signals").select(
                "confidence_score"
            ).gte("created_at", week_cutoff).execute()
            all_signals = sig_result.data or []
            high_signals = [s for s in all_signals if (s.get("confidence_score", 0) or 0) >= 60]

            # BTC price
            btc_price = 0
            try:
                price_result = supabase.table("leaderboard_snapshots").select(
                    "btc_price"
                ).order("snapshot_date", desc=True).limit(1).execute()
                if price_result.data:
                    btc_price = float(price_result.data[0].get("btc_price", 0))
            except Exception:
                pass

            total_value = total_btc * btc_price if btc_price else 0

            msg = (
                f"📊 WEEKLY BITCOIN TREASURY SUMMARY\n"
                f"Week of {datetime.now().strftime('%B %d, %Y')}\n"
                f"{'━' * 32}\n\n"
                f"🏢 Entities Tracked: {total_entities}\n"
                f"₿ Total BTC Held: {total_btc:,}\n"
                f"💰 Total Value: ${total_value / 1e9:.1f}B\n"
                f"📈 BTC Price: ${btc_price:,.0f}\n\n"
                f"🆕 New Entrants This Week: {len(new_entrants)}\n"
                f"🔮 Signals Detected: {len(all_signals)} ({len(high_signals)} high-confidence)\n\n"
            )

            if new_entrants:
                msg += "New this week:\n"
                for ne in new_entrants[:5]:
                    msg += f"  • {ne.get('company', ne.get('ticker', '?'))} — {(ne.get('btc_holdings', 0) or 0):,} BTC\n"
                if len(new_entrants) > 5:
                    msg += f"  + {len(new_entrants) - 5} more\n"
                msg += "\n"

            msg += (
                f"Want real-time alerts, personalized briefings, and competitive intelligence?\n\n"
                f"🔗 Upgrade to Pro: {DASHBOARD_URL}\n\n"
                f"—\nTreasury Signal Intelligence\n"
                f"Free weekly summary · Pro gets daily alerts"
            )

            success = self.send_to_free(msg)
            if success:
                logger.info("Telegram: weekly summary sent to free channel")
            return success

        except Exception as e:
            logger.error(f"Weekly summary error: {e}")
            return False


alerts = TelegramAlerts()

if __name__ == "__main__":
    logger.info("Telegram Alerts — sending weekly summary...")
    alerts.send_weekly_summary()
