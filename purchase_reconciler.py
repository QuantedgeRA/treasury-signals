"""
purchase_reconciler.py — v2.0
------------------------------
Central reconciliation engine for all purchase AND sale detections.

Every scanner (EDGAR, Global Filing, News, Snapshot) calls
reconcile_and_save() or reconcile_sale() instead of writing directly
to confirmed_purchases or confirmed_sales.

This module ensures:
1. No duplicate purchases/sales (same company, ±3 days, ±20% BTC)
2. Source hierarchy (EDGAR > Global Filing > News > Snapshot)
3. ALL snapshot detections → pending (never auto-confirmed)
4. Confirmation bridge (pending → confirmed when corroborated)
5. Expiry of unconfirmed pending entries after 7 days
6. Target/goal sanity gate — rejects round "target" numbers without filing proof
7. Sale tracking with same verification pipeline as purchases

Source Hierarchy:
    Rank 1 — SEC EDGAR 8-K filing (exact numbers, legal documents)
    Rank 2 — Global regulatory filing (SEDAR, TDnet, DART, RNS, etc.)
    Rank 3 — News article (approximate numbers from headlines)
    Rank 4 — Snapshot comparison (estimated price, scan date, no source document)
"""

import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from supabase import create_client
from logger import get_logger

logger = get_logger(__name__)

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# ============================================
# SOURCE HIERARCHY
# ============================================
SOURCE_RANKS = {
    "edgar": 1,        # SEC EDGAR 8-K filing
    "global_filing": 2, # International regulatory filing
    "news": 3,          # News article / press release
    "snapshot": 4,      # Snapshot comparison (least reliable)
}

# How to determine rank from source strings
def _get_source_rank(source_string):
    """Determine source rank from the source description string."""
    s = source_string.lower()
    if "edgar" in s or "sec" in s or "8-k" in s:
        return SOURCE_RANKS["edgar"]
    elif "sedar" in s or "tdnet" in s or "dart" in s or "rns" in s or "global" in s or "regulatory" in s:
        return SOURCE_RANKS["global_filing"]
    elif "news" in s or "press" in s or "article" in s or "coindesk" in s or "cointelegraph" in s:
        return SOURCE_RANKS["news"]
    else:
        return SOURCE_RANKS["snapshot"]


# ============================================
# TARGET/GOAL SANITY GATE
# ============================================
# Known "target" BTC amounts that companies announce as goals, NOT purchases.
# These get picked up by news/filing parsers and recorded as fake purchases.
SUSPICIOUS_TARGET_AMOUNTS = {100000, 210000, 1000000, 500000, 50000, 21000}


def _is_suspicious_target(btc_amount, filing_url="", source_type=""):
    """
    Reject purchases that look like corporate target announcements rather
    than actual completed transactions.

    A purchase is suspicious if:
    1. The BTC amount is a known round "target" number, AND
    2. There's no direct filing URL to prove the purchase actually happened
    
    EDGAR filings (source_type="edgar") are exempt — if an 8-K says 100,000 BTC
    was purchased, we trust the legal document.
    """
    if source_type == "edgar":
        return False  # SEC filings are legal documents — trust them
    if int(btc_amount) in SUSPICIOUS_TARGET_AMOUNTS and not filing_url:
        return True
    return False


# ============================================
# DUPLICATE DETECTION
# ============================================
# Two purchases are considered the same event if:
#   - Same company (by ticker, normalized)
#   - Within ±3 days of each other
#   - BTC amounts within 20% of each other (or both zero)
DEDUP_DAYS_WINDOW = 3
DEDUP_BTC_TOLERANCE = 0.20  # 20%


def _normalize_ticker_for_dedup(ticker):
    """Normalize ticker for deduplication matching."""
    if not ticker:
        return ""
    t = ticker.upper().strip()
    # Strip common exchange suffixes
    for suffix in [".US", ".L", ".TO", ".AX", ".DE", ".PA", ".SW", ".HK", ".KS", ".SS", ".SZ", ".SA", ".V", ".ST", ".CO", ".MI", ".BR", ".MC", ".OL", ".HE", ".IS"]:
        if t.endswith(suffix):
            t = t[:-len(suffix)]
            break
    return t


