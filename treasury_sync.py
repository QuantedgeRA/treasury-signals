"""
treasury_sync.py — Master Data Sync Engine v2.0
-------------------------------------------------
Fetches ALL Bitcoin-holding entities from BitcoinTreasuries.net:
  - 100 Public Companies
  - 72 Private Companies
  - 13 Government Entities
  - 48 ETFs and Exchanges
  - 16 DeFi / Others

Total: ~249 entities, all synced to Supabase treasury_companies table.

Sources (in priority order):
1. BitcoinTreasuries.net API (all category endpoints)
2. BitcoinTreasuries.net HTML scrape (fallback — all tables)
3. CoinGecko public companies API (supplement)

Usage:
    from treasury_sync import sync
    sync.run()   # Full sync — call once per scan cycle
"""

import os
import json
import re
import requests
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client
from logger import get_logger

logger = get_logger(__name__)

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# All known BitcoinTreasuries.net API endpoints
BT_API_ENDPOINTS = [
    # Primary entity endpoints
    ("https://api.bitcointreasuries.net/views/entities", "entities", "public_company"),
    ("https://api.bitcointreasuries.net/views/treasuries", "treasuries", "public_company"),
    # Category-specific endpoints
    ("https://api.bitcointreasuries.net/views/public", "public", "public_company"),
    ("https://api.bitcointreasuries.net/views/private", "private", "private_company"),
    ("https://api.bitcointreasuries.net/views/etf", "etf", "etf"),
    ("https://api.bitcointreasuries.net/views/etfs", "etfs", "etf"),
    ("https://api.bitcointreasuries.net/views/funds", "funds", "etf"),
    ("https://api.bitcointreasuries.net/views/defi", "defi", "defi"),
    ("https://api.bitcointreasuries.net/views/countries", "countries", "government"),
    ("https://api.bitcointreasuries.net/views/governments", "governments", "government"),
    # Alternative patterns
    ("https://api.bitcointreasuries.net/entities", "entities_alt", "public_company"),
    ("https://api.bitcointreasuries.net/treasuries", "treasuries_alt", "public_company"),
]

# Sovereign flag mapping
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
}


