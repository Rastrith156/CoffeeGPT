"""
streaming/providers/barchart_provider.py
=========================================
Barchart data provider — ONLY responsible for HTTP fetch.

Responsibilities:
  ✅ Fetch raw arabica quote from Barchart ondemand API
  ✅ Fetch raw robusta price from Barchart overview page (scrape fallback)
  ✅ Synthetic fallback in dev/test
  ❌ Does NOT normalise data (see streaming/normalizer.py)
  ❌ Does NOT write to Redis
  ❌ Does NOT detect spikes

Design: provider is stateless for price data, but tracks synthetic
state (prev_price) for deterministic noise during dev/test.

All URLs and API keys come from settings — zero hardcoded values.
"""
from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

from core.config import settings
from core.logger import bind_context


@dataclass
class RawTickData:
    """
    Raw, un-normalised tick data as returned by a data provider.
    Field names deliberately kept as returned by the upstream source.
    """
    market:    str                    # "arabica" | "robusta"
    source:    str                    # "barchart_live" | "barchart_overview" | "synthetic"
    raw:       dict[str, Any]         # original response fields
    fetched_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class BarchartProvider:
    """
    HTTP data provider for Arabica and Robusta futures prices.

    Fetches from Barchart ondemand API (Arabica) and Barchart overview
    page (Robusta). Falls back to deterministic synthetic prices in dev/test.

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
        Fetch the most liquid Arabica KC futures contract from Barchart.
        Returns RawTickData or None (production) / synthetic (dev).
        """
        client = await self._get_client()
        try:
            response = await client.get(
                settings.barchart_quote_url,
                params={
                    "apikey":  settings.barchart_api_key,
                    "symbols": settings.barchart_arabica_symbols,
                    "fields":  "settlement,previousClose,volume,previousOpenInterest,netChange,percentChange",
                },
                timeout=10.0,
            )
            response.raise_for_status()
            results = response.json().get("results") or []
            if not results:
                return self._synthetic_arabica()

            # Pick most liquid contract
            quote = max(
                [r for r in results
                 if str(r.get("symbol", "")).startswith("KC")
                 and self._safe_float(r.get("previousOpenInterest")) > 0]
                or results,
                key=lambda r: (
                    self._safe_float(r.get("previousOpenInterest")),
                    self._safe_float(r.get("volume")),
                ),
            )
            price = self._best_price(quote)
            if price <= 0:
                return self._synthetic_arabica()

            self._prev_arabica = price
            self._log.debug("Arabica fetched | symbol={} price={}", quote.get("symbol"), price)
            return RawTickData(
                market="arabica",
                source="barchart_live",
                raw={
                    "symbol":              str(quote.get("symbol") or "KC"),
                    "lastPrice":           price,
                    "netChange":           self._safe_float(quote.get("netChange")),
                    "percentChange":       self._safe_float(quote.get("percentChange")),
                    "volume":              self._safe_int(quote.get("volume")),
                    "previousOpenInterest": self._safe_int(quote.get("previousOpenInterest")),
                },
            )
        except Exception as exc:
            self._log.warning("Arabica fetch failed: {}", exc)
            if settings.is_production:
                self._log.warning("No live arabica feed in production — skipping tick")
                return None
            return self._synthetic_arabica()

    async def fetch_robusta(self) -> RawTickData | None:
        """
        Fetch Robusta RM futures price from Barchart overview page.
        Price is parsed from embedded JSON in the HTML response.
        Returns RawTickData or None (production) / synthetic (dev).
        """
        client = await self._get_client()
        try:
            response = await client.get(settings.barchart_overview_url, timeout=10.0)
            response.raise_for_status()
            price = self._parse_robusta_html(response.text)
            if price <= 0:
                return self._synthetic_robusta()

            self._prev_robusta = price
            self._log.debug("Robusta fetched | price={}", price)
            return RawTickData(
                market="robusta",
                source="barchart_overview",
                raw={
                    "symbol":        "RM",
                    "lastPrice":     price,
                    "netChange":     0.0,
                    "percentChange": 0.0,
                    "volume":        None,
                },
            )
        except Exception as exc:
            self._log.warning("Robusta fetch failed: {}", exc)
            if settings.is_production:
                self._log.warning("No live robusta feed in production — skipping tick")
                return None
            return self._synthetic_robusta()

    async def close(self) -> None:
        if self._http is not None and not self._http.is_closed:
            await self._http.aclose()
            self._http = None

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
                headers={"User-Agent": settings.stream_user_agent},
                timeout=15.0,
            )
        return self._http

    def _parse_robusta_html(self, html: str) -> float:
        patterns = [
            r'"lastPrice"\s*:\s*([\d.]+)',
            r'"close"\s*:\s*([\d.]+)',
            r'class="price"[^>]*>\s*([\d,]+(?:\.\d+)?)',
        ]
        for pattern in patterns:
            m = re.search(pattern, html)
            if m:
                try:
                    return float(m.group(1).replace(",", ""))
                except ValueError:
                    continue
        return 0.0

    def _best_price(self, quote: dict) -> float:
        for field_name in ("lastPrice", "settlement", "close", "previousClose"):
            val = self._safe_float(quote.get(field_name))
            if val > 0:
                return val
        return 0.0

    @staticmethod
    def _safe_float(value: Any) -> float:
        try:
            return float(str(value or 0).replace(",", "").strip())
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(float(str(value).replace(",", "")))
        except (TypeError, ValueError):
            return None