def _btc_amounts_match(amount1, amount2):
    """Check if two BTC amounts are within tolerance (same purchase event)."""
    if amount1 == 0 and amount2 == 0:
        return True
    if amount1 == 0 or amount2 == 0:
        return False  # One has amount, other doesn't — can't confirm match
    larger = max(amount1, amount2)
    smaller = min(amount1, amount2)
    difference_pct = (larger - smaller) / larger
    return difference_pct <= DEDUP_BTC_TOLERANCE


def _dates_within_window(date1_str, date2_str):
    """Check if two date strings are within the dedup window."""
    try:
        d1 = datetime.strptime(date1_str[:10], "%Y-%m-%d")
        d2 = datetime.strptime(date2_str[:10], "%Y-%m-%d")
        return abs((d1 - d2).days) <= DEDUP_DAYS_WINDOW
    except (ValueError, TypeError):
        return False


def _normalize_name_for_dedup(name):
    """Normalize company name for deduplication matching."""
    if not name:
        return ""
    n = name.upper().strip()
    for suffix in [' INC', ' INC.', ' CORP', ' CORP.', ' LTD', ' LTD.', ' LLC', ' PLC', ' CO', ' CO.', 
                   ' GROUP', ' HOLDINGS', ' GLOBAL', ' (MICROSTRATEGY)', ',', '.']:
        n = n.replace(suffix, '')
    return n.strip()


def _find_existing_match(ticker, btc_amount, filing_date, company_name=""):
    """
    Search confirmed_purchases for a matching entry.
    Matches by: (1) normalized ticker, or (2) normalized company name.
    Plus: within date window AND BTC amounts within tolerance.
    Returns the matching row if found, None otherwise.
    """
    norm_ticker = _normalize_ticker_for_dedup(ticker)
    norm_name = _normalize_name_for_dedup(company_name)

    try:
        result = supabase.table("confirmed_purchases").select("*").order("filing_date", desc=True).limit(100).execute()
        if not result.data:
            return None

        for row in result.data:
            row_ticker = _normalize_ticker_for_dedup(row.get("ticker", ""))
            row_name = _normalize_name_for_dedup(row.get("company", ""))
            row_date = row.get("filing_date", "")
            row_btc = float(row.get("btc_amount", 0))

            # Same company? Match by ticker OR by name
            ticker_match = norm_ticker and row_ticker and norm_ticker == row_ticker
            name_match = norm_name and row_name and (norm_name == row_name or norm_name in row_name or row_name in norm_name)
            
            if not (ticker_match or name_match):
                continue

            if not _dates_within_window(filing_date, row_date):
                continue

            if not _btc_amounts_match(btc_amount, row_btc):
                continue

            return row

    except Exception as e:
        logger.error(f"Reconciler: error searching confirmed_purchases: {e}")

    return None


def _find_pending_match(ticker, btc_amount, detected_date):
    """
    Search pending_purchases for a matching entry.
    Returns the matching row if found, None otherwise.
    """
    norm_ticker = _normalize_ticker_for_dedup(ticker)

    try:
        result = supabase.table("pending_purchases").select("*").eq("status", "pending").order("detected_date", desc=True).limit(100).execute()
        if not result.data:
            return None

        for row in result.data:
            row_ticker = _normalize_ticker_for_dedup(row.get("ticker", ""))
            row_date = row.get("detected_date", "")
            row_btc = float(row.get("btc_amount", 0))

            if row_ticker != norm_ticker:
                continue
            if not _dates_within_window(detected_date, row_date):
                continue
            if not _btc_amounts_match(btc_amount, row_btc):
                continue

            return row

    except Exception as e:
        logger.error(f"Reconciler: error searching pending_purchases: {e}")

    return None


