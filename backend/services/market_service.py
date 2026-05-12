from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

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
        return MarketFuturesResponse(
            contracts=[
                FuturesContract(
                    symbol="KC",
                    market="ICE Arabica",
                    price=1.94,
                    currency="USD/lb",
                    change=0.014,
                    volume=35180,
                ),
                FuturesContract(
                    symbol="RM",
                    market="LIFFE Robusta",
                    price=2385.0,
                    currency="USD/tonne",
                    change=-11.5,
                    volume=12640,
                ),
            ],
            timestamp=datetime.now(timezone.utc),
            service_mode="synthetic_market_feed",
        )

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
