"""
regulatory_scanner.py
---------------------
Auto-scanning for regulatory developments and notable statements.

Sources:
1. Google News RSS (free, no API key)
2. Tweet scanner (executives already monitored)
3. Supabase database (persisted items)
4. Hardcoded fallback data
"""

import os
import re
import json
import hashlib
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from dotenv import load_dotenv
from supabase import create_client
from logger import get_logger
from freshness_tracker import freshness

logger = get_logger(__name__)

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# ============================================
# NEWS SEARCH QUERIES
# ============================================

REGULATORY_QUERIES = [
    "bitcoin regulation law 2026",
    "bitcoin legislation government",
    "bitcoin strategic reserve",
    "bitcoin legal tender country",
    "central bank bitcoin",
    "crypto regulation bill passed",
    "stablecoin regulation act",
    "bitcoin mining regulation",
    "SEC crypto regulation",
    "bitcoin ETF approval",
]

STATEMENT_QUERIES = [
    "Michael Saylor bitcoin 2026",
    "Larry Fink bitcoin crypto 2026",
    "Cathie Wood bitcoin prediction 2026",
    "Jamie Dimon bitcoin crypto 2026",
    "Brian Armstrong bitcoin 2026",
    "Jack Dorsey bitcoin 2026",
    "Elon Musk bitcoin crypto 2026",
    "Ryan Cohen bitcoin GameStop 2026",
    "Trump bitcoin crypto statement 2026",
    "Jerome Powell bitcoin crypto Fed 2026",
    "Paul Atkins SEC crypto 2026",
    "David Sacks crypto czar 2026",
    "Cynthia Lummis bitcoin 2026",
    "Christine Lagarde bitcoin ECB 2026",
    "Nayib Bukele bitcoin 2026",
    "Javier Milei bitcoin crypto 2026",
    "BlackRock bitcoin ETF statement 2026",
    "Fidelity bitcoin statement 2026",
    "Wall Street bitcoin statement 2026",
    "sovereign wealth fund bitcoin 2026",
    "bitcoin corporate treasury statement 2026",
]

BULLISH_KEYWORDS = [
    "approve", "passed", "signed into law", "adopt", "reserve", "buy",
    "purchase", "bullish", "positive", "support", "embrace", "legal tender",
    "accumulate", "investment", "allocate", "pro-bitcoin", "pro-crypto",
    "favorable", "growth", "opportunity", "adoption",
]

BEARISH_KEYWORDS = [
    "ban", "restrict", "crackdown", "warning", "concern", "prohibit",
    "bearish", "negative", "reject", "oppose", "risk", "volatile",
    "fraud", "scam", "bubble", "tax increase", "enforcement",
]

CATEGORY_KEYWORDS = {
    "US Federal": ["congress", "senate", "house of representatives", "federal", "sec", "cftc", "treasury department", "white house", "president"],
    "US State": ["state of", "governor", "state legislature", "state bill", "state law"],
    "Europe": ["eu ", "european", "ecb", "uk ", "britain", "germany", "france", "switzerland", "czech"],
    "Asia-Pacific": ["japan", "china", "korea", "india", "singapore", "hong kong", "australia", "thailand", "bhutan"],
    "Latin America": ["brazil", "argentina", "el salvador", "mexico", "panama", "colombia", "chile"],
    "Middle East & Africa": ["uae", "dubai", "saudi", "nigeria", "south africa", "israel", "turkey"],
}

