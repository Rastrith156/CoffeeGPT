from __future__ import annotations

from .base import BaseConnector

class ExportConnector(BaseConnector):
    name = "exports"
    description = "Export volume and value intelligence"

    def __init__(self, market_service) -> None:
        self.market_service = market_service

    async def fetch(self) -> list[dict]:
        exports = await self.market_service.get_exports()
        return [
            self._record(
                title=f"{record.country} export profile",
                content=(
                    f"{record.country} exported {record.volume_bags_60kg} bags worth "
                    f"{record.value_usd_m} million USD."
                ),
                record_type="export_profile",
                raw=record.model_dump(mode="json"),
                metadata={"source": self.name, "title": f"{record.country} export profile"},
            )
            for record in exports.exports
        ]
