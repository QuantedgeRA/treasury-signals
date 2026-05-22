"""
atm_filing_detector.py — At-the-market (ATM) equity-offering detector.

Tier-2 build #2 follow-up: extends the STRC-volume signal (Strategy-only)
to every public BTC treasury company by parsing the underlying SEC forms
that fund the purchases.

The chain:
  S-3       → shelf registration. Declares max raise capacity ("up to $X
              over 3 years"). Not an issuance — capacity only.
  S-3/A     → amendment, usually expanding capacity or adding co-agents.
  424B5     → prospectus supplement filed in connection with a TAKEDOWN.
              When you see one of these on a treasury company, equity
              issuance is HAPPENING — proceeds typically land in BTC
              within days.
  424B7     → registration-statement supplements (often agent additions
              to an existing ATM).

The reconciler watches for purchase events (8-Ks); this scanner watches
the FUNDING side. Both feed the same hedge-fund-analyst-tier picture.

Why a separate adapter (vs. extending edgar_realtime.py): edgar_realtime
keyword-searches for "bitcoin"/"btc" across 8-K filings. ATM filings are
S-3/424B forms that almost never mention bitcoin in the headline — the
treasury connection is implicit (the issuer's other 8-Ks). So we query
EDGAR by *form type + known treasury issuers* instead of by keyword.

Defensive:
  • Public companies only (entity_type='public_company') with a known CIK.
  • Per-issuer try/except — one bad filing can't poison the batch.
  • Hard cap MAX_ISSUERS_PER_RUN so the EDGAR rate-limit budget is bounded.
  • Idempotent persist via accession_number unique constraint.
"""

from __future__ import annotations

import os
import re
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

HEADERS = {
    "User-Agent": "TreasurySignalIntelligence admin@quantedgeriskadvisory.com",
    "Accept": "application/json",
}

# EDGAR submissions endpoint — returns recent filings for a CIK
EDGAR_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"

# Forms we care about (in priority order)
ATM_FORM_TYPES = {"S-3", "S-3/A", "424B5", "424B7", "424B3", "424B4"}

# Keywords that confirm a filing is ATM-related rather than a generic shelf
ATM_KEYWORDS = [
    "at the market",
    "at-the-market",
    "at the-market",
    "atm offering",
    "atm program",
    "sales agreement",
    "controlled equity offering",
    "open market sale",
    "equity distribution agreement",
]

SALES_AGENTS = [
    "Cantor Fitzgerald",
    "TD Cowen",
    "Cowen",
    "Barclays",
    "Mizuho",
    "BTIG",
    "Stifel",
    "Citigroup",
    "Morgan Stanley",
    "Goldman Sachs",
    "Jefferies",
    "Virtu",
    "B. Riley",
    "Roth Capital",
    "H.C. Wainwright",
    "Maxim Group",
    "Needham",
    "Compass Point",
    "Aegis Capital",
]

CAPACITY_PATTERNS = [
    # "up to $5,000,000,000"
    r"up to\s+\$\s*([\d,]+(?:\.\d+)?)\s*(billion|million|B|M)?",
    # "aggregate offering price of up to $X"
    r"aggregate offering price of\s+(?:up to\s+)?\$\s*([\d,]+(?:\.\d+)?)\s*(billion|million|B|M)?",
    # "$21 billion" / "$5,000.0 million"
    r"\$\s*([\d,]+(?:\.\d+)?)\s*(billion|million)\s+(?:at[-\s]the[-\s]market|atm|sales agreement|offering)",
]

# Caps so a single run never balloons cost
MAX_ISSUERS_PER_RUN = 250        # public treasury cos; we currently track ~200
MAX_FILINGS_PER_ISSUER = 8       # newest first; ATM filings are infrequent
MIN_FILING_DATE_LOOKBACK_DAYS = 90  # ignore anything older than this on first scan
EDGAR_THROTTLE_SECONDS = 0.12    # SEC limit is 10 req/sec; stay well under


@dataclass
class AtmDetection:
    """Structured output from parsing a single EDGAR filing."""

    ticker: str
    company: str
    cik: str
    accession_number: str
    form_type: str
    filing_date: str
    filing_url: str
    status: str = "shelf"
    max_capacity_usd: Optional[float] = None
    sales_agent: Optional[str] = None
    excerpt: Optional[str] = None
    components: dict = field(default_factory=dict)


# ─── Parsing helpers ─────────────────────────────────────────────────────


