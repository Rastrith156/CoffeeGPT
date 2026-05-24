"""
streaming/providers/barchart_provider.py
=========================================
Barchart data provider — scrapes public Barchart futures overview pages.

Responsibilities:
  ✅ Scrape Arabica (KC*0) contracts from Barchart overview page
  ✅ Scrape Robusta (RM*0) contracts from Barchart overview page
  ✅ Extract all contracts with full field set from the page
  ✅ Return front-month (highest volume) as primary RawTickData
  ✅ Store all contracts in raw["contracts"] list
  ✅ Synthetic fallback in dev/test when scraping fails
  ❌ Does NOT normalise data (see streaming/normalizer.py)
  ❌ Does NOT write to Redis
  ❌ Does NOT detect spikes

Scraping strategy (two-step):
  1. GET the overview page to obtain session cookies + XSRF token
  2. Hit the internal core-api/v1/quotes/get JSON endpoint using those
     cookies to retrieve structured contract data
  3. Fall back to parsing the HTML table if the API call fails
  4. Fall back to synthetic data if everything fails

All contract fields: symbol, lastPrice, change, percentChange,
  open, high, low, previousClose, volume, openInterest, tradeTime
"""
from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx
from bs4 import BeautifulSoup

from core.config import settings
from core.logger import bind_context

# ── Constants ────────────────────────────────────────────────────────────────

_ARABICA_URL = "https://www.barchart.com/futures/quotes/KC*0/overview"
_ROBUSTA_URL = "https://www.barchart.com/futures/quotes/RM*0/overview"

_CORE_API_URL = "https://www.barchart.com/proxies/core-api/v1/quotes/get"

# Fields we request from the internal JSON API
_API_FIELDS = (
    "symbol,contractName,lastPrice,netChange,percentChange,"
    "open,high,low,previousClose,volume,openInterest,tradeTime"
)

# Realistic browser User-Agent to avoid bot detection
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


