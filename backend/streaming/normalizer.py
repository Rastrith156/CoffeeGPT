"""
streaming/normalizer.py
========================
Tick normalizer — converts RawTickData into canonical NormalisedTick dicts.

Responsibilities:
  ✅ Validate and clean raw provider fields
  ✅ Compute derived fields (volatility_pct from change_percent, currency)
  ✅ Produce a canonical, type-safe output dict for Redis caching
  ❌ Does NOT fetch data (see streaming/providers/)
  ❌ Does NOT write to Redis
  ❌ Does NOT detect spikes

NormalisedTick schema (what the rest of the system consumes):
  {
    "market":         "arabica" | "robusta"
    "symbol":         str
    "price":          float
    "change":         float
    "change_percent": float  (signed, e.g. +2.3 or -1.1)
    "change_pct":     float  (alias for change_percent — dual key)
    "volume":         int | None
    "volatility_pct": float  (abs(change_percent) × volatility_factor)
    "currency":       str
    "source":         str
    "updated_at":     ISO8601 str
  }
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from streaming.providers.barchart_provider import RawTickData

# Per-market config
_MARKET_CONFIG: dict[str, dict[str, Any]] = {
    "arabica": {
        "currency": "US cents/lb",
        "price_key": "lastPrice",
        "volatility_factor": 0.5,
    },
    "robusta": {
        "currency": "USD/tonne",
        "price_key": "lastPrice",
        "volatility_factor": 0.5,
    },
}


@dataclass(frozen=True)
class NormalisedTick:
    """Canonical, validated tick data ready for Redis and downstream agents."""
    market:         str
    symbol:         str
    price:          float
    change:         float
    change_percent: float
    volume:         int | None
    volatility_pct: float
    currency:       str
    source:         str
    updated_at:     str

    def to_dict(self) -> dict[str, Any]:
        return {
            "market":         self.market,
            "symbol":         self.symbol,
            "price":          self.price,
            "change":         self.change,
            "change_percent": self.change_percent,
            "change_pct":     self.change_percent,   # dual-key alias
            "volume":         self.volume,
            "volatility_pct": self.volatility_pct,
            "currency":       self.currency,
            "source":         self.source,
            "updated_at":     self.updated_at,
        }


class TickNormalizer:
    """
    Stateless normalizer — converts RawTickData → NormalisedTick.

    Usage:
        normalizer = TickNormalizer()
        tick = normalizer.normalize(raw_tick)
        if tick:
            await cache.update_arabica(price=tick.price, ...)
    """

    def normalize(self, raw: RawTickData) -> NormalisedTick | None:
        """
        Normalize a raw tick.

        Returns NormalisedTick on success, None if data is invalid
        (e.g. price <= 0 — do not write garbage to Redis).
        """
        market = raw.market
        cfg    = _MARKET_CONFIG.get(market)
        if cfg is None:
            return None

        data = raw.raw
        price = self._safe_float(data.get(cfg["price_key"]) or data.get("lastPrice"))
        if price <= 0:
            return None

        change    = self._safe_float(data.get("netChange"))
        change_pct = self._safe_float(data.get("percentChange"))
        volume    = self._safe_int(data.get("volume"))
        vol_pct   = round(abs(change_pct) * cfg["volatility_factor"], 3)

        return NormalisedTick(
            market=market,
            symbol=str(data.get("symbol") or market.upper()),
            price=round(price, 4 if market == "arabica" else 2),
            change=round(change, 4),
            change_percent=round(change_pct, 2),
            volume=volume,
            volatility_pct=vol_pct,
            currency=cfg["currency"],
            source=raw.source,
            updated_at=raw.fetched_at,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

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