NOTABLE_PEOPLE = {
    "michael saylor": {"title": "Executive Chairman, Strategy", "category": "CEO"},
    "phong le": {"title": "CEO, Strategy", "category": "CEO"},
    "fred thiel": {"title": "CEO, MARA Holdings", "category": "CEO"},
    "jason les": {"title": "CEO, Riot Platforms", "category": "CEO"},
    "ryan cohen": {"title": "CEO & Chairman, GameStop", "category": "CEO"},
    "simon gerovich": {"title": "CEO, Metaplanet", "category": "CEO"},
    "jack mallers": {"title": "CEO, Strike / Twenty One Capital", "category": "CEO"},
    "brian armstrong": {"title": "CEO, Coinbase", "category": "CEO"},
    "jack dorsey": {"title": "CEO, Block", "category": "CEO"},
    "elon musk": {"title": "CEO, Tesla & SpaceX", "category": "CEO"},
    "larry fink": {"title": "CEO, BlackRock", "category": "CEO"},
    "cathie wood": {"title": "CEO, ARK Invest", "category": "CEO"},
    "jamie dimon": {"title": "CEO, JPMorgan Chase", "category": "CEO"},
    "david solomon": {"title": "CEO, Goldman Sachs", "category": "CEO"},
    "donald trump": {"title": "President of the United States", "category": "Government"},
    "scott bessent": {"title": "US Treasury Secretary", "category": "Government"},
    "jerome powell": {"title": "Chair, Federal Reserve", "category": "Government"},
    "paul atkins": {"title": "SEC Chair", "category": "Government"},
    "cynthia lummis": {"title": "US Senator (R-WY)", "category": "Government"},
    "david sacks": {"title": "White House AI & Crypto Czar", "category": "Government"},
    "nayib bukele": {"title": "President of El Salvador", "category": "Government"},
    "javier milei": {"title": "President of Argentina", "category": "Government"},
    "christine lagarde": {"title": "President, European Central Bank", "category": "Government"},
    "ales michl": {"title": "Governor, Czech National Bank", "category": "Government"},
    "elizabeth warren": {"title": "US Senator (D-MA)", "category": "Government"},
    "hester peirce": {"title": "SEC Commissioner", "category": "Government"},
    "ray dalio": {"title": "Founder, Bridgewater Associates", "category": "CEO"},
    "bill ackman": {"title": "CEO, Pershing Square", "category": "CEO"},
    "changpeng zhao": {"title": "Founder, Binance", "category": "CEO"},
    "sam altman": {"title": "CEO, OpenAI", "category": "CEO"},
    "robert kiyosaki": {"title": "Author, Rich Dad Poor Dad", "category": "CEO"},
    "raoul pal": {"title": "CEO, Real Vision", "category": "CEO"},
    "anthony pompliano": {"title": "Founder, Pomp Investments", "category": "CEO"},
    "adam back": {"title": "CEO, Blockstream", "category": "CEO"},
}


def fetch_google_news_rss(query, max_results=10):
    """Fetch news articles from Google News RSS feed."""
    try:
        url = f"https://news.google.com/rss/search?q={requests.utils.quote(query)}&hl=en-US&gl=US&ceid=US:en"
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code != 200:
            logger.debug(f"Google News RSS returned {response.status_code} for '{query}'")
            return []

        root = ET.fromstring(response.content)
        articles = []

        for item in root.findall(".//item")[:max_results]:
            title = item.findtext("title", "")
            link = item.findtext("link", "")
            pub_date = item.findtext("pubDate", "")
            description = item.findtext("description", "")

            try:
                date_obj = datetime.strptime(pub_date[:25], "%a, %d %b %Y %H:%M:%S")
                date_str = date_obj.strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                date_str = datetime.now().strftime("%Y-%m-%d")

            clean_desc = re.sub(r'<[^>]+>', '', description)

            articles.append({
                "title": title, "url": link,
                "date": date_str, "description": clean_desc[:500],
            })

        return articles
    except Exception as e:
        logger.debug(f"RSS fetch error for '{query}': {e}")
        return []


def classify_btc_impact(text):
    """Classify whether text is bullish, bearish, or neutral for BTC."""
    text_lower = text.lower()

    bullish_count = sum(1 for k in BULLISH_KEYWORDS if k in text_lower)
    bearish_count = sum(1 for k in BEARISH_KEYWORDS if k in text_lower)

    strong_bullish = any(k in text_lower for k in ["bitcoin will reach", "bitcoin to ", "btc target", "million", "billion", "all-time high", "ath", "moon", "skyrocket", "surge", "soar", "record", "rally", "boom"])
    strong_bearish = any(k in text_lower for k in ["crash", "plunge", "collapse", "worthless", "zero", "ponzi", "scam", "fraud", "ban bitcoin", "prohibit"])

    if strong_bullish:
        return "VERY BULLISH"
    if strong_bearish:
        return "VERY BEARISH"
    if bullish_count > bearish_count:
        return "VERY BULLISH" if bullish_count >= 3 else "BULLISH"
    elif bearish_count > bullish_count:
        return "VERY BEARISH" if bearish_count >= 3 else "BEARISH"

    positive_context = any(k in text_lower for k in ["bitcoin", "btc", "crypto", "digital asset"])
    negative_context = any(k in text_lower for k in ["concern", "warn", "risk", "threat", "problem"])

    if positive_context and not negative_context:
        return "BULLISH"
    elif negative_context:
        return "BEARISH"
    return "NEUTRAL"