@dataclass
class RawTickData:
    """
    Raw, un-normalised tick data as returned by a data provider.
    Field names deliberately kept as returned by the upstream source.
    """
    market:    str                    # "arabica" | "robusta"
    source:    str                    # "barchart_scrape" | "synthetic"
    raw:       dict[str, Any]         # original response fields
    fetched_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class BarchartProvider:
    """
    HTTP data provider for Arabica and Robusta futures prices.

    Scrapes public Barchart overview pages for both markets.
    Falls back to deterministic synthetic prices in dev/test.

    Instantiate once per FuturesStreamService; the httpx client is reused
    across ticks.
    """

    def __init__(self) -> None:
        self._http: httpx.AsyncClient | None = None
        # Synthetic state (dev/test only)
        self._prev_arabica: float | None = None
        self._prev_robusta: float | None = None
        self._log = bind_context(stream_id="barchart_provider")

    # ── Public fetch interface ────────────────────────────────────────────────

    async def fetch_arabica(self) -> RawTickData | None:
        """
        Fetch all Arabica KC futures contracts from Barchart.
        Returns RawTickData with front-month as primary, all contracts
        in raw["contracts"], or None (production) / synthetic (dev).
        """
        try:
            contracts = await self._scrape_contracts(_ARABICA_URL, symbol_prefix="KC")
            if not contracts:
                self._log.warning("No Arabica contracts scraped — falling back")
                return self._synthetic_arabica()

            front_month = self._pick_front_month(contracts)
            price = self._safe_float(front_month.get("lastPrice"))
            if price <= 0:
                return self._synthetic_arabica()

            self._prev_arabica = price
            self._log.debug(
                "Arabica scraped | symbol={} price={} contracts={}",
                front_month.get("symbol"), price, len(contracts),
            )
            return RawTickData(
                market="arabica",
                source="barchart_scrape",
                raw={
                    "symbol":         str(front_month.get("symbol") or "KC"),
                    "lastPrice":      price,
                    "netChange":      self._safe_float(front_month.get("netChange")),
                    "percentChange":  self._safe_float(front_month.get("percentChange")),
                    "open":           self._safe_float(front_month.get("open")),
                    "high":           self._safe_float(front_month.get("high")),
                    "low":            self._safe_float(front_month.get("low")),
                    "previousClose":  self._safe_float(front_month.get("previousClose")),
                    "volume":         self._safe_int(front_month.get("volume")),
                    "openInterest":   self._safe_int(front_month.get("openInterest")),
                    "tradeTime":      front_month.get("tradeTime"),
                    "contracts":      contracts,
                },
            )
        except Exception as exc:
            self._log.warning("Arabica scrape failed: {}", exc)
            if settings.is_production:
                self._log.warning("No live arabica feed in production — skipping tick")
                return None
            return self._synthetic_arabica()

    async def fetch_robusta(self) -> RawTickData | None:
        """
        Fetch all Robusta RM futures contracts from Barchart.
        Returns RawTickData with front-month as primary, all contracts
        in raw["contracts"], or None (production) / synthetic (dev).
        """
        try:
            contracts = await self._scrape_contracts(_ROBUSTA_URL, symbol_prefix="RM")
            if not contracts:
                self._log.warning("No Robusta contracts scraped — falling back")
                return self._synthetic_robusta()

            front_month = self._pick_front_month(contracts)
            price = self._safe_float(front_month.get("lastPrice"))
            if price <= 0:
                return self._synthetic_robusta()

            self._prev_robusta = price
            self._log.debug(
                "Robusta scraped | symbol={} price={} contracts={}",
                front_month.get("symbol"), price, len(contracts),
            )
            return RawTickData(
                market="robusta",
                source="barchart_scrape",
                raw={
                    "symbol":         str(front_month.get("symbol") or "RM"),
                    "lastPrice":      price,
                    "netChange":      self._safe_float(front_month.get("netChange")),
                    "percentChange":  self._safe_float(front_month.get("percentChange")),
                    "open":           self._safe_float(front_month.get("open")),
                    "high":           self._safe_float(front_month.get("high")),
                    "low":            self._safe_float(front_month.get("low")),
                    "previousClose":  self._safe_float(front_month.get("previousClose")),
                    "volume":         self._safe_int(front_month.get("volume")),
                    "openInterest":   self._safe_int(front_month.get("openInterest")),
                    "tradeTime":      front_month.get("tradeTime"),
                    "contracts":      contracts,
                },
            )
        except Exception as exc:
            self._log.warning("Robusta scrape failed: {}", exc)
            if settings.is_production:
                self._log.warning("No live robusta feed in production — skipping tick")
                return None
            return self._synthetic_robusta()

    async def close(self) -> None:
        if self._http is not None and not self._http.is_closed:
            await self._http.aclose()
            self._http = None

    # ── Core scraping logic ───────────────────────────────────────────────────

    async def _scrape_contracts(
        self, overview_url: str, symbol_prefix: str
    ) -> list[dict[str, Any]]:
        """
        Two-step scrape:
          1. GET the overview page → obtain session cookies + XSRF token
          2. GET the internal core-api JSON endpoint with those cookies
          3. Fall back to parsing the HTML table if the API call fails

        Returns a list of contract dicts, each with the standard field set.
        """
        client = await self._get_client()

        # ── Step 1: Load overview page for cookies/XSRF ───────────────────
        page_resp = await client.get(overview_url, timeout=15.0)
        page_resp.raise_for_status()
        html = page_resp.text

        # Extract XSRF token from meta tag or cookie
        xsrf_token = self._extract_xsrf_token(html, page_resp)

        # Extract symbols from the page HTML (look for symbol patterns)
        symbols = self._extract_symbols_from_html(html, symbol_prefix)

        # ── Step 2: Try internal JSON API ─────────────────────────────────
        if symbols and xsrf_token:
            try:
                contracts = await self._fetch_via_core_api(
                    client, symbols, xsrf_token, page_resp.cookies
                )
                if contracts:
                    return contracts
            except Exception as exc:
                self._log.debug("Core API fallback failed: {} — trying HTML parse", exc)

        # ── Step 3: Fall back to HTML table parsing ───────────────────────
        contracts = self._parse_html_table(html, symbol_prefix)
        if contracts:
            return contracts

        # ── Step 4: Try regex-based JSON extraction from page ─────────────
        contracts = self._extract_json_from_html(html, symbol_prefix)
        return contracts

    async def _fetch_via_core_api(
        self,
        client: httpx.AsyncClient,
        symbols: list[str],
        xsrf_token: str,
        cookies: httpx.Cookies,
    ) -> list[dict[str, Any]]:
        """Hit the internal Barchart core-api with session credentials."""
        headers = {
            "X-XSRF-TOKEN": xsrf_token,
            "Referer": "https://www.barchart.com/futures/quotes/KC*0/overview",
            "Accept": "application/json",
        }
        params = {
            "symbols": ",".join(symbols),
            "fields": _API_FIELDS,
            "raw": "1",
        }
        resp = await client.get(
            _CORE_API_URL,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()

        # The core-api returns {"data": [...]} with quote objects
        results = data.get("data", [])
        if not results:
            return []

        contracts = []
        for item in results:
            raw = item.get("raw", item)
            contracts.append(self._normalize_contract(raw))
        return contracts

    def _extract_xsrf_token(self, html: str, response: httpx.Response) -> str:
        """Extract XSRF token from meta tag or cookies."""
        # Try meta tag first: <meta name="csrf-token" content="...">
        match = re.search(
            r'<meta\s+name=["\']csrf-token["\']\s+content=["\']([^"\']+)["\']',
            html,
        )
        if match:
            return match.group(1)

        # Try XSRF-TOKEN cookie
        for name in ("XSRF-TOKEN", "xsrf-token", "_token"):
            token = response.cookies.get(name)
            if token:
                return token

        return ""

    def _extract_symbols_from_html(
        self, html: str, symbol_prefix: str
    ) -> list[str]:
        """
        Extract futures contract symbols from the page HTML.
        Looks for patterns like KCN26, KCU26, etc. or RMN25, RMU25.
        """
        # Barchart uses 2-letter root + 1-letter month + 2-digit year
        pattern = rf'\b({re.escape(symbol_prefix)}[FGHJKMNQUVXZ]\d{{2}})\b'
        matches = re.findall(pattern, html)
        # Deduplicate while preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for sym in matches:
            if sym not in seen:
                seen.add(sym)
                unique.append(sym)
        return unique

    # ── HTML table parsing fallback ───────────────────────────────────────────

    def _parse_html_table(
        self, html: str, symbol_prefix: str
    ) -> list[dict[str, Any]]:
        """
        Parse the futures overview table from the HTML.
        Barchart renders the data in a <table> or within data-ng/bc-datatable
        components. We look for rows matching known contract symbol patterns.
        """
        soup = BeautifulSoup(html, "html.parser")
        contracts: list[dict[str, Any]] = []

        # Strategy 1: Look for standard HTML tables with contract data
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            if len(rows) < 2:
                continue

            # Detect header row to find column indices
            header_row = rows[0]
            headers = [
                th.get_text(strip=True).lower()
                for th in header_row.find_all(["th", "td"])
            ]
            if not headers:
                continue

            # Map header names to our standard fields
            col_map = self._build_column_map(headers)
            if not col_map:
                continue

            for row in rows[1:]:
                cells = row.find_all(["td", "th"])
                if not cells:
                    continue
                contract = self._extract_row_data(cells, col_map, symbol_prefix)
                if contract:
                    contracts.append(contract)

        # Strategy 2: Look for data in bc-datatable or ng-repeat elements
        if not contracts:
            contracts = self._parse_angular_table(soup, symbol_prefix)

        return contracts

    def _build_column_map(self, headers: list[str]) -> dict[str, int]:
        """Map standardised field names to column indices from header text."""
        field_patterns: dict[str, list[str]] = {
            "symbol":        ["contract", "symbol", "name", "month"],
            "lastPrice":     ["last", "price", "settle", "settlement"],
            "netChange":     ["change", "chg", "net"],
            "percentChange": ["%chg", "% chg", "pct", "%change", "percent"],
            "open":          ["open"],
            "high":          ["high"],
            "low":           ["low"],
            "previousClose": ["prev", "prior", "previous"],
            "volume":        ["vol", "volume"],
            "openInterest":  ["oi", "open int", "openinterest", "open interest"],
            "tradeTime":     ["time", "trade time", "updated"],
        }
        col_map: dict[str, int] = {}
        for field_name, patterns in field_patterns.items():
            for i, header in enumerate(headers):
                if any(p in header for p in patterns):
                    col_map[field_name] = i
                    break
        return col_map

    def _extract_row_data(
        self,
        cells: list,
        col_map: dict[str, int],
        symbol_prefix: str,
    ) -> dict[str, Any] | None:
        """Extract a single contract row from table cells."""
        def cell_text(idx: int) -> str:
            if idx < len(cells):
                # Also check for data-value attribute (Barchart uses these)
                val = cells[idx].get("data-value") or cells[idx].get_text(strip=True)
                return str(val).strip()
            return ""

        # Require at least a symbol/contract column
        sym_idx = col_map.get("symbol", 0)
        sym_text = cell_text(sym_idx)

        # Check if this row contains a valid futures symbol
        sym_match = re.search(
            rf'({re.escape(symbol_prefix)}[FGHJKMNQUVXZ]\d{{2}})',
            sym_text,
        )
        if not sym_match:
            return None

        contract: dict[str, Any] = {"symbol": sym_match.group(1)}
        for field_name, idx in col_map.items():
            if field_name == "symbol":
                continue
            raw_val = cell_text(idx)
            if field_name in ("volume", "openInterest"):
                contract[field_name] = self._safe_int(raw_val)
            elif field_name == "tradeTime":
                contract[field_name] = raw_val or None
            else:
                contract[field_name] = self._safe_float(raw_val)
        return contract

    def _parse_angular_table(
        self, soup: BeautifulSoup, symbol_prefix: str
    ) -> list[dict[str, Any]]:
        """
        Fall back to parsing data from Angular/bc-datatable components
        or any element with data attributes containing contract info.
        """
        contracts: list[dict[str, Any]] = []

        # Look for elements with data-symbol or similar attributes
        for elem in soup.find_all(attrs={"data-symbol": True}):
            sym = elem.get("data-symbol", "")
            if sym.startswith(symbol_prefix):
                contract: dict[str, Any] = {"symbol": sym}
                # Try to extract price from nearby elements
                for attr in ("data-last", "data-price", "data-last-price"):
                    val = elem.get(attr)
                    if val:
                        contract["lastPrice"] = self._safe_float(val)
                        break
                if "lastPrice" in contract:
                    contracts.append(contract)

        return contracts

    def _extract_json_from_html(
        self, html: str, symbol_prefix: str
    ) -> list[dict[str, Any]]:
        """
        Last-resort: extract contract data from embedded JSON in the page.
        Barchart sometimes includes quote data in inline <script> blocks.
        """
        contracts: list[dict[str, Any]] = []

        # Look for JSON objects containing our symbol prefix and lastPrice
        # Pattern: {..., "symbol": "KCN26", "lastPrice": 123.45, ...}
        json_pattern = re.compile(
            r'\{[^{}]*"symbol"\s*:\s*"('
            + re.escape(symbol_prefix)
            + r'[FGHJKMNQUVXZ]\d{2})"[^{}]*"lastPrice"\s*:\s*([\d.]+)[^{}]*\}'
        )
        for match in json_pattern.finditer(html):
            try:
                # Try to parse the full JSON object
                raw_json = match.group(0)
                contract = self._normalize_contract(self._parse_json_fragment(raw_json))
                if contract.get("symbol"):
                    contracts.append(contract)
            except Exception:
                continue

        return contracts

    def _parse_json_fragment(self, fragment: str) -> dict[str, Any]:
        """Safely parse a JSON fragment from HTML."""
        import json
        try:
            return json.loads(fragment)
        except json.JSONDecodeError:
            # Try to fix common issues (trailing commas, etc.)
            cleaned = re.sub(r',\s*}', '}', fragment)
            cleaned = re.sub(r',\s*]', ']', cleaned)
            return json.loads(cleaned)

    def _normalize_contract(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Normalize a contract dict to our standard field set."""
        return {
            "symbol":        str(raw.get("symbol", "")),
            "lastPrice":     self._safe_float(raw.get("lastPrice")),
            "netChange":     self._safe_float(
                raw.get("netChange") or raw.get("change")
            ),
            "percentChange": self._safe_float(raw.get("percentChange")),
            "open":          self._safe_float(raw.get("open")),
            "high":          self._safe_float(raw.get("high")),
            "low":           self._safe_float(raw.get("low")),
            "previousClose": self._safe_float(raw.get("previousClose")),
            "volume":        self._safe_int(raw.get("volume")),
            "openInterest":  self._safe_int(raw.get("openInterest")),
            "tradeTime":     raw.get("tradeTime"),
        }

    def _pick_front_month(self, contracts: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Select the front-month contract — the one with the highest volume.
        If all volumes are None/0, pick the first contract (nearest expiry).
        """
        valid = [c for c in contracts if (self._safe_int(c.get("volume")) or 0) > 0]
        if valid:
            return max(valid, key=lambda c: self._safe_int(c.get("volume")) or 0)
        return contracts[0]

    # ── Synthetic fallbacks (dev/test only) ───────────────────────────────────

    def _synthetic_arabica(self) -> RawTickData:
        t    = datetime.now(timezone.utc)
        base = 1.86 + math.sin(t.minute / 10.0) * 0.015 + random.gauss(0, 0.003)
        prev = self._prev_arabica or base
        self._prev_arabica = base
        pct  = ((base - prev) / prev * 100) if prev > 0 else 0.0
        return RawTickData(
            market="arabica",
            source="synthetic",
            raw={
                "symbol":        "KC",
                "lastPrice":     round(base, 4),
                "netChange":     round(base - prev, 4),
                "percentChange": round(pct, 2),
                "volume":        random.randint(20_000, 50_000),
            },
        )

    def _synthetic_robusta(self) -> RawTickData:
        t    = datetime.now(timezone.utc)
        base = 2385.0 + math.cos(t.minute / 12.0) * 18.0 + random.gauss(0, 4.0)
        prev = self._prev_robusta or base
        self._prev_robusta = base
        pct  = ((base - prev) / prev * 100) if prev > 0 else 0.0
        return RawTickData(
            market="robusta",
            source="synthetic",
            raw={
                "symbol":        "RM",
                "lastPrice":     round(base, 2),
                "netChange":     round(base - prev, 2),
                "percentChange": round(pct, 2),
                "volume":        random.randint(5_000, 20_000),
            },
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                follow_redirects=True,
                headers={
                    "User-Agent": _USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept-Encoding": "gzip, deflate, br",
                    "Connection": "keep-alive",
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "none",
                    "Sec-Fetch-User": "?1",
                    "Upgrade-Insecure-Requests": "1",
                },
                timeout=15.0,
            )
        return self._http

    @staticmethod
    def _safe_float(value: Any) -> float:
        try:
            return float(str(value or 0).replace(",", "").replace("%", "").strip())
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(float(str(value).replace(",", "").strip()))
        except (TypeError, ValueError):
            return None
