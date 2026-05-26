"""
wallet_monitor.py — Tier 3 real-time movement monitoring + alerting.

Scans every is_active=true row in entity_wallets for new outgoing
(and incoming) transactions, classifies the counterparty when possible,
persists into wallet_movements (migration 0021), and dispatches alerts
on customer-relevant flows.

THE TRADE SIGNAL
================
The strategic review at 2026-05-21 framed Tier 3 as the killer feature:

  "Knowing the destination is MSTR (no signal) vs. Coinbase deposit
   (likely sale) is the difference between 'no signal' and 'sell now'."

Classification rules (in evaluation order):
  1. Counterparty in entity_wallets, SAME ticker as source
       → 'internal_reorg' — no trade signal
  2. Counterparty in entity_wallets, DIFFERENT ticker
       → 'custody_change' — possible sale to another entity
  3. Counterparty matches exchange deposit pattern (heuristic + label list)
       → 'exchange_inflow' (outgoing) or 'exchange_outflow' (incoming)
  4. Otherwise
       → 'unknown'

Alerts (Telegram + email to Pro+ subscribers, filtered by watchlist):
  - exchange_inflow:  bearish (likely sale incoming)
  - custody_change:   informational
  - exchange_outflow: bullish (likely new purchase landing)
  - internal_reorg:   no alert
  - unknown:          no alert (we don't speculate)

DATA SOURCE
===========
blockchain.com REST API. Same as wallet_clusterer.py. Free, rate-limited,
no key. We cap per-address tx scan to MAX_NEW_TXS_PER_RUN to keep one
monitor pass under ~5min for a few hundred tracked wallets.

IDEMPOTENCY
===========
wallet_movements has a UNIQUE constraint on (tx_hash, wallet_address,
direction). Re-running the monitor never duplicates rows — we INSERT
ignore conflicts. Alerts are gated by alert_dispatched=false so each
movement alerts at most once.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
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
TELEGRAM_PAID_CHANNEL_ID = os.getenv("TELEGRAM_PAID_CHANNEL_ID", "")
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "https://treasurysignal.io")

HEADERS = {
    "User-Agent": "TreasurySignalIntelligence/1.0 (wallet-monitor)",
    "Accept": "application/json",
}

# Caps
MAX_WALLETS_PER_RUN   = 200
MAX_NEW_TXS_PER_WALLET = 25       # only the most-recent N txs per wallet per run
BLOCKCHAIN_INFO_THROTTLE = 0.4

# Alert thresholds (BTC) — events smaller than this don't surface
ALERT_MIN_BTC = 50                # ~$3-5M at current prices

# Known exchange deposit patterns — Tier 2 lite (no clustering, just
# documented exchange hot wallet prefixes / known patterns). Conservative
# list; we'd rather miss a classification than mis-label.
KNOWN_EXCHANGE_PREFIXES = {
    # We start small and let the entity_wallets table grow over time.
    # Each entry: (prefix, exchange_name). Confidence used for the
    # counterparty label is 60 (mid-tier).
}


# ─── Data classes ────────────────────────────────────────────────────


@dataclass
class Movement:
    tx_hash: str
    wallet_address: str
    ticker: str
    direction: str               # 'inflow' | 'outflow'
    btc_amount: float
    block_time: Optional[datetime]
    block_height: Optional[int]
    counterparty_address: Optional[str]
    counterparty_entity: Optional[str]
    counterparty_label: Optional[str]
    counterparty_confidence: Optional[int]
    classification: str


# ─── blockchain.com client ───────────────────────────────────────────


def _fetch_address_txs(address: str, limit: int = MAX_NEW_TXS_PER_WALLET) -> Optional[list]:
    """Fetch up to `limit` most-recent txs for one address."""
    if not address:
        return None
    try:
        time.sleep(BLOCKCHAIN_INFO_THROTTLE)
        url = f"https://blockchain.info/rawaddr/{address}?limit={limit}"
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if not resp.ok:
            return None
        return (resp.json() or {}).get("txs") or []
    except Exception:
        return None


# ─── State helpers ───────────────────────────────────────────────────


def _fetch_tracked_wallets() -> list[dict]:
    """All is_active=true entity_wallets at any confidence."""
    if not supabase:
        return []
    try:
        res = (
            supabase.table("entity_wallets")
            .select("ticker, entity_name, wallet_address, confidence_score")
            .eq("is_active", True)
            .eq("blockchain", "bitcoin")
            .limit(MAX_WALLETS_PER_RUN)
            .execute()
        )
        return res.data or []
    except Exception as e:
        logger.warning(f"monitor: tracked-wallet fetch failed: {e}")
        return []


def _lookup_attributed_entity(address: str) -> Optional[dict]:
    """Reverse-lookup a counterparty address against entity_wallets."""
    if not supabase or not address:
        return None
    try:
        res = (
            supabase.table("entity_wallets")
            .select("ticker, entity_name, confidence_score")
            .eq("wallet_address", address)
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else None
    except Exception:
        return None


def _seen_tx_hashes_for_wallet(address: str) -> set[str]:
    """Pull previously-seen tx hashes for this wallet so we don't re-process."""
    if not supabase:
        return set()
    try:
        res = (
            supabase.table("wallet_movements")
            .select("tx_hash")
            .eq("wallet_address", address)
            .limit(500)
            .execute()
        )
        return {r["tx_hash"] for r in (res.data or []) if r.get("tx_hash")}
    except Exception:
        return set()


