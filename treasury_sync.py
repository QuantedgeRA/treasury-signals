"""
treasury_sync.py — Master Data Sync Engine v5.2
-------------------------------------------------
FIX: Entity types are now set AFTER all merging via a separate
category tracker. This guarantees correct classification.

Pipeline:
  1. CoinGecko API (primary — cost basis data)
  2. BT category pages (supplement — adds private, ETF, gov, DeFi)
  3. BT main page (supplement — catches remaining public companies)
  4. POST-PROCESS: Set entity_type from category tracker
  5. Wipe + rewrite to Supabase
"""

import os
import re
import json
import requests
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client
from bs4 import BeautifulSoup
from logger import get_logger

logger = get_logger(__name__)

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "contact@quantedgeriskadvisory.com")
EMAIL_FROM = os.getenv("EMAIL_FROM_ADDRESS", "briefing@quantedgeriskadvisory.com")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

BT_PAGES = [
    {"url": "https://bitcointreasuries.net/private-companies", "category": "private_company", "label": "Private Companies", "is_government": False},
    {"url": "https://bitcointreasuries.net/governments", "category": "government", "label": "Government Entities", "is_government": True},
    {"url": "https://bitcointreasuries.net/etfs-and-exchanges", "category": "etf", "label": "ETFs and Exchanges", "is_government": False},
    {"url": "https://bitcointreasuries.net/defi-and-other", "category": "defi", "label": "DeFi and Other", "is_government": False},
    {"url": "https://bitcointreasuries.net/", "category": "public_company", "label": "Public Companies", "is_government": False},
]

SOVEREIGN_FLAGS = {
    "united states": ("🇺🇸 United States", "US-GOV", "US"),
    "china": ("🇨🇳 China", "CN-GOV", "CN"),
    "united kingdom": ("🇬🇧 United Kingdom", "UK-GOV", "GB"),
    "ukraine": ("🇺🇦 Ukraine", "UA-GOV", "UA"),
    "bhutan": ("🇧🇹 Bhutan", "BT-GOV", "BT"),
    "el salvador": ("🇸🇻 El Salvador", "SV-GOV", "SV"),
    "finland": ("🇫🇮 Finland", "FI-GOV", "FI"),
    "germany": ("🇩🇪 Germany", "DE-GOV", "DE"),
    "georgia": ("🇬🇪 Georgia", "GE-GOV", "GE"),
    "czech": ("🇨🇿 Czech Republic", "CZ-GOV", "CZ"),
    "north korea": ("🇰🇵 North Korea", "KP-GOV", "KP"),
    "japan": ("🇯🇵 Japan", "JP-GOV", "JP"),
    "switzerland": ("🇨🇭 Switzerland", "CH-GOV", "CH"),
    "russia": ("🇷🇺 Russia", "RU-GOV", "RU"),
    "brazil": ("🇧🇷 Brazil", "BR-GOV", "BR"),
    "canada": ("🇨🇦 Canada", "CA-GOV", "CA"),
    "australia": ("🇦🇺 Australia", "AU-GOV", "AU"),
    "india": ("🇮🇳 India", "IN-GOV", "IN"),
    "norway": ("🇳🇴 Norway", "NO-GOV", "NO"),
    "poland": ("🇵🇱 Poland", "PL-GOV", "PL"),
    "thailand": ("🇹🇭 Thailand", "TH-GOV", "TH"),
    "singapore": ("🇸🇬 Singapore", "SG-GOV", "SG"),
    "saudi": ("🇸🇦 Saudi Arabia", "SA-GOV", "SA"),
    "venezuela": ("🇻🇪 Venezuela", "VE-GOV", "VE"),
    "iran": ("🇮🇷 Iran", "IR-GOV", "IR"),
    "turkey": ("🇹🇷 Turkey", "TR-GOV", "TR"),
    "tonga": ("🇹🇴 Tonga", "TO-GOV", "TO"),
    "kazakhstan": ("🇰🇿 Kazakhstan", "KZ-GOV", "KZ"),
    "hong kong": ("🇭🇰 Hong Kong", "HK-GOV", "HK"),
    "ethiopia": ("🇪🇹 Ethiopia", "ET-GOV", "ET"),
    "myanmar": ("🇲🇲 Myanmar", "MM-GOV", "MM"),
    "colombia": ("🇨🇴 Colombia", "CO-GOV", "CO"),
    "liechtenstein": ("🇱🇮 Liechtenstein", "LI-GOV", "LI"),
    "montenegro": ("🇲🇪 Montenegro", "ME-GOV", "ME"),
}

