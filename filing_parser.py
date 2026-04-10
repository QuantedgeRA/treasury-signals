"""
filing_parser.py — AI-Powered Filing Parser
=============================================
When a new filing is detected by the global scanner, this module:
1. Fetches the full filing text
2. Sends it to Claude API to extract structured BTC data
3. Updates treasury_companies with primary source data
4. Primary source data ALWAYS overrides aggregator data

Uses Claude claude-sonnet-4-20250514 for extraction.

Usage:
    from filing_parser import parse_and_update
    parse_and_update()  # Call after global_filing_scanner
"""

import os
import re
import json
import time
import requests
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client
from logger import get_logger

try:
    from purchase_reconciler import reconcile_and_save, reconcile_sale
    HAS_RECONCILER = True
except ImportError:
    HAS_RECONCILER = False

logger = get_logger(__name__)
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

HEADERS_WEB = {
    'User-Agent': 'TreasurySignalIntelligence admin@quantedgeriskadvisory.com',
    'Accept': 'text/html,application/xhtml+xml',
}

# Data source priority (higher = more authoritative)
SOURCE_PRIORITY = {
    'sec_filing': 100,
    'regulatory_filing': 90,
    'etf_issuer': 85,
    'government_official': 80,
    'defi_onchain': 80,
    'press_release': 60,
    'aggregator': 10,
}

EXTRACTION_PROMPT = """You are a financial data extraction specialist. Extract Bitcoin treasury information from this filing/article.

Return ONLY valid JSON with these fields (use null if not found):
{
  "company_name": "exact legal name of the company",
  "ticker": "stock ticker symbol (e.g. MSTR, MARA) or null",
  "btc_holdings": total BTC currently held (number, not string),
  "btc_purchased": BTC purchased in this transaction (number or null),
  "btc_sold": BTC sold in this transaction (number or null),
  "purchase_price_usd": total USD spent on this purchase (number or null),
  "sale_price_usd": total USD received from this sale (number or null),
  "avg_price_per_btc": average price per BTC for this transaction (number or null),
  "event_type": "purchase" or "sale" or "holding_update" or "new_treasury" or "other",
  "date": "YYYY-MM-DD of the event",
  "entity_type": "public_company" or "private_company" or "government" or "etf" or "defi",
  "confidence": 0.0 to 1.0 how confident you are in the extraction
}

CRITICAL RULES:
- Only extract data for COMPLETED transactions explicitly stated in the text. Do NOT guess or infer.
- DISTINGUISH between TARGETS/GOALS and ACTUAL PURCHASES:
  * "aims to acquire 100,000 BTC" → this is a TARGET, set btc_purchased to null
  * "acquired 4,871 BTC for $330M" → this is an ACTUAL purchase, set btc_purchased to 4871
  * "plans to buy", "targets", "goal of", "seeking to acquire" → these are NOT purchases
  * Only set btc_purchased when the text confirms the transaction HAS BEEN COMPLETED
- btc_holdings is the TOTAL held, not just the new purchase amount.
- If the text only mentions a purchase amount but not total holdings, set btc_holdings to null.
- If the text describes a SALE (sold, divested, liquidated, offloaded), set btc_sold and event_type to "sale".
- If numbers are ambiguous, set confidence lower.
- Return ONLY the JSON object, no other text.

TEXT TO ANALYZE:
"""


def _fetch_filing_text(url):
    """Fetch text content from a filing URL."""
    if not url or url.startswith('https://news.google.com'):
        return ""
    try:
        resp = requests.get(url, headers=HEADERS_WEB, timeout=30)
        if resp.ok:
            # Strip HTML
            text = re.sub(r'<[^>]+>', ' ', resp.text)
            text = re.sub(r'\s+', ' ', text)
            return text[:15000]  # Limit to 15K chars for Claude context
    except:
        pass
    return ""


def _call_claude(text):
    """Call Claude API to extract structured BTC data from filing text."""
    if not ANTHROPIC_API_KEY:
        logger.debug("  Parser: no ANTHROPIC_API_KEY set")
        return None

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                'Content-Type': 'application/json',
                'x-api-key': ANTHROPIC_API_KEY,
                'anthropic-version': '2023-06-01',
            },
            json={
                'model': 'claude-sonnet-4-20250514',
                'max_tokens': 500,
                'messages': [{'role': 'user', 'content': EXTRACTION_PROMPT + text[:12000]}],
            },
            timeout=60,
        )
        if resp.ok:
            data = resp.json()
            content = data.get('content', [{}])[0].get('text', '')
            # Parse JSON from response
            content = content.strip()
            if content.startswith('```'):
                content = re.sub(r'```json?\s*', '', content)
                content = re.sub(r'```\s*$', '', content)
            return json.loads(content)
    except json.JSONDecodeError as e:
        logger.debug(f"  Parser: JSON decode error: {e}")
    except Exception as e:
        logger.debug(f"  Parser: Claude API error: {e}")
    return None


def _should_update(current_source, new_source):
    """Check if new data source should override current data source."""
    current_priority = SOURCE_PRIORITY.get(current_source, 10)
    new_priority = SOURCE_PRIORITY.get(new_source, 10)
    return new_priority >= current_priority


