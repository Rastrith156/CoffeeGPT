from __future__ import annotations

from .base import BaseConnector

class BuyerConnector(BaseConnector):
    name = "buyers"
    description = "Buyer signals and procurement posture"

    async def fetch(self) -> list[dict]:
        buyers = [
            {
                "buyer": "Specialty Roasters North America",
                "segment": "specialty",
                "signal": "seeking traceable washed Arabica lots",
            },
            {
                "buyer": "European Retail Blend Desk",
                "segment": "mainstream",
                "signal": "stable Robusta coverage for next 2 quarters",
            },
        ]
        return [
            self._record(
                title=item["buyer"],
                content=f"{item['buyer']} in {item['segment']} segment is {item['signal']}.",
                record_type="buyer_signal",
                raw=item,
                metadata={"source": self.name, "title": item["buyer"]},
            )
            for item in buyers
        ]
