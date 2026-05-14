from __future__ import annotations

import asyncio
import html
import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from core.config import settings
from core.logger import logger
from models.schemas import (
    CommodityVariety,
    ExportRecord,
    FuturesContract,
    HistoryWindow,
    MarketExportsResponse,
    MarketFuturesResponse,
    MarketPricePoint,
    MarketPricesResponse,
    MarketSummaryResponse,
)


class MarketService:
    BARCHART_QUOTE_URL = "https://ondemand.websol.barchart.com/getQuote.json"
    BARCHART_HISTORY_URL = "https://ondemand.websol.barchart.com/getHistory.json"
    BARCHART_PUBLIC_API_KEY = "2d8b3b803594b13e02a7dc827f4a63f8"
    BARCHART_USER_AGENT = "Mozilla/5.0 (compatible; CoffeeGPT/1.0; +https://localhost)"
    ARABICA_SYMBOLS = "KCY00,KC*1,KC*2,KC*3,KC*4"
    ROBUSTA_OVERVIEW_URL = "https://www.barchart.com/futures/quotes/RM*0/overview"
    HEADER_INIT_PATTERN = re.compile(r'symbolHeaderCtrl"\s+data-ng-init=\'init\((\{.*?\})\)\'', re.S)
    INLINE_DATA_PATTERN = re.compile(
        r'<script type="application/json" id="barchart-www-inline-data">(.*?)</script>',
        re.S,
    )
    PERIOD_TO_DAYS = {
        HistoryWindow.d1.value: 1,
        HistoryWindow.d7.value: 7,
        HistoryWindow.d30.value: 30,
        HistoryWindow.d90.value: 90,
        HistoryWindow.y1.value: 365,
    }

    async def get_prices(
        self,
        variety: CommodityVariety = CommodityVariety.arabica,
        period: str = HistoryWindow.d7.value,
    ) -> MarketPricesResponse:
        days = self.PERIOD_TO_DAYS.get(period, 7)
        base_price = 1.86 if variety == CommodityVariety.arabica else 1.14
        drift = 0.0011 if variety == CommodityVariety.arabica else 0.0007
        today = datetime.now(timezone.utc)
        points: list[MarketPricePoint] = []

        for offset in range(days):
            date_value = (today - timedelta(days=(days - offset - 1))).date().isoformat()
            seasonal = math.sin(offset / 5.0) * 0.021
            volatility = math.cos(offset / 9.0) * 0.008
            price = round(base_price + (offset * drift) + seasonal + volatility, 4)
            points.append(MarketPricePoint(date=date_value, price_usd_per_lb=price))

        first_price = points[0].price_usd_per_lb
        latest_price = points[-1].price_usd_per_lb
        change_pct = round(((latest_price - first_price) / first_price) * 100, 2)

        return MarketPricesResponse(
            variety=variety,
            currency="USD/lb",
            period=period,
            data=points,
            latest=latest_price,
            change_pct=change_pct,
            service_mode="synthetic_market_feed",
        )

    async def get_futures(self) -> MarketFuturesResponse:
        live_contracts = await self._live_futures_contracts()
        if live_contracts:
            return MarketFuturesResponse(
                contracts=live_contracts,
                timestamp=datetime.now(timezone.utc),
                service_mode="live_barchart_market_feed",
            )
        return self._demo_futures_response()

    async def get_exports(self, country: str | None = None) -> MarketExportsResponse:
        records = [
            ExportRecord(country_code="BRA", country="Brazil", volume_bags_60kg=41000000, value_usd_m=7800),
            ExportRecord(country_code="VNM", country="Vietnam", volume_bags_60kg=29000000, value_usd_m=3600),
            ExportRecord(country_code="COL", country="Colombia", volume_bags_60kg=12100000, value_usd_m=2450),
            ExportRecord(country_code="ETH", country="Ethiopia", volume_bags_60kg=8300000, value_usd_m=1200),
        ]
        if country:
            records = [record for record in records if record.country_code == country.upper()]
        return MarketExportsResponse(
            exports=records,
            year=2025,
            unit="60kg bags",
            service_mode="curated_export_dataset",
        )

    async def get_ai_summary(self) -> MarketSummaryResponse:
        arabica = await self.get_prices(CommodityVariety.arabica, HistoryWindow.d30.value)
        robusta = await self.get_prices(CommodityVariety.robusta, HistoryWindow.d30.value)
        sentiment = "cautiously_bullish" if arabica.change_pct >= 0 else "mixed"
        summary = (
            "Arabica remains firmer than Robusta in the current baseline scenario, with weather risk "
            "signals keeping premium contracts supported while export availability from Brazil and "
            "Vietnam prevents a sharper supply squeeze."
        )
        return MarketSummaryResponse(
            summary=summary,
            sentiment=sentiment,
            signals={
                "arabica_change_pct_30d": arabica.change_pct,
                "robusta_change_pct_30d": robusta.change_pct,
                "arabica_latest_usd_lb": arabica.latest,
                "robusta_latest_usd_lb": robusta.latest,
            },
            generated_at=datetime.now(timezone.utc),
            service_mode="synthetic_market_feed",
        )

    async def _live_futures_contracts(self) -> list[FuturesContract]:
        try:
            async with httpx.AsyncClient(
                timeout=15,
                follow_redirects=True,
                headers={"User-Agent": self.BARCHART_USER_AGENT},
            ) as client:
                results = await asyncio.gather(
                    self._fetch_arabica_contract(client),
                    self._fetch_robusta_contract(client),
                    return_exceptions=True,
                )
        except Exception as exc:
            logger.warning("Live futures fetch failed, falling back to demo market feed: {}", exc)
            return []

        contracts: list[FuturesContract] = []
        for market_key, result in zip(("arabica", "robusta"), results, strict=False):
            if isinstance(result, Exception):
                logger.warning("Live {} futures fetch failed: {}", market_key, result)
                continue
            if result is not None:
                contracts.append(result)
        return contracts

    async def _fetch_arabica_contract(self, client: httpx.AsyncClient) -> FuturesContract | None:
        response = await client.get(
            self.BARCHART_QUOTE_URL,
            params={
                "apikey": self.BARCHART_PUBLIC_API_KEY,
                "symbols": self.ARABICA_SYMBOLS,
                "fields": "settlement,previousClose,previousOpenInterest",
            },
        )
        response.raise_for_status()
        payload = response.json()
        results = payload.get("results") or []
        if not results:
            return None

        quote = self._select_active_arabica_contract(results)
        history_points = await self._fetch_barchart_history(client, quote.get("symbol", ""))
        volatility_pct = self._volatility_from_history(history_points)
        timestamp = self._parse_timestamp(
            quote.get("tradeTimestamp") or quote.get("serverTimestamp"),
            fallback=datetime.now(timezone.utc),
        )
        contract_name = str(quote.get("name") or "Coffee").strip()
        return FuturesContract(
            market_key="arabica",
            symbol=str(quote.get("symbol") or "KC"),
            market=f"ICE Arabica {contract_name}".strip(),
            price=self._quote_price(quote),
            currency="US cents/lb",
            change=self._coerce_float(quote.get("netChange")),
            change_percent=self._coerce_float(quote.get("percentChange")),
            volume=self._coerce_int(quote.get("volume")),
            volatility_pct=volatility_pct,
            open_interest=self._coerce_int(quote.get("previousOpenInterest")),
            open_price=self._coerce_float(quote.get("open")),
            high_price=self._coerce_float(quote.get("high")),
            low_price=self._coerce_float(quote.get("low")),
            previous_close=self._coerce_float(quote.get("previousClose")),
            contract_month=self._contract_month(str(quote.get("symbol") or "")),
            timestamp=timestamp,
            source_mode="live_barchart_quote_history",
        )

    async def _fetch_robusta_contract(self, client: httpx.AsyncClient) -> FuturesContract | None:
        response = await client.get(self.ROBUSTA_OVERVIEW_URL)
        response.raise_for_status()
        page = response.text

        header_quote = self._parse_barchart_header_quote(page)
        inline_quote = self._parse_barchart_inline_quote(page)
        if not header_quote:
            return None

        symbol = str(header_quote.get("symbol") or "RM").strip()
        price = self._coerce_float(header_quote.get("lastPrice"))
        previous_close = self._coerce_float(
            inline_quote.get("previousClose") if inline_quote else header_quote.get("previousClose")
        )
        high_price = self._coerce_float(inline_quote.get("previousHigh") if inline_quote else header_quote.get("high"))
        low_price = self._coerce_float(inline_quote.get("previousLow") if inline_quote else header_quote.get("low"))
        open_price = self._coerce_float(
            inline_quote.get("previousOpen") if inline_quote else header_quote.get("open")
        )
        timestamp = self._parse_timestamp(
            inline_quote.get("tradeTime") if inline_quote else None,
            fallback=self._parse_session_date(header_quote.get("sessionDateDisplayLong")),
        )
        volatility_pct = self._robusta_volatility(price, high_price, low_price)

        return FuturesContract(
            market_key="robusta",
            symbol=symbol,
            market="ICE Europe Robusta Coffee",
            price=price,
            currency="USD/tonne",
            change=self._coerce_float(header_quote.get("priceChange")),
            change_percent=self._coerce_percent(header_quote.get("percentChange")),
            volume=None,
            volatility_pct=volatility_pct,
            open_interest=None,
            open_price=open_price,
            high_price=high_price,
            low_price=low_price,
            previous_close=previous_close,
            contract_month=str(header_quote.get("contractName") or "").strip() or self._contract_month(symbol),
            timestamp=timestamp,
            source_mode="live_barchart_overview",
        )

    async def _fetch_barchart_history(self, client: httpx.AsyncClient, symbol: str) -> list[dict]:
        if not symbol:
            return []
        response = await client.get(
            self.BARCHART_HISTORY_URL,
            params={
                "apikey": self.BARCHART_PUBLIC_API_KEY,
                "symbol": symbol,
                "type": "daily",
                "maxRecords": 30,
            },
        )
        response.raise_for_status()
        payload = response.json()
        return list(payload.get("results") or [])

    def _select_active_arabica_contract(self, quotes: list[dict]) -> dict:
        def sort_key(item: dict) -> tuple[float, float, float]:
            return (
                self._coerce_float(item.get("previousOpenInterest")),
                self._coerce_float(item.get("volume")),
                self._coerce_float(item.get("lastPrice") or item.get("settlement") or item.get("close")),
            )

        active = [
            item
            for item in quotes
            if str(item.get("symbol") or "").strip().startswith("KC")
            and self._coerce_float(item.get("previousOpenInterest")) > 0
        ]
        candidates = active or quotes
        return max(candidates, key=sort_key)

    def _parse_barchart_header_quote(self, page: str) -> dict:
        match = self.HEADER_INIT_PATTERN.search(page)
        if match is None:
            return {}
        payload = html.unescape(match.group(1))
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return {}

    def _parse_barchart_inline_quote(self, page: str) -> dict:
        match = self.INLINE_DATA_PATTERN.search(page)
        if match is None:
            return {}
        try:
            payload = json.loads(html.unescape(match.group(1)))
        except json.JSONDecodeError:
            return {}
        if not isinstance(payload, dict) or not payload:
            return {}
        first_item = next(iter(payload.values()), {})
        return dict((first_item or {}).get("quote") or {})

    def _volatility_from_history(self, history_points: list[dict]) -> float:
        closes = [self._coerce_float(point.get("close")) for point in history_points if self._coerce_float(point.get("close")) > 0]
        if len(closes) < 2:
            return 0.0
        returns = [
            (current - previous) / previous
            for previous, current in zip(closes, closes[1:], strict=False)
            if previous > 0
        ]
        if not returns:
            return 0.0
        mean_return = sum(returns) / len(returns)
        variance = sum((value - mean_return) ** 2 for value in returns) / len(returns)
        return round((variance ** 0.5) * 100, 2)

    def _robusta_volatility(self, price: float, high_price: float, low_price: float) -> float:
        snapshot_volatility = self._historical_snapshot_volatility("robusta")
        if snapshot_volatility > 0:
            return snapshot_volatility
        if price <= 0:
            return 0.0
        intraday_range = max(high_price - low_price, 0.0)
        return round((intraday_range / price) * 100, 2)

    def _historical_snapshot_volatility(self, market_key: str) -> float:
        memory_prices = self._historical_memory_prices(market_key)
        if len(memory_prices) >= 2:
            return self._volatility_from_price_series(memory_prices)

        prices: list[float] = []
        seen_dates: set[str] = set()
        raw_files = sorted(settings.raw_data_dir.glob("futures_*.json"), reverse=True)
        for path in raw_files:
            for snapshot in self._snapshot_prices_from_file(path, market_key):
                snapshot_date = str(snapshot.get("date") or "").strip()
                if not snapshot_date or snapshot_date in seen_dates:
                    continue
                seen_dates.add(snapshot_date)
                prices.append(self._coerce_float(snapshot.get("price")))
            if len(prices) >= 30:
                break

        prices = [price for price in prices if price > 0]
        return self._volatility_from_price_series(list(reversed(prices[:30])))

    def _historical_memory_prices(self, market_key: str) -> list[float]:
        path = settings.processed_data_dir / "futures_history" / "markets" / f"{market_key}.jsonl"
        if not path.exists():
            return []

        prices: list[float] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                payload = json.loads(line)
                if str(payload.get("market") or "").strip().lower() != market_key:
                    continue
                prices.append(self._coerce_float(payload.get("price")))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return []
        return [price for price in prices[-30:] if price > 0]

    def _volatility_from_price_series(self, prices: list[float]) -> float:
        prices = [price for price in prices if price > 0]
        if len(prices) < 2:
            return 0.0
        returns = [
            (current - previous) / previous
            for previous, current in zip(prices, prices[1:], strict=False)
            if previous > 0
        ]
        if not returns:
            return 0.0
        mean_return = sum(returns) / len(returns)
        variance = sum((value - mean_return) ** 2 for value in returns) / len(returns)
        return round((variance ** 0.5) * 100, 2)

    def _snapshot_prices_from_file(self, path: Path, market_key: str) -> list[dict]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(payload, list):
            return []

        snapshots: list[dict] = []
        for record in payload:
            if not isinstance(record, dict) or record.get("record_type") != "futures_snapshot":
                continue
            metadata = record.get("metadata") or {}
            raw = record.get("raw") or {}
            if str(metadata.get("market") or raw.get("market_key") or "").strip().lower() != market_key:
                continue
            snapshots.append(
                {
                    "date": metadata.get("snapshot_date") or str(metadata.get("published_at") or "")[:10],
                    "price": raw.get("price"),
                }
            )
        return snapshots

    def _quote_price(self, quote: dict) -> float:
        for field in ("lastPrice", "settlement", "close", "previousClose"):
            value = self._coerce_float(quote.get(field))
            if value > 0:
                return value
        return 0.0

    def _contract_month(self, symbol: str) -> str | None:
        match = re.fullmatch(r"[A-Z]+([FGHJKMNQUVXZ])(\d{2})", symbol or "")
        if match is None:
            return None
        month_map = {
            "F": "Jan",
            "G": "Feb",
            "H": "Mar",
            "J": "Apr",
            "K": "May",
            "M": "Jun",
            "N": "Jul",
            "Q": "Aug",
            "U": "Sep",
            "V": "Oct",
            "X": "Nov",
            "Z": "Dec",
        }
        month = month_map.get(match.group(1), match.group(1))
        year = f"20{match.group(2)}"
        return f"{month} {year}"

    def _parse_session_date(self, value) -> datetime:
        text = str(value or "").strip()
        if not text:
            return datetime.now(timezone.utc)
        cleaned = text.replace("st", "").replace("nd", "").replace("rd", "").replace("th", "")
        try:
            return datetime.strptime(cleaned, "%a, %b %d, %Y").replace(tzinfo=timezone.utc)
        except ValueError:
            return datetime.now(timezone.utc)

    def _parse_timestamp(self, value, fallback: datetime) -> datetime:
        text = str(value or "").strip()
        if not text:
            return fallback
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return fallback

    def _coerce_percent(self, value) -> float:
        text = str(value or "").replace("%", "").replace(",", "").strip()
        return self._coerce_float(text)

    def _coerce_int(self, value) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(float(str(value).replace(",", "").strip()))
        except (TypeError, ValueError):
            return None

    def _coerce_float(self, value) -> float:
        try:
            return float(str(value).replace(",", "").strip() or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _demo_futures_response(self) -> MarketFuturesResponse:
        now = datetime.now(timezone.utc)
        return MarketFuturesResponse(
            contracts=[
                FuturesContract(
                    market_key="arabica",
                    symbol="KC",
                    market="ICE Arabica",
                    price=1.94,
                    currency="USD/lb",
                    change=0.014,
                    change_percent=0.72,
                    volume=35180,
                    volatility_pct=1.8,
                    open_interest=80461,
                    contract_month="Jul 2026",
                    timestamp=now,
                    source_mode="synthetic_market_feed",
                ),
                FuturesContract(
                    market_key="robusta",
                    symbol="RM",
                    market="ICE Europe Robusta",
                    price=2385.0,
                    currency="USD/tonne",
                    change=-11.5,
                    change_percent=-0.48,
                    volume=12640,
                    volatility_pct=1.2,
                    open_interest=18810,
                    contract_month="Jul 2026",
                    timestamp=now,
                    source_mode="synthetic_market_feed",
                ),
            ],
            timestamp=now,
            service_mode="synthetic_market_feed",
        )