# ============================================
# MAIN RECONCILIATION FUNCTION
# ============================================
def reconcile_and_save(purchase, source_type="snapshot", is_new_entrant=False):
    """
    Central entry point for all purchase detections.
    
    Every scanner calls this instead of writing directly to confirmed_purchases.
    
    Args:
        purchase: dict with keys: company, ticker, btc_amount, usd_amount,
                  price_per_btc, filing_date, source, notes, filing_url
        source_type: "edgar", "global_filing", "news", or "snapshot"
        is_new_entrant: True if this is a new entity detected by snapshot comparison
    
    Returns:
        dict with: action ("confirmed", "upgraded", "duplicate_skipped", "pending", "pending_confirmed"),
                   purchase_id, details
    """
    company = purchase.get("company", "Unknown")
    ticker = purchase.get("ticker", "")
    btc_amount = float(purchase.get("btc_amount", 0))
    usd_amount = float(purchase.get("usd_amount", 0))
    price_per_btc = float(purchase.get("price_per_btc", 0))
    filing_date = purchase.get("filing_date", datetime.now().strftime("%Y-%m-%d"))
    source = purchase.get("source", source_type)
    notes = purchase.get("notes", "")
    filing_url = purchase.get("filing_url", "")
    source_rank = _get_source_rank(source)

    norm_ticker = _normalize_ticker_for_dedup(ticker)
    logger.debug(f"Reconciler: processing {company} ({ticker}), {btc_amount:,.0f} BTC, source: {source_type} (rank {source_rank})")

    # ─── STEP 0: Target/goal sanity gate ───
    if _is_suspicious_target(btc_amount, filing_url, source_type):
        logger.warning(f"Reconciler: 🚫 REJECTED — {company} ({ticker}): {btc_amount:,.0f} BTC looks like a target/goal, not a real purchase (no filing URL)")
        return {"action": "rejected_target", "purchase_id": None, "details": f"{btc_amount:,.0f} BTC is a known target amount with no filing proof"}

    # ─── STEP 1: ALL snapshot detections → pending (never auto-confirm) ───
    # Snapshot comparisons (BitcoinTreasuries.net deltas) are the least reliable
    # source. Data corrections, rounding changes, and delayed reporting all
    # produce false positives. Both new entrants AND existing entity increases
    # must be corroborated by EDGAR, news, or global regulatory filings before
    # they can be marked as confirmed purchases.
    if source_type == "snapshot":
        pending_id = f"pending_{norm_ticker}_{filing_date}"

        # Check if already pending
        existing_pending = _find_pending_match(ticker, btc_amount, filing_date)
        if existing_pending:
            logger.debug(f"Reconciler: {company} already pending — skipping")
            return {"action": "duplicate_skipped", "purchase_id": existing_pending.get("pending_id"), "details": "Already in pending"}

        # Check if already confirmed (maybe another scanner already caught it)
        existing_confirmed = _find_existing_match(ticker, btc_amount, filing_date, company)
        if existing_confirmed:
            logger.debug(f"Reconciler: {company} already confirmed — skipping pending")
            return {"action": "duplicate_skipped", "purchase_id": existing_confirmed.get("purchase_id"), "details": "Already confirmed"}

        # Save to pending — awaits corroboration from a higher-ranked source
        entrant_label = "New entrant" if is_new_entrant else "Existing entity delta"
        try:
            supabase.table("pending_purchases").upsert({
                "pending_id": pending_id,
                "company": company,
                "ticker": ticker,
                "btc_amount": btc_amount,
                "usd_amount": usd_amount,
                "price_per_btc": price_per_btc,
                "detected_date": filing_date,
                "source": source,
                "source_rank": source_rank,
                "notes": notes,
                "status": "pending",
                "is_new_entrant": is_new_entrant,
            }, on_conflict="pending_id").execute()
            logger.info(f"Reconciler: ⏳ PENDING — {company} ({ticker}): {btc_amount:,.0f} BTC ({entrant_label}, awaiting confirmation)")
            return {"action": "pending", "purchase_id": pending_id, "details": f"{entrant_label}, awaiting confirmation from EDGAR/News/Global"}
        except Exception as e:
            logger.error(f"Reconciler: failed to save pending: {e}")
            return {"action": "error", "purchase_id": None, "details": str(e)}

    # ─── STEP 2: Check for matching pending entry → confirm it ───
    pending_match = _find_pending_match(ticker, btc_amount, filing_date)
    if pending_match and source_type != "snapshot":
        # A non-snapshot scanner found a match for a pending entry
        # This confirms the pending entry is a real purchase
        pending_id = pending_match.get("pending_id")

        # Use the better data (current detection if higher rank)
        best_btc = btc_amount if source_rank < pending_match.get("source_rank", 4) else float(pending_match.get("btc_amount", 0))
        best_usd = usd_amount if source_rank < pending_match.get("source_rank", 4) else float(pending_match.get("usd_amount", 0))
        best_price = price_per_btc if source_rank < pending_match.get("source_rank", 4) else float(pending_match.get("price_per_btc", 0))
        best_date = filing_date if source_rank < pending_match.get("source_rank", 4) else pending_match.get("detected_date", filing_date)
        best_url = filing_url if filing_url else ""

        # Write to confirmed_purchases
        purchase_id = f"confirmed_{norm_ticker}_{best_date}"
        try:
            supabase.table("confirmed_purchases").upsert({
                "purchase_id": purchase_id,
                "company": company,
                "ticker": ticker,
                "btc_amount": best_btc,
                "usd_amount": best_usd,
                "price_per_btc": best_price,
                "filing_date": best_date,
                "filing_url": best_url,
                "was_predicted": False,
                "source": f"Confirmed: {source_type} (rank {source_rank})",
            }, on_conflict="purchase_id").execute()

            # Mark pending as confirmed
            supabase.table("pending_purchases").update({
                "status": "confirmed",
                "confirmed_at": datetime.now().isoformat(),
                "confirmed_by": source_type,
            }).eq("pending_id", pending_id).execute()

            logger.info(f"Reconciler: ✅ CONFIRMED — {company} ({ticker}): {best_btc:,.0f} BTC (was pending, confirmed by {source_type})")
            return {"action": "pending_confirmed", "purchase_id": purchase_id, "details": f"Pending entry confirmed by {source_type}"}
        except Exception as e:
            logger.error(f"Reconciler: failed to confirm pending: {e}")
            return {"action": "error", "purchase_id": None, "details": str(e)}

    # ─── STEP 3: Check for existing confirmed entry → upgrade or skip ───
    existing = _find_existing_match(ticker, btc_amount, filing_date, company)
    if existing:
        existing_id = existing.get("purchase_id", "")
        existing_source = existing.get("source", existing.get("filing_url", ""))
        existing_rank = _get_source_rank(existing_source)

        if source_rank < existing_rank:
            # New detection is from a better source — upgrade the existing entry
            purchase_id = f"confirmed_{norm_ticker}_{filing_date}"
            try:
                # Delete old entry and insert upgraded one
                if existing_id:
                    supabase.table("confirmed_purchases").delete().eq("purchase_id", existing_id).execute()

                supabase.table("confirmed_purchases").upsert({
                    "purchase_id": purchase_id,
                    "company": company,
                    "ticker": ticker,
                    "btc_amount": btc_amount,
                    "usd_amount": usd_amount,
                    "price_per_btc": price_per_btc,
                    "filing_date": filing_date,
                    "filing_url": filing_url,
                    "was_predicted": existing.get("was_predicted", False),
                    "source": f"Upgraded: {source_type} (rank {source_rank}, was rank {existing_rank})",
                }, on_conflict="purchase_id").execute()

                logger.info(f"Reconciler: ⬆️ UPGRADED — {company}: {source_type} (rank {source_rank}) replaced rank {existing_rank}")
                return {"action": "upgraded", "purchase_id": purchase_id, "details": f"Upgraded from rank {existing_rank} to rank {source_rank}"}
            except Exception as e:
                logger.error(f"Reconciler: upgrade failed: {e}")
                return {"action": "error", "purchase_id": None, "details": str(e)}
        else:
            # Existing entry is from equal or better source — skip
            logger.debug(f"Reconciler: duplicate skipped — {company} already confirmed (rank {existing_rank} ≤ {source_rank})")
            return {"action": "duplicate_skipped", "purchase_id": existing_id, "details": f"Already confirmed with rank {existing_rank}"}

    # ─── STEP 4: No match found anywhere → new confirmed purchase ───
    # Only non-snapshot sources auto-confirm. Snapshot new entrants were handled in Step 1.
    purchase_id = f"confirmed_{norm_ticker}_{filing_date}"
    try:
        supabase.table("confirmed_purchases").upsert({
            "purchase_id": purchase_id,
            "company": company,
            "ticker": ticker,
            "btc_amount": btc_amount,
            "usd_amount": usd_amount,
            "price_per_btc": price_per_btc,
            "filing_date": filing_date,
            "filing_url": filing_url,
            "was_predicted": False,
            "source": f"{source_type} (rank {source_rank})",
        }, on_conflict="purchase_id").execute()

        logger.info(f"Reconciler: ✅ CONFIRMED — {company} ({ticker}): {btc_amount:,.0f} BTC via {source_type}")
        return {"action": "confirmed", "purchase_id": purchase_id, "details": f"New purchase confirmed via {source_type}"}
    except Exception as e:
        logger.error(f"Reconciler: failed to save confirmed: {e}")
        return {"action": "error", "purchase_id": None, "details": str(e)}


