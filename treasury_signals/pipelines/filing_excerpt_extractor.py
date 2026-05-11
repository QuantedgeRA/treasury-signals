"""
filing_excerpt_extractor.py — BTC-relevant sentence extraction + Claude scoring.

The "moat" pipeline. Reads recent edgar_filings, fetches the full filing
text, extracts every sentence mentioning Bitcoin, sends them to Claude
for impact scoring + categorization, and stores the structured excerpts
in the filing_excerpts table.

Downstream consumers (added in follow-up commits):
  - Slack sender pushes excerpts with impact_score >= per-team threshold
  - /filings frontend feed sorts by impact + recency
  - Daily digest email rolls up top excerpts per company

Pipeline contract:
  Input  — edgar_filings rows (already populated by edgar_realtime.py)
  Output — filing_excerpts rows (one row per material sentence)

This module is read-only against edgar_filings and append-only against
filing_excerpts. It does NOT mutate treasury_companies or trigger any
reconciler logic — that path is owned by filing_parser.py.
"""

import os
import re
import json
import time
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from supabase import create_client
from treasury_signals.logger import get_logger
from treasury_signals.observability import capture_exception

logger = get_logger(__name__)
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CLAUDE_MODEL = "claude-sonnet-4-5-20250929"

HEADERS_WEB = {
    "User-Agent": "TreasurySignalIntelligence admin@quantedgeriskadvisory.com",
    "Accept": "text/html,application/xhtml+xml",
}

# Sentences must mention at least one of these to be candidates for Claude.
# Conservative on purpose — false positives are cheap to filter at the Claude
# step, false negatives are silent and bad.
BTC_KEYWORDS = (
    "bitcoin", "btc", "digital asset", "crypto", "cryptocurrency",
    "satoshi", "lightning", "blockchain",
)

# Hard caps. Per filing: too many sentences = wasted tokens. The Claude prompt
# returns AT MOST this many excerpts even when more are submitted.
MAX_CANDIDATE_SENTENCES = 40
MAX_EXCERPTS_PER_FILING = 15
MAX_FILING_TEXT_CHARS = 40_000  # SEC 8-Ks fit comfortably; bigger ones get truncated


SCORING_PROMPT = """You are extracting BTC-relevant material from a corporate SEC filing for a treasury-intelligence product. Treasury operators (CFOs, IR leads) read this output to decide whether to alert their team within 10 minutes of the filing landing.

Your job: pick the MOST MATERIAL sentences from the candidates below, score each 0-100 on impact, and categorize.

CATEGORIES (use exactly one):
  acquisition       — actual BTC purchase, holdings increased (NOT a target/goal)
  sale              — BTC sold, divested, liquidated, written down
  financing         — capital raise where proceeds are linked to BTC strategy (ATM offering, convertible notes earmarked for BTC, etc.)
  policy_change     — treasury policy update, new reserve target, board mandate, custody arrangement change
  risk_factor       — BTC-specific risk disclosure (volatility, custody, regulatory)
  forward_looking   — guidance / plans / intentions ("plans to", "intends to", "expects to acquire") — NOT confirmed events
  general           — mentions BTC but doesn't fit above (typically low impact)

IMPACT SCORING (0-100):
  90-100  — confirmed material transaction (>$50M BTC purchase, new treasury policy adoption, major divestment)
  70-89   — meaningful confirmed event (any acquisition >100 BTC, policy refinement, financing tied to BTC)
  50-69   — confirmed but smaller, or material forward-looking statement from leadership
  30-49   — risk factor language, generic policy mention, contextual reference
  0-29    — boilerplate, definitions, glossary entries, "may" statements

RULES:
- Return AT MOST {max_excerpts} excerpts. If fewer than {max_excerpts} sentences are material, return fewer. Do NOT pad.
- Each excerpt_text MUST be a verbatim sentence (or short paragraph) from the candidates. Do not paraphrase.
- DISTINGUISH targets vs purchases: "aims to acquire 100,000 BTC by 2027" is forward_looking (score 40-60). "Acquired 4,871 BTC for $330M on October 15" is acquisition (score 80+).
- btc_amount and usd_amount: parse from the excerpt. NULL if not stated.
- claude_summary: ONE sentence, max 25 words, paraphrasing the action and amount in plain English.
- Return ONLY valid JSON. No prose, no markdown fences.

OUTPUT JSON SHAPE:
{{
  "excerpts": [
    {{
      "excerpt_text": "verbatim sentence from the filing",
      "impact_score": 0-100,
      "category": "acquisition" | "sale" | "financing" | "policy_change" | "risk_factor" | "forward_looking" | "general",
      "claude_summary": "one-sentence plain-English summary",
      "btc_amount": number or null,
      "usd_amount": number or null
    }}
  ]
}}

FILING METADATA:
  Company: {company}
  Ticker: {ticker}
  Form: {form_type}
  Date: {filing_date}

CANDIDATE SENTENCES (each line is one sentence, numbered):
{candidates}
"""


