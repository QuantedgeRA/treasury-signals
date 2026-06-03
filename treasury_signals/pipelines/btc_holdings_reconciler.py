"""
btc_holdings_reconciler.py — divergence-proof source-of-truth for
treasury_companies.btc_holdings.

DESIGN
======
The pre-2026-05-22 architecture had ~25 modules writing directly to
treasury_companies.btc_holdings. Last-writer-wins; no provenance; no
divergence detection. The KEEL bug (CoinGecko reported 1,558 while
BitcoinTreasuries reported the correct 2,469) was inevitable under that
shape and would have recurred for any newer/recently-renamed entity.

This module is the SINGLE WRITER of btc_holdings going forward. Every
other source writes attributed observations to btc_holdings_observations
via record_observation(); the reconciler reads those observations,
applies a trust hierarchy + staleness penalty, picks the canonical
value, writes it back to treasury_companies, and alerts on divergence.

INVARIANTS
==========
- Every change to treasury_companies.btc_holdings carries (source, timestamp).
  No NULL-source writes after the backfill.
- Every observation has a source citation. Anyone asking "why is X's value Y?"
  gets an audit trail via v_btc_holdings_provenance.
- When sources disagree by > threshold, a divergence_alert is generated AND
  a Telegram message is sent. Silent disagreement is impossible.
- Manual overrides (source='manual_override') always win — they're how a
  human breaks ties.

TRUST HIERARCHY
===============
Higher = more authoritative. Effective trust = base_trust - staleness_penalty.

    manual_override        999    human-verified; ultimate trump
    edgar_8k               100    SEC 8-K with explicit BTC amount
    10q_10k_disclosure      95    quarterly/annual filing
    press_release           85    company-issued press release
    company_irpage          80    investor-relations page (scraped from issuer)
    bitcointreasuries       60    aggregator, comprehensive + frequently updated
    coingecko               40    aggregator, has been stale on KEEL/etc.
    defillama               30    DeFi-focused aggregator
    bt_self_reported        25    BitcoinTreasuries' "self-reported" flag values
    backfill_initial        10    initial seed value, lowest possible trust

Staleness: -10 per 30 days since observed_at. A 91-day-old EDGAR observation
(100 - 30) still beats a fresh CoinGecko (40), as expected. A 90-day-old
press release (85 - 30 = 55) beats fresh CoinGecko but loses to fresh
BitcoinTreasuries.

DIVERGENCE THRESHOLDS
=====================
A disagreement is "alert-worthy" when EITHER:
  - spread_btc >= 50 (absolute) AND spread_pct >= 1%, OR
  - spread_pct >= 5% (relative)

Both gates exist because:
  - 5% spread on 100 BTC = 5 BTC, not worth waking up for
  - 0.5% spread on 800,000 BTC = 4,000 BTC, definitely worth waking up for
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
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
TELEGRAM_ADMIN_CHANNEL_ID = os.getenv("TELEGRAM_ADMIN_CHANNEL_ID", "") or os.getenv("TELEGRAM_PAID_CHANNEL_ID", "")
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "https://treasurysignal.io")

# ─── Trust hierarchy ──────────────────────────────────────────────────────

SOURCE_TRUST: dict[str, int] = {
    "manual_override": 999,
    "edgar_8k": 100,
    "10q_10k_disclosure": 95,
    "press_release": 85,
    "company_irpage": 80,
    "bitcointreasuries": 60,
    "coingecko": 40,
    "defillama": 30,
    "bt_self_reported": 25,
    "backfill_initial": 10,
}
UNKNOWN_SOURCE_TRUST = 20  # any source not in the map gets this floor

# Each 30 days of staleness costs 10 trust points
STALENESS_PENALTY_PER_30_DAYS = 10
MAX_OBSERVATION_AGE_DAYS = 180  # observations older than this are ignored entirely

# Divergence alert thresholds — see module docstring
DIVERGENCE_MIN_BTC = 50
DIVERGENCE_MIN_PCT_FOR_BTC_GATE = 1.0
DIVERGENCE_MIN_PCT = 5.0

# Only consider observations from sources with at least this effective trust
# when computing spread. Low-trust signals shouldn't drive alerts.
DIVERGENCE_MIN_TRUST = 30


# ─── Data classes ─────────────────────────────────────────────────────────


@dataclass
class Observation:
    """One claim about (ticker, btc_value) from one source at one point in time."""

    ticker: str
    source: str
    btc_value: float
    observed_at: datetime
    source_url: Optional[str] = None
    excerpt: Optional[str] = None
    components: dict = field(default_factory=dict)


@dataclass
class ResolveResult:
    """Output of resolve_ticker(): the chosen value + provenance + divergence."""

    ticker: str
    resolved_value: float
    resolved_source: str
    resolved_trust: float          # effective trust = base - staleness
    observations: list[Observation]
    spread_btc: float
    spread_pct: float
    is_divergent: bool
    diverging_sources: list[str]


# ─── Recording observations (public write API) ────────────────────────────


def record_observation(
    ticker: str,
    source: str,
    btc_value: float,
    *,
    source_url: Optional[str] = None,
    excerpt: Optional[str] = None,
    components: Optional[dict] = None,
    observed_at: Optional[datetime] = None,
) -> bool:
    """Append an observation to btc_holdings_observations.

    This is the new public write API. Every source (CoinGecko, BitcoinTreasuries,
    EDGAR parsers, press-release scrapers, manual overrides) writes here
    instead of directly to treasury_companies.btc_holdings. The reconciler
    reads from this ledger to compute the canonical value.

    Returns True on successful insert, False on validation or DB failure.
    """
    if not supabase:
        logger.warning("reconciler: supabase unconfigured, observation dropped")
        return False
    ticker = (ticker or "").strip().upper()
    if not ticker:
        logger.debug("reconciler: empty ticker, observation dropped")
        return False
    source = (source or "").strip().lower()
    if not source:
        logger.debug(f"reconciler: empty source for {ticker}, observation dropped")
        return False
    try:
        btc_value = float(btc_value)
    except (TypeError, ValueError):
        logger.debug(f"reconciler: non-numeric btc_value for {ticker}/{source}: {btc_value!r}")
        return False
    if btc_value < 0 or btc_value > 50_000_000:
        # Sanity check: total BTC supply is ~21M; >50M means the parser
        # grabbed a market-cap number or similar.
        logger.warning(f"reconciler: implausible btc_value for {ticker}/{source}: {btc_value}")
        return False

    payload = {
        "ticker": ticker,
        "source": source,
        "btc_value": btc_value,
        "observed_at": (observed_at or datetime.now(timezone.utc)).isoformat(),
        "source_url": source_url,
        "excerpt": (excerpt or "")[:1000] or None,
        "components": components or {},
    }
    try:
        supabase.table("btc_holdings_observations").insert(payload).execute()
        return True
    except Exception as e:
        logger.warning(f"reconciler: insert failed for {ticker}/{source}: {e}")
        capture_exception(e, context={
            "where": "btc_holdings_reconciler.record_observation",
            "ticker": ticker,
            "source": source,
        })
        return False


# ─── Trust scoring ────────────────────────────────────────────────────────


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_observed_at(s) -> datetime:
    if isinstance(s, datetime):
        return s if s.tzinfo else s.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


def effective_trust(source: str, observed_at: datetime, now: Optional[datetime] = None) -> float:
    """Trust score after applying staleness penalty.

    Pure function. Caller may pass `now` for deterministic testing.
    """
    base = SOURCE_TRUST.get(source.lower(), UNKNOWN_SOURCE_TRUST)
    if observed_at == datetime.min.replace(tzinfo=timezone.utc):
        return 0.0
    now = now or _now_utc()
    age_days = max(0, (now - observed_at).total_seconds() / 86400.0)
    penalty = (age_days / 30.0) * STALENESS_PENALTY_PER_30_DAYS
    return max(0.0, base - penalty)


# ─── Resolution ───────────────────────────────────────────────────────────


def _fetch_observations_for_ticker(ticker: str) -> list[Observation]:
    """Pull most-recent observation per source for one ticker, within the
    MAX_OBSERVATION_AGE_DAYS window.

    Returns at most one Observation per source.
    """
    if not supabase:
        return []
    cutoff = (_now_utc() - timedelta(days=MAX_OBSERVATION_AGE_DAYS)).isoformat()
    try:
        res = (
            supabase.table("btc_holdings_observations")
            .select("ticker, source, btc_value, observed_at, source_url, excerpt, components")
            .eq("ticker", ticker)
            .gte("observed_at", cutoff)
            .order("observed_at", desc=True)
            .execute()
        )
    except Exception as e:
        logger.warning(f"reconciler: fetch failed for {ticker}: {e}")
        return []

    # Take only the most-recent row per source (rows are already DESC ordered).
    seen_sources: set[str] = set()
    obs: list[Observation] = []
    for row in (res.data or []):
        src = (row.get("source") or "").lower()
        if not src or src in seen_sources:
            continue
        seen_sources.add(src)
        try:
            btc_val = float(row.get("btc_value") or 0)
        except (TypeError, ValueError):
            continue
        obs.append(Observation(
            ticker=row.get("ticker") or ticker,
            source=src,
            btc_value=btc_val,
            observed_at=_parse_observed_at(row.get("observed_at")),
            source_url=row.get("source_url"),
            excerpt=row.get("excerpt"),
            components=row.get("components") or {},
        ))
    return obs


def _compute_divergence(observations: list[Observation]) -> tuple[float, float, list[str]]:
    """Returns (spread_btc, spread_pct, diverging_sources).

    Only considers observations with effective trust >= DIVERGENCE_MIN_TRUST,
    so a stale CoinGecko reading doesn't drive an alert all by itself.
    """
    if not observations:
        return 0.0, 0.0, []
    now = _now_utc()
    weighted = [
        (o, effective_trust(o.source, o.observed_at, now))
        for o in observations
    ]
    qualifying = [(o, t) for (o, t) in weighted if t >= DIVERGENCE_MIN_TRUST]
    if len(qualifying) < 2:
        return 0.0, 0.0, []
    values = [o.btc_value for (o, _) in qualifying]
    vmin = min(values)
    vmax = max(values)
    spread_btc = vmax - vmin
    spread_pct = (spread_btc / vmax * 100) if vmax > 0 else 0.0
    diverging = [o.source for (o, _) in qualifying] if spread_btc > 0 else []
    return spread_btc, spread_pct, diverging


def _is_divergent(spread_btc: float, spread_pct: float) -> bool:
    """Apply the divergence-threshold rules described in the module docstring."""
    if spread_btc >= DIVERGENCE_MIN_BTC and spread_pct >= DIVERGENCE_MIN_PCT_FOR_BTC_GATE:
        return True
    if spread_pct >= DIVERGENCE_MIN_PCT:
        return True
    return False


def resolve_ticker(ticker: str) -> Optional[ResolveResult]:
    """Pull observations + apply trust hierarchy → canonical (value, source).

    Returns None when no observations exist for this ticker — the caller
    should leave treasury_companies untouched in that case (don't zero it out).
    """
    observations = _fetch_observations_for_ticker(ticker)
    if not observations:
        return None

    now = _now_utc()
    scored = [(o, effective_trust(o.source, o.observed_at, now)) for o in observations]
    # Sort by trust DESC, then by observed_at DESC for ties.
    scored.sort(key=lambda x: (-x[1], -x[0].observed_at.timestamp()))
    chosen_obs, chosen_trust = scored[0]

    spread_btc, spread_pct, diverging = _compute_divergence(observations)

    # A human manual_override is adjudicated truth. The aggregators disagreeing
    # with it is the EXPECTED state — they're the very reason the override was
    # needed (e.g. COIN: bitcointreasuries scraped 182 vs the real 16,492). So
    # we don't keep raising divergence alerts for an overridden ticker; that
    # would re-open a "resolved" alert on every cycle forever. (Trade-off: a
    # stale override won't self-alert if real holdings later move — overrides
    # should be reviewed periodically, which is a separate concern from the
    # aggregator-disagreement noise this suppresses.)
    is_override = chosen_obs.source == "manual_override"
    return ResolveResult(
        ticker=ticker,
        resolved_value=chosen_obs.btc_value,
        resolved_source=chosen_obs.source,
        resolved_trust=chosen_trust,
        observations=observations,
        spread_btc=spread_btc,
        spread_pct=spread_pct,
        is_divergent=(not is_override) and _is_divergent(spread_btc, spread_pct),
        diverging_sources=diverging,
    )


# ─── Persistence + alerts ─────────────────────────────────────────────────


def _create_divergence_alert(result: ResolveResult) -> Optional[int]:
    """Upsert a divergence_alert row per ticker. Returns the row id.

    Dedupe strategy: at most ONE 'open' alert per ticker exists at any
    time. When reconcile_ticker runs again on the same ticker and a
    divergence is still present, we UPDATE the existing open alert
    in place (refreshes source_values + spread + detected_at) instead
    of inserting a new row. This prevents the alerts table from
    ballooning when treasury_sync runs the reconciler on each cycle.

    When the divergence eventually clears (sources converge), the
    open alert is auto-resolved by _maybe_resolve_divergence_alert()
    called from reconcile_ticker.
    """
    if not supabase:
        return None
    source_values = {
        o.source: {
            "value": o.btc_value,
            "observed_at": o.observed_at.isoformat(),
            "source_url": o.source_url,
            "effective_trust": effective_trust(o.source, o.observed_at),
        }
        for o in result.observations
    }
    payload = {
        "ticker": result.ticker,
        "source_values": source_values,
        "min_value": min(o.btc_value for o in result.observations),
        "max_value": max(o.btc_value for o in result.observations),
        "spread_btc": result.spread_btc,
        "spread_pct": result.spread_pct,
        "resolved_value": result.resolved_value,
        "resolved_source": result.resolved_source,
        "resolved_trust_score": result.resolved_trust,
        "status": "open",
        "detected_at": _now_utc().isoformat(),
    }

    # Look for an existing open alert for this ticker. If present, UPDATE
    # in place so we don't create duplicates each reconcile cycle.
    try:
        existing = (
            supabase.table("btc_holdings_divergence_alerts")
            .select("id")
            .eq("ticker", result.ticker)
            .eq("status", "open")
            .order("detected_at", desc=True)
            .limit(1)
            .execute()
        )
    except Exception:
        existing = None

    open_id = existing.data[0]["id"] if (existing and existing.data) else None

    try:
        if open_id is not None:
            supabase.table("btc_holdings_divergence_alerts").update(payload).eq(
                "id", open_id
            ).execute()
            return open_id
        res = supabase.table("btc_holdings_divergence_alerts").insert(payload).execute()
        return (res.data[0]["id"] if res.data else None)
    except Exception as e:
        logger.warning(f"reconciler: divergence alert upsert failed for {result.ticker}: {e}")
        capture_exception(e, context={
            "where": "btc_holdings_reconciler._create_divergence_alert",
            "ticker": result.ticker,
        })
        return None


def _maybe_resolve_open_alert(ticker: str) -> None:
    """When a ticker's sources converge and no longer diverge, close any
    open alert row so it stops appearing in widgets/dashboards.

    Called from reconcile_ticker on the no-divergence path.
    """
    if not supabase:
        return
    try:
        supabase.table("btc_holdings_divergence_alerts").update(
            {"status": "auto_resolved", "acknowledged_at": _now_utc().isoformat()}
        ).eq("ticker", ticker).eq("status", "open").execute()
    except Exception as e:
        logger.debug(f"reconciler: auto-resolve open alert for {ticker}: {e}")


def _send_telegram_divergence_alert(result: ResolveResult, alert_id: Optional[int]) -> None:
    """Notify the admin channel about a new divergence."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_ADMIN_CHANNEL_ID:
        return
    lines = [
        f"🚨 **BTC HOLDINGS DIVERGENCE — {result.ticker}**",
        "",
        f"Sources disagree by **{result.spread_btc:,.0f} BTC** ({result.spread_pct:.1f}%).",
        "",
    ]
    for o in result.observations:
        trust = effective_trust(o.source, o.observed_at)
        chosen_marker = " ← chosen" if o.source == result.resolved_source else ""
        age_d = (_now_utc() - o.observed_at).days
        lines.append(
            f"• `{o.source:<22}` {o.btc_value:>10,.0f} BTC  "
            f"trust={trust:>5.1f}  age={age_d:>3}d{chosen_marker}"
        )
    lines.append("")
    lines.append(f"Resolved → **{result.resolved_value:,.0f} BTC** via `{result.resolved_source}`")
    if alert_id:
        lines.append(f"Alert id: {alert_id}")
    lines.append(f"⏰ {_now_utc().strftime('%Y-%m-%d %H:%M UTC')}")

    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_ADMIN_CHANNEL_ID,
                "text": "\n".join(lines),
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
    except Exception as e:
        logger.debug(f"reconciler: telegram divergence alert send failed: {e}")


def _persist_resolved(result: ResolveResult, alert_id: Optional[int]) -> bool:
    """Write the chosen value + provenance back to treasury_companies."""
    if not supabase:
        return False
    payload = {
        "btc_holdings": int(round(result.resolved_value)),
        "btc_resolved_source": result.resolved_source,
        "btc_resolved_at": _now_utc().isoformat(),
        "btc_divergence_spread_pct": round(result.spread_pct, 2),
        "btc_divergence_alert_id": alert_id,
        "last_updated": _now_utc().isoformat(),
    }
    try:
        supabase.table("treasury_companies").update(payload).eq("ticker", result.ticker).execute()
        return True
    except Exception as e:
        logger.warning(f"reconciler: treasury_companies update failed for {result.ticker}: {e}")
        capture_exception(e, context={
            "where": "btc_holdings_reconciler._persist_resolved",
            "ticker": result.ticker,
        })
        return False


# ─── Public reconciliation API ────────────────────────────────────────────


def reconcile_ticker(ticker: str, *, send_alerts: bool = True) -> Optional[ResolveResult]:
    """End-to-end: resolve → persist → alert (if divergent). For one ticker.

    Returns the ResolveResult on success (regardless of whether divergence
    was detected), or None when no observations exist for this ticker.
    """
    ticker = (ticker or "").strip().upper()
    if not ticker:
        return None
    result = resolve_ticker(ticker)
    if not result:
        return None

    alert_id: Optional[int] = None
    if result.is_divergent:
        alert_id = _create_divergence_alert(result)
        if send_alerts:
            _send_telegram_divergence_alert(result, alert_id)
    else:
        # No divergence detected this run — auto-close any prior open alert
        # so the divergence stops appearing in widgets/digests once sources
        # have converged. Status 'auto_resolved' (vs 'acknowledged') makes
        # the audit log distinguish human-triaged from auto-cleared events.
        _maybe_resolve_open_alert(ticker)

    _persist_resolved(result, alert_id)

    if result.is_divergent:
        logger.warning(
            f"DIVERGENCE {ticker}: {result.spread_btc:,.0f} BTC spread ({result.spread_pct:.1f}%) "
            f"chose {result.resolved_source}={result.resolved_value:,.0f}"
        )
    else:
        logger.debug(
            f"reconciled {ticker}: {result.resolved_value:,.0f} via {result.resolved_source}"
        )
    return result


def reconcile_all(
    *,
    only_tickers: Optional[list[str]] = None,
    send_alerts: bool = True,
) -> dict:
    """Batch-reconcile every ticker with recent observations.

    Returns a stats dict: {'reconciled', 'divergent', 'no_observations', 'errors'}.
    """
    if not supabase:
        return {"reconciled": 0, "divergent": 0, "no_observations": 0, "errors": 0}

    if only_tickers:
        tickers = [t.upper() for t in only_tickers if t]
    else:
        # All tickers that have at least one observation in the window.
        try:
            cutoff = (_now_utc() - timedelta(days=MAX_OBSERVATION_AGE_DAYS)).isoformat()
            res = (
                supabase.table("btc_holdings_observations")
                .select("ticker")
                .gte("observed_at", cutoff)
                .execute()
            )
            tickers = sorted({(r.get("ticker") or "").upper() for r in (res.data or []) if r.get("ticker")})
        except Exception as e:
            logger.warning(f"reconciler: ticker list fetch failed: {e}")
            return {"reconciled": 0, "divergent": 0, "no_observations": 0, "errors": 1}

    reconciled = 0
    divergent = 0
    no_obs = 0
    errors = 0
    divergent_tickers: list[str] = []

    for t in tickers:
        try:
            r = reconcile_ticker(t, send_alerts=send_alerts)
            if r is None:
                no_obs += 1
                continue
            reconciled += 1
            if r.is_divergent:
                divergent += 1
                divergent_tickers.append(t)
        except Exception as e:
            errors += 1
            logger.warning(f"reconciler: {t} failed: {e}")
            capture_exception(e, context={
                "where": "btc_holdings_reconciler.reconcile_all",
                "ticker": t,
            })

    logger.info(
        f"reconcile_all: {reconciled} reconciled, {divergent} divergent, "
        f"{no_obs} no-obs, {errors} errors. "
        f"Divergent: {divergent_tickers[:10]}"
        + (f" +{len(divergent_tickers)-10} more" if len(divergent_tickers) > 10 else "")
    )
    return {
        "reconciled": reconciled,
        "divergent": divergent,
        "no_observations": no_obs,
        "errors": errors,
        "divergent_tickers": divergent_tickers,
    }


# ─── Manual smoke test ────────────────────────────────────────────────────


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        for t in sys.argv[1:]:
            r = reconcile_ticker(t, send_alerts=False)
            if r is None:
                print(f"{t}: NO OBSERVATIONS")
                continue
            print(f"{t}: resolved={r.resolved_value:,.0f} via {r.resolved_source} (trust {r.resolved_trust:.1f})")
            print(f"  spread: {r.spread_btc:,.0f} BTC ({r.spread_pct:.1f}%)  divergent={r.is_divergent}")
            for o in r.observations:
                age_d = (_now_utc() - o.observed_at).days
                print(f"  • {o.source:<22} {o.btc_value:>10,.0f}  age={age_d}d  trust={effective_trust(o.source, o.observed_at):.1f}")
    else:
        print("Reconciling all tickers with observations in window…")
        stats = reconcile_all()
        print(stats)