# ============================================
# CONFIRMATION BRIDGE — promote pending entries
# ============================================
def promote_pending_purchases():
    """
    Check all pending purchases against recent EDGAR/News/Global detections.
    If a match is found, promote the pending entry to confirmed.
    
    Call this once per scan cycle.
    """
    try:
        pending = supabase.table("pending_purchases").select("*").eq("status", "pending").execute()
        if not pending.data:
            return 0

        promoted = 0
        for entry in pending.data:
            ticker = entry.get("ticker", "")
            btc_amount = float(entry.get("btc_amount", 0))
            detected_date = entry.get("detected_date", "")

            # Check if any confirmed purchase now matches this pending entry
            match = _find_existing_match(ticker, btc_amount, detected_date, entry.get('company', ''))
            if match:
                # Already confirmed by another scanner — mark pending as confirmed
                try:
                    supabase.table("pending_purchases").update({
                        "status": "confirmed",
                        "confirmed_at": datetime.now().isoformat(),
                        "confirmed_by": "auto_match",
                    }).eq("pending_id", entry["pending_id"]).execute()
                    promoted += 1
                    logger.info(f"Reconciler: ⏳→✅ Promoted pending: {entry['company']} ({ticker})")
                except Exception as e:
                    logger.error(f"Reconciler: promote failed for {entry['company']}: {e}")

        if promoted:
            logger.info(f"Reconciler: {promoted} pending purchase(s) promoted to confirmed")
        return promoted

    except Exception as e:
        logger.error(f"Reconciler: promote_pending error: {e}")
        return 0