def classify_category(text):
    """Classify which region/category a regulatory item belongs to."""
    text_lower = text.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if keyword in text_lower:
                return category
    return "Global"


def detect_notable_person(text):
    """Check if text mentions a notable person."""
    text_lower = text.lower()
    for person_name, info in NOTABLE_PEOPLE.items():
        if person_name in text_lower:
            return {"person": person_name.title(), **info}
    return None


def generate_item_id(text):
    """Generate a unique ID for deduplication."""
    return hashlib.md5(text[:100].encode()).hexdigest()[:12]


def scan_regulatory_news():
    """Scan Google News for new regulatory developments."""
    logger.info("Scanning for regulatory news...")
    new_items = []

    for query in REGULATORY_QUERIES:
        articles = fetch_google_news_rss(query, max_results=5)
        for article in articles:
            try:
                article_date = datetime.strptime(article["date"], "%Y-%m-%d")
                if (datetime.now() - article_date).days > 30:
                    continue
            except (ValueError, TypeError):
                continue

            combined_text = f"{article['title']} {article['description']}"
            btc_impact = classify_btc_impact(combined_text)
            category = classify_category(combined_text)

            regulation_keywords = ["regulation", "law", "bill", "act", "legislation", "policy", "reserve", "legal", "ruling", "approval", "ban"]
            if not any(k in combined_text.lower() for k in regulation_keywords):
                continue

            item_id = f"auto_{generate_item_id(article['title'])}"

            new_items.append({
                "item_id": item_id,
                "title": article["title"][:200],
                "category": category,
                "type": "News",
                "status": "Reported",
                "status_color": "yellow",
                "date_updated": article["date"],
                "summary": article["description"][:400],
                "impact": f"Detected from news — {btc_impact}",
                "btc_impact": btc_impact,
                "country": "",
                "source_url": article["url"],
                "auto_detected": True,
            })

    # Deduplicate
    seen_titles = set()
    unique_items = []
    for item in new_items:
        title_key = item["title"][:50].lower()
        if title_key not in seen_titles:
            seen_titles.add(title_key)
            unique_items.append(item)

    logger.info(f"Found {len(unique_items)} regulatory news items")
    if unique_items:
        freshness.record_success("google_news_reg", detail=f"{len(unique_items)} items found")
        freshness.set_provenance("regulatory", "Google News RSS (auto-scan)", "live")
    return unique_items


def scan_notable_statements():
    """Scan Google News for notable statements about Bitcoin."""
    logger.info("Scanning for notable statements...")
    new_statements = []

    for query in STATEMENT_QUERIES:
        articles = fetch_google_news_rss(query, max_results=5)
        for article in articles:
            try:
                article_date = datetime.strptime(article["date"], "%Y-%m-%d")
                if (datetime.now() - article_date).days > 30:
                    continue
            except (ValueError, TypeError):
                continue

            combined_text = f"{article['title']} {article['description']}"
            person_info = detect_notable_person(combined_text)

            if not person_info:
                continue

            impact = classify_btc_impact(combined_text)
            statement_id = f"auto_{generate_item_id(article['title'])}"

            new_statements.append({
                "statement_id": statement_id,
                "person": person_info["person"],
                "title": person_info["title"],
                "date": article["date"],
                "statement": article["title"][:300],
                "impact": impact,
                "category": person_info["category"],
                "source_url": article["url"],
                "auto_detected": True,
            })

    # Deduplicate
    seen = set()
    unique = []
    for s in new_statements:
        key = f"{s['person']}_{s['date']}"
        if key not in seen:
            seen.add(key)
            unique.append(s)

    logger.info(f"Found {len(unique)} notable statements")
    if unique:
        freshness.record_success("google_news_stmt", detail=f"{len(unique)} statements found")
        freshness.set_provenance("statements", "Google News RSS (auto-scan)", "live")
    return unique


def save_regulatory_items(items):
    """Save new regulatory items to Supabase."""
    saved = 0
    for item in items:
        try:
            existing = supabase.table("regulatory_items").select("item_id").eq("item_id", item["item_id"]).execute()
            if existing.data:
                continue
            supabase.table("regulatory_items").insert(item).execute()
            saved += 1
        except Exception as e:
            logger.debug(f"Could not save regulatory item {item.get('item_id', '')}: {e}")
    if saved:
        logger.info(f"{saved} new regulatory item(s) saved to database")
    return saved