def _determine_data_source(filing_source):
    """Map filing source string to data_source category."""
    source_lower = (filing_source or '').lower()
    if 'sec' in source_lower or 'edgar' in source_lower:
        return 'sec_filing'
    if any(reg in source_lower for reg in ['sedar', 'edinet', 'tdnet', 'dart', 'rns', 'hkex', 'asx', 'amf', 'bafin', 'cvm', 'bse', 'sgx', 'tase', 'oslo', 'kap', 'finansinspektionen']):
        return 'regulatory_filing'
    if 'etf' in source_lower or 'ishares' in source_lower or 'fidelity' in source_lower or 'grayscale' in source_lower:
        return 'etf_issuer'
    if 'gov' in source_lower or 'bitcoin.gob' in source_lower:
        return 'government_official'
    if 'defi' in source_lower or 'llama' in source_lower or 'etherscan' in source_lower:
        return 'defi_onchain'
    if 'news' in source_lower or 'press' in source_lower or 'coindesk' in source_lower or 'cointelegraph' in source_lower:
        return 'press_release'
    return 'press_release'


def _update_entity(extracted, data_source):
    """Update treasury_companies with extracted data if it's higher priority."""
    if not extracted or not extracted.get('company_name'):
        return False

    confidence = extracted.get('confidence', 0)
    if confidence < 0.5:
        logger.debug(f"  Parser: low confidence ({confidence}), skipping {extracted.get('company_name')}")
        return False

    company = extracted['company_name']
    ticker = extracted.get('ticker', '')
    btc_holdings = extracted.get('btc_holdings')
    btc_purchased = extracted.get('btc_purchased')
    entity_type = extracted.get('entity_type', 'public_company')

    btc_sold = extracted.get('btc_sold')

    # Find entity in database — try ticker first, then company name
    entity = None
    if ticker:
        result = supabase.table("treasury_companies").select(
            "id, company, ticker, btc_holdings, data_source"
        ).ilike("ticker", f"%{ticker}%").limit(1).execute()
        if result.data:
            entity = result.data[0]

    if not entity:
        result = supabase.table("treasury_companies").select(
            "id, company, ticker, btc_holdings, data_source"
        ).ilike("company", f"%{company[:20]}%").limit(1).execute()
        if result.data:
            entity = result.data[0]

    if entity:
        current_source = entity.get('data_source', 'aggregator')
        current_btc = entity.get('btc_holdings', 0) or 0

        # ─── 3x SANITY CHECK: reject purchases that exceed current holdings by 3x+ ───
        # This catches target numbers (e.g., "100,000 BTC target") being parsed as purchases
        if btc_purchased and btc_purchased > 0 and current_btc > 0:
            if btc_purchased > current_btc * 3:
                logger.warning(f"  Parser: 🚫 REJECTED — {company}: {int(btc_purchased):,} BTC purchase exceeds current holdings ({current_btc:,}) by >3x — likely a target/goal, not a real purchase")
                return False

        # Only update if new source is higher or equal priority
        if not _should_update(current_source, data_source):
            logger.debug(f"  Parser: {company} — {data_source} cannot override {current_source}")
            return False

        update_data = {
            'data_source': data_source,
            'source_updated_at': datetime.now().isoformat(),
        }

        if btc_holdings and btc_holdings > 0:
            update_data['btc_holdings'] = int(btc_holdings)
        elif btc_purchased and btc_purchased > 0:
            update_data['btc_holdings'] = current_btc + int(btc_purchased)

        if update_data.get('btc_holdings'):
            supabase.table("treasury_companies").update(update_data).eq("id", entity["id"]).execute()
            old_btc = current_btc
            new_btc = update_data.get('btc_holdings', old_btc)
            logger.info(f"  Parser: {entity['company']} ({entity.get('ticker', '')}) — {old_btc:,} → {new_btc:,} BTC [{data_source}]")

            # Route purchase events through reconciler for proper confirmed_purchases tracking
            if HAS_RECONCILER and btc_purchased and btc_purchased > 0 and extracted.get('event_type') in ('purchase', 'new_treasury'):
                source_type_map = {
                    'sec_filing': 'edgar', 'regulatory_filing': 'global_filing',
                    'etf_issuer': 'global_filing', 'government_official': 'global_filing',
                    'press_release': 'news',
                }
                reconciler_source = source_type_map.get(data_source, 'news')
                try:
                    reconcile_and_save({
                        "company": entity.get('company', company),
                        "ticker": entity.get('ticker', ticker),
                        "btc_amount": int(btc_purchased),
                        "usd_amount": int(extracted.get('purchase_price_usd', 0) or 0),
                        "price_per_btc": int(extracted.get('avg_price_per_btc', 0) or 0),
                        "filing_date": extracted.get('date', datetime.now().strftime('%Y-%m-%d')),
                        "filing_url": "",
                        "source": f"AI Filing Parser [{data_source}]",
                        "notes": f"Extracted by Claude from {data_source} filing. Confidence: {confidence}",
                    }, source_type=reconciler_source, is_new_entrant=False)
                    logger.info(f"  Parser → Reconciler: {entity['company']} — {int(btc_purchased):,} BTC purchase [{reconciler_source}]")
                except Exception as e:
                    logger.debug(f"  Parser → Reconciler error: {e}")

            # Route sale events through sale reconciler
            if HAS_RECONCILER and btc_sold and btc_sold > 0 and extracted.get('event_type') == 'sale':
                source_type_map = {
                    'sec_filing': 'edgar', 'regulatory_filing': 'global_filing',
                    'etf_issuer': 'global_filing', 'government_official': 'global_filing',
                    'press_release': 'news',
                }
                reconciler_source = source_type_map.get(data_source, 'news')
                try:
                    reconcile_sale({
                        "company": entity.get('company', company),
                        "ticker": entity.get('ticker', ticker),
                        "btc_amount": int(btc_sold),
                        "usd_amount": int(extracted.get('sale_price_usd', 0) or 0),
                        "price_per_btc": int(extracted.get('avg_price_per_btc', 0) or 0),
                        "filing_date": extracted.get('date', datetime.now().strftime('%Y-%m-%d')),
                        "filing_url": "",
                        "source": f"AI Filing Parser [{data_source}]",
                        "notes": f"Sale extracted by Claude from {data_source} filing. Confidence: {confidence}",
                    }, source_type=reconciler_source)
                    logger.info(f"  Parser → Reconciler: {entity['company']} — {int(btc_sold):,} BTC sale [{reconciler_source}]")
                except Exception as e:
                    logger.debug(f"  Parser → Sale Reconciler error: {e}")

            return True
    else:
        # New entity — insert if we have BTC holdings data
        if btc_holdings and btc_holdings > 0:
            try:
                supabase.table("treasury_companies").insert({
                    'company': company[:200],
                    'ticker': (ticker or '')[:20],
                    'btc_holdings': int(btc_holdings),
                    'entity_type': entity_type,
                    'is_government': entity_type == 'government',
                    'data_source': data_source,
                    'source_updated_at': datetime.now().isoformat(),
                }).execute()
                logger.info(f"  Parser: NEW ENTITY — {company} ({ticker}) — {int(btc_holdings):,} BTC [{data_source}]")
                return True
            except Exception as e:
                logger.debug(f"  Parser: insert error for {company}: {e}")

    return False


