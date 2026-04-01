"""
ticker_validator.py — Authoritative Ticker Validation & Auto-Correction v2
============================================================================
Validates and corrects tickers for ALL public companies in treasury_companies.

Two authoritative sources:
  1. SEC company_tickers.json — definitive for US companies (free, no auth, daily)
  2. Yahoo Finance — validates any global ticker (US + international)

SAFETY RULES:
  - NEVER replace a common stock ticker with a warrant (-W, -WT, -WW, -PD, -R)
  - Strip exchange suffixes (.US, .V, .T, .HK, etc.) BEFORE validating
  - Fuzzy name matching threshold: 0.92 (very strict to avoid wrong matches)
  - Skip garbled/emoji entries entirely
  - Log all changes for manual review

Usage:
    from ticker_validator import validate_all_tickers
    validate_all_tickers()  # Call once per day
"""

import os
import re
import json
import time
import requests
from datetime import datetime
from difflib import SequenceMatcher
from dotenv import load_dotenv
from supabase import create_client
from logger import get_logger

logger = get_logger(__name__)
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

HEADERS = {
    'User-Agent': 'TreasurySignalIntelligence admin@quantedgeriskadvisory.com',
    'Accept': 'application/json',
}

# Exchange suffixes to strip (aggregators like BitcoinTreasuries.net append these)
EXCHANGE_SUFFIXES = [
    '.US', '.V', '.CN', '.NE', '.T', '.HK', '.L', '.MI', '.SA',
    '.IS', '.DE', '.PA', '.AS', '.SW', '.AX', '.SI', '.KS', '.TW',
    '.TO', '.ST', '.OL', '.HE', '.CO', '.MC', '.LS', '.WA',
]

# Warrant/preferred/rights patterns — NEVER use these as corrections
WARRANT_PATTERNS = re.compile(
    r'.+(-WT|-WS|-W|WW|W$|-PD|-PA|-PB|-PC|-R$|-RW|-RI|/CL)$',
    re.IGNORECASE
)

# Cache
_sec_data = None
_sec_name_to_tickers = None


def _strip_suffix(ticker):
    """Strip exchange suffix. MSTR.US → MSTR. Keeps non-exchange dots like 3350.T."""
    if not ticker:
        return ticker
    upper = ticker.upper().strip()
    for suffix in EXCHANGE_SUFFIXES:
        if upper.endswith(suffix):
            return upper[:-len(suffix)]
    return upper


def _is_garbled(text):
    """Check if text is garbled unicode, emoji flags, or BTC amounts stored as tickers."""
    if not text:
        return True
    if 'Â¿' in text or 'ð' in text or '¿' in text:
        return True
    if re.match(r'^[\d,\.\s]+$', text.strip()):
        return True
    if not re.search(r'[A-Za-z]', text):
        return True
    return False


def _is_warrant(ticker):
    """Check if ticker is a warrant, preferred share, or rights — NOT common stock."""
    if not ticker:
        return False
    return bool(WARRANT_PATTERNS.match(ticker.upper()))


def _load_sec_tickers():
    """Load SEC's official company_tickers.json — source of truth for US tickers."""
    global _sec_data, _sec_name_to_tickers

    if _sec_data is not None:
        return _sec_data

    try:
        resp = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers=HEADERS, timeout=30
        )
        if resp.ok:
            raw = resp.json()
            _sec_data = {}
            _sec_name_to_tickers = {}

            for key, entry in raw.items():
                ticker = (entry.get("ticker", "") or "").upper().strip()
                cik = str(entry.get("cik_str", ""))
                name = (entry.get("title", "") or "").strip()
                if not ticker:
                    continue

                _sec_data[ticker] = {"cik": cik, "name": name, "ticker": ticker}

                # Build name → list of tickers (company can have stock + warrants)
                name_key = _normalize_name(name)
                if name_key and len(name_key) >= 3:
                    if name_key not in _sec_name_to_tickers:
                        _sec_name_to_tickers[name_key] = []
                    _sec_name_to_tickers[name_key].append(ticker)

            logger.info(f"  SEC tickers loaded: {len(_sec_data)} entries")
            return _sec_data
    except Exception as e:
        logger.debug(f"  SEC tickers fetch error: {e}")

    _sec_data = {}
    _sec_name_to_tickers = {}
    return _sec_data