def save_notable_statements(statements):
    """Save new statements to Supabase."""
    saved = 0
    for s in statements:
        try:
            existing = supabase.table("notable_statements").select("statement_id").eq("statement_id", s["statement_id"]).execute()
            if existing.data:
                continue
            supabase.table("notable_statements").insert(s).execute()
            saved += 1
        except Exception as e:
            logger.debug(f"Could not save statement {s.get('statement_id', '')}: {e}")
    if saved:
        logger.info(f"{saved} new statement(s) saved to database")
    return saved


def seed_hardcoded_data():
    """Seed the hardcoded regulatory items and statements into Supabase."""
    from regulatory_tracker import REGULATORY_ITEMS as HARDCODED_ITEMS, NOTABLE_STATEMENTS as HARDCODED_STATEMENTS

    logger.info("Seeding hardcoded regulatory data...")
    reg_saved = 0
    for item in HARDCODED_ITEMS:
        item_id = f"seed_{generate_item_id(item['title'])}"
        try:
            existing = supabase.table("regulatory_items").select("item_id").eq("item_id", item_id).execute()
            if existing.data:
                continue
            row = {
                "item_id": item_id, "title": item["title"], "category": item["category"],
                "type": item["type"], "status": item["status"], "status_color": item["status_color"],
                "date_updated": item["date_updated"], "summary": item["summary"],
                "impact": item["impact"], "btc_impact": item["btc_impact"], "auto_detected": False,
            }
            supabase.table("regulatory_items").insert(row).execute()
            reg_saved += 1
        except Exception as e:
            logger.debug(f"Seed failed for regulatory item: {e}")

    logger.info(f"{reg_saved} regulatory items seeded")

    stmt_saved = 0
    for s in HARDCODED_STATEMENTS:
        stmt_id = f"seed_{generate_item_id(s['person'] + s['date'])}"
        try:
            existing = supabase.table("notable_statements").select("statement_id").eq("statement_id", stmt_id).execute()
            if existing.data:
                continue
            row = {
                "statement_id": stmt_id, "person": s["person"], "title": s["title"],
                "date": s["date"], "statement": s["statement"],
                "impact": s["impact"], "category": s["category"], "auto_detected": False,
            }
            supabase.table("notable_statements").insert(row).execute()
            stmt_saved += 1
        except Exception as e:
            logger.debug(f"Seed failed for statement: {e}")

    logger.info(f"{stmt_saved} statements seeded")
    return reg_saved, stmt_saved


def get_all_regulatory_from_db():
    """Get all regulatory items from database."""
    try:
        result = supabase.table("regulatory_items").select("*").order("date_updated", desc=True).limit(100).execute()
        return result.data if result.data else []
    except Exception as e:
        logger.error(f"Failed to fetch regulatory items from DB: {e}", exc_info=True)
        return []


def get_all_statements_from_db():
    """Get all statements from database."""
    try:
        result = supabase.table("notable_statements").select("*").order("date", desc=True).limit(100).execute()
        return result.data if result.data else []
    except Exception as e:
        logger.error(f"Failed to fetch statements from DB: {e}", exc_info=True)
        return []


def run_full_scan():
    """Run the full regulatory + statements scan."""
    logger.info("Running regulatory & statements auto-scan...")

    reg_items = scan_regulatory_news()
    if reg_items:
        save_regulatory_items(reg_items)

    statements = scan_notable_statements()
    if statements:
        save_notable_statements(statements)

    all_reg = get_all_regulatory_from_db()
    all_stmt = get_all_statements_from_db()

    auto_reg = len([r for r in all_reg if r.get("auto_detected")])
    auto_stmt = len([s for s in all_stmt if s.get("auto_detected")])

    logger.info(f"DB totals: {len(all_reg)} regulatory items ({auto_reg} auto) | {len(all_stmt)} statements ({auto_stmt} auto)")

    return reg_items, statements


# ============================================
# QUICK TEST
# ============================================
if __name__ == "__main__":
    logger.info("Regulatory & Statements Auto-Scanner — testing...")
    seed_hardcoded_data()
    reg_items = scan_regulatory_news()
    statements = scan_notable_statements()
    save_regulatory_items(reg_items)
    save_notable_statements(statements)
    logger.info("Regulatory Scanner test complete")
