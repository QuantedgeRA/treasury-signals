"""
telegram_alerts.py — Tiered Telegram Alert System
---------------------------------------------------
Pro (Paid Channel): Real-time alerts for signals, purchases, new entrants
Free Channel: Weekly summary only (sent on Mondays) — shows WHAT, hides WHO

Usage:
    from telegram_alerts import alerts
    alerts.send_signal_alert(signal_data)     # Pro only
    alerts.send_new_entrant_alert(entrant)    # Pro only
    alerts.send_weekly_summary()              # Free channel, Mondays
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
                logger.warning(f"Telegram {res.status_code}: {data.get('description', '')}")
                return False
        except Exception as e:
            logger.warning(f"Telegram error: {e}")
            return False

    def send_to_pro(self, message):
        return self._send(TELEGRAM_PAID_CHANNEL_ID, message)

    def send_to_free(self, message):
        return self._send(TELEGRAM_FREE_CHANNEL_ID, message)

    # ─── PRO-ONLY REAL-TIME ALERTS ───────────────────────────

    def send_signal_alert(self, signal):
        score = signal.get("confidence_score", 0) or 0
        if score < 60:
            return
        level = "🔴 STRONG" if score >= 80 else "🟡 ELEVATED"
        author = signal.get("author_username", "unknown")
        text = (signal.get("tweet_text", "") or "")[:200]
        msg = (
            f"{level} PURCHASE SIGNAL\n\n"
            f"📊 Confidence: {score}%\n"
            f"👤 Source: @{author}\n"
            f"💬 \"{text}\"\n\n"
            f"🔗 {DASHBOARD_URL}/dashboard\n\n"
            f"—\n⚡ TSI Pro Alert"
        )
        self.send_to_pro(msg)

    def send_new_entrant_alert(self, entrant):
        company = entrant.get("company", entrant.get("ticker", "Unknown"))
        ticker = entrant.get("ticker", "")
        btc = entrant.get("btc_holdings", 0) or 0
        msg = (
            f"🆕 NEW BITCOIN TREASURY ENTRANT\n\n"
            f"🏢 {company}{' (' + ticker + ')' if ticker else ''}\n"
            f"₿ {btc:,} BTC\n"
            f"📅 {datetime.now().strftime('%Y-%m-%d')}\n\n"
            f"🔗 {DASHBOARD_URL}/leaderboard\n\n"
            f"—\n⚡ TSI Pro Alert"
        )
        self.send_to_pro(msg)

    def send_competitor_alert(self, alert_data):
        company = alert_data.get("company", "")
        ticker = alert_data.get("ticker", "")
        detail = alert_data.get("detail", "")
        msg = (
            f"👁️ WATCHLIST ALERT\n\n"
            f"🏢 {company}{' (' + ticker + ')' if ticker else ''}\n"
            f"📋 {detail}\n\n"
            f"🔗 {DASHBOARD_URL}/competitive\n\n"
            f"—\n⚡ TSI Pro Alert"
        )
        self.send_to_pro(msg)

    def send_rank_change_alert(self, name, old_rank, new_rank, ticker):
        direction = "⬆️ MOVED UP" if new_rank < old_rank else "⬇️ MOVED DOWN"
        msg = (
            f"{direction}\n\n"
            f"🏢 {name} ({ticker})\n"
            f"📊 #{old_rank} → #{new_rank}\n\n"
            f"—\n⚡ TSI Pro Alert"
        )
        self.send_to_pro(msg)

    # ─── FREE CHANNEL — WEEKLY SUMMARY (show WHAT, hide WHO) ─

    def send_weekly_summary(self):
        logger.info("Telegram: generating weekly free summary...")

        try:
            # Entities
            result = supabase.table("treasury_companies").select(
                "btc_holdings"
            ).eq("is_government", False).gt("btc_holdings", 0).execute()
            companies = result.data or []
            total_entities = len(companies)
            total_btc = sum(c.get("btc_holdings", 0) or 0 for c in companies)

            # New entrants (count only — no names for free)
            week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            ne_result = supabase.table("new_entrants").select("id").gte(
                "first_seen", week_ago
            ).execute()
            entrant_count = len(ne_result.data or [])

            # Signals (count only — no details for free)
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

            total_value = total_btc * btc_price

            msg = (
                f"📊 WEEKLY BITCOIN TREASURY SUMMARY\n"
                f"{datetime.now().strftime('%B %d, %Y')}\n"
                f"{'━' * 30}\n\n"

                f"🏢 <b>{total_entities}</b> entities tracked\n"
                f"₿ <b>{total_btc:,}</b> BTC held collectively\n"
                f"💰 <b>${total_value / 1e9:.1f}B</b> total treasury value\n"
                f"📈 BTC Price: <b>${btc_price:,.0f}</b>\n\n"

                f"{'━' * 30}\n\n"

                f"🔮 <b>{len(all_signals)}</b> purchase signals detected\n"
                f"    └ <b>{len(high_signals)}</b> scored 60%+ confidence\n"
                f"    └ 🔒 <i>Signal details → Pro only</i>\n\n"

                f"🆕 <b>{entrant_count}</b> new companies added BTC this week\n"
                f"    └ 🔒 <i>Company names → Pro only</i>\n\n"

                f"{'━' * 30}\n\n"

                f"📱 <b>Free subscribers see this weekly.</b>\n"
                f"⚡ <b>Pro subscribers see it daily — personalized to their company,</b> "
                f"<b>with full signal details, competitor alerts, and real-time Telegram notifications.</b>\n\n"

                f"🔗 Start 7-day free trial:\n"
                f"{DASHBOARD_URL}\n\n"

                f"—\nTreasury Signal Intelligence\n"
                f"QuantEdge Risk Advisory"
            )

            success = self.send_to_free(msg)
            if success:
                logger.info("Telegram: weekly free summary sent")
            return success

        except Exception as e:
            logger.error(f"Weekly summary error: {e}")
            return False


alerts = TelegramAlerts()

if __name__ == "__main__":
    alerts.send_weekly_summary()
