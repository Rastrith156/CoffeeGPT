from __future__ import annotations

from .base import BaseConnector

class LocalMarketConnector(BaseConnector):
    name = "local_markets"
    description = "Hyperlocal physical market observations"

    async def fetch(self) -> list[dict]:
        local_markets = [
            {
                "market": "Kochere Station Market",
                "country": "Ethiopia",
                "observation": "higher cherry competition among exporters",
            },
            {
                "market": "Huila Cooperative Board",
                "country": "Colombia",
                "observation": "quality differentials holding firm for washed lots",
            },
        ]
        return [
            self._record(
                title=item["market"],
                content=f"{item['market']} in {item['country']} reports {item['observation']}.",
                record_type="local_market_signal",
                raw=item,
                metadata={"source": self.name, "title": item["market"]},
            )
            for item in local_markets
        ]