class TreasurySync:
    """Syncs ALL Bitcoin-holding entities to Supabase."""

    def __init__(self):
        self._last_sync = None
        self._entity_count = 0

    def run(self):
        """Full sync: fetch from all sources, merge, upsert to DB."""
        logger.info("Treasury Sync v2: starting full entity sync...")

        all_entities = {}  # ticker -> entity dict (deduped by ticker)

        # ─── Phase 1: BitcoinTreasuries.net API (all endpoints) ───
        api_entities = self._fetch_all_bt_api_endpoints()
        for e in api_entities:
            key = e["ticker"]
            all_entities[key] = e
        logger.info(f"Treasury Sync: {len(all_entities)} entities from BT API endpoints")

        # ─── Phase 2: BitcoinTreasuries.net HTML scrape (catches anything API missed) ───
        html_entities = self._scrape_all_html_tables()
        new_from_html = 0
        for e in html_entities:
            key = e["ticker"]
            if key not in all_entities:
                all_entities[key] = e
                new_from_html += 1
            else:
                # Update holdings if HTML has more recent data
                if e.get("btc_holdings", 0) > all_entities[key].get("btc_holdings", 0):
                    all_entities[key]["btc_holdings"] = e["btc_holdings"]
        if new_from_html > 0:
            logger.info(f"Treasury Sync: +{new_from_html} new entities from HTML scrape")

        # ─── Phase 3: CoinGecko (supplement with cost basis data) ───
        cg_entities = self._fetch_coingecko()
        new_from_cg = 0
        for e in cg_entities:
            key = e["ticker"]
            if key not in all_entities:
                all_entities[key] = e
                new_from_cg += 1
            else:
                existing = all_entities[key]
                if not existing.get("country") or existing["country"] in ("Unknown", ""):
                    existing["country"] = e.get("country", "")
                if e.get("total_cost_usd", 0) > 0 and existing.get("total_cost_usd", 0) == 0:
                    existing["total_cost_usd"] = e["total_cost_usd"]
                    existing["avg_purchase_price"] = e.get("avg_purchase_price", 0)
        if new_from_cg > 0:
            logger.info(f"Treasury Sync: +{new_from_cg} new entities from CoinGecko")

        if not all_entities:
            logger.warning("Treasury Sync: no entities fetched from any source")
            return 0

        # ─── Upsert all to Supabase ───
        count = self._upsert_all(all_entities)
        self._last_sync = datetime.now()
        self._entity_count = count

        # ─── Update snapshot ───
        self._update_snapshot_count(all_entities)

        # ─── Summary ───
        by_type = {}
        for e in all_entities.values():
            t = e.get("entity_type", "unknown")
            by_type[t] = by_type.get(t, 0) + 1

        type_summary = ", ".join(f"{v} {k}" for k, v in sorted(by_type.items(), key=lambda x: -x[1]))
        logger.info(f"Treasury Sync COMPLETE: {count} entities synced ({type_summary})")
        return count

    # ═══════════════════════════════════════════════════════════════
    # PHASE 1: BitcoinTreasuries.net API (all endpoints)
    # ═══════════════════════════════════════════════════════════════

    def _fetch_all_bt_api_endpoints(self):
        """Hit every known BT API endpoint and merge results."""
        all_entities = []
        seen_tickers = set()
        successful_endpoints = []

        for url, source_name, default_type in BT_API_ENDPOINTS:
            try:
                resp = requests.get(url, headers=HEADERS, timeout=20)
                if resp.status_code != 200:
                    continue

                data = resp.json()
                if not isinstance(data, list) or len(data) == 0:
                    continue

                count_before = len(all_entities)
                for item in data:
                    try:
                        entity = self._parse_bt_entity(item, source_name, default_type)
                        if entity and entity.get("btc_holdings", 0) > 0 and entity["ticker"] not in seen_tickers:
                            all_entities.append(entity)
                            seen_tickers.add(entity["ticker"])
                    except Exception:
                        continue

                new_count = len(all_entities) - count_before
                if new_count > 0:
                    successful_endpoints.append(f"{source_name}({new_count})")
                    logger.debug(f"Treasury Sync: {url} → {new_count} new entities")

            except Exception as e:
                logger.debug(f"Treasury Sync: {url} failed: {e}")
                continue

        if successful_endpoints:
            logger.info(f"Treasury Sync: BT API endpoints: {', '.join(successful_endpoints)}")

        return all_entities

    def _parse_bt_entity(self, item, source, default_type):
        """Parse a single entity from any BT API endpoint."""
        # Extract name
        name = ""
        for field in ["name", "company", "entity", "title", "label"]:
            name = item.get(field, "")
            if name:
                break
        if not name:
            return None

        # Extract ticker
        ticker = ""
        for field in ["symbol", "ticker", "code"]:
            ticker = item.get(field, "")
            if ticker:
                break
        if not ticker:
            ticker = re.sub(r'[^A-Za-z0-9]', '', name.upper()[:10])
        ticker = ticker.upper().strip()
        if not ticker:
            return None

        # Extract BTC holdings
        btc = 0
        for field in ["total_holdings", "btc", "btc_holdings", "holdings", "total_btc", "bitcoin", "amount"]:
            val = item.get(field)
            if val:
                try:
                    btc = int(float(str(val).replace(",", "").replace(" ", "")))
                    if btc > 0:
                        break
                except:
                    pass

        if btc <= 0:
            return None

        # Extract country
        country = item.get("country") or item.get("domicile") or item.get("jurisdiction") or ""

        # Determine entity type
        entity_type = default_type
        is_gov = False
        category = (item.get("category") or item.get("type") or item.get("entity_type") or "").lower()
        name_lower = name.lower()

        if any(kw in category for kw in ["gov", "country", "nation", "sovereign", "state"]):
            entity_type = "government"
            is_gov = True
        elif any(kw in category for kw in ["etf", "fund", "trust", "etp", "exchange"]):
            entity_type = "etf"
        elif any(kw in category for kw in ["private"]):
            entity_type = "private_company"
        elif any(kw in category for kw in ["defi", "protocol", "dao"]):
            entity_type = "defi"
        elif any(kw in name_lower for kw in ["government", " gov", "reserve"]):
            entity_type = "government"
            is_gov = True
        elif any(kw in name_lower for kw in ["etf", "grayscale", "ishares", "fidelity wise", "bitwise", "ark 21", "vaneck", "invesco", "wisdomtree", "valkyrie", "franklin"]):
            entity_type = "etf"
        elif any(kw in name_lower for kw in ["protocol", "defi", "dao", "wrapped", "bridge"]):
            entity_type = "defi"

        # Handle sovereign entities specifically
        if source == "countries" or entity_type == "government":
            is_gov = True
            entity_type = "government"
            # Try to match flag
            for key, (display, gov_ticker, gov_country) in SOVEREIGN_FLAGS.items():
                if key in name_lower:
                    name = display
                    ticker = gov_ticker
                    country = gov_country
                    break
            else:
                if not ticker.endswith("-GOV"):
                    ticker = f"{ticker[:4]}-GOV"

        # Sector mapping
        sector = item.get("sector") or item.get("industry") or ""
        if not sector:
            sector = self._guess_sector(name, entity_type)

        # Cost basis
        cost = 0
        avg_price = 0
        for field in ["total_entry_value_usd", "total_cost_usd", "cost_basis", "entry_value"]:
            val = item.get(field)
            if val:
                try:
                    cost = int(float(str(val).replace(",", "")))
                    if btc > 0 and cost > 0:
                        avg_price = int(cost / btc)
                    break
                except:
                    pass

        return {
            "ticker": ticker,
            "company": name,
            "btc_holdings": btc,
            "avg_purchase_price": avg_price,
            "total_cost_usd": cost,
            "country": country,
            "sector": sector,
            "is_government": is_gov,
            "entity_type": entity_type,
            "data_source": f"bt_{source}",
        }

    def _guess_sector(self, name, entity_type):
        """Guess sector from entity name and type."""
        name_lower = name.lower()
        if entity_type == "government":
            return "Government"
        elif entity_type == "etf":
            return "ETF / Fund"
        elif entity_type == "defi":
            return "DeFi / Protocol"
        elif any(kw in name_lower for kw in ["mining", "miner", "mara", "riot", "cleanspark", "bitfarms", "hut 8", "iris energy", "core scientific"]):
            return "Bitcoin Mining"
        elif any(kw in name_lower for kw in ["exchange", "coinbase", "kraken", "binance"]):
            return "Crypto Exchange"
        elif any(kw in name_lower for kw in ["bank", "financial", "capital"]):
            return "Financial Services"
        elif any(kw in name_lower for kw in ["tesla", "auto"]):
            return "Automotive"
        elif any(kw in name_lower for kw in ["game", "gme"]):
            return "Retail / Gaming"
        elif any(kw in name_lower for kw in ["block", "square", "payment", "pay"]):
            return "Fintech / Payments"
        else:
            return "Technology"

    # ═══════════════════════════════════════════════════════════════
    # PHASE 2: HTML Scrape (catches everything API might miss)
    # ═══════════════════════════════════════════════════════════════

    def _scrape_all_html_tables(self):
        """Scrape ALL tables from BitcoinTreasuries.net HTML."""
        entities = []
        try:
            from bs4 import BeautifulSoup

            # Scrape multiple pages to get all categories
            pages = [
                ("https://bitcointreasuries.net/", "main"),
                ("https://bitcointreasuries.net/entities/public", "public"),
                ("https://bitcointreasuries.net/entities/private", "private"),
                ("https://bitcointreasuries.net/entities/etf", "etf"),
                ("https://bitcointreasuries.net/entities/defi", "defi"),
                ("https://bitcointreasuries.net/entities/countries", "government"),
            ]

            seen_tickers = set()

            for url, category in pages:
                try:
                    resp = requests.get(url, headers=HEADERS, timeout=20)
                    if resp.status_code != 200:
                        continue

                    soup = BeautifulSoup(resp.text, "lxml")
                    tables = soup.find_all("table")

                    for table in tables:
                        rows = table.find_all("tr")[1:]  # skip header
                        for row in rows:
                            cols = row.find_all("td")
                            if len(cols) < 2:
                                continue
                            try:
                                entity = self._parse_html_row(cols, category)
                                if entity and entity["ticker"] not in seen_tickers:
                                    entities.append(entity)
                                    seen_tickers.add(entity["ticker"])
                            except Exception:
                                continue

                except Exception as e:
                    logger.debug(f"Treasury Sync: HTML scrape {url} failed: {e}")
                    continue

            if entities:
                logger.info(f"Treasury Sync: HTML scrape — {len(entities)} entities from {len(pages)} pages")

        except ImportError:
            logger.debug("Treasury Sync: BeautifulSoup not available for HTML scrape")
        except Exception as e:
            logger.warning(f"Treasury Sync: HTML scrape failed: {e}")

        return entities

    def _parse_html_row(self, cols, category):
        """Parse a single HTML table row."""
        # Try to extract name from first column
        name = cols[0].get_text(strip=True)
        if not name:
            return None

        # Remove any rank numbers from beginning
        name = re.sub(r'^\d+\s*', '', name).strip()
        if not name:
            return None

        # Try to extract ticker
        ticker = ""
        if len(cols) > 1:
            potential_ticker = cols[1].get_text(strip=True)
            # Only use as ticker if it looks like one (short, alpha)
            if potential_ticker and len(potential_ticker) <= 12 and re.match(r'^[A-Za-z0-9.\-:]+$', potential_ticker):
                ticker = potential_ticker.upper()

        if not ticker:
            ticker = re.sub(r'[^A-Za-z0-9]', '', name.upper()[:10])

        # Find BTC amount — scan all columns for a number
        btc = 0
        for col in cols[1:]:
            text = col.get_text(strip=True).replace(",", "").replace(" ", "")
            # Look for a reasonably-sized number
            match = re.search(r'([\d.]+)', text)
            if match:
                try:
                    val = float(match.group(1))
                    if 1 <= val <= 50_000_000:  # reasonable BTC range
                        btc = int(val)
                        break
                except:
                    pass

        if btc <= 0:
            return None

        # Map category
        type_map = {
            "main": "public_company", "public": "public_company",
            "private": "private_company", "etf": "etf",
            "defi": "defi", "government": "government",
        }
        entity_type = type_map.get(category, "public_company")
        is_gov = entity_type == "government"

        # Handle government names
        if is_gov:
            for key, (display, gov_ticker, gov_country) in SOVEREIGN_FLAGS.items():
                if key in name.lower():
                    name = display
                    ticker = gov_ticker
                    break

        return {
            "ticker": ticker,
            "company": name,
            "btc_holdings": btc,
            "avg_purchase_price": 0,
            "total_cost_usd": 0,
            "country": "",
            "sector": self._guess_sector(name, entity_type),
            "is_government": is_gov,
            "entity_type": entity_type,
            "data_source": f"bt_html_{category}",
        }

    # ═══════════════════════════════════════════════════════════════
    # PHASE 3: CoinGecko (supplement)
    # ═══════════════════════════════════════════════════════════════

    def _fetch_coingecko(self):
        """Fetch public companies from CoinGecko."""
        entities = []
        try:
            resp = requests.get(
                "https://api.coingecko.com/api/v3/companies/public_treasury/bitcoin",
                headers=HEADERS, timeout=15
            )
            if resp.status_code != 200:
                return []

            data = resp.json()
            for item in data.get("companies", []):
                try:
                    ticker = (item.get("symbol") or "").upper()
                    name = item.get("name") or ""
                    btc = int(item.get("total_holdings", 0))
                    if not ticker or not name or btc <= 0:
                        continue

                    cost = int(float(item.get("total_entry_value_usd", 0) or 0))
                    avg = int(cost / btc) if btc > 0 and cost > 0 else 0

                    entities.append({
                        "ticker": ticker,
                        "company": name,
                        "btc_holdings": btc,
                        "avg_purchase_price": avg,
                        "total_cost_usd": cost,
                        "country": item.get("country", ""),
                        "sector": "Technology",
                        "is_government": False,
                        "entity_type": "public_company",
                        "data_source": "coingecko",
                    })
                except Exception:
                    continue

            if entities:
                logger.info(f"Treasury Sync: CoinGecko — {len(entities)} public companies")

        except Exception as e:
            logger.debug(f"Treasury Sync: CoinGecko failed: {e}")

        return entities

    # ═══════════════════════════════════════════════════════════════
    # DATABASE OPERATIONS
    # ═══════════════════════════════════════════════════════════════

    def _upsert_all(self, all_entities):
        """Upsert all entities to treasury_companies table."""
        count = 0
        errors = 0

        for ticker, entity in all_entities.items():
            try:
                row = {
                    "ticker": ticker,
                    "company": entity["company"][:200],
                    "btc_holdings": entity.get("btc_holdings", 0),
                    "avg_purchase_price": entity.get("avg_purchase_price", 0),
                    "total_cost_usd": entity.get("total_cost_usd", 0),
                    "country": (entity.get("country") or "")[:100],
                    "sector": (entity.get("sector") or "")[:100],
                    "is_government": entity.get("is_government", False),
                    "data_source": entity.get("data_source", "sync"),
                    "last_updated": datetime.now().isoformat(),
                }

                supabase.table("treasury_companies").upsert(
                    row, on_conflict="ticker"
                ).execute()
                count += 1

            except Exception as e:
                errors += 1
                if errors <= 5:
                    logger.debug(f"Treasury Sync: upsert error for {ticker}: {e}")

        if errors > 0:
            logger.warning(f"Treasury Sync: {errors} upsert errors out of {count + errors}")

        return count

    def _update_snapshot_count(self, all_entities):
        """Update today's leaderboard snapshot with accurate totals."""
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            total_btc = sum(e.get("btc_holdings", 0) for e in all_entities.values())
            entity_count = len(all_entities)

            supabase.table("leaderboard_snapshots").upsert({
                "snapshot_date": today,
                "total_btc": total_btc,
                "entity_count": entity_count,
            }, on_conflict="snapshot_date").execute()

            logger.debug(f"Treasury Sync: snapshot — {entity_count} entities, {total_btc:,} BTC")
        except Exception as e:
            logger.debug(f"Treasury Sync: snapshot update failed: {e}")


# ============================================
# GLOBAL INSTANCE
# ============================================
sync = TreasurySync()


# ============================================
# QUICK TEST
# ============================================
if __name__ == "__main__":
    logger.info("Treasury Sync v2 — running full sync test...")
    count = sync.run()
    print(f"\n{'='*60}")
    print(f"  TREASURY SYNC v2 COMPLETE")
    print(f"  {count} entities synced to Supabase")
    print(f"{'='*60}\n")