# ============================================
# EXPIRY — discard unconfirmed pending entries
# ============================================
PENDING_EXPIRY_DAYS = 7


def expire_stale_pending():
    """
    Discard pending purchases that have not been confirmed within 7 days.
    These are almost certainly existing holders that appeared due to
    data source changes, not real purchases.
    
    Call this once per day.
    """
    try:
        cutoff = (datetime.now() - timedelta(days=PENDING_EXPIRY_DAYS)).strftime("%Y-%m-%d")

        pending = supabase.table("pending_purchases").select("*").eq("status", "pending").lt("detected_date", cutoff).execute()

        if not pending.data:
            return 0

        expired = 0
        for entry in pending.data:
            try:
                supabase.table("pending_purchases").update({
                    "status": "discarded",
                    "notes": entry.get("notes", "") + f" | Expired after {PENDING_EXPIRY_DAYS} days without confirmation",
                }).eq("pending_id", entry["pending_id"]).execute()
                expired += 1
                logger.info(f"Reconciler: 🗑️ Expired pending: {entry['company']} ({entry['ticker']}): {float(entry.get('btc_amount', 0)):,.0f} BTC — no confirmation after {PENDING_EXPIRY_DAYS} days")
            except Exception as e:
                logger.error(f"Reconciler: expire failed for {entry['company']}: {e}")

        if expired:
            logger.info(f"Reconciler: {expired} pending purchase(s) expired and discarded")
        return expired

    except Exception as e:
        logger.error(f"Reconciler: expire_stale error: {e}")
        return 0


# ============================================
# SALE RECONCILIATION (mirrors purchase pipeline)
# ============================================