def _parse_capacity_usd(text: str) -> Optional[float]:
    """Find the largest dollar capacity figure in the text.

    Returns USD as a float. Filters out anything below $10M (too small to be
    a treasury-relevant ATM and almost certainly a parse error).
    """
    if not text:
        return None
    text_lower = text.lower()
    candidates: list[float] = []
    for pattern in CAPACITY_PATTERNS:
        for match in re.finditer(pattern, text_lower):
            try:
                num = float(match.group(1).replace(",", ""))
                unit = (match.group(2) or "").lower() if match.lastindex and match.lastindex >= 2 else ""
                if unit in ("billion", "b"):
                    num *= 1_000_000_000
                elif unit in ("million", "m"):
                    num *= 1_000_000
                if num >= 10_000_000:  # noise floor
                    candidates.append(num)
            except (ValueError, IndexError):
                continue
    return max(candidates) if candidates else None


def _find_sales_agent(text: str) -> Optional[str]:
    """Return the first canonical sales-agent name found in the text."""
    if not text:
        return None
    for agent in SALES_AGENTS:
        if agent.lower() in text.lower():
            return agent
    return None


def _has_atm_keyword(text: str) -> bool:
    if not text:
        return False
    text_lower = text.lower()
    return any(kw in text_lower for kw in ATM_KEYWORDS)


def _classify_status(form_type: str, has_atm_keyword: bool) -> str:
    """Map (form_type, ATM-mention) → status enum used in atm_filings.status.

    424B* = takedown (actual issuance event)
    S-3 or S-3/A with ATM keyword = active (sales agreement in place)
    S-3 or S-3/A without ATM keyword = shelf (capacity only)
    """
    if form_type.startswith("424B"):
        return "takedown"
    if has_atm_keyword:
        return "active"
    return "shelf"


def _extract_excerpt(text: str, max_chars: int = 500) -> str:
    """Pull a 500-char window around the first ATM-keyword match for audit."""
    if not text:
        return ""
    text_lower = text.lower()
    for kw in ATM_KEYWORDS:
        idx = text_lower.find(kw)
        if idx != -1:
            start = max(0, idx - 150)
            end = min(len(text), idx + 350)
            return text[start:end].strip()
    return text[:max_chars].strip()


# ─── EDGAR fetch helpers ─────────────────────────────────────────────────


def _zero_pad_cik(cik: str) -> str:
    """EDGAR submissions URL needs a 10-digit zero-padded CIK."""
    return str(cik).strip().lstrip("0").zfill(10)