# Which category wins when an entity appears on multiple pages
# Higher number = more specific = wins
TYPE_PRIORITY = {
    "government": 5,
    "etf": 4,
    "defi": 4,
    "private_company": 3,
    "public_company": 1,
}

SECTOR_MAP = {
    "government": "Government",
    "etf": "ETF / Fund",
    "defi": "DeFi / Protocol",
    "private_company": "Private Company",
}


def normalize_name(name):
    n = name.lower().strip()
    for suffix in [" inc.", " inc", " corp.", " corp", " ltd.", " ltd", " plc", " ag", " se", " sa",
                   " co.", " co", " holdings", " holding", " group", " limited",
                   " technologies", " technology", " digital", " solutions", " platforms", " capital"]:
        n = n.replace(suffix, "")
    n = re.sub(r'\(.*?\)', '', n)
    n = re.sub(r'[^a-z0-9\s]', '', n)
    n = re.sub(r'\s+', ' ', n).strip()
    return n


class EntityStore:
    """Deduplicates by ticker + normalized name. Tracks category per entity."""

    def __init__(self):
        self._by_ticker = {}
        self._name_to_ticker = {}
        self._categories = {}  # ticker -> set of categories this entity appeared on

    def add(self, entity, is_primary=False):
        ticker = entity["ticker"]
        name = entity["company"]
        norm = normalize_name(name)
        category = entity.get("entity_type", "public_company")

        # Find existing by ticker
        if ticker in self._by_ticker:
            self._merge(self._by_ticker[ticker], entity, is_primary)
            self._categories.setdefault(ticker, set()).add(category)
            if norm and norm not in self._name_to_ticker:
                self._name_to_ticker[norm] = ticker
            return False

        # Find existing by normalized name
        if norm and norm in self._name_to_ticker:
            canonical = self._name_to_ticker[norm]
            if canonical in self._by_ticker:
                self._merge(self._by_ticker[canonical], entity, is_primary)
                self._categories.setdefault(canonical, set()).add(category)
                return False

        # New entity
        self._by_ticker[ticker] = entity.copy()
        self._categories[ticker] = {category}
        if norm:
            self._name_to_ticker[norm] = ticker
        return True

    def _merge(self, existing, incoming, incoming_is_primary):
        if incoming_is_primary:
            existing["btc_holdings"] = incoming.get("btc_holdings", existing["btc_holdings"])
            if incoming.get("total_cost_usd", 0) > 0:
                existing["total_cost_usd"] = incoming["total_cost_usd"]
                existing["avg_purchase_price"] = incoming.get("avg_purchase_price", 0)
            if incoming.get("country"):
                existing["country"] = incoming["country"]
            existing["data_source"] = incoming.get("data_source", existing["data_source"])
        else:
            if not existing.get("country") or existing["country"] in ("", "Unknown"):
                if incoming.get("country"):
                    existing["country"] = incoming["country"]
            if existing.get("data_source", "").startswith("bt_"):
                if incoming.get("btc_holdings", 0) > existing.get("btc_holdings", 0):
                    existing["btc_holdings"] = incoming["btc_holdings"]

    def apply_categories(self):
        """POST-PROCESS: Set entity_type based on most specific category seen."""
        for ticker, entity in self._by_ticker.items():
            cats = self._categories.get(ticker, {"public_company"})
            # Pick the category with highest priority
            best_cat = max(cats, key=lambda c: TYPE_PRIORITY.get(c, 0))
            entity["entity_type"] = best_cat
            entity["is_government"] = (best_cat == "government")
            # Update sector if we have a specific mapping
            if best_cat in SECTOR_MAP:
                entity["sector"] = SECTOR_MAP[best_cat]
            elif not entity.get("sector") or entity["sector"] == "Technology":
                entity["sector"] = _guess_sector(entity["company"], best_cat)

    def get_all(self):
        return self._by_ticker

    def count(self):
        return len(self._by_ticker)


