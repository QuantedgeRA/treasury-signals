"""
equity_volume_tracker.py — generalized treasury-equity volume-spike detector.

Tier-2 build #2 follow-up: extends [[strc_tracker]] (Strategy-only) to every
public BTC-treasury company. When a treasury equity's daily volume spikes
significantly above its 20-day average AND that company has an active ATM
on file ([[atm_filing_detector]]), the proceeds historically fund the next
BTC purchase within days.

This module is the analytical join between two leading indicators:

  1. atm_filings table  — "is the company currently capable of issuing?"
  2. yfinance volume    — "is the company actually issuing right now?"

Together they answer "is a BTC purchase imminent?" for ANY treasury equity,
not just MSTR. That's the wedge for the $99-199/mo hedge-fund-analyst tier
the strategic review identified.

[[strc_tracker]] is intentionally preserved as-is for Strategy because:
  - STRC is a preferred stock (not common), so the volume signal is purer
    (preferreds trade less than commons, ratio swings stand out more).
  - Historical alert templates reference STRC by name; renaming would break
    user mental model.
  - This module covers MSTR's common-stock signal alongside everyone else's.

Defensive:
  • Per-ticker try/except so one bad ticker can't poison the batch.
  • Batched yfinance pulls (50 tickers per call) for budget.
  • Skip tickers with no active ATM filing — emits SUPPRESSED signal
    instead of a noisy "high volume" alert without funding context.
  • Hard caps so the daily run is bounded.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import requests
from dotenv import load_dotenv
from supabase import create_client

from treasury_signals.logger import get_logger
from treasury_signals.observability import capture_exception
from treasury_signals.freshness_tracker import freshness

logger = get_logger(__name__)
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_PAID_CHANNEL_ID = os.getenv("TELEGRAM_PAID_CHANNEL_ID", "")

# Caps
MAX_TICKERS_PER_RUN = 250
MIN_BTC_HOLDINGS = 100        # noise floor — tiny holders' equity moves on noise
YFINANCE_CHUNK = 50            # batch size per yf.download call
HISTORY_PERIOD = "1mo"         # for 20-day moving average

# Signal thresholds — match strc_tracker.py vocabulary so the alert UX is consistent.
# Tightened slightly for common stock because base-rate volume is higher than
# for preferreds, so noise floor is higher.
THRESHOLD_VERY_HIGH = 3.0      # ratio of today_vol / 20d_avg
THRESHOLD_HIGH = 2.0
THRESHOLD_ELEVATED = 1.5

# Dollar-volume floors so a low-priced stock can't trigger a screaming alert
# on a tiny absolute dollar move.
DOLLAR_VOL_FLOOR_VERY_HIGH_M = 50    # $50M
DOLLAR_VOL_FLOOR_HIGH_M = 20         # $20M
DOLLAR_VOL_FLOOR_ELEVATED_M = 5      # $5M

# ATM-filing freshness window — only consider an ATM "active" if filed/refreshed
# in the last 180 days. Older shelves have usually been issued against in full
# or expired (S-3 has 3-year statutory life, but practical decay is faster).
ATM_FRESHNESS_DAYS = 180


@dataclass
class EquityVolumeSignal:
    """Structured per-ticker result from the daily scan."""

    ticker: str
    company: str
    date: str
    price: float
    volume: int
    dollar_volume_m: float
    avg_volume: int
    avg_dollar_volume_m: float
    volume_ratio: float
    level: str = "NORMAL"          # NORMAL | ELEVATED | HIGH | VERY_HIGH | SUPPRESSED
    is_signal: bool = False
    has_active_atm: bool = False
    atm_capacity_usd: Optional[float] = None
    atm_status: Optional[str] = None   # 'active' | 'takedown' | 'shelf' | None
    message: str = ""


def _fetch_tickers() -> list[dict]:
    """Treasury companies eligible for equity-volume scan."""
    if not supabase:
        return []
    try:
        res = (
            supabase.table("treasury_companies")
            .select("ticker, company, btc_holdings, entity_type")
            .eq("entity_type", "public_company")
            .gte("btc_holdings", MIN_BTC_HOLDINGS)
            .limit(MAX_TICKERS_PER_RUN)
            .execute()
        )
        return [r for r in (res.data or []) if (r.get("ticker") or "").strip()]
    except Exception as e:
        logger.warning(f"equity_vol: ticker fetch failed: {e}")
        return []


def _fetch_active_atms() -> dict[str, dict]:
    """Build {ticker_upper: {status, max_capacity_usd, filing_date}} for
    every treasury issuer with an ATM filing inside the freshness window.

    Active or takedown status preferred; pure 'shelf' (capacity-only) is
    excluded because it doesn't represent issuance capability yet.
    """
    if not supabase:
        return {}
    cutoff = (datetime.now() - timedelta(days=ATM_FRESHNESS_DAYS)).strftime("%Y-%m-%d")
    try:
        res = (
            supabase.table("atm_filings")
            .select("ticker, status, max_capacity_usd, filing_date, sales_agent")
            .in_("status", ["active", "takedown"])
            .gte("filing_date", cutoff)
            .order("filing_date", desc=True)
            .execute()
        )
    except Exception as e:
        # atm_filings may not be migrated yet; degrade gracefully so the
        # volume scanner still runs (signals just won't have the funding
        # join — they get reported with has_active_atm=False).
        logger.debug(f"equity_vol: atm_filings query failed (probably pre-migration): {e}")
        return {}

    out: dict[str, dict] = {}
    for row in (res.data or []):
        t = (row.get("ticker") or "").upper()
        if not t:
            continue
        # Keep the most recent per ticker (results are date-DESC ordered)
        if t not in out:
            out[t] = {
                "status": row.get("status"),
                "max_capacity_usd": row.get("max_capacity_usd"),
                "filing_date": row.get("filing_date"),
                "sales_agent": row.get("sales_agent"),
            }
    return out


def _fetch_volume_data(tickers: list[str]) -> dict[str, dict]:
    """Batched yfinance volume + close pull. Returns {ticker_upper: {...}}.

    Tickers that fail to fetch return as None — caller logs + skips. yfinance
    occasionally bunches a multi-ticker frame oddly when single-ticker, so we
    explicitly branch on chunk size.
    """
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("equity_vol: yfinance not installed — skipping")
        return {}

    if not tickers:
        return {}

    out: dict[str, dict] = {}
    for i in range(0, len(tickers), YFINANCE_CHUNK):
        chunk = tickers[i : i + YFINANCE_CHUNK]
        try:
            data = yf.download(
                tickers=" ".join(chunk),
                period=HISTORY_PERIOD,
                interval="1d",
                progress=False,
                group_by="ticker",
                threads=True,
            )
        except Exception as e:
            logger.debug(f"equity_vol: yfinance chunk {i // YFINANCE_CHUNK} failed: {e}")
            continue

        for t in chunk:
            try:
                if len(chunk) == 1:
                    df = data
                else:
                    if t not in data.columns.get_level_values(0):
                        continue
                    df = data[t]

                vol = df["Volume"].dropna() if "Volume" in df else None
                close = df["Close"].dropna() if "Close" in df else None
                if vol is None or close is None or vol.empty or close.empty:
                    continue

                latest_vol = int(vol.iloc[-1])
                latest_close = float(close.iloc[-1])
                latest_date = vol.index[-1].strftime("%Y-%m-%d")

                # 20-day average EXCLUDING today (so today's spike isn't
                # diluted into its own baseline)
                avg_period = min(20, len(vol) - 1)
                if avg_period > 0:
                    avg_vol = int(vol.iloc[:-1].tail(avg_period).mean())
                else:
                    avg_vol = latest_vol

                out[t] = {
                    "date": latest_date,
                    "volume": latest_vol,
                    "avg_volume": avg_vol,
                    "price": round(latest_close, 4),
                }
            except Exception as e:
                logger.debug(f"equity_vol: parse failed for {t}: {e}")
                continue

    return out


def _classify(ratio: float, dollar_vol_m: float, has_active_atm: bool) -> tuple[str, bool, str]:
    """Returns (level, is_signal, message)."""
    # When there's no active ATM in our records, we still report volume
    # ratios — they're informational — but mark them SUPPRESSED so the
    # downstream alert doesn't fire. The volume might be on news; not
    # something we want to call as a "raising capital" signal.
    if not has_active_atm:
        if ratio >= THRESHOLD_HIGH:
            return (
                "SUPPRESSED",
                False,
                f"Volume {ratio}x normal (${dollar_vol_m}M) but no active ATM on file — alert suppressed.",
            )
        return "NORMAL", False, f"Volume {ratio}x average (${dollar_vol_m}M). Normal trading."

    if ratio >= THRESHOLD_VERY_HIGH and dollar_vol_m >= DOLLAR_VOL_FLOOR_VERY_HIGH_M:
        return (
            "VERY_HIGH",
            True,
            f"Volume {ratio}x normal (${dollar_vol_m}M) with active ATM. Aggressive issuance — BTC buy likely imminent.",
        )
    if ratio >= THRESHOLD_HIGH and dollar_vol_m >= DOLLAR_VOL_FLOOR_HIGH_M:
        return (
            "HIGH",
            True,
            f"Volume {ratio}x normal (${dollar_vol_m}M) with active ATM. Capital raise underway — BTC buy likely within days.",
        )
    if ratio >= THRESHOLD_ELEVATED and dollar_vol_m >= DOLLAR_VOL_FLOOR_ELEVATED_M:
        return (
            "ELEVATED",
            True,
            f"Volume {ratio}x normal (${dollar_vol_m}M) with active ATM. Above-average issuance activity.",
        )
    return "NORMAL", False, f"Volume {ratio}x average (${dollar_vol_m}M). Normal trading."


def _persist_signal(s: EquityVolumeSignal) -> None:
    """Upsert one signal into equity_volume_signals (migration 0017).

    Powers the customer-facing /signals dashboard page. Same-day re-runs
    update in place via UNIQUE(ticker, signal_date). Errors are swallowed
    so a Supabase hiccup never breaks the Telegram alert path.
    """
    if not supabase:
        return
    try:
        supabase.table("equity_volume_signals").upsert(
            {
                "ticker": s.ticker,
                "company": s.company,
                "signal_date": s.date,
                "level": s.level,
                "is_signal": bool(s.is_signal),
                "volume_ratio": s.volume_ratio,
                "volume": int(s.volume),
                "avg_volume": int(s.avg_volume),
                "dollar_volume_m": s.dollar_volume_m,
                "avg_dollar_volume_m": s.avg_dollar_volume_m,
                "price": s.price,
                "has_active_atm": bool(s.has_active_atm),
                "atm_capacity_usd": s.atm_capacity_usd,
                "atm_status": s.atm_status,
                "message": s.message,
                "components": {},
            },
            on_conflict="ticker,signal_date",
        ).execute()
    except Exception as e:
        logger.debug(f"equity_vol persist failed for {s.ticker}: {e}")


def _send_telegram_alert(s: EquityVolumeSignal) -> None:
    if not s.is_signal:
        return
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_PAID_CHANNEL_ID:
        return

    emoji = {"VERY_HIGH": "🔴", "HIGH": "🟠", "ELEVATED": "🟡"}.get(s.level, "📊")
    lines = [
        f"{emoji} **EQUITY VOLUME — {s.ticker}**",
        "",
        f"**{s.company}**",
        f"Volume ratio: **{s.volume_ratio}x** normal",
        f"Today: ${s.dollar_volume_m}M ({s.volume:,} shares)",
        f"20d avg: ${s.avg_dollar_volume_m}M ({s.avg_volume:,})",
        f"Price: ${s.price}",
    ]
    if s.has_active_atm:
        cap = ""
        if s.atm_capacity_usd:
            cap = (
                f" (capacity ${s.atm_capacity_usd / 1e9:.1f}B)"
                if s.atm_capacity_usd >= 1e9
                else f" (capacity ${s.atm_capacity_usd / 1e6:.0f}M)"
            )
        lines.append("")
        lines.append(f"📜 ATM status: **{s.atm_status}**{cap}")
    lines.append("")
    lines.append(s.message)
    lines.append("")
    lines.append("Why this matters:")
    lines.append("Treasury-equity ATM proceeds fund BTC purchases.")
    lines.append("Volume spike + active shelf → buy historically within days.")
    lines.append("")
    lines.append("---")
    lines.append("Treasury Purchase Signal Intelligence")

    msg = "\n".join(lines)
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_PAID_CHANNEL_ID,
                "text": msg,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
    except Exception as e:
        logger.debug(f"equity_vol telegram send failed: {e}")


def scan_treasury_equity_volume() -> dict:
    """Run the volume scan + join against active ATMs + emit signals.

    Returns: {'scanned', 'signals', 'suppressed', 'errors', 'by_level': {...}}.
    """
    issuers = _fetch_tickers()
    if not issuers:
        logger.info("equity_vol: no eligible issuers")
        return {"scanned": 0, "signals": 0, "suppressed": 0, "errors": 0, "by_level": {}}

    tickers = [(r["ticker"] or "").upper() for r in issuers]
    atm_map = _fetch_active_atms()
    vol_data = _fetch_volume_data(tickers)

    scanned = 0
    signals = 0
    suppressed = 0
    errors = 0
    by_level: dict[str, int] = {}

    for issuer in issuers:
        ticker = (issuer.get("ticker") or "").upper()
        company = issuer.get("company") or ticker

        v = vol_data.get(ticker)
        if not v:
            continue

        scanned += 1
        avg_vol = max(v["avg_volume"], 1)
        ratio = round(v["volume"] / avg_vol, 2)
        dollar_vol = v["volume"] * v["price"]
        avg_dollar_vol = avg_vol * v["price"]

        atm_info = atm_map.get(ticker, {})
        has_active = bool(atm_info)
        level, is_signal, message = _classify(ratio, round(dollar_vol / 1e6, 1), has_active)

        sig = EquityVolumeSignal(
            ticker=ticker,
            company=company,
            date=v["date"],
            price=v["price"],
            volume=v["volume"],
            dollar_volume_m=round(dollar_vol / 1e6, 1),
            avg_volume=avg_vol,
            avg_dollar_volume_m=round(avg_dollar_vol / 1e6, 1),
            volume_ratio=ratio,
            level=level,
            is_signal=is_signal,
            has_active_atm=has_active,
            atm_capacity_usd=float(atm_info.get("max_capacity_usd") or 0) or None if has_active else None,
            atm_status=atm_info.get("status") if has_active else None,
            message=message,
        )

        by_level[level] = by_level.get(level, 0) + 1
        if level == "SUPPRESSED":
            suppressed += 1

        # Persist every signal (including NORMAL) so the dashboard has a
        # complete daily view. Migration 0017 created equity_volume_signals
        # with UNIQUE(ticker, signal_date) so same-day re-runs upsert cleanly.
        _persist_signal(sig)

        if is_signal:
            signals += 1
            try:
                _send_telegram_alert(sig)
                logger.info(
                    f"equity_vol signal: {ticker} {level} ({ratio}x, ${sig.dollar_volume_m}M, "
                    f"atm={sig.atm_status})"
                )
            except Exception as e:
                errors += 1
                logger.debug(f"equity_vol alert send failed for {ticker}: {e}")
                capture_exception(e, context={
                    "where": "equity_volume_tracker.scan_treasury_equity_volume",
                    "ticker": ticker,
                })

    if scanned > 0:
        freshness.record_success(
            "equity_volume_tracker",
            detail=f"{scanned} tickers, {signals} signals, {suppressed} suppressed",
        )

    logger.info(
        f"Equity volume scan: {scanned} scanned, {signals} signals, "
        f"{suppressed} suppressed (no ATM), levels={by_level}"
    )
    return {
        "scanned": scanned,
        "signals": signals,
        "suppressed": suppressed,
        "errors": errors,
        "by_level": by_level,
    }


# ─── Manual smoke test ────────────────────────────────────────────────────


if __name__ == "__main__":
    print("Treasury-equity volume scanner — manual run...")
    stats = scan_treasury_equity_volume()
    print(stats)
