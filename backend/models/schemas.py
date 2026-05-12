from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class APIModel(BaseModel):
    model_config = ConfigDict(use_enum_values=True, populate_by_name=True)


class CommodityVariety(str, Enum):
    arabica = "arabica"
    robusta = "robusta"


class HistoryWindow(str, Enum):
    d1 = "1d"
    d7 = "7d"
    d30 = "30d"
    d90 = "90d"
    y1 = "1y"


class NewsCategory(str, Enum):
    all = "all"
    prices = "prices"
    policy = "policy"
    weather = "weather"
    trade = "trade"


class IngestionSource(str, Enum):
    all = "all"
    prices = "prices"
    news = "news"
    weather = "weather"
    policies = "policies"
    exports = "exports"
    buyers = "buyers"
    local_markets = "local_markets"


class HealthResponse(APIModel):
    status: str
    timestamp: datetime


class DependencyStatus(APIModel):
    name: str
    status: str
    detail: str | None = None
    latency_ms: float | None = None


class DetailedHealthResponse(APIModel):
    status: str
    timestamp: datetime
    services: list[DependencyStatus] = Field(default_factory=list)


class SourceCitation(APIModel):
    source: str
    title: str | None = None
    record_type: str | None = None


class ChatRequest(APIModel):
    message: str = Field(..., min_length=1, max_length=2000)
    session_id: str = Field(default="default")
    use_rag: bool = Field(default=True)


class ChatResponse(APIModel):
    answer: str
    sources: list[SourceCitation] = Field(default_factory=list)
    session_id: str
    model: str
    provider: str = "lmstudio"
    response_id: str | None = None
    retrieval_mode: str


class MarketPricePoint(APIModel):
    date: str
    price_usd_per_lb: float


class MarketPricesResponse(APIModel):
    variety: CommodityVariety
    currency: str
    period: str
    data: list[MarketPricePoint]
    latest: float
    change_pct: float
    service_mode: str


class FuturesContract(APIModel):
    symbol: str
    market: str
    price: float
    currency: str
    change: float
    volume: int


class MarketFuturesResponse(APIModel):
    contracts: list[FuturesContract]
    timestamp: datetime
    service_mode: str


class ExportRecord(APIModel):
    country_code: str
    country: str
    volume_bags_60kg: int
    value_usd_m: int


class MarketExportsResponse(APIModel):
    exports: list[ExportRecord]
    year: int
    unit: str
    service_mode: str


class MarketSummaryResponse(APIModel):
    summary: str
    sentiment: str
    signals: dict[str, str | float]
    generated_at: datetime
    service_mode: str


class WeatherCurrentResponse(APIModel):
    region: str
    lat: float
    lon: float
    temperature_c: float
    humidity_pct: float
    rainfall_mm: float
    wind_speed_ms: float
    description: str
    timestamp: datetime
    service_mode: str


class WeatherForecastPoint(APIModel):
    day: int
    date: str
    temp_c: float
    humidity_pct: float
    rainfall_mm: float


class WeatherForecastResponse(APIModel):
    region: str
    days: int
    forecast: list[WeatherForecastPoint]
    service_mode: str


class RiskSignal(APIModel):
    name: str
    level: str
    score: float
    trigger: str | None = None


class RiskAssessmentResponse(APIModel):
    region: str
    risks: list[RiskSignal]
    overall_risk: str
    assessed_at: datetime
    service_mode: str


class NewsArticle(APIModel):
    title: str
    source: str
    url: str
    published_at: str
    summary: str
    category: str


class NewsFeedResponse(APIModel):
    category: str
    count: int
    articles: list[NewsArticle]
    service_mode: str


class SentimentSummaryResponse(APIModel):
    overall_sentiment: str
    score: float
    signals: dict[str, str]
    top_themes: list[str]
    generated_at: datetime
    service_mode: str


class PolicyUpdate(APIModel):
    country: str
    title: str
    status: str
    impact: str
    date: str


class PolicyUpdatesResponse(APIModel):
    policies: list[PolicyUpdate]
    count: int
    fetched_at: datetime
    service_mode: str


class ForecastEngineMetadata(APIModel):
    engine_mode: str
    prophet_available: bool
    xgboost_available: bool


class PriceForecastRequest(APIModel):
    variety: CommodityVariety = Field(default=CommodityVariety.arabica)
    horizon_days: int = Field(default=30, ge=1, le=365)


class PriceForecastPoint(APIModel):
    date: str
    forecast_usd_per_lb: float
    lower_80: float
    upper_80: float


class PriceForecastResponse(APIModel):
    variety: CommodityVariety
    horizon_days: int
    model: str
    engine: ForecastEngineMetadata
    forecast: list[PriceForecastPoint]
    summary: dict[str, float | str]
    generated_at: datetime


class DemandForecastRequest(APIModel):
    region: str = Field(default="global")
    horizon_months: int = Field(default=3, ge=1, le=24)


class DemandForecastPoint(APIModel):
    month: str
    demand_bags_m: float


class DemandForecastResponse(APIModel):
    region: str
    horizon_months: int
    engine: ForecastEngineMetadata
    forecast: list[DemandForecastPoint]
    generated_at: datetime


class SupplyRiskResponse(APIModel):
    overall_risk: str
    risk_score: float
    factors: dict[str, dict[str, float | str]]
    assessed_at: datetime
    engine: ForecastEngineMetadata


class IngestionTriggerRequest(APIModel):
    source: IngestionSource = Field(default=IngestionSource.all)
    force_refresh: bool = Field(default=False)


class IngestionRunResponse(APIModel):
    status: str
    source: str
    dispatch_mode: str
    job_id: str | None = None
    message: str


class IngestionJobRecord(APIModel):
    source: str
    status: str
    records_ingested: int
    documents_indexed: int = 0
    started_at: datetime
    finished_at: datetime | None = None
    detail: str | None = None
    dispatch_mode: str = "background"


class IngestionStatusResponse(APIModel):
    total_jobs: int
    recent_jobs: list[IngestionJobRecord] = Field(default_factory=list)
    last_updated: datetime


class SourceDefinition(APIModel):
    name: str
    description: str
    enabled: bool = True


class SourceCatalogResponse(APIModel):
    sources: list[SourceDefinition]
    total: int
