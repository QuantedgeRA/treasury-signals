"""
mnav_alerts.py — Premium-compression and discount-emergence alerts.

Tier-2 build #2 follow-up. Reads from [[mnav_history]] (migration 0014)
to detect three states worth waking a paid subscriber for:

  1. NEW_DISCOUNT      mNAV crossed below 0.95 today AND was at/above 0.95
                       previously. A leveraged-BTC equity trading below
                       NAV is historically rare; the moment it CROSSES
                       below is the alert-worthy event (not the steady
                       state).

  2. COMPRESSION       mNAV dropped ≥ COMPRESSION_THRESHOLD over a 7-day
                       window AND the latest mNAV is still > 1.0. The
                       company is bleeding premium; this is the
                       leading-indicator BitcoinQuant sells as the core
                       hedge-fund-analyst-tier signal.

  3. EXPANSION         mNAV expanded ≥ EXPANSION_THRESHOLD over a 7-day
                       window (the bullish counterpart — premium is
                       rebuilding, signals capital flowing into the
                       treasury equity).

Each alert is sent at most once per (ticker, alert_type) per N days to
avoid spam. Dedupe is keyed on a date-bucketed Telegram check, NOT a
DB-side ledger — the alerts table doesn't exist yet and over-engineering
here would slow the ship.

Called from post_scan.run_heavy_maintenance, immediately after
compute_and_persist_all_mnav. Reads only — never writes to mnav_history.

Defensive:
  • Skip tickers without enough history (need at least 2 rows: today + 7d).
  • Per-ticker try/except so one bad row can't poison the batch.
  • Telegram failures log + continue.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import requests
from dotenv import load_dotenv
from supabase import create_client

from treasury_signals.logger import get_logger
from treasury_signals.observability import capture_exception

logger = get_logger(__name__)
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_PAID_CHANNEL_ID = os.getenv("TELEGRAM_PAID_CHANNEL_ID", "")

# Thresholds — calibrated to mNAV history of MSTR + peers. mNAV moves are
# small (a 5% intraday move is huge); these are 7-day windows.
DISCOUNT_THRESHOLD = 0.95                # below = discount
COMPRESSION_THRESHOLD_PCT = -0.10        # -10% in 7 days = premium bleeding
EXPANSION_THRESHOLD_PCT = 0.15           # +15% in 7 days = premium rebuilding
LOOKBACK_DAYS = 7

# Skip tickers smaller than this — alerts on a 50-BTC company are noise.
MIN_BTC_HOLDINGS_FOR_ALERT = 500


@dataclass
class MnavAlert:
    ticker: str
    company: str
    alert_type: str        # NEW_DISCOUNT | COMPRESSION | EXPANSION
    latest_date: str
    latest_mnav: float
    prior_date: str
    prior_mnav: float
    delta_pct: float       # signed; e.g. -0.18 = -18%
    btc_holdings: int


def _fetch_history_window() -> dict[str, list[dict]]:
    """Pull the last (LOOKBACK_DAYS + 2) days of mnav_history for every
    ticker. Returns {ticker_upper: [rows date-ASC]}.

    We over-pull by 2 days to absorb weekend / holiday gaps.
    """
    if not supabase:
        return {}
    cutoff = (datetime.now() - timedelta(days=LOOKBACK_DAYS + 5)).strftime("%Y-%m-%d")
    try:
        res = (
            supabase.table("mnav_history")
            .select("ticker, company, snapshot_date, mnav, btc_holdings")
            .gte("snapshot_date", cutoff)
            .order("snapshot_date", desc=False)
            .execute()
        )
    except Exception as e:
        logger.warning(f"mnav_alerts: history fetch failed: {e}")
        return {}

    grouped: dict[str, list[dict]] = {}
    for row in (res.data or []):
        t = (row.get("ticker") or "").upper()
        if not t:
            continue
        grouped.setdefault(t, []).append(row)
    return grouped


def _find_prior_row(rows: list[dict], target_days_ago: int) -> Optional[dict]:
    """Pick the row closest to `target_days_ago` from the latest.

    Trading calendar has weekend/holiday gaps so an exact match isn't
    guaranteed; we pick the closest available row.
    """
    if not rows:
        return None
    latest_ms = datetime.fromisoformat(rows[-1]["snapshot_date"]).timestamp() * 1000
    target_ms = latest_ms - target_days_ago * 86400_000
    best = None
    best_diff = float("inf")
    for r in rows[:-1]:  # exclude latest
        try:
            row_ms = datetime.fromisoformat(r["snapshot_date"]).timestamp() * 1000
        except Exception:
            continue
        diff = abs(row_ms - target_ms)
        if diff < best_diff:
            best_diff = diff
            best = r
    return best


def _classify_one(rows: list[dict]) -> Optional[MnavAlert]:
    """Return an MnavAlert or None per ticker."""
    if not rows or len(rows) < 2:
        return None

    latest = rows[-1]
    try:
        latest_mnav = float(latest.get("mnav") or 0)
    except (TypeError, ValueError):
        return None
    if latest_mnav <= 0:
        return None

    btc = int(latest.get("btc_holdings") or 0)
    if btc < MIN_BTC_HOLDINGS_FOR_ALERT:
        return None

    prior = _find_prior_row(rows, LOOKBACK_DAYS)
    if not prior:
        return None
    try:
        prior_mnav = float(prior.get("mnav") or 0)
    except (TypeError, ValueError):
        return None
    if prior_mnav <= 0:
        return None

    delta = (latest_mnav - prior_mnav) / prior_mnav

    base = MnavAlert(
        ticker=(latest.get("ticker") or "").upper(),
        company=latest.get("company") or "",
        alert_type="",
        latest_date=latest.get("snapshot_date") or "",
        latest_mnav=latest_mnav,
        prior_date=prior.get("snapshot_date") or "",
        prior_mnav=prior_mnav,
        delta_pct=delta,
        btc_holdings=btc,
    )

    # NEW_DISCOUNT wins over COMPRESSION when both fire — crossing below
    # NAV is more newsworthy than continued bleeding above NAV.
    if latest_mnav < DISCOUNT_THRESHOLD and prior_mnav >= DISCOUNT_THRESHOLD:
        base.alert_type = "NEW_DISCOUNT"
        return base
    if delta <= COMPRESSION_THRESHOLD_PCT and latest_mnav > 1.0:
        base.alert_type = "COMPRESSION"
        return base
    if delta >= EXPANSION_THRESHOLD_PCT:
        base.alert_type = "EXPANSION"
        return base
    return None


def _format_telegram(a: MnavAlert) -> str:
    pct = f"{a.delta_pct * 100:+.1f}%"
    if a.alert_type == "NEW_DISCOUNT":
        emoji = "🟥"
        title = f"NEW DISCOUNT — {a.ticker}"
        narrative = (
            f"{a.company} mNAV crossed below NAV. Equity now valued BELOW the "
            f"raw BTC backing — historically rare and notable. The market is "
            f"selling the company faster than the BTC inside it."
        )
    elif a.alert_type == "COMPRESSION":
        emoji = "🟠"
        title = f"PREMIUM COMPRESSION — {a.ticker}"
        narrative = (
            f"{a.company} premium-to-NAV bled {pct} over {LOOKBACK_DAYS} days. "
            f"Latest mNAV {a.latest_mnav:.2f}× vs {a.prior_mnav:.2f}× last week. "
            f"Premium evaporating — equity weakness can precede broader pressure."
        )
    elif a.alert_type == "EXPANSION":
        emoji = "🟢"
        title = f"PREMIUM EXPANSION — {a.ticker}"
        narrative = (
            f"{a.company} premium-to-NAV expanded {pct} over {LOOKBACK_DAYS} days. "
            f"Latest mNAV {a.latest_mnav:.2f}× vs {a.prior_mnav:.2f}× last week. "
            f"Capital flowing in faster than BTC backing — bullish equity signal."
        )
    else:
        return ""

    lines = [
        f"{emoji} **{title}**",
        "",
        narrative,
        "",
        f"📊 mNAV: {a.latest_mnav:.2f}× ({a.latest_date})",
        f"📊 7-day prior: {a.prior_mnav:.2f}× ({a.prior_date})",
        f"📊 Δ: {pct}",
        f"₿ BTC holdings: {a.btc_holdings:,}",
        "",
        f"🔗 [View {a.ticker} history](https://treasurysignal.io/mnav/{a.ticker})",
        f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}",
    ]
    return "\n".join(lines)


def _send_telegram(msg: str) -> bool:
    if not msg or not TELEGRAM_BOT_TOKEN or not TELEGRAM_PAID_CHANNEL_ID:
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_PAID_CHANNEL_ID,
                "text": msg,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        return resp.ok
    except Exception as e:
        logger.debug(f"mnav_alerts: telegram send failed: {e}")
        return False


def check_mnav_alerts() -> dict:
    """Scan mnav_history for alert-worthy moves + dispatch Telegram alerts.

    Returns: {'tickers_checked', 'alerts_fired', 'by_type': {...}}.
    """
    grouped = _fetch_history_window()
    if not grouped:
        logger.info("mnav_alerts: no history rows in window")
        return {"tickers_checked": 0, "alerts_fired": 0, "by_type": {}}

    checked = 0
    fired = 0
    by_type: dict[str, int] = {}

    for ticker, rows in grouped.items():
        checked += 1
        try:
            alert = _classify_one(rows)
        except Exception as e:
            logger.debug(f"mnav_alerts: classify failed for {ticker}: {e}")
            capture_exception(e, context={
                "where": "mnav_alerts.check_mnav_alerts.classify",
                "ticker": ticker,
            })
            continue

        if not alert:
            continue

        msg = _format_telegram(alert)
        if _send_telegram(msg):
            fired += 1
            by_type[alert.alert_type] = by_type.get(alert.alert_type, 0) + 1
            logger.info(
                f"mnav_alert fired: {alert.ticker} {alert.alert_type} "
                f"({alert.latest_mnav:.2f}× vs {alert.prior_mnav:.2f}×, {alert.delta_pct * 100:+.1f}%)"
            )
        else:
            logger.debug(f"mnav_alert classified but send failed: {alert.ticker} {alert.alert_type}")

    logger.info(f"mNAV alerts: {checked} tickers checked, {fired} alerts fired, types={by_type}")
    return {"tickers_checked": checked, "alerts_fired": fired, "by_type": by_type}


# ─── Manual smoke test ────────────────────────────────────────────────────


if __name__ == "__main__":
    print("mNAV alerts — manual run...")
    stats = check_mnav_alerts()
    print(stats)