def _find_existing_sale_match(ticker, btc_amount, filing_date, company_name=""):
    """Search confirmed_sales for a matching entry."""
    norm_ticker = _normalize_ticker_for_dedup(ticker)
    norm_name = _normalize_name_for_dedup(company_name)
    try:
        result = supabase.table("confirmed_sales").select("*").order("filing_date", desc=True).limit(100).execute()
        if not result.data:
            return None
        for row in result.data:
            row_ticker = _normalize_ticker_for_dedup(row.get("ticker", ""))
            row_name = _normalize_name_for_dedup(row.get("company", ""))
            row_date = row.get("filing_date", "")
            row_btc = float(row.get("btc_amount", 0))
            ticker_match = norm_ticker and row_ticker and norm_ticker == row_ticker
            name_match = norm_name and row_name and (norm_name == row_name or norm_name in row_name or row_name in norm_name)
            if not (ticker_match or name_match):
                continue
            if not _dates_within_window(filing_date, row_date):
                continue
            if not _btc_amounts_match(btc_amount, row_btc):
                continue
            return row
    except Exception as e:
        logger.error(f"Reconciler: error searching confirmed_sales: {e}")
    return None


def _find_pending_sale_match(ticker, btc_amount, detected_date):
    """Search pending_purchases for a matching sale entry."""
    norm_ticker = _normalize_ticker_for_dedup(ticker)
    try:
        result = supabase.table("pending_purchases").select("*").eq("status", "pending").eq("transaction_type", "sale").order("detected_date", desc=True).limit(100).execute()
        if not result.data:
            return None
        for row in result.data:
            row_ticker = _normalize_ticker_for_dedup(row.get("ticker", ""))
            row_date = row.get("detected_date", "")
            row_btc = float(row.get("btc_amount", 0))
            if row_ticker != norm_ticker:
                continue
            if not _dates_within_window(detected_date, row_date):
                continue
            if not _btc_amounts_match(btc_amount, row_btc):
                continue
            return row
    except Exception as e:
        logger.error(f"Reconciler: error searching pending sales: {e}")
    return None


