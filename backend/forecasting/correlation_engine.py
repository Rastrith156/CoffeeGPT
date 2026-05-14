from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from core.config import settings
from models.schemas import (
    CorrelationDriver,
    HistoricalFuturesSnapshot,
    MarketCorrelationInsight,
    MarketCorrelationResponse,
    NewsArticle,
)


class CorrelationEngine:
    MARKET_REGIONS = {
        "arabica": ("Sul de Minas", "Cerrado Mineiro", "Espirito Santo"),
        "robusta": ("Dak Lak", "Lam Dong", "Gia Lai"),
    }
    MARKET_KEYWORDS = {
        "arabica": ("arabica", "brazil", "frost", "minas"),
        "robusta": ("robusta", "vietnam", "dak lak", "lam dong"),
    }
    BULLISH_NEWS_TERMS = (
        "drought",
        "dry",
        "frost",
        "flood",
        "heavy rainfall",
        "delay",
        "delays",
        "shortfall",
        "tight",
        "risk",
        "concern",
        "drop",
        "decline",
        "lower",
        "reduced",
        "reduction",
        "slower",
        "disruption",
        "cut",
        "exports down",
        "shipments down",
    )
    BEARISH_NEWS_TERMS = (
        "improves",
        "improved",
        "increase",
        "higher output",
        "record crop",
        "ample",
        "recovery",
        "better weather",
        "faster",
        "normalizing",
        "normalising",
        "stabilizes",
        "stabilises",
        "strong harvest",
        "boost",
        "expanded",
        "exports rise",
        "shipment pace improves",
    )
    DRIVER_WEIGHTS = {
        "weather": 0.46,
        "news": 0.34,
        "futures": 0.20,
    }

    def __init__(self, history_root: Path | None = None) -> None:
        self.history_root = history_root or (settings.processed_data_dir / "futures_history")

    def load_history(
        self,
        market: str | None = None,
        limit: int = 90,
    ) -> dict[str, list[HistoricalFuturesSnapshot]]:
        markets = [market.lower()] if market else sorted(self.MARKET_REGIONS)
        history: dict[str, list[HistoricalFuturesSnapshot]] = {}

        for market_key in markets:
            path = self.history_root / "markets" / f"{market_key}.jsonl"
            if not path.exists():
                history[market_key] = []
                continue

            items: list[HistoricalFuturesSnapshot] = []
            try:
                for line in path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    items.append(HistoricalFuturesSnapshot.model_validate(json.loads(line)))
            except (OSError, ValueError, TypeError):
                history[market_key] = []
                continue

            history[market_key] = items[-limit:]

        return history

    def analyze(
        self,
        *,
        futures_snapshots: list[HistoricalFuturesSnapshot],
        weather_context: dict[str, list],
        news_articles: list[NewsArticle],
        generated_at: datetime | None = None,
    ) -> MarketCorrelationResponse:
        history_map = self.load_history(limit=120)
        insights: list[MarketCorrelationInsight] = []

        for snapshot in futures_snapshots:
            market_key = snapshot.market.lower()
            market_history = history_map.get(market_key, [])

            weather_driver, weather_signals = self._weather_driver(
                market=market_key,
                snapshots=weather_context.get(market_key, []),
            )
            news_driver, news_signals = self._news_driver(
                market=market_key,
                news_articles=news_articles,
            )
            futures_driver, futures_signals, anomaly_flag = self._futures_driver(
                snapshot=snapshot,
                history=market_history,
            )

            drivers = [driver for driver in (weather_driver, news_driver, futures_driver) if driver is not None]
            direction, confidence = self._aggregate_direction(snapshot=snapshot, drivers=drivers)
            supporting_signals = {
                **weather_signals,
                **news_signals,
                **futures_signals,
            }
            insights.append(
                MarketCorrelationInsight(
                    market=market_key,
                    direction=direction,
                    confidence=confidence,
                    causal_summary=self._build_causal_summary(
                        snapshot=snapshot,
                        direction=direction,
                        drivers=drivers,
                        anomaly_flag=anomaly_flag,
                    ),
                    drivers=drivers,
                    price=snapshot.price,
                    change_percent=snapshot.change_percent,
                    volatility=snapshot.volatility,
                    anomaly_flag=anomaly_flag,
                    supporting_signals=supporting_signals,
                )
            )

        return MarketCorrelationResponse(
            generated_at=generated_at or datetime.now(timezone.utc),
            engine_mode="heuristic_causal_intelligence",
            cross_market_summary=self._cross_market_summary(insights),
            insights=insights,
            service_mode="heuristic_causal_intelligence",
        )

    def _weather_driver(
        self,
        *,
        market: str,
        snapshots: list,
    ) -> tuple[CorrelationDriver | None, dict[str, str | float]]:
        if not snapshots:
            return None, {}

        rainfall_totals: list[float] = []
        humidity_values: list[float] = []
        precipitation_probabilities: list[float] = []
        forecast_min_temps: list[float] = []
        regions: list[str] = []

        for snapshot in snapshots:
            regions.append(snapshot.profile.name)
            rainfall_totals.append(sum(point.rainfall_mm for point in snapshot.forecast.forecast[:3]))
            humidity_values.append(snapshot.current.humidity_pct)
            precipitation_probabilities.append(
                max((point.precipitation_probability_pct for point in snapshot.forecast.forecast[:3]), default=0.0)
            )
            forecast_min_temps.append(
                min([snapshot.current.temperature_c, *[point.temp_c for point in snapshot.forecast.forecast[:3]]])
            )

        avg_rainfall = self._average(rainfall_totals)
        avg_humidity = self._average(humidity_values)
        avg_probability = self._average(precipitation_probabilities)
        min_temp = min(forecast_min_temps) if forecast_min_temps else 0.0
        evidence = [
            f"Regions tracked: {', '.join(regions)}",
            f"Average 3-day rainfall: {avg_rainfall:.1f} mm",
            f"Average precipitation probability: {avg_probability:.0f}%",
            f"Average humidity: {avg_humidity:.0f}%",
        ]
        if market == "arabica" and min_temp <= 4:
            return (
                CorrelationDriver(
                    driver_type="weather",
                    signal="frost risk threatens Arabica supply",
                    impact="bullish",
                    confidence=0.9,
                    evidence=[*evidence, f"Lowest projected temperature: {min_temp:.1f} C"],
                ),
                {
                    "weather_rainfall_mm_3d": round(avg_rainfall, 2),
                    "weather_precip_probability_pct": round(avg_probability, 1),
                    "weather_min_temp_c": round(min_temp, 1),
                },
            )
        if avg_rainfall >= 18 or avg_probability >= 70:
            confidence = min(0.92, 0.62 + min(avg_rainfall / 40.0, 0.18) + min(avg_probability / 250.0, 0.12))
            return (
                CorrelationDriver(
                    driver_type="weather",
                    signal="heavy rainfall raises harvest and disease risk",
                    impact="bullish",
                    confidence=round(confidence, 2),
                    evidence=evidence,
                ),
                {
                    "weather_rainfall_mm_3d": round(avg_rainfall, 2),
                    "weather_precip_probability_pct": round(avg_probability, 1),
                    "weather_humidity_pct": round(avg_humidity, 1),
                },
            )
        if avg_rainfall <= 2.5 and avg_humidity <= 68:
            return (
                CorrelationDriver(
                    driver_type="weather",
                    signal="dry spell elevates crop stress",
                    impact="bullish",
                    confidence=0.76,
                    evidence=evidence,
                ),
                {
                    "weather_rainfall_mm_3d": round(avg_rainfall, 2),
                    "weather_humidity_pct": round(avg_humidity, 1),
                },
            )
        if 5 <= avg_rainfall <= 12 and 65 <= avg_humidity <= 82:
            return (
                CorrelationDriver(
                    driver_type="weather",
                    signal="balanced moisture supports crop development",
                    impact="bearish",
                    confidence=0.57,
                    evidence=evidence,
                ),
                {
                    "weather_rainfall_mm_3d": round(avg_rainfall, 2),
                    "weather_humidity_pct": round(avg_humidity, 1),
                },
            )
        return (
            CorrelationDriver(
                driver_type="weather",
                signal="weather backdrop is mixed",
                impact="neutral",
                confidence=0.42,
                evidence=evidence,
            ),
            {
                "weather_rainfall_mm_3d": round(avg_rainfall, 2),
                "weather_humidity_pct": round(avg_humidity, 1),
            },
        )

    def _news_driver(
        self,
        *,
        market: str,
        news_articles: list[NewsArticle],
    ) -> tuple[CorrelationDriver | None, dict[str, str | float]]:
        if not news_articles:
            return None, {}

        keywords = self.MARKET_KEYWORDS.get(market, ())
        relevant_articles = [
            article
            for article in news_articles
            if self._is_relevant_article(article=article, keywords=keywords)
        ]
        if not relevant_articles:
            return None, {}

        bullish_score = 0
        bearish_score = 0
        evidence: list[str] = []
        for article in relevant_articles[:4]:
            text = f"{article.title} {article.summary}".lower()
            bullish_score += self._count_terms(text, self.BULLISH_NEWS_TERMS)
            bearish_score += self._count_terms(text, self.BEARISH_NEWS_TERMS)
            evidence.append(article.title)

        net_score = bullish_score - bearish_score
        if net_score > 0:
            impact = "bullish"
            signal = "news flow points to tighter supply and export friction"
        elif net_score < 0:
            impact = "bearish"
            signal = "news flow suggests smoother supply and shipment conditions"
        else:
            impact = "neutral"
            signal = "news flow is mixed"

        confidence = 0.45 + min(abs(net_score) * 0.08, 0.28) + min(len(evidence) * 0.04, 0.12)
        return (
            CorrelationDriver(
                driver_type="news",
                signal=signal,
                impact=impact,
                confidence=round(min(confidence, 0.9), 2),
                evidence=evidence,
            ),
            {
                "news_relevant_articles": float(len(relevant_articles)),
                "news_net_score": float(net_score),
            },
        )

    def _futures_driver(
        self,
        *,
        snapshot: HistoricalFuturesSnapshot,
        history: list[HistoricalFuturesSnapshot],
    ) -> tuple[CorrelationDriver | None, dict[str, str | float], str | None]:
        comparable_history = [
            item
            for item in history
            if item.snapshot_date and item.snapshot_date != snapshot.snapshot_date
        ]
        recent_history = comparable_history[-30:]
        avg_abs_change = self._average([abs(item.change_percent) for item in recent_history])
        avg_volatility = self._average([item.volatility for item in recent_history])

        unusual_move_ratio = abs(snapshot.change_percent) / avg_abs_change if avg_abs_change > 0 else 0.0
        volatility_ratio = snapshot.volatility / avg_volatility if avg_volatility > 0 else 0.0
        anomaly_flag = None
        if unusual_move_ratio >= 1.75 or abs(snapshot.change_percent) >= 2.0:
            anomaly_flag = "above_normal_move"
        elif volatility_ratio >= 1.4 or snapshot.volatility >= 2.5:
            anomaly_flag = "elevated_volatility"

        if snapshot.change_percent > 0.2:
            impact = "bullish"
            signal = "futures tape confirms buying pressure"
        elif snapshot.change_percent < -0.2:
            impact = "bearish"
            signal = "futures tape confirms selling pressure"
        else:
            impact = "neutral"
            signal = "futures tape is close to flat"

        confidence = 0.4
        if abs(snapshot.change_percent) >= 0.8:
            confidence += 0.12
        if unusual_move_ratio >= 1.25:
            confidence += min((unusual_move_ratio - 1.25) * 0.18, 0.2)
        if volatility_ratio >= 1.15:
            confidence += min((volatility_ratio - 1.15) * 0.15, 0.12)

        evidence = [
            f"Daily move: {snapshot.change_percent:+.2f}%",
            f"Session volatility: {snapshot.volatility:.2f}%",
        ]
        if avg_abs_change > 0:
            evidence.append(f"Recent average absolute move: {avg_abs_change:.2f}%")
        if avg_volatility > 0:
            evidence.append(f"Recent average volatility: {avg_volatility:.2f}%")

        return (
            CorrelationDriver(
                driver_type="futures",
                signal=signal,
                impact=impact,
                confidence=round(min(confidence, 0.9), 2),
                evidence=evidence,
            ),
            {
                "recent_avg_abs_change_pct": round(avg_abs_change, 2),
                "recent_avg_volatility_pct": round(avg_volatility, 2),
                "unusual_move_ratio": round(unusual_move_ratio, 2),
                "volatility_ratio": round(volatility_ratio, 2),
            },
            anomaly_flag,
        )

    def _aggregate_direction(
        self,
        *,
        snapshot: HistoricalFuturesSnapshot,
        drivers: list[CorrelationDriver],
    ) -> tuple[str, float]:
        score = 0.0
        confidence = 0.32

        for driver in drivers:
            weight = self.DRIVER_WEIGHTS.get(driver.driver_type, 0.15)
            direction = 1 if driver.impact == "bullish" else -1 if driver.impact == "bearish" else 0
            score += direction * weight * driver.confidence
            confidence += weight * driver.confidence * 0.55

        if snapshot.change_percent > 0.35:
            score += 0.08
        elif snapshot.change_percent < -0.35:
            score -= 0.08

        if score >= 0.12:
            direction = "bullish"
        elif score <= -0.12:
            direction = "bearish"
        else:
            direction = "mixed"

        return direction, round(min(max(confidence, 0.3), 0.95), 2)

    def _build_causal_summary(
        self,
        *,
        snapshot: HistoricalFuturesSnapshot,
        direction: str,
        drivers: list[CorrelationDriver],
        anomaly_flag: str | None,
    ) -> str:
        market_label = snapshot.market.capitalize()
        change = abs(snapshot.change_percent)
        move_verb = self._movement_verb(snapshot.change_percent)
        directional_drivers = [driver for driver in drivers if driver.impact != "neutral"]
        primary_driver = max(directional_drivers or drivers, key=lambda item: item.confidence, default=None)

        if primary_driver is None:
            summary = (
                f"{market_label} futures {move_verb} {change:.2f}% today, but the current signal set remains thin "
                f"and causality is still tentative."
            )
        elif direction == "mixed":
            summary = (
                f"{market_label} futures {move_verb} {change:.2f}% today while weather, news, and tape signals "
                f"remain mixed."
            )
        else:
            summary = (
                f"{market_label} futures {move_verb} {change:.2f}% today as {primary_driver.signal.lower()}."
            )

        if anomaly_flag == "above_normal_move":
            summary += " The magnitude is above recent daily norms."
        elif anomaly_flag == "elevated_volatility":
            summary += " Volatility is running above its recent baseline."
        return summary

    def _cross_market_summary(self, insights: list[MarketCorrelationInsight]) -> str:
        if not insights:
            return "Cross-market signal set is unavailable."

        arabica = next((item for item in insights if item.market == "arabica"), None)
        robusta = next((item for item in insights if item.market == "robusta"), None)
        if arabica is None or robusta is None:
            lead = max(insights, key=lambda item: abs(item.change_percent))
            return (
                f"{lead.market.capitalize()} is the clearest coffee futures signal today, with "
                f"{lead.direction} drivers dominating the setup."
            )

        spread = arabica.change_percent - robusta.change_percent
        if arabica.direction == "bullish" and robusta.direction == "bullish":
            if spread >= 1.0:
                return (
                    "Coffee futures are broadly constructive, with Arabica leading as Brazil-linked supply risk "
                    "appears stronger than Robusta-specific pressure."
                )
            if spread <= -1.0:
                return (
                    "Coffee futures are broadly constructive, with Robusta leading as Vietnam-linked supply and "
                    "export pressure looks more acute."
                )
            return (
                "Both Arabica and Robusta are firm, pointing to a wider coffee-complex supply concern rather than a "
                "single isolated market shock."
            )
        if arabica.direction == "bearish" and robusta.direction == "bearish":
            return (
                "Both contracts are under pressure, suggesting the market is leaning toward easier supply, softer "
                "risk perception, or weaker short-term demand conviction."
            )
        if spread >= 1.0:
            return (
                "Arabica is outperforming Robusta, which usually signals a more Brazil-specific weather or quality "
                "story rather than broad coffee demand strength."
            )
        if spread <= -1.0:
            return (
                "Robusta is outperforming Arabica, pointing to a more Vietnam-centered export or supply tightening "
                "story."
            )
        return (
            "Cross-market tone is split, with futures suggesting market-specific drivers are outweighing any broad "
            "coffee-complex narrative today."
        )

    def _is_relevant_article(self, *, article: NewsArticle, keywords: tuple[str, ...]) -> bool:
        lowered = f"{article.title} {article.summary}".lower()
        return any(keyword in lowered for keyword in keywords)

    def _movement_verb(self, change_percent: float) -> str:
        if change_percent > 0.12:
            return "rose"
        if change_percent < -0.12:
            return "fell"
        return "was little changed"

    def _count_terms(self, text: str, terms: tuple[str, ...]) -> int:
        return sum(text.count(term) for term in terms)

    def _average(self, values: list[float]) -> float:
        filtered = [value for value in values if value is not None]
        if not filtered:
            return 0.0
        return sum(filtered) / len(filtered)
