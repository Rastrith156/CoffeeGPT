from __future__ import annotations
from models.schemas import CommodityVariety, HistoryWindow
from .base import BaseConnector

class PriceConnector(BaseConnector):
    name = "prices"
    description = "Coffee spot and historical pricing intelligence"

    def __init__(self, market_service) -> None:
        self.market_service = market_service

    async def fetch(self) -> list[dict]:
        arabica = await self.market_service.get_prices(CommodityVariety.arabica, HistoryWindow.d30.value)
        robusta = await self.market_service.get_prices(CommodityVariety.robusta, HistoryWindow.d30.value)
        return [
            self._record(
                title="Arabica 30 day market curve",
                content=f"Arabica latest price is {arabica.latest} USD/lb with {arabica.change_pct}% change over 30 days.",
                record_type="market_prices",
                raw=arabica.model_dump(mode="json"),
                metadata={"source": self.name, "title": "Arabica 30 day market curve"},
            ),
            self._record(
                title="Robusta 30 day market curve",
                content=f"Robusta latest price is {robusta.latest} USD/lb with {robusta.change_pct}% change over 30 days.",
                record_type="market_prices",
                raw=robusta.model_dump(mode="json"),
                metadata={"source": self.name, "title": "Robusta 30 day market curve"},
            ),
        ]