# ─────────────────────────── HELPERS ─────────────────────────────────────


def _fetch_filing_text(url: str) -> str:
    """Fetch + strip HTML. Mirrors the helper in filing_parser.py but with
    a larger char ceiling because we want Claude to see late-document risk
    factor sections that the parser truncates."""
    if not url or url.startswith("https://news.google.com"):
        return ""
    try:
        time.sleep(0.4)  # SEC rate limit cushion
        resp = requests.get(url, headers=HEADERS_WEB, timeout=30)
        if not resp.ok:
            return ""
        text = re.sub(r"<[^>]+>", " ", resp.text)
        text = re.sub(r"\s+", " ", text)
        return text[:MAX_FILING_TEXT_CHARS]
    except Exception as e:
        logger.debug(f"  Excerpt fetch error: {e}")
        return ""


def _extract_candidate_sentences(text: str) -> list[str]:
    """Split filing text into sentences, keep those containing BTC keywords.
    Returns at most MAX_CANDIDATE_SENTENCES, ordered as they appear in the
    document (early sentences usually contain the lede)."""
    if not text:
        return []

    # Crude sentence split — SEC filings have predictable punctuation. We
    # avoid heavyweight NLP tooling because the downstream Claude call is
    # forgiving about boundaries.
    raw = re.split(r"(?<=[.!?])\s+(?=[A-Z\"\(])", text)

    seen = set()
    candidates = []
    for s in raw:
        s_clean = s.strip()
        if len(s_clean) < 30 or len(s_clean) > 1500:
            continue
        lower = s_clean.lower()
        if not any(kw in lower for kw in BTC_KEYWORDS):
            continue
        # Dedupe identical sentences (filings often repeat boilerplate)
        key = lower[:120]
        if key in seen:
            continue
        seen.add(key)
        candidates.append(s_clean)
        if len(candidates) >= MAX_CANDIDATE_SENTENCES:
            break

    return candidates