def reconcile_sale(sale, source_type="snapshot"):
    """
    Central entry point for all sale detections.
    Mirrors reconcile_and_save() but writes to confirmed_sales.

    Args:
        sale: dict with keys: company, ticker, btc_amount, usd_amount,
              price_per_btc, filing_date, source, notes, filing_url
        source_type: "edgar", "global_filing", "news", or "snapshot"

    Returns:
        dict with: action, sale_id, details
    """
    company = sale.get("company", "Unknown")
    ticker = sale.get("ticker", "")
    btc_amount = float(sale.get("btc_amount", 0))
    usd_amount = float(sale.get("usd_amount", 0))
    price_per_btc = float(sale.get("price_per_btc", 0))
    filing_date = sale.get("filing_date", datetime.now().strftime("%Y-%m-%d"))
    source = sale.get("source", source_type)
    notes = sale.get("notes", "")
    filing_url = sale.get("filing_url", "")
    source_rank = _get_source_rank(source)

    norm_ticker = _normalize_ticker_for_dedup(ticker)
    logger.debug(f"Reconciler (sale): processing {company} ({ticker}), {btc_amount:,.0f} BTC sold, source: {source_type} (rank {source_rank})")

    # ─── ALL snapshot sale detections → pending ───
    if source_type == "snapshot":
        pending_id = f"pending_sale_{norm_ticker}_{filing_date}"

        existing_pending = _find_pending_sale_match(ticker, btc_amount, filing_date)
        if existing_pending:
            return {"action": "duplicate_skipped", "sale_id": existing_pending.get("pending_id"), "details": "Already in pending"}

        existing_confirmed = _find_existing_sale_match(ticker, btc_amount, filing_date, company)
        if existing_confirmed:
            return {"action": "duplicate_skipped", "sale_id": existing_confirmed.get("sale_id"), "details": "Already confirmed"}

        try:
            supabase.table("pending_purchases").upsert({
                "pending_id": pending_id,
                "company": company,
                "ticker": ticker,
                "btc_amount": btc_amount,
                "usd_amount": usd_amount,
                "price_per_btc": price_per_btc,
                "detected_date": filing_date,
                "source": source,
                "source_rank": source_rank,
                "notes": notes,
                "status": "pending",
                "transaction_type": "sale",
            }, on_conflict="pending_id").execute()
            logger.info(f"Reconciler: ⏳ PENDING SALE — {company} ({ticker}): {btc_amount:,.0f} BTC (awaiting confirmation)")
            return {"action": "pending", "sale_id": pending_id, "details": "Sale awaiting confirmation"}
        except Exception as e:
            logger.error(f"Reconciler: failed to save pending sale: {e}")
            return {"action": "error", "sale_id": None, "details": str(e)}

    # ─── Check for matching pending sale → confirm it ───
    pending_match = _find_pending_sale_match(ticker, btc_amount, filing_date)
    if pending_match:
        pending_id = pending_match.get("pending_id")
        best_btc = btc_amount if source_rank < pending_match.get("source_rank", 4) else float(pending_match.get("btc_amount", 0))
        best_usd = usd_amount if source_rank < pending_match.get("source_rank", 4) else float(pending_match.get("usd_amount", 0))
        best_date = filing_date if source_rank < pending_match.get("source_rank", 4) else pending_match.get("detected_date", filing_date)
        best_url = filing_url if filing_url else ""

        sale_id = f"sale_{norm_ticker}_{best_date}"
        try:
            supabase.table("confirmed_sales").upsert({
                "sale_id": sale_id,
                "company": company,
                "ticker": ticker,
                "btc_amount": best_btc,
                "usd_amount": best_usd,
                "price_per_btc": price_per_btc,
                "filing_date": best_date,
                "filing_url": best_url,
                "source": f"Confirmed: {source_type} (rank {source_rank})",
            }, on_conflict="sale_id").execute()
            supabase.table("pending_purchases").update({
                "status": "confirmed",
                "confirmed_at": datetime.now().isoformat(),
                "confirmed_by": source_type,
            }).eq("pending_id", pending_id).execute()
            logger.info(f"Reconciler: ✅ CONFIRMED SALE — {company} ({ticker}): {best_btc:,.0f} BTC (was pending, confirmed by {source_type})")
            return {"action": "confirmed", "sale_id": sale_id, "details": f"Sale confirmed by {source_type}"}
        except Exception as e:
            logger.error(f"Reconciler: failed to confirm pending sale: {e}")
            return {"action": "error", "sale_id": None, "details": str(e)}

    # ─── Check for existing confirmed sale → upgrade or skip ───
    existing = _find_existing_sale_match(ticker, btc_amount, filing_date, company)
    if existing:
        existing_rank = _get_source_rank(existing.get("source", ""))
        if source_rank < existing_rank:
            sale_id = f"sale_{norm_ticker}_{filing_date}"
            try:
                old_id = existing.get("sale_id", "")
                if old_id:
                    supabase.table("confirmed_sales").delete().eq("sale_id", old_id).execute()
                supabase.table("confirmed_sales").upsert({
                    "sale_id": sale_id, "company": company, "ticker": ticker,
                    "btc_amount": btc_amount, "usd_amount": usd_amount,
                    "price_per_btc": price_per_btc, "filing_date": filing_date,
                    "filing_url": filing_url,
                    "source": f"Upgraded: {source_type} (rank {source_rank})",
                }, on_conflict="sale_id").execute()
                logger.info(f"Reconciler: ⬆️ UPGRADED SALE — {company}: {source_type} replaced rank {existing_rank}")
                return {"action": "upgraded", "sale_id": sale_id, "details": f"Upgraded from rank {existing_rank}"}
            except Exception as e:
                return {"action": "error", "sale_id": None, "details": str(e)}
        else:
            return {"action": "duplicate_skipped", "sale_id": existing.get("sale_id"), "details": f"Already confirmed with rank {existing_rank}"}

    # ─── New confirmed sale (non-snapshot sources) ───
    sale_id = f"sale_{norm_ticker}_{filing_date}"
    try:
        supabase.table("confirmed_sales").upsert({
            "sale_id": sale_id, "company": company, "ticker": ticker,
            "btc_amount": btc_amount, "usd_amount": usd_amount,
            "price_per_btc": price_per_btc, "filing_date": filing_date,
            "filing_url": filing_url,
            "source": f"{source_type} (rank {source_rank})",
        }, on_conflict="sale_id").execute()
        logger.info(f"Reconciler: 🔴 CONFIRMED SALE — {company} ({ticker}): {btc_amount:,.0f} BTC via {source_type}")
        return {"action": "confirmed", "sale_id": sale_id, "details": f"Sale confirmed via {source_type}"}
    except Exception as e:
        logger.error(f"Reconciler: failed to save confirmed sale: {e}")
        return {"action": "error", "sale_id": None, "details": str(e)}