def _fetch_recent_filings(cik: str) -> list[dict]:
    """Pull the most-recent filings for one CIK via the submissions JSON.

    EDGAR returns them newest-first in parallel arrays. We zip them into
    dicts and return up to MAX_FILINGS_PER_ISSUER matching ATM form types.
    """
    if not cik:
        return []
    padded = _zero_pad_cik(cik)
    url = EDGAR_SUBMISSIONS.format(cik=padded)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if not resp.ok:
            return []
        data = resp.json()
        recent = (data.get("filings", {}) or {}).get("recent", {}) or {}
        forms = recent.get("form", [])
        accessions = recent.get("accessionNumber", [])
        dates = recent.get("filingDate", [])
        primary_docs = recent.get("primaryDocument", [])

        cutoff = (datetime.now() - timedelta(days=MIN_FILING_DATE_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
        results: list[dict] = []
        for i, form in enumerate(forms):
            if form not in ATM_FORM_TYPES:
                continue
            f_date = dates[i] if i < len(dates) else ""
            if f_date and f_date < cutoff:
                continue
            acc = accessions[i] if i < len(accessions) else ""
            doc = primary_docs[i] if i < len(primary_docs) else ""
            results.append({
                "form_type": form,
                "accession_number": acc,
                "filing_date": f_date,
                "primary_document": doc,
                "cik": padded,
            })
            if len(results) >= MAX_FILINGS_PER_ISSUER:
                break
        return results
    except Exception as e:
        logger.debug(f"ATM: submissions fetch failed for CIK {cik}: {e}")
        return []


def _fetch_filing_text(cik: str, accession_number: str, primary_document: str) -> str:
    """Fetch the primary document for a filing and return text (HTML-stripped)."""
    if not accession_number or not primary_document:
        return ""
    acc_no_dashes = accession_number.replace("-", "")
    cik_no_pad = str(int(cik))
    url = f"https://www.sec.gov/Archives/edgar/data/{cik_no_pad}/{acc_no_dashes}/{primary_document}"
    try:
        resp = requests.get(url, headers={**HEADERS, "Accept": "text/html"}, timeout=20)
        if not resp.ok:
            return ""
        # ATM filings are long — cap to first 200KB. Cover page + summary
        # always has the capacity + sales-agent info.
        raw = resp.text[:200_000]
        # Cheap HTML-strip: drop tags. We don't need structure, just keywords.
        stripped = re.sub(r"<[^>]+>", " ", raw)
        stripped = re.sub(r"\s+", " ", stripped)
        return stripped
    except Exception as e:
        logger.debug(f"ATM: text fetch failed for {accession_number}: {e}")
        return ""


def _build_filing_url(cik: str, accession_number: str) -> str:
    """Filing-index URL on SEC.gov (canonical citable link)."""
    if not accession_number:
        return ""
    cik_no_pad = str(int(cik))
    acc_no_dashes = accession_number.replace("-", "")
    return f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik_no_pad}&type={accession_number}"


# ─── Persistence ─────────────────────────────────────────────────────────


def _persist_detection(d: AtmDetection) -> bool:
    if not supabase:
        return False
    try:
        supabase.table("atm_filings").upsert(
            {
                "ticker": d.ticker,
                "company": d.company,
                "cik": d.cik,
                "accession_number": d.accession_number,
                "form_type": d.form_type,
                "filing_date": d.filing_date,
                "filing_url": d.filing_url,
                "status": d.status,
                "max_capacity_usd": round(d.max_capacity_usd, 2) if d.max_capacity_usd else None,
                "sales_agent": d.sales_agent,
                "excerpt": (d.excerpt or "")[:1000],
                "components": d.components,
            },
            on_conflict="accession_number",
        ).execute()
        return True
    except Exception as e:
        logger.warning(f"ATM persist failed for {d.accession_number}: {e}")
        capture_exception(e, context={
            "where": "atm_filing_detector._persist_detection",
            "accession": d.accession_number,
            "ticker": d.ticker,
        })
        return False


def _send_telegram_alert(d: AtmDetection) -> None:
    """Post a Telegram alert when a new takedown / active ATM is detected.

    We DON'T alert on plain 'shelf' filings — those are just capacity
    paperwork. The high-signal events are takedowns (424B5) and the moment
    a sales agreement gets attached to a shelf.
    """
    if d.status not in ("takedown", "active"):
        return
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_PAID_CHANNEL_ID:
        return

    emoji = "💵" if d.status == "takedown" else "📜"
    headline = "ATM TAKEDOWN" if d.status == "takedown" else "ACTIVE ATM"

    lines = [
        f"{emoji} **{headline} — {d.ticker}**",
        "",
        f"**{d.company}** filed {d.form_type} on {d.filing_date}",
    ]
    if d.max_capacity_usd and d.max_capacity_usd >= 1e6:
        cap_str = f"${d.max_capacity_usd / 1e9:.2f}B" if d.max_capacity_usd >= 1e9 else f"${d.max_capacity_usd / 1e6:.0f}M"
        lines.append(f"💰 Capacity: {cap_str}")
    if d.sales_agent:
        lines.append(f"🏦 Sales agent: {d.sales_agent}")
    if d.status == "takedown":
        lines.append("")
        lines.append("Equity issuance event. Treasury-equity ATM proceeds historically fund the next BTC purchase within days.")
    elif d.status == "active":
        lines.append("")
        lines.append("Sales agreement attached to shelf. Issuance can begin at any time.")
    if d.filing_url:
        lines.append("")
        lines.append(f"📄 [View filing]({d.filing_url})")
    lines.append(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}")

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
        logger.debug(f"ATM telegram send failed: {e}")


# ─── Main driver ─────────────────────────────────────────────────────────


def _fetch_issuers() -> list[dict]:
    """Public BTC-treasury companies with a CIK resolvable via SEC's
    company_tickers.json.

    treasury_companies has no `cik` column (verified 2026-05-21); the SEC
    ticker→CIK map is cached in-process by ticker_validator. Joining at
    runtime avoids a schema migration just for this scanner.
    """
    if not supabase:
        return []
    try:
        res = (
            supabase.table("treasury_companies")
            .select("ticker, company, btc_holdings, entity_type")
            .eq("entity_type", "public_company")
            .gt("btc_holdings", 0)
            .limit(MAX_ISSUERS_PER_RUN)
            .execute()
        )
        rows = res.data or []
    except Exception as e:
        logger.warning(f"ATM: issuer fetch failed: {e}")
        return []

    # Join to SEC CIK map. Tickers that don't resolve (foreign listings, OTC
    # without an SEC registration) are silently dropped — they don't file on
    # EDGAR so there's nothing to scan anyway.
    try:
        from treasury_signals.sync.ticker_validator import _load_sec_tickers
        sec_map = _load_sec_tickers() or {}
    except Exception as e:
        logger.warning(f"ATM: SEC ticker map load failed: {e}")
        sec_map = {}

    out = []
    for r in rows:
        ticker = (r.get("ticker") or "").upper().strip()
        sec_entry = sec_map.get(ticker)
        if sec_entry and sec_entry.get("cik"):
            r["cik"] = sec_entry["cik"]
            out.append(r)
    return out


def _get_processed_accessions() -> set[str]:
    """Skip filings we've already persisted."""
    if not supabase:
        return set()
    try:
        res = supabase.table("atm_filings").select("accession_number").execute()
        return {r["accession_number"] for r in (res.data or []) if r.get("accession_number")}
    except Exception:
        return set()


def scan_atm_filings() -> dict:
    """Scan all tracked public treasury issuers for new ATM-related filings.

    Returns a stats dict: {'issuers_scanned', 'filings_found', 'new_detections',
    'takedowns', 'active', 'shelves', 'errors'}.
    """
    if not supabase:
        logger.warning("atm_filing_detector: supabase unconfigured — skipping")
        return {"issuers_scanned": 0, "filings_found": 0, "new_detections": 0, "errors": 0}

    issuers = _fetch_issuers()
    if not issuers:
        logger.info("atm_filing_detector: no eligible issuers")
        return {"issuers_scanned": 0, "filings_found": 0, "new_detections": 0, "errors": 0}

    processed = _get_processed_accessions()

    issuers_scanned = 0
    filings_found = 0
    new_detections = 0
    takedowns = 0
    active = 0
    shelves = 0
    errors = 0

    for issuer in issuers:
        ticker = (issuer.get("ticker") or "").upper()
        company = issuer.get("company") or ticker
        cik = issuer.get("cik") or ""
        issuers_scanned += 1

        try:
            filings = _fetch_recent_filings(cik)
        except Exception as e:
            errors += 1
            logger.debug(f"ATM: filings fetch failed for {ticker}: {e}")
            continue

        filings_found += len(filings)

        for f in filings:
            acc = f.get("accession_number", "")
            if not acc or acc in processed:
                continue

            time.sleep(EDGAR_THROTTLE_SECONDS)
            try:
                text = _fetch_filing_text(cik, acc, f.get("primary_document", ""))
            except Exception as e:
                errors += 1
                logger.debug(f"ATM: text fetch failed for {ticker}/{acc}: {e}")
                continue

            has_atm = _has_atm_keyword(text)
            form_type = f.get("form_type", "")

            # S-3 / S-3/A without ATM keywords = generic shelf; skip persistence
            # to avoid noise (every IPO-stage company files these). 424B* always
            # persisted because the takedown itself is the signal.
            if form_type in ("S-3", "S-3/A") and not has_atm:
                continue

            status = _classify_status(form_type, has_atm)
            detection = AtmDetection(
                ticker=ticker,
                company=company,
                cik=cik,
                accession_number=acc,
                form_type=form_type,
                filing_date=f.get("filing_date", ""),
                filing_url=_build_filing_url(cik, acc),
                status=status,
                max_capacity_usd=_parse_capacity_usd(text),
                sales_agent=_find_sales_agent(text),
                excerpt=_extract_excerpt(text),
                components={
                    "source": "sec_edgar_submissions",
                    "primary_document": f.get("primary_document", ""),
                },
            )

            if _persist_detection(detection):
                new_detections += 1
                processed.add(acc)
                if status == "takedown":
                    takedowns += 1
                elif status == "active":
                    active += 1
                else:
                    shelves += 1
                _send_telegram_alert(detection)
                logger.info(
                    f"ATM detected: {ticker} {form_type} ({status}) "
                    f"cap={'$' + format(detection.max_capacity_usd or 0, ',.0f') if detection.max_capacity_usd else 'n/a'} "
                    f"agent={detection.sales_agent or 'n/a'}"
                )

    if issuers_scanned > 0:
        freshness.record_success(
            "atm_filing_detector",
            detail=f"{issuers_scanned} issuers, {new_detections} new ({takedowns}t/{active}a/{shelves}s)",
        )

    logger.info(
        f"ATM scanner: {issuers_scanned} issuers scanned, {filings_found} filings found, "
        f"{new_detections} new ({takedowns} takedowns, {active} active, {shelves} shelves), {errors} errors"
    )
    return {
        "issuers_scanned": issuers_scanned,
        "filings_found": filings_found,
        "new_detections": new_detections,
        "takedowns": takedowns,
        "active": active,
        "shelves": shelves,
        "errors": errors,
    }


# ─── Manual smoke test ────────────────────────────────────────────────────


if __name__ == "__main__":
    print("ATM filing detector — manual run (last 90 days)...")
    stats = scan_atm_filings()
    print(stats)