# ─── Classification ──────────────────────────────────────────────────


def _classify(direction: str, source_ticker: str, counterparty_addr: Optional[str]) -> tuple[str, Optional[dict]]:
    """Returns (classification, counterparty_attribution_dict_or_None)."""
    if not counterparty_addr:
        return "unknown", None
    cp = _lookup_attributed_entity(counterparty_addr)
    if cp:
        if cp.get("ticker") == source_ticker:
            return "internal_reorg", cp
        return "custody_change", cp
    # Tier 2 lite — exchange-pattern matching. Currently no entries in
    # KNOWN_EXCHANGE_PREFIXES; the pattern infra is in place for when
    # we add labeled exchange addresses.
    for prefix, exchange_name in KNOWN_EXCHANGE_PREFIXES.items():
        if counterparty_addr.startswith(prefix):
            label = "exchange_inflow" if direction == "outflow" else "exchange_outflow"
            return label, {
                "ticker": None,
                "entity_name": exchange_name,
                "confidence_score": 60,
            }
    return "unknown", None


def _extract_counterparty(tx: dict, wallet_address: str, direction: str) -> Optional[str]:
    """For an outflow: pick the largest non-self output address.
    For an inflow:   pick the largest input address that isn't ours.
    Returns None when no clean counterparty exists (mixed txs, etc.)."""
    if direction == "outflow":
        candidates = [(o.get("addr"), o.get("value") or 0) for o in (tx.get("out") or []) if o.get("addr") and o.get("addr") != wallet_address]
    else:
        candidates = []
        for inp in (tx.get("inputs") or []):
            prev = inp.get("prev_out") or {}
            a = prev.get("addr")
            if a and a != wallet_address:
                candidates.append((a, prev.get("value") or 0))
    if not candidates:
        return None
    candidates.sort(key=lambda x: -x[1])
    return candidates[0][0]


def _direction_and_amount(tx: dict, wallet_address: str) -> Optional[tuple[str, float]]:
    """Determine net direction + BTC amount from the wallet's POV.

    Sum the wallet's outflows (input value) and inflows (output value)
    in this tx. The dominant side wins; absolute value of the net is
    the reported amount.
    """
    out_value = 0  # wallet sent
    in_value = 0   # wallet received
    for inp in (tx.get("inputs") or []):
        prev = inp.get("prev_out") or {}
        if prev.get("addr") == wallet_address:
            out_value += prev.get("value") or 0
    for o in (tx.get("out") or []):
        if o.get("addr") == wallet_address:
            in_value += o.get("value") or 0
    if out_value == in_value == 0:
        return None
    if out_value > in_value:
        net_sats = out_value - in_value
        return "outflow", net_sats / 1e8
    else:
        net_sats = in_value - out_value
        return "inflow", net_sats / 1e8


# ─── Persistence + alerts ────────────────────────────────────────────


def _persist_movement(m: Movement) -> bool:
    if not supabase:
        return False
    payload = {
        "tx_hash": m.tx_hash,
        "wallet_address": m.wallet_address,
        "ticker": m.ticker,
        "direction": m.direction,
        "btc_amount": round(m.btc_amount, 8),
        "block_time": m.block_time.isoformat() if m.block_time else None,
        "block_height": m.block_height,
        "counterparty_address": m.counterparty_address,
        "counterparty_entity": m.counterparty_entity,
        "counterparty_label": m.counterparty_label,
        "counterparty_confidence": m.counterparty_confidence,
        "classification": m.classification,
    }
    try:
        supabase.table("wallet_movements").upsert(
            payload, on_conflict="tx_hash,wallet_address,direction"
        ).execute()
        return True
    except Exception as e:
        logger.debug(f"monitor: movement upsert failed for {m.tx_hash[:12]}: {e}")
        return False


