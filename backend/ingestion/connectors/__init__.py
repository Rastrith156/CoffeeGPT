from .base import BaseConnector
from .prices import PriceConnector
from .futures import FuturesConnector
from .news import NewsConnector
from .weather import WeatherConnector
from .policies import PolicyConnector
from .exports import ExportConnector
from .buyers import BuyerConnector
from .local_markets import LocalMarketConnector

def build_connectors(market_service, weather_service, news_service, regions: list[str]) -> dict[str, BaseConnector]:
    return {
        "prices": PriceConnector(market_service),
        "futures": FuturesConnector(market_service, weather_service, news_service),
        "news": NewsConnector(news_service),
        "weather": WeatherConnector(weather_service, regions),
        "policies": PolicyConnector(news_service),
        "exports": ExportConnector(market_service),
        "buyers": BuyerConnector(),
        "local_markets": LocalMarketConnector(),
    }