def _normalize_name(name):
    """Normalize company name for matching."""
    if not name:
        return ""
    name = name.upper().strip()
    for suffix in [', INC.', ', INC', ' INC.', ' INC', ', LTD.', ', LTD', ' LTD.',
                   ' LTD', ', LLC', ' LLC', ', LP', ' L.P.', ' LP', ', CORP.', ', CORP',
                   ' CORP.', ' CORP', ' CO.', ' CO', ', PLC', ' PLC',
                   ' HOLDINGS', ' HOLDING', ' GROUP', ' TECHNOLOGIES',
                   ' TECHNOLOGY', ' DIGITAL', ' ASSETS', ' CAPITAL',
                   ' INTERNATIONAL', ' SOLUTIONS', ' PLATFORMS', ' MINING']:
        name = name.replace(suffix, '')
    name = re.sub(r'\([^)]*\)', '', name)
    name = re.sub(r'[^A-Z0-9 ]', '', name).strip()
    return name


def _pick_common_stock(tickers):
    """From a list of tickers for one company, pick the common stock (not warrants)."""
    common = [t for t in tickers if not _is_warrant(t)]
    if common:
        return min(common, key=len)  # Shortest ticker = most likely common stock
    return None


def _find_sec_ticker_by_name(company_name):
    """Look up correct COMMON STOCK ticker from SEC by company name. Very strict matching."""
    global _sec_name_to_tickers

    if not _sec_name_to_tickers:
        _load_sec_tickers()
    if not _sec_name_to_tickers:
        return None

    target = _normalize_name(company_name)
    if not target or len(target) < 4:
        return None

    # Exact name match first
    if target in _sec_name_to_tickers:
        return _pick_common_stock(_sec_name_to_tickers[target])

    # Fuzzy match — VERY strict to avoid Strategy → STRD type mistakes
    best_name = None
    best_score = 0
    for sec_name in _sec_name_to_tickers:
        # Quick length filter — names must be similar length
        if abs(len(target) - len(sec_name)) > max(5, len(target) * 0.3):
            continue
        score = SequenceMatcher(None, target, sec_name).ratio()
        if score > best_score and score >= 0.92:
            best_score = score
            best_name = sec_name

    if best_name:
        result = _pick_common_stock(_sec_name_to_tickers[best_name])
        if result:
            logger.debug(f"    Fuzzy: '{target}' → '{best_name}' ({best_score:.2f}) → {result}")
            return result

    return None


def _validate_ticker_yahoo(ticker):
    """Validate a ticker on Yahoo Finance."""
    if not ticker or _is_garbled(ticker):
        return None
    try:
        resp = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
            params={"range": "1d", "interval": "1d"},
            headers={**HEADERS, 'User-Agent': 'Mozilla/5.0'},
            timeout=10,
        )
        if resp.ok:
            data = resp.json()
            meta = data.get("chart", {}).get("result", [{}])[0].get("meta", {})
            if meta.get("symbol"):
                return {"valid": True, "symbol": meta["symbol"], "name": meta.get("shortName", "")}
        return {"valid": False}
    except Exception:
        return None


def _update_ticker(entity_id, old_ticker, new_ticker, company):
    """Update ticker in both treasury_companies and confirmed_purchases."""
    try:
        supabase.table("treasury_companies").update(
            {"ticker": new_ticker}
        ).eq("id", entity_id).execute()

        if old_ticker:
            supabase.table("confirmed_purchases").update(
                {"ticker": new_ticker}
            ).eq("ticker", old_ticker).execute()
        return True
    except Exception as e:
        logger.debug(f"  Update error for {company}: {e}")
        return False