def _guess_sector(name, entity_type):
    n = name.lower()
    if entity_type == "government": return "Government"
    if entity_type == "etf": return "ETF / Fund"
    if entity_type == "defi": return "DeFi / Protocol"
    if entity_type == "private_company": return "Private Company"
    if any(kw in n for kw in ["mining", "miner", "mara", "riot", "cleanspark", "bitfarms", "hut 8", "iris", "core scientific", "bitfufu", "canaan"]): return "Bitcoin Mining"
    if any(kw in n for kw in ["exchange", "coinbase", "kraken", "binance"]): return "Crypto Exchange"
    if any(kw in n for kw in ["bank", "financial", "capital"]): return "Financial Services"
    if any(kw in n for kw in ["tesla"]): return "Automotive"
    if any(kw in n for kw in ["block", "square", "payment"]): return "Fintech / Payments"
    return "Technology"


class StalenessTracker:

    def __init__(self):
        self._last_success = {}
        self._last_counts = {}
        self._alert_sent_today = {}

    def record_success(self, source, count):
        self._last_success[source] = datetime.now()
        self._last_counts[source] = count

    def record_failure(self, source, error=""):
        logger.warning(f"STALENESS: {source} failed — {error}")

    def check_and_alert(self, total_entities):
        issues = []
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")

        if not self._last_success.get("coingecko"):
            issues.append("CoinGecko (PRIMARY): never succeeded")

        expected = {"private_company": 20, "government": 5, "etf": 15, "defi": 5, "public_company": 80}
        for page in BT_PAGES:
            key = f"bt_{page['category']}"
            count = self._last_counts.get(key, 0)
            minimum = expected.get(page["category"], 5)
            if count < minimum:
                issues.append(f"BT {page['label']}: {count} (expected {minimum}+)")

        if total_entities < 200:
            issues.append(f"TOTAL: {total_entities} (expected 300+)")

        if not issues:
            return

        issue_key = str(len(issues)) + today
        if self._alert_sent_today.get("key") == issue_key:
            return

        logger.warning("STALENESS ALERT:")
        for issue in issues:
            logger.warning(f"  ⚠️  {issue}")

        if RESEND_API_KEY:
            try:
                body = [f"<h2>TSI Data Alert</h2><p>{now.strftime('%Y-%m-%d %H:%M')}</p><ul>"]
                for issue in issues:
                    body.append(f"<li><strong>{issue}</strong></li>")
                body.append("</ul><p style='color:#999;font-size:11px;'>Admin-only.</p>")
                requests.post("https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
                    json={"from": f"TSI Alerts <{EMAIL_FROM}>", "to": [ADMIN_EMAIL],
                          "subject": f"⚠️ TSI Data Alert", "html": "\n".join(body)},
                    timeout=10)
            except Exception:
                pass
        self._alert_sent_today["key"] = issue_key


