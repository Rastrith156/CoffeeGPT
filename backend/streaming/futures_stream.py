"""
streaming/futures_stream.py
===========================
STEP 2 — Live Futures Stream Service

Architecture:
    Live Feed (Barchart/Yahoo/synthetic)
         ↓
    Normalizer
         ↓
    Redis hot cache
         ↓
    Alert Engine

Streams Arabica and Robusta prices continuously.
Falls back gracefully when live feeds are unavailable.
"""
from __future__ import annotations

import asyncio
import math
import random
from datetime import datetime, timezone

import httpx

from core.config import settings
from core.logger import logger
from streaming.redis_cache import RedisMarketCache

# ─── Poll intervals ─────────────────────────────────────────────────────────
STREAM_INTERVAL_SECONDS: int = 30   # poll every 30 s
SPIKE_THRESHOLD_PCT: float  = 2.0   # % move triggers a spike alert


class FuturesStreamService:
    """
    Continuously polls live futures data, normalises it,
    writes it to Redis, and fires alerts through the alert engine.

    Call  start()  as an asyncio task from the runtime container.
    """

    BARCHART_QUOTE_URL  = "https://ondemand.websol.barchart.com/getQuote.json"
    BARCHART_API_KEY    = "2d8b3b803594b13e02a7dc827f4a63f8"
    ARABICA_SYMBOLS     = "KCY00,KC*1"
    ROBUSTA_OVERVIEW_URL = "https://www.barchart.com/futures/quotes/RM*0/overview"
    USER_AGENT = "Mozilla/5.0 (compatible; CoffeeGPT-Stream/1.0)"

    def __init__(self, cache: RedisMarketCache | None = None) -> None:
        self._cache      = cache or RedisMarketCache()
        self._prev_arabica_price: float | None = None
        self._prev_robusta_price: float | None = None
        self._running    = False
        self._http: httpx.AsyncClient | None = None

    # ─── Public API ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Run forever — designed to be launched as an asyncio.Task."""
        self._running = True
        logger.info("FuturesStreamService started (interval={}s)", STREAM_INTERVAL_SECONDS)
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("FuturesStreamService tick error: {}", exc)
            await asyncio.sleep(STREAM_INTERVAL_SECONDS)

    async def stop(self) -> None:
        self._running = False
        if self._http is not None:
            await self._http.aclose()

    # ─── Core tick ───────────────────────────────────────────────────────────

    async def _tick(self) -> None:
        arabica = await self._fetch_arabica()
        robusta = await self._fetch_robusta()

        # Write to Redis
        if arabica:
            await self._cache.update_arabica(
                price=arabica["price"],
                change_percent=arabica["change_percent"],
                volume=arabica.get("volume"),
            )
        if robusta:
            await self._cache.update_robusta(
                price=robusta["price"],
                change_percent=robusta["change_percent"],
                volume=robusta.get("volume"),
            )

        # Combined volatility
        a_vol = arabica.get("volatility_pct", 0.0) if arabica else 0.0
        r_vol = robusta.get("volatility_pct", 0.0) if robusta else 0.0
        await self._cache.update_volatility(a_vol, r_vol)

        # Compound market state
        state = self._build_market_state(arabica, robusta)
        await self._cache.update_market_state(state)

        # Spike detection
        if arabica:
            await self._detect_spike("arabica", arabica)
        if robusta:
            await self._detect_spike("robusta", robusta)

        logger.debug(
            "FuturesStream tick | arabica={} robusta={}",
            arabica and arabica["price"],
            robusta and robusta["price"],
        )

    # ─── Live fetchers ───────────────────────────────────────────────────────

    async def _fetch_arabica(self) -> dict | None:
        client = await self._http_client()
        try:
            response = await client.get(
                self.BARCHART_QUOTE_URL,
                params={
                    "apikey": self.BARCHART_API_KEY,
                    "symbols": self.ARABICA_SYMBOLS,
                    "fields": "settlement,previousClose,volume,previousOpenInterest",
                },
                timeout=10,
            )
            response.raise_for_status()
            results = response.json().get("results") or []
            if not results:
                return self._synthetic_arabica()

            quote = max(
                [r for r in results if str(r.get("symbol", "")).startswith("KC") and self._safe_float(r.get("previousOpenInterest")) > 0]
                or results,
                key=lambda r: (self._safe_float(r.get("previousOpenInterest")), self._safe_float(r.get("volume"))),
            )
            price = self._quote_price(quote)
            if price <= 0:
                return self._synthetic_arabica()

            return {
                "market": "arabica",
                "symbol": str(quote.get("symbol") or "KC"),
                "price": price,
                "change": self._safe_float(quote.get("netChange")),
                "change_percent": self._safe_float(quote.get("percentChange")),
                "volume": self._safe_int(quote.get("volume")),
                "volatility_pct": 0.0,  # computed in market monitor
                "currency": "US cents/lb",
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "source": "barchart_live",
            }
        except Exception as exc:
            logger.warning("Arabica live fetch failed: {} — using synthetic", exc)
            return self._synthetic_arabica()

    async def _fetch_robusta(self) -> dict | None:
        client = await self._http_client()
        try:
            response = await client.get(self.ROBUSTA_OVERVIEW_URL, timeout=10)
            response.raise_for_status()
            price = self._parse_robusta_price(response.text)
            if price <= 0:
                return self._synthetic_robusta()
            return {
                "market": "robusta",
                "symbol": "RM",
                "price": price,
                "change": 0.0,
                "change_percent": 0.0,
                "volume": None,
                "volatility_pct": 0.0,
                "currency": "USD/tonne",
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "source": "barchart_overview",
            }
        except Exception as exc:
            logger.warning("Robusta live fetch failed: {} — using synthetic", exc)
            return self._synthetic_robusta()

    # ─── Spike detection ─────────────────────────────────────────────────────

    async def _detect_spike(self, market: str, data: dict) -> None:
        change_pct = abs(self._safe_float(data.get("change_percent")))
        if change_pct < SPIKE_THRESHOLD_PCT:
            return

        spike = {
            "market": market,
            "price": data["price"],
            "change_percent": data["change_percent"],
            "threshold_pct": SPIKE_THRESHOLD_PCT,
            "severity": "high" if change_pct >= 4.0 else "medium",
            "message": (
                f"⚡ {market.title()} futures spike detected: "
                f"{data['change_percent']:+.2f}% at {data['price']} {data.get('currency', '')}"
            ),
        }
        await self._cache.push_spike(spike)
        await self._cache.push_alert({
            "type": "price_spike",
            "market": market,
            **spike,
        })
        logger.info("Spike alert | {} {:.2f}%", market, data["change_percent"])

    # ─── Synthetic fallbacks ─────────────────────────────────────────────────

    def _synthetic_arabica(self) -> dict:
        """Deterministic synthetic price with micro-volatility."""
        t = datetime.now(timezone.utc)
        base = 1.86 + math.sin(t.minute / 10.0) * 0.015 + random.gauss(0, 0.003)
        prev = self._prev_arabica_price or base
        change = base - prev
        change_pct = ((base - prev) / prev) * 100 if prev > 0 else 0.0
        self._prev_arabica_price = base
        return {
            "market": "arabica",
            "symbol": "KC",
            "price": round(base, 4),
            "change": round(change, 4),
            "change_percent": round(change_pct, 2),
            "volume": random.randint(20000, 50000),
            "volatility_pct": round(abs(change_pct) * 0.5, 2),
            "currency": "US cents/lb",
            "updated_at": t.isoformat(),
            "source": "synthetic_stream",
        }

    def _synthetic_robusta(self) -> dict:
        t = datetime.now(timezone.utc)
        base = 2385.0 + math.cos(t.minute / 12.0) * 18.0 + random.gauss(0, 4.0)
        prev = self._prev_robusta_price or base
        change = base - prev
        change_pct = ((base - prev) / prev) * 100 if prev > 0 else 0.0
        self._prev_robusta_price = base
        return {
            "market": "robusta",
            "symbol": "RM",
            "price": round(base, 2),
            "change": round(change, 2),
            "change_percent": round(change_pct, 2),
            "volume": random.randint(5000, 20000),
            "volatility_pct": round(abs(change_pct) * 0.5, 2),
            "currency": "USD/tonne",
            "updated_at": t.isoformat(),
            "source": "synthetic_stream",
        }

    # ─── Helpers ─────────────────────────────────────────────────────────────

    async def _http_client(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                follow_redirects=True,
                headers={"User-Agent": self.USER_AGENT},
            )
        return self._http

    def _build_market_state(self, arabica: dict | None, robusta: dict | None) -> dict:
        """Composite market state written to coffee:live:market_state"""
        a_price = arabica["price"] if arabica else 0.0
        r_price = robusta["price"] if robusta else 0.0
        a_change = arabica["change_percent"] if arabica else 0.0
        r_change = robusta["change_percent"] if robusta else 0.0
        avg_change = (a_change + r_change) / 2 if arabica and robusta else a_change or r_change
        sentiment = (
            "strongly_bullish" if avg_change >= 3.0
            else "bullish"       if avg_change >= 1.0
            else "strongly_bearish" if avg_change <= -3.0
            else "bearish"       if avg_change <= -1.0
            else "neutral"
        )
        return {
            "arabica_price": a_price,
            "arabica_change_pct": a_change,
            "arabica_currency": arabica.get("currency", "US cents/lb") if arabica else "US cents/lb",
            "robusta_price": r_price,
            "robusta_change_pct": r_change,
            "robusta_currency": robusta.get("currency", "USD/tonne") if robusta else "USD/tonne",
            "market_sentiment": sentiment,
            "stream_sources": list({
                (arabica or {}).get("source", "synthetic"),
                (robusta or {}).get("source", "synthetic"),
            }),
        }

    def _parse_robusta_price(self, html: str) -> float:
        """Best-effort parse of Robusta price from Barchart overview page."""
        import re
        patterns = [
            r'"lastPrice"\s*:\s*([\d.]+)',
            r'"close"\s*:\s*([\d.]+)',
            r'class="price"\s*[^>]*>\s*([\d,]+(?:\.\d+)?)',
        ]
        for pattern in patterns:
            match = re.search(pattern, html)
            if match:
                try:
                    return float(match.group(1).replace(",", ""))
                except ValueError:
                    continue
        return 0.0

    def _quote_price(self, quote: dict) -> float:
        for field in ("lastPrice", "settlement", "close", "previousClose"):
            val = self._safe_float(quote.get(field))
            if val > 0:
                return val
        return 0.0

    def _safe_float(self, value) -> float:
        try:
            return float(str(value or 0).replace(",", "").strip())
        except (TypeError, ValueError):
            return 0.0

    def _safe_int(self, value) -> int | None:
        if value is None:
            return None
        try:
            return int(float(str(value).replace(",", "")))
        except (TypeError, ValueError):
            return None