def validate_all_tickers():
    """
    Validate and auto-correct tickers.

    Flow per company:
    1. Skip garbled entries, non-public entities
    2. Strip exchange suffix (.US, .V, etc.)
    3. Check if STRIPPED ticker exists in SEC → valid, just clean the suffix
    4. If not in SEC, search by company name → find correct common stock ticker
    5. For international tickers, validate via Yahoo Finance
    6. NEVER replace with warrants or preferred shares
    """
    logger.info("Ticker validator v2: starting...")
    start = time.time()

    sec_data = _load_sec_tickers()

    try:
        result = supabase.table("treasury_companies").select(
            "id, company, ticker, entity_type, country, btc_holdings"
        ).gt("btc_holdings", 0).order("btc_holdings", desc=True).execute()
        companies = result.data or []
    except Exception as e:
        logger.debug(f"  Fetch error: {e}")
        return {"checked": 0, "corrected": 0, "errors": []}

    checked = 0
    corrected = 0
    errors = []

    for c in companies:
        entity_type = (c.get("entity_type") or "").lower()
        raw_ticker = (c.get("ticker") or "").strip()
        company = c.get("company") or ""
        country = (c.get("country") or "").lower()

        # Skip non-public entities and garbled data
        if entity_type in ("government", "defi", "etf"):
            continue
        if _is_garbled(company) or _is_garbled(raw_ticker):
            continue
        if not company:
            continue

        checked += 1
        stripped = _strip_suffix(raw_ticker)
        had_suffix = stripped != raw_ticker.upper().strip()

        # Detect international tickers (contain dot that's NOT an exchange suffix, or non-US country)
        is_intl = ('.' in stripped) or (
            country and 'us' not in country and 'united states' not in country
            and 'america' not in country and country != ''
        )

        # ═══ STEP 1: Check stripped ticker in SEC ═══
        if sec_data and stripped and stripped in sec_data:
            # Ticker is valid in SEC
            if had_suffix:
                # Just clean the suffix: MARA.US → MARA
                if _update_ticker(c["id"], raw_ticker, stripped, company):
                    logger.info(f"  CLEANED: {company} — {raw_ticker} → {stripped}")
                    corrected += 1
            continue

        # ═══ STEP 2: US-style — search SEC by company name ═══
        if not is_intl and sec_data:
            correct = _find_sec_ticker_by_name(company)
            if correct and correct != stripped and not _is_warrant(correct):
                if _update_ticker(c["id"], raw_ticker, correct, company):
                    logger.info(f"  CORRECTED: {company} — {raw_ticker} → {correct} (SEC name match)")
                    corrected += 1
                continue
            elif not stripped:
                # No ticker at all — try to find one
                if correct and not _is_warrant(correct):
                    if _update_ticker(c["id"], raw_ticker, correct, company):
                        logger.info(f"  ADDED: {company} — (none) → {correct} (SEC name match)")
                        corrected += 1
                continue

        # ═══ STEP 3: International — validate via Yahoo ═══
        if stripped:
            yf = _validate_ticker_yahoo(stripped)
            if yf and yf.get("valid"):
                yf_sym = yf.get("symbol", "").upper()
                if had_suffix and yf_sym == stripped:
                    # Just clean suffix
                    if _update_ticker(c["id"], raw_ticker, stripped, company):
                        logger.info(f"  CLEANED: {company} — {raw_ticker} → {stripped} (Yahoo)")
                        corrected += 1
                elif yf_sym and yf_sym != stripped and yf_sym != raw_ticker.upper() and not _is_warrant(yf_sym):
                    # Yahoo says different symbol
                    if _update_ticker(c["id"], raw_ticker, yf_sym, company):
                        logger.info(f"  CORRECTED: {company} — {raw_ticker} → {yf_sym} (Yahoo)")
                        corrected += 1
            elif yf and not yf.get("valid"):
                errors.append(f"{company} ({raw_ticker}): not found anywhere")
            time.sleep(0.3)

    elapsed = time.time() - start
    logger.info(f"Ticker validator v2: {checked} checked, {corrected} corrected, {len(errors)} warnings ({elapsed:.1f}s)")
    for e in errors[:15]:
        logger.debug(f"  ⚠️  {e}")

    return {"checked": checked, "corrected": corrected, "errors": errors}


if __name__ == "__main__":
    logger.info("Ticker validator v2 — manual run...")
    result = validate_all_tickers()
    print(f"\nChecked: {result['checked']}")
    print(f"Corrected: {result['corrected']}")
    if result['errors']:
        print(f"\nWarnings ({len(result['errors'])}):")
        for e in result['errors'][:20]:
            print(f"  ⚠️  {e}")