class TreasurySync:

    def __init__(self):
        self._last_sync = None
        self._entity_count = 0
        self._staleness = StalenessTracker()

    def run(self):
        logger.info("Treasury Sync v5.2: starting full entity sync...")
        store = EntityStore()

        # ═══ LAYER 1: CoinGecko (PRIMARY) ═══
        logger.info("--- Layer 1: CoinGecko (PRIMARY) ---")
        try:
            cg = self._fetch_coingecko()
            cg_new = sum(1 for e in cg if store.add(e, is_primary=True))
            self._staleness.record_success("coingecko", len(cg))
            logger.info(f"  CoinGecko               -> {len(cg)} fetched, {cg_new} unique")
        except Exception as e:
            self._staleness.record_failure("coingecko", str(e))
            logger.warning(f"  CoinGecko FAILED: {e}")

        # ═══ LAYER 2: BitcoinTreasuries.net (SUPPLEMENT) ═══
        logger.info("--- Layer 2: BitcoinTreasuries.net (SUPPLEMENT) ---")
        for page in BT_PAGES:
            try:
                entities = self._scrape_page(page)
                new = merged = 0
                for e in entities:
                    if store.add(e, is_primary=False):
                        new += 1
                    else:
                        merged += 1
                self._staleness.record_success(f"bt_{page['category']}", len(entities))
                logger.info(f"  {page['label']:25s} -> {len(entities):>4} scraped, {new:>4} new, {merged:>4} merged")
            except Exception as e:
                self._staleness.record_failure(f"bt_{page['category']}", str(e))
                logger.warning(f"  {page['label']:25s} -> FAILED: {e}")

        # ═══ POST-PROCESS: Apply correct entity types ═══
        store.apply_categories()

        all_entities = store.get_all()
        total = store.count()

        if total == 0:
            logger.warning("Treasury Sync: no entities fetched")
            self._staleness.check_and_alert(0)
            return 0

        # ═══ WIPE + REWRITE ═══
        count = self._wipe_and_rewrite(all_entities)
        self._last_sync = datetime.now()
        self._entity_count = count
        self._update_snapshot(all_entities)
        self._staleness.check_and_alert(count)

        # ═══ SUMMARY ═══
        by_type = {}
        for e in all_entities.values():
            t = e.get("entity_type", "unknown")
            by_type[t] = by_type.get(t, 0) + 1
        type_str = ", ".join(f"{v} {k}" for k, v in sorted(by_type.items(), key=lambda x: -x[1]))
        total_btc = sum(e.get("btc_holdings", 0) for e in all_entities.values())
        logger.info(f"Treasury Sync COMPLETE: {count} unique entities, {total_btc:,} BTC")
        logger.info(f"  Breakdown: {type_str}")
        return count

    # ═══════════════════════════════════════════════════════════
    # COINGECKO
    # ═══════════════════════════════════════════════════════════

    def _fetch_coingecko(self):
        entities = []
        cg_headers = HEADERS.copy()
        cg_api_key = os.getenv("COINGECKO_API_KEY", "")
        if cg_api_key:
            cg_headers["x-cg-demo-api-key"] = cg_api_key
        resp = requests.get("https://api.coingecko.com/api/v3/companies/public_treasury/bitcoin", headers=cg_headers, timeout=15)
        if resp.status_code != 200:
            raise Exception(f"HTTP {resp.status_code}")
        for item in resp.json().get("companies", []):
            try:
                ticker = (item.get("symbol") or "").upper()
                name = item.get("name") or ""
                btc = int(item.get("total_holdings", 0))
                if not ticker or not name or btc <= 0:
                    continue
                cost = int(float(item.get("total_entry_value_usd", 0) or 0))
                avg = int(cost / btc) if btc > 0 and cost > 0 else 0
                entities.append({
                    "ticker": ticker, "company": name, "btc_holdings": btc,
                    "avg_purchase_price": avg, "total_cost_usd": cost,
                    "country": item.get("country", ""), "sector": "Technology",
                    "is_government": False, "entity_type": "public_company",
                    "data_source": "aggregator",
                })
            except Exception:
                continue
        return entities

    # ═══════════════════════════════════════════════════════════
    # BITCOINTREASURIES.NET
    # ═══════════════════════════════════════════════════════════

    def _scrape_page(self, page):
        entities = []
        resp = requests.get(page["url"], headers=HEADERS, timeout=20)
        if resp.status_code != 200:
            raise Exception(f"HTTP {resp.status_code}")

        # Use html.parser (not lxml) — proven to capture all rows
        soup = BeautifulSoup(resp.text, "html.parser")
        rows = soup.select("table tr")
        if not rows:
            return entities

        logger.info(f"  {page['label']}: found {len(rows)} total <tr> tags in HTML")

        # Detect format from first data row
        first_data_row = None
        for row in rows:
            cells = row.find_all("td")
            if len(cells) >= 3:
                first_data_row = [td.get_text(strip=True) for td in cells]
                break

        fmt = self._detect_format(first_data_row) if first_data_row else "A"

        # For public companies page (format B), use the existing parser
        if fmt == "B":
            parsed = 0
            failed = 0
            skipped_cols = 0
            for row in rows:
                cols = row.find_all("td")
                if len(cols) < 2:
                    skipped_cols += 1
                    continue
                try:
                    texts = [td.get_text(strip=True) for td in cols]
                    entity = self._parse_b(texts, page)
                    if entity and entity.get("btc_holdings", 0) > 0:
                        entities.append(entity)
                        parsed += 1
                    else:
                        failed += 1
                except Exception:
                    failed += 1
            logger.info(f"  {page['label']}: {parsed} parsed, {failed} failed, {skipped_cols} skipped (<2 cols) out of {len(rows)} rows")
            return entities

        # For non-public pages (Private, Government, ETF, DeFi):
        # Use entity_name_fixer's EXACT proven approach — inline BTC + name extraction
        is_gov = page["is_government"]
        category = page["category"]
        parsed = 0
        failed = 0
        skipped_cols = 0

        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 2:
                skipped_cols += 1
                continue

            texts = [td.get_text(strip=True) for td in cells]

            # BTC: take largest number < 50M (entity_name_fixer's exact approach)
            btc = 0
            for t in texts:
                clean = t.replace('\u20bf', '').replace('₿', '').replace(',', '').replace(' ', '')
                clean = re.sub(r'[^\d.]', '', clean)
                try:
                    val = int(float(clean)) if clean else 0
                    if val > btc and val < 50_000_000:
                        btc = val
                except:
                    pass

            if btc <= 0:
                failed += 1
                continue

            # Name: longest text starting with ASCII letter (entity_name_fixer's exact approach)
            name = ""
            for t in texts:
                stripped = t.strip()
                if (len(stripped) > len(name) and
                    stripped[0:1].isascii() and stripped[0:1].isalpha() and
                    not stripped.replace(',', '').replace('.', '').replace(' ', '').isdigit()):
                    name = stripped

            if not name:
                failed += 1
                continue

            # Clean name: remove concatenated tickers
            name = re.sub(r'([a-z])\s*([A-Z]{2,6})$', r'\1', name).strip()

            # Generate ticker from name
            ticker = re.sub(r'[^A-Za-z0-9]', '', name.upper()[:10])
            if not ticker:
                ticker = f"UNK{parsed}"

            # Country: 2-letter uppercase code
            country = ""
            for t in texts[:4]:
                t_stripped = t.strip()
                if len(t_stripped) == 2 and t_stripped.isalpha() and t_stripped.isupper():
                    country = t_stripped
                    break

            # Handle government entities
            if is_gov:
                for key, (display, gov_ticker, gov_country) in SOVEREIGN_FLAGS.items():
                    if key in name.lower():
                        name = display
                        ticker = gov_ticker
                        country = gov_country
                        break
                else:
                    if not ticker.endswith("-GOV"):
                        ticker = f"{ticker[:5]}-GOV"

            if not country:
                country = self._get_country(name, is_gov)

            entities.append({
                "ticker": ticker.upper(), "company": name[:200], "btc_holdings": btc,
                "avg_purchase_price": 0, "total_cost_usd": 0,
                "country": country,
                "sector": _guess_sector(name, category),
                "is_government": is_gov, "entity_type": category,
                "data_source": "aggregator",
            })
            parsed += 1

        logger.info(f"  {page['label']}: {parsed} parsed, {failed} failed, {skipped_cols} skipped (<2 cols) out of {len(rows)} rows")
        return entities

        return entities

    def _detect_format(self, texts):
        if len(texts) < 4:
            return "A"
        col1 = texts[1]
        if len(col1) <= 6 and not col1.isascii():
            return "A"
        if len(col1) > 3:
            return "B"
        return "A"

    def _parse_row(self, cols, fmt, page):
        texts = [td.get_text(strip=True) for td in cols]
        if fmt == "B":
            return self._parse_b(texts, page)
        return self._parse_a(texts, page)

    def _parse_a(self, texts, page):
        """
        Parse rows from non-public pages (Private, Government, ETF, DeFi).
        Uses entity_name_fixer's EXACT approach (proven 71/71):
        - Take largest number < 50M as BTC
        - Pick longest alphabetic text as name
        """
        if len(texts) < 2:
            return None

        # BTC extraction — EXACT copy of entity_name_fixer approach
        # Takes the largest number from any cell, < 50M sanity cap
        btc = 0
        for t in texts:
            clean = t.replace('\u20bf', '').replace('₿', '').replace(',', '').replace(' ', '')
            clean = re.sub(r'[^\d.]', '', clean)
            try:
                val = int(float(clean)) if clean else 0
                if val > btc and val < 50_000_000:
                    btc = val
            except:
                pass

        if btc <= 0:
            return None

        # Name extraction — EXACT copy of entity_name_fixer approach
        # Pick the longest text that starts with an ASCII letter
        name = ""
        for t in texts:
            stripped = t.strip()
            if (len(stripped) > len(name) and
                stripped[0:1].isascii() and stripped[0:1].isalpha() and
                not stripped.replace(",", "").replace(".", "").replace(" ", "").isdigit()):
                name = stripped

        if not name:
            return None

        # Clean name: remove concatenated tickers at end
        name = re.sub(r'([a-z])\s*([A-Z]{2,6})$', r'\1', name).strip()

        # Extract ticker from name or generate one
        ticker = ""
        name_clean, ticker_extracted = self._extract_name_ticker(name)
        if name_clean:
            name = name_clean
        if ticker_extracted:
            ticker = ticker_extracted
        if not ticker:
            ticker = re.sub(r'[^A-Za-z0-9]', '', name.upper()[:10])
        if not ticker:
            return None

        # Extract country — 2-letter uppercase code
        country = ""
        for t in texts[:4]:
            t_stripped = t.strip()
            if len(t_stripped) == 2 and t_stripped.isalpha() and t_stripped.isupper():
                country = t_stripped
                break

        # Handle government entities
        is_gov = page["is_government"]
        if is_gov:
            for key, (display, gov_ticker, gov_country) in SOVEREIGN_FLAGS.items():
                if key in name.lower():
                    name = display
                    ticker = gov_ticker
                    country = gov_country
                    break
            else:
                if not ticker.endswith("-GOV"):
                    ticker = f"{ticker[:5]}-GOV"

        if not country:
            country = self._get_country(name, is_gov)

        return {
            "ticker": ticker.upper(), "company": name[:200], "btc_holdings": btc,
            "avg_purchase_price": 0, "total_cost_usd": 0,
            "country": country,
            "sector": _guess_sector(name, page["category"]),
            "is_government": is_gov, "entity_type": page["category"],
            "data_source": "aggregator",
        }

    def _parse_b(self, texts, page):
        if len(texts) < 5:
            return None
        name = texts[1]
        ticker = texts[3] if len(texts) > 3 else ""
        if not name:
            return None
        btc_clean = re.sub(r'[^\d.]', '', texts[4].replace(",", "") if len(texts) > 4 else "0")
        btc = int(float(btc_clean)) if btc_clean else 0
        if btc <= 0:
            return None
        if not ticker:
            ticker = re.sub(r'[^A-Za-z0-9]', '', name.upper()[:10])
        return {
            "ticker": ticker.upper(), "company": name[:200], "btc_holdings": btc,
            "avg_purchase_price": 0, "total_cost_usd": 0, "country": "",
            "sector": _guess_sector(name, page["category"]),
            "is_government": False, "entity_type": page["category"],
            "data_source": "aggregator",
        }

    def _extract_btc(self, text):
        if not text:
            return 0
        # Skip obvious non-BTC values
        text_stripped = text.strip()
        if text_stripped.startswith("$") or text_stripped.endswith("%"):
            return 0
        # Remove BTC symbols
        clean = text.replace("\u20bf", "").replace("₿", "").replace(",", "").replace(" ", "")
        # Remove trailing M/B (millions/billions indicator from USD columns)
        if clean.endswith("M") or clean.endswith("B"):
            clean = clean[:-1]
        clean = re.sub(r'[^\d.]', '', clean)
        try:
            return int(float(clean)) if clean else 0
        except:
            return 0

    def _extract_name_ticker(self, raw):
        if not raw:
            return "", ""
        match = re.search(r'^(.+?)([A-Z][A-Z0-9]{1,7})(Buy|Sel)?$', raw)
        if match and len(match.group(1).strip()) >= 2:
            return match.group(1).strip(), match.group(2)
        return raw.strip(), ""

    def _get_country(self, name, is_gov):
        if is_gov:
            for key, (_, _, c) in SOVEREIGN_FLAGS.items():
                if key in name.lower():
                    return c
        return ""

    # ═══════════════════════════════════════════════════════════
    # DATABASE
    # ═══════════════════════════════════════════════════════════

    def _wipe_and_rewrite(self, all_entities):
        try:
            supabase.table("treasury_companies").delete().gte("id", 0).execute()
        except Exception as e:
            logger.warning(f"Could not clear table: {e}")

        count = errors = 0
        for ticker, entity in all_entities.items():
            try:
                supabase.table("treasury_companies").insert({
                    "ticker": ticker, "company": entity["company"][:200],
                    "btc_holdings": entity.get("btc_holdings", 0),
                    "avg_purchase_price": entity.get("avg_purchase_price", 0),
                    "total_cost_usd": entity.get("total_cost_usd", 0),
                    "country": (entity.get("country") or "")[:100],
                    "sector": (entity.get("sector") or "")[:100],
                    "is_government": entity.get("is_government", False),
                    "entity_type": entity.get("entity_type", "public_company"),
                    "data_source": entity.get("data_source", "aggregator"),
                    "last_updated": datetime.now().isoformat(),
                }).execute()
                count += 1
            except Exception as e:
                errors += 1
                if errors <= 3:
                    logger.debug(f"Insert error {ticker}: {e}")
        if errors > 0:
            logger.warning(f"Treasury Sync: {errors} insert errors")
        return count

    def _update_snapshot(self, all_entities):
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            total_btc = sum(e.get("btc_holdings", 0) for e in all_entities.values())
            supabase.table("leaderboard_snapshots").upsert({
                "snapshot_date": today, "total_btc": total_btc,
                "entity_count": len(all_entities),
            }, on_conflict="snapshot_date").execute()
        except Exception as e:
            logger.debug(f"Snapshot update failed: {e}")


sync = TreasurySync()

if __name__ == "__main__":
    logger.info("Treasury Sync v5.2 — full sync...")
    count = sync.run()
    print(f"\n{'='*60}")
    print(f"  TREASURY SYNC v5.2 COMPLETE")
    print(f"  {count} unique entities synced")
    print(f"{'='*60}\n")
