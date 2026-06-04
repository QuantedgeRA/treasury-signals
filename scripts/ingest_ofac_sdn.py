"""
ingest_ofac_sdn.py — OFAC sanctions BTC addresses into entity_wallets.

Wallet attribution's strict-honesty bound (confidence > 95 needs a primary
source) makes broad treasury-EQUITY coverage hard — public companies don't
disclose cold-storage addresses. But one corpus is gold-standard primary
source and free: the US Treasury OFAC Specially Designated Nationals (SDN)
list, which publishes the BTC addresses of sanctioned entities directly in a
machine-readable feed. We parse those programmatically (no manual address
entry → no fat-finger misattribution risk) and upsert them at confidence 100.

This serves the wallet-LOOKUP / counterparty-screening use case
(/api/v1/wallet-lookup → "this address is OFAC-sanctioned, entity X, program
Y"), which is genuinely valuable to a desk. It does NOT serve "what's MSTR's
wallet" — that still needs the Arkham decision (see
[[wallet-attribution-regime-b-pending]]).

Provenance / honesty:
  - source         : US Treasury OFAC SDN list (sdn.xml), primary source.
  - confidence      : 100 (government-published). source_citation set on every
                      row, satisfying the confidence>95 rule.
  - attribution_method = 'ofac_sdn'
  - ticker          = 'OFAC.SDN' sentinel (these aren't treasury equities, so
                      they stay out of the per-ticker company views; the
                      by-address lookup still finds them).
  - The attribution is "address sanctioned / associated with entity X per
    OFAC" — association, not a claim of sole control. Noted per row.

Usage:
    python scripts/ingest_ofac_sdn.py            # dry-run: counts + sample
    python scripts/ingest_ofac_sdn.py --apply    # upsert into entity_wallets
"""
from __future__ import annotations

import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import requests
from dotenv import load_dotenv
from supabase import create_client

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
if not (SUPABASE_URL and SUPABASE_KEY):
    sys.exit("SUPABASE_URL + SUPABASE_KEY required in .env")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

OFAC_SDN_URL = "https://www.treasury.gov/ofac/downloads/sdn.xml"
HEADERS = {"User-Agent": "TreasurySignalIntelligence admin@quantedgeriskadvisory.com"}
XBT_ID_TYPE = "Digital Currency Address - XBT"

# Basic BTC address sanity (legacy base58 1.../3..., bech32 bc1...). Defensive
# only — OFAC data is clean, but we never want to write a garbage address.
_BTC_RE = re.compile(r"^(bc1[a-z0-9]{20,80}|[13][a-km-zA-HJ-NP-Z1-9]{20,40})$")


def _localname(tag: str) -> str:
    """Strip the XML namespace: '{http://...}sdnEntry' -> 'sdnEntry'."""
    return tag.rsplit("}", 1)[-1]


def _child_text(entry, name: str) -> str:
    for c in entry:
        if _localname(c.tag) == name and c.text:
            return c.text.strip()
    return ""


def _entity_name(entry) -> str:
    last = _child_text(entry, "lastName")
    first = _child_text(entry, "firstName")
    return (f"{first} {last}".strip() if first else last) or "Unknown sanctioned entity"


def _programs(entry) -> list[str]:
    for c in entry:
        if _localname(c.tag) == "programList":
            return [p.text.strip() for p in c if p.text]
    return []


def _xbt_addresses(entry) -> list[str]:
    """Return all XBT (Bitcoin) addresses declared in this sdnEntry's idList."""
    out = []
    for c in entry:
        if _localname(c.tag) != "idList":
            continue
        for idnode in c:
            if _localname(idnode.tag) != "id":
                continue
            id_type = _child_text(idnode, "idType")
            id_num = _child_text(idnode, "idNumber")
            if id_type == XBT_ID_TYPE and id_num:
                out.append(id_num.strip())
    return out


def fetch_and_parse() -> list[dict]:
    """Download the OFAC SDN list and return one row dict per BTC address."""
    resp = requests.get(OFAC_SDN_URL, headers=HEADERS, timeout=120)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)

    rows: dict[str, dict] = {}  # keyed by address → dedupe
    skipped = 0
    for entry in root:
        if _localname(entry.tag) != "sdnEntry":
            continue
        addrs = _xbt_addresses(entry)
        if not addrs:
            continue
        name = _entity_name(entry)
        uid = _child_text(entry, "uid")
        sdn_type = _child_text(entry, "sdnType")
        progs = ", ".join(_programs(entry)) or "n/a"
        for addr in addrs:
            if not _BTC_RE.match(addr):
                skipped += 1
                continue
            # First entity to claim an address wins (rare cross-listing).
            rows.setdefault(addr, {
                "ticker": "OFAC.SDN",
                "entity_name": name[:200],
                "wallet_address": addr,
                "blockchain": "bitcoin",
                "confidence_score": 100,
                "attribution_method": "ofac_sdn",
                "source_citation": OFAC_SDN_URL,
                "is_active": True,
                "notes": (
                    f"OFAC SDN uid {uid}; sdnType {sdn_type or 'n/a'}; "
                    f"programs: {progs}. Sanctioned address per US Treasury — "
                    f"association with the listed entity, not a claim of sole control."
                ),
            })
    if skipped:
        print(f"  (skipped {skipped} non-BTC-shaped XBT id values)")
    return list(rows.values())


def main():
    apply = "--apply" in sys.argv
    print(f"OFAC SDN ingest — source: {OFAC_SDN_URL}")
    rows = fetch_and_parse()
    print(f"Parsed {len(rows)} unique BTC addresses from sanctioned entities.")

    # How many are new vs already present?
    try:
        existing = supabase.table("entity_wallets").select("wallet_address").eq(
            "attribution_method", "ofac_sdn"
        ).execute().data or []
        existing_addrs = {r["wallet_address"] for r in existing}
        new = [r for r in rows if r["wallet_address"] not in existing_addrs]
        print(f"Already in entity_wallets (ofac_sdn): {len(existing_addrs)} | new this run: {len(new)}")
    except Exception as e:
        print(f"  (couldn't read existing rows: {e})")

    print("\nSample:")
    for r in rows[:5]:
        print(f"  {r['wallet_address']:<46} {r['entity_name'][:50]}")

    if not apply:
        print("\nDry-run. Re-run with --apply to upsert into entity_wallets.")
        return

    # Upsert in batches on the unique wallet_address constraint. Idempotent:
    # re-running refreshes entity_name/notes/programs as OFAC updates listings.
    written = 0
    for i in range(0, len(rows), 100):
        batch = rows[i:i + 100]
        try:
            supabase.table("entity_wallets").upsert(
                batch, on_conflict="wallet_address"
            ).execute()
            written += len(batch)
            print(f"  upserted {written}/{len(rows)}")
        except Exception as e:
            print(f"  batch {i//100} failed: {e}")
    print(f"\nDone. Upserted {written} OFAC SDN BTC addresses.")


if __name__ == "__main__":
    main()