def promote_pending_sales():
    """Check pending sales against confirmed_sales — promote if matched."""
    try:
        pending = supabase.table("pending_purchases").select("*").eq("status", "pending").eq("transaction_type", "sale").execute()
        if not pending.data:
            return 0
        promoted = 0
        for entry in pending.data:
            match = _find_existing_sale_match(entry.get("ticker", ""), float(entry.get("btc_amount", 0)), entry.get("detected_date", ""), entry.get("company", ""))
            if match:
                try:
                    supabase.table("pending_purchases").update({
                        "status": "confirmed", "confirmed_at": datetime.now().isoformat(), "confirmed_by": "auto_match",
                    }).eq("pending_id", entry["pending_id"]).execute()
                    promoted += 1
                    logger.info(f"Reconciler: ⏳→✅ Promoted pending sale: {entry['company']} ({entry['ticker']})")
                except Exception as e:
                    logger.error(f"Reconciler: promote sale failed: {e}")
        if promoted:
            logger.info(f"Reconciler: {promoted} pending sale(s) promoted to confirmed")
        return promoted
    except Exception as e:
        logger.error(f"Reconciler: promote_pending_sales error: {e}")
        return 0


# ============================================
# STATUS REPORT
# ============================================
def get_reconciler_stats():
    """Get current reconciler statistics for logging/dashboard."""
    try:
        confirmed = supabase.table("confirmed_purchases").select("purchase_id", count="exact").execute()
        pending_buys = supabase.table("pending_purchases").select("pending_id", count="exact").eq("status", "pending").neq("transaction_type", "sale").execute()
        pending_sales = supabase.table("pending_purchases").select("pending_id", count="exact").eq("status", "pending").eq("transaction_type", "sale").execute()
        discarded = supabase.table("pending_purchases").select("pending_id", count="exact").eq("status", "discarded").execute()
        promoted = supabase.table("pending_purchases").select("pending_id", count="exact").eq("status", "confirmed").execute()
        confirmed_sales = supabase.table("confirmed_sales").select("sale_id", count="exact").execute()

        return {
            "confirmed_total": confirmed.count if confirmed.count else 0,
            "pending_buys": pending_buys.count if pending_buys.count else 0,
            "pending_sales": pending_sales.count if pending_sales.count else 0,
            "discarded_count": discarded.count if discarded.count else 0,
            "promoted_count": promoted.count if promoted.count else 0,
            "confirmed_sales": confirmed_sales.count if confirmed_sales.count else 0,
        }
    except Exception as e:
        logger.error(f"Reconciler stats error: {e}")
        return {"confirmed_total": 0, "pending_buys": 0, "pending_sales": 0, "discarded_count": 0, "promoted_count": 0, "confirmed_sales": 0}


# ============================================
# QUICK TEST
# ============================================
if __name__ == "__main__":
    logger.info("Purchase Reconciler v2.0 — self-test")
    logger.info("=" * 60)

    stats = get_reconciler_stats()
    logger.info(f"Confirmed purchases: {stats['confirmed_total']}")
    logger.info(f"Confirmed sales: {stats['confirmed_sales']}")
    logger.info(f"Pending buys: {stats['pending_buys']}")
    logger.info(f"Pending sales: {stats['pending_sales']}")
    logger.info(f"Previously promoted: {stats['promoted_count']}")
    logger.info(f"Previously discarded: {stats['discarded_count']}")

    promoted = promote_pending_purchases()
    logger.info(f"Purchase promotion check: {promoted} promoted")

    promoted_sales = promote_pending_sales()
    logger.info(f"Sale promotion check: {promoted_sales} promoted")

    expired = expire_stale_pending()
    logger.info(f"Expiry check: {expired} expired")

    logger.info("Reconciler self-test complete")