def parse_and_update(max_filings=20):
    """
    Main function: Parse recent unprocessed filings and extract BTC data.
    Call after global_filing_scanner runs.
    """
    logger.info("Filing parser: processing recent filings with AI...")

    # Get recent filings that haven't been AI-parsed yet
    try:
        result = supabase.table("edgar_filings").select(
            "accession_number, company_name, ticker_cik, filing_url, source, event_type, btc_amount"
        ).order("processed_at", desc=True).limit(max_filings * 3).execute()

        filings = result.data or []
    except Exception as e:
        logger.debug(f"  Parser: fetch error: {e}")
        return {'parsed': 0, 'updated': 0}

    if not filings:
        logger.debug("  Parser: no filings to process")
        return {'parsed': 0, 'updated': 0}

    parsed = 0
    updated = 0

    # Prioritize filings that look like they have BTC data
    priority_filings = []
    other_filings = []
    for f in filings:
        if f.get('btc_amount', 0) > 0 or f.get('event_type') in ('purchase', 'sale'):
            priority_filings.append(f)
        elif f.get('filing_url') and not f['filing_url'].startswith('https://news.google.com'):
            other_filings.append(f)

    to_process = (priority_filings + other_filings)[:max_filings]

    for filing in to_process:
        url = filing.get('filing_url', '')
        source = filing.get('source', '')
        data_source = _determine_data_source(source)

        # If filing already has a BTC amount from regex extraction, use it directly
        if filing.get('btc_amount', 0) > 0 and filing.get('company_name'):
            extracted = {
                'company_name': filing['company_name'],
                'ticker': filing.get('ticker_cik', ''),
                'btc_holdings': filing['btc_amount'],
                'event_type': filing.get('event_type', 'holding_update'),
                'confidence': 0.7,
                'entity_type': 'public_company',
            }
            if _update_entity(extracted, data_source):
                updated += 1
            parsed += 1
            continue

        # Fetch and parse with Claude
        text = _fetch_filing_text(url)
        if not text or len(text) < 100:
            continue

        # Quick check — does the text even mention BTC?
        text_lower = text.lower()
        if not any(kw in text_lower for kw in ['bitcoin', 'btc', 'digital asset']):
            continue

        extracted = _call_claude(text)
        if extracted:
            if _update_entity(extracted, data_source):
                updated += 1
            parsed += 1

        time.sleep(1)  # Rate limit Claude API calls

    logger.info(f"Filing parser: {parsed} parsed, {updated} entities updated from primary sources")
    return {'parsed': parsed, 'updated': updated}


if __name__ == "__main__":
    logger.info("Filing parser — manual run...")
    result = parse_and_update(max_filings=10)
    print(f"Parsed: {result['parsed']}, Updated: {result['updated']}")