def _call_claude_for_excerpts(
    company: str, ticker: str, form_type: str, filing_date: str, candidates: list[str]
) -> list[dict]:
    """One Claude call per filing. Returns a list of excerpt dicts or []."""
    if not ANTHROPIC_API_KEY:
        logger.debug("  Excerpt extractor: no ANTHROPIC_API_KEY set")
        return []
    if not candidates:
        return []

    numbered = "\n".join(f"{i+1}. {s}" for i, s in enumerate(candidates))
    prompt = SCORING_PROMPT.format(
        company=company or "Unknown",
        ticker=ticker or "—",
        form_type=form_type or "8-K",
        filing_date=filing_date or "—",
        candidates=numbered,
        max_excerpts=MAX_EXCERPTS_PER_FILING,
    )

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "Content-Type": "application/json",
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": CLAUDE_MODEL,
                "max_tokens": 4000,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=90,
        )
        if not resp.ok:
            logger.debug(f"  Excerpt extractor: Claude HTTP {resp.status_code}: {resp.text[:200]}")
            return []

        body = resp.json()
        content = body.get("content", [{}])[0].get("text", "").strip()
        # Strip code fences if Claude wraps the JSON despite being told not to
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```\s*$", "", content)

        parsed = json.loads(content)
        return parsed.get("excerpts", []) or []

    except json.JSONDecodeError as e:
        logger.debug(f"  Excerpt extractor: JSON decode error: {e}")
        return []
    except Exception as e:
        logger.debug(f"  Excerpt extractor: Claude API error: {e}")
        capture_exception(e, context={"where": "filing_excerpt_extractor._call_claude_for_excerpts"})
        return []


def _get_filings_needing_excerpts(lookback_hours: int, limit: int) -> list[dict]:
    """Pull recent edgar_filings that don't have any filing_excerpts rows yet.

    Implementation note: Supabase doesn't expose LEFT JOIN easily through the
    PostgREST client. We do it in two cheap queries instead — fetch recent
    filings + fetch the set of filing_ids already extracted, then diff.
    """
    cutoff = (datetime.utcnow() - timedelta(hours=lookback_hours)).isoformat()

    try:
        filings_res = (
            supabase.table("edgar_filings")
            .select("id, accession_number, company_name, ticker_cik, filing_date, form_type, filing_url")
            .gte("processed_at", cutoff)
            .order("processed_at", desc=True)
            .limit(limit * 3)  # over-fetch — we'll skip already-extracted ones
            .execute()
        )
        filings = filings_res.data or []
    except Exception as e:
        logger.debug(f"  Excerpt extractor: filing fetch error: {e}")
        return []

    if not filings:
        return []

    filing_ids = [f["id"] for f in filings if f.get("id")]
    try:
        extracted_res = (
            supabase.table("filing_excerpts")
            .select("filing_id")
            .in_("filing_id", filing_ids)
            .execute()
        )
        already_extracted = {r["filing_id"] for r in (extracted_res.data or []) if r.get("filing_id")}
    except Exception as e:
        # Table may not exist yet on a fresh DB without the migration applied —
        # surface that explicitly so it's obvious why the pipeline no-ops.
        logger.warning(f"  Excerpt extractor: filing_excerpts read error (run migration 0011?): {e}")
        return []

    pending = [f for f in filings if f.get("id") and f["id"] not in already_extracted]
    return pending[:limit]


def _store_excerpts(filing: dict, excerpts: list[dict]) -> int:
    """Insert excerpts. Returns count of rows stored."""
    if not excerpts:
        return 0

    rows = []
    for e in excerpts:
        excerpt_text = (e.get("excerpt_text") or "").strip()
        if not excerpt_text:
            continue
        category = (e.get("category") or "general").strip()
        # Defensive — Claude occasionally invents categories. Coerce to 'general'.
        valid_categories = {
            "acquisition", "sale", "financing", "policy_change",
            "risk_factor", "forward_looking", "general",
        }
        if category not in valid_categories:
            category = "general"

        try:
            impact = int(e.get("impact_score", 0) or 0)
            impact = max(0, min(100, impact))
        except (TypeError, ValueError):
            impact = 0

        rows.append({
            "filing_id": filing["id"],
            "accession_number": filing.get("accession_number"),
            "company_name": (filing.get("company_name") or "")[:200] or None,
            "ticker": (filing.get("ticker_cik") or "")[:50] or None,
            "filing_date": filing.get("filing_date"),
            "filing_url": (filing.get("filing_url") or "")[:500] or None,
            "form_type": filing.get("form_type"),
            "excerpt_text": excerpt_text[:5000],
            "claude_summary": (e.get("claude_summary") or "")[:500] or None,
            "impact_score": impact,
            "category": category,
            "btc_amount": e.get("btc_amount"),
            "usd_amount": e.get("usd_amount"),
        })

    if not rows:
        return 0

    try:
        supabase.table("filing_excerpts").insert(rows).execute()
        return len(rows)
    except Exception as e:
        logger.warning(f"  Excerpt store error: {e}")
        capture_exception(e, context={
            "where": "filing_excerpt_extractor._store_excerpts",
            "filing_id": filing.get("id"),
            "rows": len(rows),
        })
        return 0


# ─────────────────────────── PUBLIC ENTRY POINT ──────────────────────────


def extract_excerpts_for_recent_filings(lookback_hours: int = 24, max_filings: int = 10) -> dict:
    """Process the most recent un-extracted filings. Designed to be called
    from the post-scan scheduler hook every cycle.

    Args:
        lookback_hours: how far back to consider edgar_filings rows.
        max_filings: cap per run to control Claude spend.

    Returns:
        {"processed": N, "excerpts": M}
    """
    logger.info(f"Excerpt extractor: scanning last {lookback_hours}h for unprocessed filings...")

    if not ANTHROPIC_API_KEY:
        logger.info("  Excerpt extractor: ANTHROPIC_API_KEY not set — skipping (config gate)")
        return {"processed": 0, "excerpts": 0}

    filings = _get_filings_needing_excerpts(lookback_hours, max_filings)
    if not filings:
        logger.info("  Excerpt extractor: no new filings to process")
        return {"processed": 0, "excerpts": 0}

    total_excerpts = 0
    for filing in filings:
        url = filing.get("filing_url") or ""
        if not url:
            continue

        text = _fetch_filing_text(url)
        if not text or len(text) < 200:
            logger.debug(f"  Excerpt extractor: empty or tiny filing text for {filing.get('accession_number')}")
            continue

        candidates = _extract_candidate_sentences(text)
        if not candidates:
            logger.debug(f"  Excerpt extractor: no BTC-relevant sentences in {filing.get('accession_number')}")
            continue

        excerpts = _call_claude_for_excerpts(
            company=filing.get("company_name") or "",
            ticker=filing.get("ticker_cik") or "",
            form_type=filing.get("form_type") or "8-K",
            filing_date=str(filing.get("filing_date") or ""),
            candidates=candidates,
        )

        stored = _store_excerpts(filing, excerpts)
        total_excerpts += stored
        logger.info(
            f"  Excerpt extractor: {filing.get('company_name','?')} "
            f"({filing.get('ticker_cik','?')}) — {len(candidates)} candidates, {stored} excerpts stored"
        )

        time.sleep(1)  # Claude rate-limit cushion

    logger.info(f"Excerpt extractor: {len(filings)} filings processed, {total_excerpts} excerpts stored")
    return {"processed": len(filings), "excerpts": total_excerpts}


if __name__ == "__main__":
    logger.info("Filing excerpt extractor — manual run (last 72h, max 5 filings)...")
    result = extract_excerpts_for_recent_filings(lookback_hours=72, max_filings=5)
    print(f"Processed: {result['processed']}, Excerpts: {result['excerpts']}")
