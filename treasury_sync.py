"""
treasury_sync.py — Master Data Sync Engine v3.1
-------------------------------------------------
Fetches ALL Bitcoin-holding entities from BitcoinTreasuries.net:

  Page                     URL                          Expected
  ───────────────────────────────────────────────────────────────
  Public Companies         /                            ~100
  Private Companies        /private-companies           ~74
  Government Entities      /governments                 ~16
  ETFs and Exchanges       /etfs-and-exchanges          ~49
  DeFi and Other           /defi-and-other              ~17
                                                        ─────
                                                        ~256 total

Supplements with CoinGecko API for cost basis data.

Usage:
    from treasury_sync import sync
    sync.run()
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
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

BT_PAGES = [
    {"url": "https://bitcointreasuries.net/", "category": "public_company", "label": "Public Companies", "is_government": False},
    {"url": "https://bitcointreasuries.net/private-companies", "category": "private_company", "label": "Private Companies", "is_government": False},
    {"url": "https://bitcointreasuries.net/governments", "category": "government", "label": "Government Entities", "is_government": True},
    {"url": "https://bitcointreasuries.net/etfs-and-exchanges", "category": "etf", "label": "ETFs and Exchanges", "is_government": False},
    {"url": "https://bitcointreasuries.net/defi-and-other", "category": "defi", "label": "DeFi and Other", "is_government": False},
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


class TreasurySync:

    def __init__(self):
        self._last_sync = None
        self._entity_count = 0

    def run(self):
        logger.info("Treasury Sync v3.1: starting full entity sync...")

        all_entities = {}

        # ─── Phase 1: Scrape all 5 BitcoinTreasuries.net pages ───
        for page in BT_PAGES:
            try:
                entities = self._scrape_page(page)
                new = 0
                for e in entities:
                    key = e["ticker"]
                    if key not in all_entities:
                        all_entities[key] = e
                        new += 1
                    elif e.get("btc_holdings", 0) > all_entities[key].get("btc_holdings", 0):
                        all_entities[key]["btc_holdings"] = e["btc_holdings"]
                logger.info(f"  {page['label']:25s} -> {len(entities):>4} scraped, {new:>4} new")
            except Exception as e:
                logger.warning(f"  {page['label']:25s} -> FAILED: {e}")

        bt_total = len(all_entities)
        logger.info(f"Treasury Sync: {bt_total} entities from BitcoinTreasuries.net")

        # ─── Phase 2: CoinGecko supplement ───
        try:
            cg_entities = self._fetch_coingecko()
            new_cg = 0
            for e in cg_entities:
                key = e["ticker"]
                if key not in all_entities:
                    all_entities[key] = e
                    new_cg += 1
                else:
                    existing = all_entities[key]
                    if not existing.get("country") or existing["country"] in ("", "Unknown"):
                        existing["country"] = e.get("country", "")
                    if e.get("total_cost_usd", 0) > 0 and existing.get("total_cost_usd", 0) == 0:
                        existing["total_cost_usd"] = e["total_cost_usd"]
                        existing["avg_purchase_price"] = e.get("avg_purchase_price", 0)
            if new_cg > 0:
                logger.info(f"  CoinGecko supplement    -> +{new_cg} new entities")
        except Exception as e:
            logger.debug(f"  CoinGecko failed: {e}")

        if not all_entities:
            logger.warning("Treasury Sync: no entities fetched")
            return 0

        # ─── Phase 3: Upsert ───
        count = self._upsert_all(all_entities)
        self._last_sync = datetime.now()
        self._entity_count = count

        # ─── Phase 4: Update snapshot ───
        self._update_snapshot(all_entities)

        # ─── Summary ───
        by_type = {}
        for e in all_entities.values():
            t = e.get("entity_type", "unknown")
            by_type[t] = by_type.get(t, 0) + 1
        type_str = ", ".join(f"{v} {k}" for k, v in sorted(by_type.items(), key=lambda x: -x[1]))
        total_btc = sum(e.get("btc_holdings", 0) for e in all_entities.values())
        logger.info(f"Treasury Sync COMPLETE: {count} entities, {total_btc:,} BTC ({type_str})")
        return count

    # ═══════════════════════════════════════════════════════════
    # SCRAPING
    # ═══════════════════════════════════════════════════════════

    def _scrape_page(self, page):
        """Scrape all tables from a BT page."""
        entities = []
        resp = requests.get(page["url"], headers=HEADERS, timeout=20)
        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        tables = soup.find_all("table")

        for table in tables:
            rows = table.find_all("tr")
            if len(rows) < 2:
                continue

            # Detect table format from first data row
            first_row_cols = rows[1].find_all("td")
            first_texts = [td.get_text(strip=True) for td in first_row_cols]
            fmt = self._detect_format(first_texts)

            for row in rows[1:]:
                cols = row.find_all("td")
                if len(cols) < 3:
                    continue
                try:
                    entity = self._parse_row_positional(cols, fmt, page)
                    if entity and entity.get("btc_holdings", 0) > 0:
                        entities.append(entity)
                except Exception:
                    continue

        return entities

    def _detect_format(self, texts):
        """Detect which table format we're dealing with.

        Format A (category pages: private, etf, defi, gov):
            col[0]=rank, col[1]=flag, col[2]=name, col[3]=₿btc, col[4]=$usd, col[5]=%supply
            Headers: ['#', 'Name', 'Bitcoin', 'In USD', '/21M']

        Format B (main page tables 0-2):
            col[0]=rank, col[1]=name, col[2]=flag, col[3]=ticker, col[4]=btc_number, col[5]=ratio
            Headers: ['Rank', '', 'Country flag', 'Ticker', 'Bitcoin']

        Format C (main page table 3):
            col[0]=rank, col[1]=flag, col[2]=nameTickerBuy, col[3]=₿btc, col[4]=$usd, col[5]=$cap, col[6]=$hidden
        """
        if len(texts) < 4:
            return "unknown"

        # Check if col[3] starts with ₿ (bitcoin symbol)
        col3 = texts[3] if len(texts) > 3 else ""
        has_btc_symbol = "₿" in col3 or "\u20bf" in col3

        # Check if col[1] looks like a short flag (non-ASCII, short)
        col1 = texts[1]
        col1_is_flag = len(col1) <= 6 and not col1.isascii()

        if has_btc_symbol and col1_is_flag:
            # Could be format A or C
            # Format A: col[2] is a clean name
            # Format C: col[2] has ticker embedded like "StrategyMSTRBuy"
            col2 = texts[2]
            if "$" in (texts[4] if len(texts) > 4 else ""):
                # Both A and C have $ in col[4]
                # In format C, col[2] tends to have uppercase letters embedded
                return "A"  # Treat the same — positional parsing handles both
            return "A"

        # Format B: col[1] is the name (long text), col[3] is ticker (short)
        if not col1_is_flag and len(col1) > 3:
            return "B"

        return "A"  # Default

    def _parse_row_positional(self, cols, fmt, page):
        """Parse row based on detected format."""
        texts = [td.get_text(strip=True) for td in cols]

        if fmt == "B":
            return self._parse_format_b(texts, page)
        else:
            return self._parse_format_a(texts, page)

    def _parse_format_a(self, texts, page):
        """Parse format A/C: [rank, flag, name, ₿btc, $usd, ...]
        Used by: category pages + main page table 3.
        """
        if len(texts) < 4:
            return None

        # col[0] = rank (skip)
        # col[1] = flag (skip)
        # col[2] = name (may have ticker embedded)
        # col[3] = ₿xxx,xxx

        raw_name = texts[2]
        if not raw_name:
            return None

        # Extract BTC from col[3]
        btc = self._extract_btc(texts[3])

        # If col[3] didn't have BTC, try other columns
        if btc <= 0:
            for t in texts[3:]:
                btc = self._extract_btc(t)
                if btc > 0:
                    break

        if btc <= 0:
            return None

        # Parse name and ticker
        name, ticker = self._extract_name_ticker(raw_name)

        if not name:
            return None
        if not ticker:
            ticker = re.sub(r'[^A-Za-z0-9]', '', name.upper()[:10])
        if not ticker:
            return None

        # Handle governments
        is_gov = page["is_government"]
        entity_type = page["category"]

        if is_gov:
            for key, (display, gov_ticker, country) in SOVEREIGN_FLAGS.items():
                if key in name.lower():
                    name = display
                    ticker = gov_ticker
                    break
            else:
                if not ticker.endswith("-GOV"):
                    ticker = f"{ticker[:5]}-GOV"

        return {
            "ticker": ticker.upper(),
            "company": name[:200],
            "btc_holdings": btc,
            "avg_purchase_price": 0,
            "total_cost_usd": 0,
            "country": self._get_country(name, is_gov),
            "sector": self._guess_sector(name, entity_type),
            "is_government": is_gov,
            "entity_type": entity_type,
            "data_source": f"bt_{page['category']}",
        }

    def _parse_format_b(self, texts, page):
        """Parse format B: [rank, name, flag, ticker, btc_number, ratio]
        Used by: main page tables 0-2.
        """
        if len(texts) < 5:
            return None

        # col[1] = company name
        # col[3] = ticker
        # col[4] = btc number (plain, no ₿)

        name = texts[1]
        ticker = texts[3] if len(texts) > 3 else ""

        if not name:
            return None

        # BTC is in col[4] — plain number with commas
        btc_text = texts[4] if len(texts) > 4 else "0"
        btc_clean = btc_text.replace(",", "").replace(" ", "")
        btc_clean = re.sub(r'[^\d.]', '', btc_clean)
        btc = 0
        if btc_clean:
            try:
                btc = int(float(btc_clean))
            except:
                pass

        if btc <= 0:
            return None

        if not ticker:
            ticker = re.sub(r'[^A-Za-z0-9]', '', name.upper()[:10])

        return {
            "ticker": ticker.upper(),
            "company": name[:200],
            "btc_holdings": btc,
            "avg_purchase_price": 0,
            "total_cost_usd": 0,
            "country": "",
            "sector": self._guess_sector(name, page["category"]),
            "is_government": False,
            "entity_type": "public_company",
            "data_source": "bt_public_top",
        }

    def _extract_btc(self, text):
        """Extract BTC amount from text like '₿762,099' or '₿164,000'."""
        if not text:
            return 0
        # Remove ₿ symbol and commas
        clean = text.replace("₿", "").replace("\u20bf", "").replace(",", "").replace(" ", "")
        clean = re.sub(r'[^\d.]', '', clean)
        if clean:
            try:
                return int(float(clean))
            except:
                pass
        return 0

    def _extract_name_ticker(self, raw):
        """Extract name and ticker from strings like 'Block.one' or 'StrategyMSTRBuy'."""
        if not raw:
            return "", ""

        # Check for embedded ticker pattern: "CompanyNameTICKERBuy" or "CompanyNameTICKER"
        # Look for transition from lowercase/space to UPPERCASE at end
        match = re.search(r'^(.+?)([A-Z][A-Z0-9]{1,7})(Buy|Sel)?$', raw)
        if match:
            name_part = match.group(1).strip()
            ticker_part = match.group(2)
            # Make sure name_part is reasonable (not just one char)
            if len(name_part) >= 2:
                return name_part, ticker_part

        # No embedded ticker — name is the whole string
        return raw.strip(), ""

    def _get_country(self, name, is_gov):
        """Try to get country code."""
        if is_gov:
            for key, (_, _, country) in SOVEREIGN_FLAGS.items():
                if key in name.lower():
                    return country
        return ""

    def _guess_sector(self, name, entity_type):
        n = name.lower()
        if entity_type == "government":
            return "Government"
        if entity_type == "etf":
            return "ETF / Fund"
        if entity_type == "defi":
            return "DeFi / Protocol"
        if entity_type == "private_company":
            return "Private Company"
        if any(kw in n for kw in ["mining", "miner", "mara", "riot", "cleanspark", "bitfarms", "hut 8", "iris", "core scientific", "bitfufu", "canaan"]):
            return "Bitcoin Mining"
        if any(kw in n for kw in ["exchange", "coinbase", "kraken", "binance"]):
            return "Crypto Exchange"
        if any(kw in n for kw in ["bank", "financial", "capital"]):
            return "Financial Services"
        if any(kw in n for kw in ["tesla"]):
            return "Automotive"
        if any(kw in n for kw in ["block", "square", "payment"]):
            return "Fintech / Payments"
        return "Technology"

    # ═══════════════════════════════════════════════════════════
    # COINGECKO
    # ═══════════════════════════════════════════════════════════

    def _fetch_coingecko(self):
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
                        "ticker": ticker, "company": name, "btc_holdings": btc,
                        "avg_purchase_price": avg, "total_cost_usd": cost,
                        "country": item.get("country", ""), "sector": "Technology",
                        "is_government": False, "entity_type": "public_company",
                        "data_source": "coingecko",
                    })
                except Exception:
                    continue
            if entities:
                logger.info(f"  CoinGecko               -> {len(entities)} public companies (with cost basis)")
        except Exception as e:
            logger.debug(f"CoinGecko failed: {e}")
        return entities

    # ═══════════════════════════════════════════════════════════
    # DATABASE
    # ═══════════════════════════════════════════════════════════

    def _upsert_all(self, all_entities):
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
                supabase.table("treasury_companies").upsert(row, on_conflict="ticker").execute()
                count += 1
            except Exception as e:
                errors += 1
                if errors <= 3:
                    logger.debug(f"Upsert error {ticker}: {e}")
        if errors > 0:
            logger.warning(f"Treasury Sync: {errors} upsert errors")
        return count

    def _update_snapshot(self, all_entities):
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            total_btc = sum(e.get("btc_holdings", 0) for e in all_entities.values())
            supabase.table("leaderboard_snapshots").upsert({
                "snapshot_date": today,
                "total_btc": total_btc,
                "entity_count": len(all_entities),
            }, on_conflict="snapshot_date").execute()
        except Exception as e:
            logger.debug(f"Snapshot update failed: {e}")


sync = TreasurySync()

if __name__ == "__main__":
    logger.info("Treasury Sync v3.1 — full sync...")
    count = sync.run()
    print(f"\n{'='*60}")
    print(f"  TREASURY SYNC v3.1 COMPLETE")
    print(f"  {count} entities synced to Supabase")
    print(f"{'='*60}\n")
