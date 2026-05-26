"""
wallet_clusterer.py — Tier 2 probabilistic wallet attribution.

Given one or more "seed" addresses with HIGH-confidence attribution
(typically primary-source-disclosed, or community-known with high
agreement), this module expands the seed into the full likely cluster
of co-controlled addresses using two well-documented heuristics:

  1. COMMON-INPUT HEURISTIC (CIH)
     If two addresses appear together as INPUTS in the same transaction,
     they are almost certainly controlled by the same entity. (Spending
     bitcoin requires the private key for every input, so the spender
     must own all input addresses.) This is the strongest on-chain
     signal short of a signed message from the address.
     Confidence: high (75-85 within 1 hop, decaying 10pt per additional hop)

  2. CHANGE-ADDRESS HEURISTIC (CAH)
     Some transactions create "change" outputs returning unspent value to
     a new address controlled by the spender. We identify likely change
     by:
       - exact-amount-match output → known recipient (the other output is change)
       - single-output-later-spent-quickly pattern
       - script-type matching the input script type
     Confidence: medium (55-70 — change-addr inference is fallible)

Decisions baked into the design:

  - We do NOT use exchange-pattern matching at this tier. That requires
    a corpus of labeled exchange addresses; we don't have one and don't
    want to depend on Arkham-style data.
  - We HARD-CAP at hop_distance = 3. After 3 hops the false-positive
    rate explodes; the strategic review's "82% confidence" framing only
    holds for tight clusters.
  - Every derived address writes BOTH to entity_wallets (the canonical
    table) AND to wallet_clusters (the audit trail). Each derived row
    in entity_wallets has attribution_method='cluster_expansion' or
    'change_addr', and source_citation pointing to the evidence tx hash.

Per [[wallet_attribution_design]]: confidence > 95 still requires a
primary-source citation — clustering can never produce a 100-confidence
row. The strict bound is preserved.

Data source: blockchain.com REST API. Free tier, no key, rate-limited to
about 10 req/sec. We sleep aggressively to stay under.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
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

HEADERS = {
    "User-Agent": "TreasurySignalIntelligence/1.0 (wallet-clusterer)",
    "Accept": "application/json",
}

# Caps + thresholds — tuned for safety, not exhaustiveness. Better to
# under-cluster than to over-claim.
MAX_HOP_DISTANCE = 3
MAX_TX_PER_ADDRESS = 200         # blockchain.com paginates at 50 per call
MAX_DERIVED_PER_RUN = 5000       # safety stop; one seed shouldn't yield this many
BLOCKCHAIN_INFO_THROTTLE = 0.4   # seconds between requests

# Per-heuristic base confidence (before hop decay)
CONF_COMMON_INPUT_BASE = 82
CONF_CHANGE_ADDR_BASE  = 62
HOP_DECAY_PER_LEVEL    = 10


# ─── Data classes ────────────────────────────────────────────────────


@dataclass
class DerivedAttribution:
    """One newly-discovered address attributed to an entity via heuristic."""
    derived_address: str
    seed_address: str
    ticker: str
    hop_distance: int
    heuristic: str                        # 'common_input' | 'change_addr'
    confidence_score: int
    evidence_tx_hash: str
    evidence_notes: str = ""
    components: dict = field(default_factory=dict)


# ─── blockchain.com client ───────────────────────────────────────────


def _fetch_address_txs(address: str, offset: int = 0) -> Optional[dict]:
    """Fetch the transaction history for one address via blockchain.com.

    Returns the parsed JSON dict or None on error. Each call returns up
    to 50 transactions.
    """
    if not address:
        return None
    try:
        time.sleep(BLOCKCHAIN_INFO_THROTTLE)
        url = f"https://blockchain.info/rawaddr/{address}?limit=50&offset={offset}"
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code == 429:
            logger.warning(f"clusterer: rate-limited on {address}, backing off 5s")
            time.sleep(5)
            return None
        if not resp.ok:
            return None
        return resp.json()
    except Exception as e:
        logger.debug(f"clusterer: fetch failed for {address}: {e}")
        return None


def _fetch_all_txs(address: str, cap: int = MAX_TX_PER_ADDRESS) -> list[dict]:
    """Page through blockchain.com until we have up to `cap` txs."""
    out: list[dict] = []
    offset = 0
    while len(out) < cap:
        page = _fetch_address_txs(address, offset=offset)
        if not page:
            break
        txs = page.get("txs") or []
        if not txs:
            break
        out.extend(txs)
        if len(txs) < 50:
            break
        offset += 50
    return out[:cap]


# ─── Heuristics ──────────────────────────────────────────────────────


def common_input_partners(address: str, tx: dict) -> list[str]:
    """Return all OTHER input addresses appearing alongside `address` in tx.

    The CIH claim: addresses spent together as inputs in a single tx
    share an owner. Returns deduped addresses, excluding the input
    address itself.
    """
    inputs = tx.get("inputs") or []
    input_addrs: list[str] = []
    for i in inputs:
        prev = i.get("prev_out") or {}
        addr = prev.get("addr")
        if addr:
            input_addrs.append(addr)
    if address not in input_addrs:
        # CIH only applies when our subject IS an input; otherwise the tx
        # doesn't tell us anything about co-ownership.
        return []
    return sorted(set(a for a in input_addrs if a != address))


def likely_change_address(address: str, tx: dict) -> Optional[str]:
    """Try to identify the change output of a tx where `address` is an input.

    Heuristics (simplest first):
      1. If there are exactly 2 outputs and one matches the script type
         of inputs, that one is likely change.
      2. If one output is "round" (e.g. 0.1, 1.0, 10.0 BTC) and another
         is fractional/precise, the precise one is likely change.

    Returns the change address or None when we can't decide cleanly.
    We bias toward FALSE NEGATIVES — better to miss a change-addr than
    to over-cluster.
    """
    inputs = tx.get("inputs") or []
    outputs = tx.get("out") or []
    if len(outputs) != 2:
        return None
    # Bail if `address` is itself an output (self-send, no useful inference)
    if any((o.get("addr") == address) for o in outputs):
        return None

    # Get input script types (rough proxy via address prefix)
    def _prefix_type(addr: str) -> str:
        if not addr: return ""
        if addr.startswith("bc1"): return "bech32"
        if addr.startswith("3"):   return "p2sh"
        if addr.startswith("1"):   return "p2pkh"
        return ""
    input_types = {_prefix_type((i.get("prev_out") or {}).get("addr") or "") for i in inputs}

    candidates = []
    for o in outputs:
        addr = o.get("addr")
        if not addr:
            continue
        # Same-script-type match
        same_type = _prefix_type(addr) in input_types
        value_btc = (o.get("value") or 0) / 1e8
        # "Round" detection: value is a clean multiple of 0.01 BTC
        is_round = (round(value_btc * 100) - value_btc * 100 == 0) and value_btc >= 0.01
        candidates.append((addr, same_type, is_round, value_btc))

    if len(candidates) != 2:
        return None
    # Heuristic combination
    a, b = candidates
    # If exactly one is "round" and the other isn't → other is change
    if a[2] and not b[2]:
        return b[0]
    if b[2] and not a[2]:
        return a[0]
    # If exactly one is same-type → that's change
    if a[1] and not b[1]:
        return a[0]
    if b[1] and not a[1]:
        return b[0]
    return None  # ambiguous


# ─── Persistence ─────────────────────────────────────────────────────


def _persist_attribution(d: DerivedAttribution, entity_name: Optional[str]) -> bool:
    """Upsert into entity_wallets + wallet_clusters atomically-ish.

    Two tables means two writes; we accept eventual consistency on
    failure (the cluster row is the audit; the entity_wallets row is
    the customer-facing surface). If entity_wallets write succeeds and
    wallet_clusters fails, the audit trail is incomplete but the data
    is correct. The opposite (cluster row without entity row) is the
    less acceptable case so we do entity_wallets second.
    """
    if not supabase:
        return False
    cluster_row = {
        "derived_address": d.derived_address,
        "seed_address": d.seed_address,
        "ticker": d.ticker,
        "hop_distance": d.hop_distance,
        "heuristic": d.heuristic,
        "confidence_score": d.confidence_score,
        "confidence_decay": HOP_DECAY_PER_LEVEL,
        "evidence_tx_hash": d.evidence_tx_hash,
        "evidence_notes": d.evidence_notes,
        "components": d.components,
    }
    try:
        supabase.table("wallet_clusters").upsert(
            cluster_row, on_conflict="derived_address,seed_address"
        ).execute()
    except Exception as e:
        logger.warning(f"clusterer: cluster row upsert failed: {e}")
        capture_exception(e, context={"where": "wallet_clusterer._persist.cluster"})
        # continue — we still want the entity row written if possible

    # entity_wallets: only INSERT if this address isn't already there
    # with a HIGHER confidence. We never downgrade existing attributions.
    try:
        existing = (
            supabase.table("entity_wallets")
            .select("id, confidence_score")
            .eq("wallet_address", d.derived_address)
            .limit(1)
            .execute()
        )
        if existing.data and existing.data[0].get("confidence_score", 0) >= d.confidence_score:
            return True   # already higher, do nothing
        method_tag = "cluster_expansion" if d.heuristic == "common_input" else "change_addr"
        attribution_row = {
            "ticker": d.ticker,
            "entity_name": entity_name,
            "wallet_address": d.derived_address,
            "blockchain": "bitcoin",
            "confidence_score": d.confidence_score,
            "attribution_method": method_tag,
            "source_citation": f"https://blockchain.info/tx/{d.evidence_tx_hash}",
            "notes": (f"Derived via {d.heuristic} from {d.seed_address[:8]}...{d.seed_address[-6:]} "
                      f"at hop {d.hop_distance}. {d.evidence_notes}")[:1000],
            "components": d.components,
        }
        supabase.table("entity_wallets").upsert(
            attribution_row, on_conflict="wallet_address"
        ).execute()
        return True
    except Exception as e:
        logger.warning(f"clusterer: entity_wallets upsert failed: {e}")
        capture_exception(e, context={"where": "wallet_clusterer._persist.entity"})
        return False


# ─── Expansion driver ────────────────────────────────────────────────


def expand_from_seed(
    seed_address: str,
    ticker: str,
    entity_name: Optional[str] = None,
    max_hops: int = MAX_HOP_DISTANCE,
    dry_run: bool = True,
) -> dict:
    """Walk the cluster outward from a seed address.

    Returns: {'seed', 'hops_walked', 'derived_count', 'by_heuristic', 'by_hop'}

    BFS by hop level. At each level, fetch the address's transaction
    history, apply both heuristics to every tx where the address is an
    input, and collect new addresses with confidence scores.
    """
    if not seed_address:
        return {"seed": "", "derived_count": 0, "error": "empty seed"}

    visited: set[str] = {seed_address}
    current_frontier: list[str] = [seed_address]
    derived: list[DerivedAttribution] = []
    by_heuristic = {"common_input": 0, "change_addr": 0}
    by_hop = {}

    for hop in range(1, max_hops + 1):
        if not current_frontier:
            break
        next_frontier_set: set[str] = set()
        for src in current_frontier:
            txs = _fetch_all_txs(src)
            for tx in txs:
                txh = tx.get("hash") or ""
                # CIH: get all input partners when src is an input
                for partner in common_input_partners(src, tx):
                    if partner in visited:
                        continue
                    conf = max(0, CONF_COMMON_INPUT_BASE - HOP_DECAY_PER_LEVEL * (hop - 1))
                    derived.append(DerivedAttribution(
                        derived_address=partner,
                        seed_address=seed_address,
                        ticker=ticker,
                        hop_distance=hop,
                        heuristic="common_input",
                        confidence_score=conf,
                        evidence_tx_hash=txh,
                        evidence_notes=f"Co-input with {src[:8]}...{src[-6:]} in tx {txh[:12]}...",
                    ))
                    by_heuristic["common_input"] += 1
                    by_hop[hop] = by_hop.get(hop, 0) + 1
                    visited.add(partner)
                    next_frontier_set.add(partner)
                # CAH: look for likely change output when src is an input
                change = likely_change_address(src, tx)
                if change and change not in visited:
                    conf = max(0, CONF_CHANGE_ADDR_BASE - HOP_DECAY_PER_LEVEL * (hop - 1))
                    derived.append(DerivedAttribution(
                        derived_address=change,
                        seed_address=seed_address,
                        ticker=ticker,
                        hop_distance=hop,
                        heuristic="change_addr",
                        confidence_score=conf,
                        evidence_tx_hash=txh,
                        evidence_notes=f"Likely change of {src[:8]}...{src[-6:]} in tx {txh[:12]}...",
                    ))
                    by_heuristic["change_addr"] += 1
                    by_hop[hop] = by_hop.get(hop, 0) + 1
                    visited.add(change)
                    next_frontier_set.add(change)
                if len(derived) >= MAX_DERIVED_PER_RUN:
                    logger.warning(f"clusterer: hit MAX_DERIVED_PER_RUN={MAX_DERIVED_PER_RUN}, stopping")
                    break
            if len(derived) >= MAX_DERIVED_PER_RUN:
                break
        if len(derived) >= MAX_DERIVED_PER_RUN:
            break
        current_frontier = list(next_frontier_set)

    logger.info(
        f"clusterer: seed={seed_address[:12]}... ticker={ticker} "
        f"-> {len(derived)} derived (by_heuristic={by_heuristic}, by_hop={by_hop})"
    )

    if not dry_run:
        ok = 0
        fail = 0
        for d in derived:
            if _persist_attribution(d, entity_name):
                ok += 1
            else:
                fail += 1
        logger.info(f"clusterer: persisted {ok} ok, {fail} failed")

    return {
        "seed": seed_address,
        "hops_walked": min(max_hops, hop),
        "derived_count": len(derived),
        "by_heuristic": by_heuristic,
        "by_hop": by_hop,
        "dry_run": dry_run,
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python -m treasury_signals.pipelines.wallet_clusterer SEED_ADDRESS TICKER [--apply]")
        sys.exit(1)
    seed = sys.argv[1]
    ticker = sys.argv[2]
    apply = "--apply" in sys.argv
    stats = expand_from_seed(seed_address=seed, ticker=ticker, dry_run=not apply)
    print(stats)