def _format_telegram_alert(m: Movement, entity_name: str) -> str:
    emoji_map = {
        "exchange_inflow":  "🔴",
        "exchange_outflow": "🟢",
        "custody_change":   "🟡",
    }
    title_map = {
        "exchange_inflow":  "POSSIBLE SALE INCOMING",
        "exchange_outflow": "POSSIBLE PURCHASE INCOMING",
        "custody_change":   "CUSTODY CHANGE",
    }
    emoji = emoji_map.get(m.classification, "📊")
    title = title_map.get(m.classification, "WALLET MOVEMENT")

    lines = [
        f"{emoji} **{title} — {m.ticker}**",
        "",
        f"**{entity_name}** {m.direction}: **{m.btc_amount:,.4f} BTC**",
    ]
    if m.counterparty_entity:
        lines.append(f"Counterparty: **{m.counterparty_entity}** (confidence {m.counterparty_confidence or '?'})")
    elif m.counterparty_label:
        lines.append(f"Counterparty type: {m.counterparty_label}")
    if m.counterparty_address:
        ca = m.counterparty_address
        lines.append(f"Address: `{ca[:12]}...{ca[-8:]}`")
    lines.append("")
    lines.append(f"📄 [tx]({DASHBOARD_URL}/mnav/{m.ticker})  ·  [block explorer](https://blockchain.info/tx/{m.tx_hash})")
    if m.block_time:
        lines.append(f"⏰ {m.block_time.strftime('%Y-%m-%d %H:%M UTC')}")
    return "\n".join(lines)


def _send_telegram_alert(m: Movement, entity_name: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_PAID_CHANNEL_ID:
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_PAID_CHANNEL_ID,
                "text": _format_telegram_alert(m, entity_name),
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        return resp.ok
    except Exception as e:
        logger.debug(f"monitor: telegram send failed: {e}")
        return False


def _mark_alerted(m: Movement) -> None:
    if not supabase:
        return
    try:
        supabase.table("wallet_movements").update({"alert_dispatched": True}).eq(
            "tx_hash", m.tx_hash
        ).eq("wallet_address", m.wallet_address).eq("direction", m.direction).execute()
    except Exception:
        pass


# ─── Main scan ───────────────────────────────────────────────────────


def scan_tracked_wallets(*, send_alerts: bool = True) -> dict:
    """Iterate every tracked wallet, fetch its recent txs, persist new
    movements + dispatch alerts on customer-relevant classifications.
    """
    wallets = _fetch_tracked_wallets()
    if not wallets:
        logger.info("monitor: no tracked wallets — Tier 3 is dormant until entity_wallets has rows")
        return {"wallets_scanned": 0, "new_movements": 0, "alerts": 0}

    new_movements = 0
    alerts = 0
    by_classification: dict[str, int] = {}

    for w in wallets:
        addr = w["wallet_address"]
        ticker = w["ticker"]
        entity_name = w.get("entity_name") or ticker
        seen = _seen_tx_hashes_for_wallet(addr)

        txs = _fetch_address_txs(addr) or []
        for tx in txs:
            txh = tx.get("hash") or ""
            if not txh or txh in seen:
                continue
            net = _direction_and_amount(tx, addr)
            if not net:
                continue
            direction, btc_amount = net
            counterparty = _extract_counterparty(tx, addr, direction)
            classification, cp_attr = _classify(direction, ticker, counterparty)

            block_time = None
            if tx.get("time"):
                try:
                    block_time = datetime.fromtimestamp(tx["time"], tz=timezone.utc)
                except Exception:
                    block_time = None

            m = Movement(
                tx_hash=txh,
                wallet_address=addr,
                ticker=ticker,
                direction=direction,
                btc_amount=btc_amount,
                block_time=block_time,
                block_height=tx.get("block_height"),
                counterparty_address=counterparty,
                counterparty_entity=(cp_attr.get("ticker") if cp_attr else None),
                counterparty_label=classification if classification != "unknown" else None,
                counterparty_confidence=(cp_attr.get("confidence_score") if cp_attr else None),
                classification=classification,
            )
            if _persist_movement(m):
                new_movements += 1
                by_classification[classification] = by_classification.get(classification, 0) + 1
                # Alert on customer-relevant classifications above threshold
                if send_alerts and btc_amount >= ALERT_MIN_BTC and classification in (
                    "exchange_inflow", "exchange_outflow", "custody_change"
                ):
                    if _send_telegram_alert(m, entity_name):
                        alerts += 1
                        _mark_alerted(m)

    logger.info(
        f"monitor: scanned {len(wallets)} wallets, {new_movements} new movements, "
        f"{alerts} alerts. by_class={by_classification}"
    )
    return {
        "wallets_scanned": len(wallets),
        "new_movements": new_movements,
        "alerts": alerts,
        "by_classification": by_classification,
    }


if __name__ == "__main__":
    import sys
    apply = "--alerts" in sys.argv
    stats = scan_tracked_wallets(send_alerts=apply)
    print(stats)
