from __future__ import annotations

from models.schemas import CommodityVariety, HistoryWindow, SourceDefinition


class BaseConnector:
    name = ""
    description = ""

    def descriptor(self) -> SourceDefinition:
        return SourceDefinition(name=self.name, description=self.description, enabled=True)

    def _record(
        self,
        title: str,
        content: str,
        record_type: str,
        raw: dict,
        metadata: dict,
    ) -> dict:
        return {
            "title": title,
            "content": content,
            "record_type": record_type,
            "raw": raw,
            "metadata": metadata,
        }


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


class NewsConnector(BaseConnector):
    name = "news"
    description = "Coffee news and macro-intelligence feed"

    def __init__(self, news_service) -> None:
        self.news_service = news_service

    async def fetch(self) -> list[dict]:
        feed = await self.news_service.get_latest(limit=10, category="all")
        return [
            self._record(
                title=article.title,
                content=f"{article.title}\n{article.summary}",
                record_type="news_article",
                raw=article.model_dump(mode="json"),
                metadata={"source": self.name, "title": article.title},
            )
            for article in feed.articles
        ]


class WeatherConnector(BaseConnector):
    name = "weather"
    description = "Growing region weather observations"

    def __init__(self, weather_service, regions: list[str]) -> None:
        self.weather_service = weather_service
        self.regions = regions

    async def fetch(self) -> list[dict]:
        records = []
        for region in self.regions:
            weather = await self.weather_service.get_current(region)
            records.append(
                self._record(
                    title=f"{region} current weather",
                    content=(
                        f"{region} weather: {weather.temperature_c} C, humidity {weather.humidity_pct}%, "
                        f"rainfall {weather.rainfall_mm} mm, condition {weather.description}."
                    ),
                    record_type="weather_snapshot",
                    raw=weather.model_dump(mode="json"),
                    metadata={"source": self.name, "title": f"{region} current weather"},
                )
            )
        return records


class PolicyConnector(BaseConnector):
    name = "policies"
    description = "Government and buyer policy tracker"

    def __init__(self, news_service) -> None:
        self.news_service = news_service

    async def fetch(self) -> list[dict]:
        updates = await self.news_service.get_policy_updates()
        return [
            self._record(
                title=policy.title,
                content=f"{policy.country}: {policy.title}. Status: {policy.status}. Impact: {policy.impact}.",
                record_type="policy_update",
                raw=policy.model_dump(mode="json"),
                metadata={"source": self.name, "title": policy.title},
            )
            for policy in updates.policies
        ]


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


def build_connectors(market_service, weather_service, news_service, regions: list[str]) -> dict[str, BaseConnector]:
    return {
        "prices": PriceConnector(market_service),
        "news": NewsConnector(news_service),
        "weather": WeatherConnector(weather_service, regions),
        "policies": PolicyConnector(news_service),
        "exports": ExportConnector(market_service),
        "buyers": BuyerConnector(),
        "local_markets": LocalMarketConnector(),
    }
