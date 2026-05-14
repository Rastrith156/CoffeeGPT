from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from core.config import settings
from forecasting.correlation_engine import CorrelationEngine
from models.schemas import (
    HistoricalFuturesSnapshot,
    MarketCorrelationResponse,
    MarketRiskAssessmentResponse,
    NewsArticle,
    RiskFactorScore,
)


class RiskEngine:
    MARKET_WEIGHTS = {
        "arabica": 0.60,
        "robusta": 0.40,
    }
    COMPONENT_WEIGHTS = {
        "weather": 0.38,
        "supply": 0.34,
        "volatility": 0.28,
    }
    NEWS_KEYWORDS = (
        "coffee",
        "arabica",
        "robusta",
        "brazil",
        "vietnam",
        "harvest",
        "crop",
        "futures",
        "export",
        "exports",
        "supply",
        "shipment",
        "shipments",
    )

    def __init__(self, history_root: Path | None = None) -> None:
        self.history_root = history_root or (settings.processed_data_dir / "futures_history")

    def analyze(
        self,
        *,
        futures_snapshots: list[HistoricalFuturesSnapshot],
        weather_context: dict[str, list],
        news_articles: list[NewsArticle],
        correlations: MarketCorrelationResponse | None = None,
        generated_at: datetime | None = None,
    ) -> MarketRiskAssessmentResponse:
        generated_at = generated_at or datetime.now(timezone.utc)
        history_map = self._load_history(limit=120)

        weather_risk, weather_summary, weather_evidence = self._weather_risk(weather_context)
        news_score, news_summary, news_evidence = self._news_pressure(news_articles)
        volatility_risk, volatility_summary, volatility_evidence = self._volatility_risk(
            futures_snapshots=futures_snapshots,
            history_map=history_map,
        )
        futures_pressure, futures_evidence = self._futures_pressure(
            futures_snapshots=futures_snapshots,
            correlations=correlations,
        )
        supply_risk, supply_summary, supply_evidence = self._supply_risk(
            weather_risk=weather_risk,
            news_score=news_score,
            futures_pressure=futures_pressure,
            correlations=correlations,
            futures_evidence=futures_evidence,
            news_evidence=news_evidence,
        )

        market_risk_score = self._clamp(
            weather_risk * self.COMPONENT_WEIGHTS["weather"]
            + supply_risk * self.COMPONENT_WEIGHTS["supply"]
            + volatility_risk * self.COMPONENT_WEIGHTS["volatility"]
        )
        market_risk = self._risk_label(market_risk_score)
        factors = [
            RiskFactorScore(
                factor="weather",
                score=round(weather_risk, 2),
                weight=self.COMPONENT_WEIGHTS["weather"],
                summary=weather_summary,
                evidence=weather_evidence[:3],
            ),
            RiskFactorScore(
                factor="supply",
                score=round(supply_risk, 2),
                weight=self.COMPONENT_WEIGHTS["supply"],
                summary=supply_summary,
                evidence=supply_evidence[:3],
            ),
            RiskFactorScore(
                factor="volatility",
                score=round(volatility_risk, 2),
                weight=self.COMPONENT_WEIGHTS["volatility"],
                summary=volatility_summary,
                evidence=volatility_evidence[:3],
            ),
        ]
        confidence = self._confidence(
            futures_snapshots=futures_snapshots,
            weather_context=weather_context,
            news_articles=news_articles,
            correlations=correlations,
            scores=[weather_risk, supply_risk, volatility_risk],
        )
        explanation = self._build_explanation(market_risk=market_risk, factors=factors)

        return MarketRiskAssessmentResponse(
            market_risk=market_risk,
            market_risk_score=round(market_risk_score, 2),
            weather_risk=round(weather_risk, 2),
            supply_risk=round(supply_risk, 2),
            volatility_risk=round(volatility_risk, 2),
            confidence=confidence,
            explanation=explanation,
            factors=factors,
            generated_at=generated_at,
            service_mode="heuristic_risk_engine",
        )

    def _load_history(
        self,
        *,
        market: str | None = None,
        limit: int = 90,
    ) -> dict[str, list[HistoricalFuturesSnapshot]]:
        markets = [market.lower()] if market else sorted(self.MARKET_WEIGHTS)
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

    def _weather_risk(self, weather_context: dict[str, list]) -> tuple[float, str, list[str]]:
        if not weather_context:
            return 0.40, "weather visibility is still limited across major origins", []

        weighted_scores = 0.0
        total_weight = 0.0
        lead_score = 0.0
        lead_summary = "weather signals are mixed across major coffee regions"
        lead_evidence: list[str] = []

        for market, snapshots in weather_context.items():
            if not snapshots:
                continue

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

            origin_label = "Brazil" if market == "arabica" else "Vietnam" if market == "robusta" else market.title()
            if market == "arabica" and min_temp <= 4:
                score = 0.91
                summary = "frost risk is rising in Brazil Arabica zones"
            elif avg_rainfall >= 18 or avg_probability >= 72:
                score = self._clamp(
                    0.70 + min(avg_rainfall / 120.0, 0.12) + min(avg_probability / 500.0, 0.10),
                    floor=0.0,
                    ceiling=0.94,
                )
                summary = (
                    f"{origin_label} rainfall is disrupting {market.capitalize()} harvest conditions"
                    if market in {"arabica", "robusta"}
                    else f"heavy rainfall is lifting crop risk in {origin_label}"
                )
            elif avg_rainfall <= 2.5 and avg_humidity <= 68:
                score = 0.67
                summary = f"dry weather is stressing {origin_label} coffee conditions"
            elif 5 <= avg_rainfall <= 12 and 65 <= avg_humidity <= 82:
                score = 0.32
                summary = f"weather is comparatively balanced in {origin_label} coffee areas"
            else:
                score = 0.48
                summary = f"weather signals remain mixed in {origin_label}"

            evidence = [
                f"{origin_label} regions tracked: {', '.join(regions)}",
                f"Average 3-day rainfall: {avg_rainfall:.1f} mm",
                f"Average precipitation probability: {avg_probability:.0f}%",
                f"Average humidity: {avg_humidity:.0f}%",
            ]
            if min_temp > 0:
                evidence.append(f"Lowest projected temperature: {min_temp:.1f} C")

            weight = self.MARKET_WEIGHTS.get(market.lower(), 0.5)
            weighted_scores += score * weight
            total_weight += weight

            if score >= lead_score:
                lead_score = score
                lead_summary = summary
                lead_evidence = evidence

        if total_weight == 0:
            return 0.40, "weather visibility is still limited across major origins", []

        return round(weighted_scores / total_weight, 4), lead_summary, lead_evidence

    def _news_pressure(self, news_articles: list[NewsArticle]) -> tuple[float, str, list[str]]:
        if not news_articles:
            return 0.42, "news flow is not yet a major supply-risk driver", []

        relevant_articles = [
            article
            for article in news_articles
            if self._is_relevant_article(article)
        ]
        if not relevant_articles:
            return 0.42, "news flow is not yet a major supply-risk driver", []

        bullish_score = 0
        bearish_score = 0
        evidence: list[str] = []
        for article in relevant_articles[:5]:
            text = f"{article.title} {article.summary}".lower()
            bullish_score += self._count_terms(text, CorrelationEngine.BULLISH_NEWS_TERMS)
            bearish_score += self._count_terms(text, CorrelationEngine.BEARISH_NEWS_TERMS)
            evidence.append(article.title)

        net_score = bullish_score - bearish_score
        score = self._clamp(
            0.42
            + min(max(net_score, 0) * 0.06, 0.30)
            - min(max(-net_score, 0) * 0.04, 0.14)
            + min(len(evidence) * 0.03, 0.10),
            floor=0.14,
            ceiling=0.90,
        )

        if net_score > 1:
            summary = "news flow continues to flag tighter supply and harvest disruption"
        elif net_score < 0:
            summary = "news flow is leaning toward easier supply conditions"
        else:
            summary = "news flow remains mixed on near-term supply direction"
        return round(score, 4), summary, evidence

    def _volatility_risk(
        self,
        *,
        futures_snapshots: list[HistoricalFuturesSnapshot],
        history_map: dict[str, list[HistoricalFuturesSnapshot]],
    ) -> tuple[float, str, list[str]]:
        if not futures_snapshots:
            return 0.38, "futures volatility visibility is still limited", []

        weighted_scores = 0.0
        total_weight = 0.0
        lead_score = 0.0
        lead_summary = "futures volatility is close to recent norms"
        lead_evidence: list[str] = []

        for snapshot in futures_snapshots:
            history = [
                item
                for item in history_map.get(snapshot.market.lower(), [])
                if item.snapshot_date and item.snapshot_date != snapshot.snapshot_date
            ][-30:]
            avg_abs_change = self._average([abs(item.change_percent) for item in history])
            avg_volatility = self._average([item.volatility for item in history])
            unusual_move_ratio = abs(snapshot.change_percent) / avg_abs_change if avg_abs_change > 0 else 0.0
            volatility_ratio = snapshot.volatility / avg_volatility if avg_volatility > 0 else 0.0

            if volatility_ratio >= 1.45 or snapshot.volatility >= 2.4:
                score = self._clamp(
                    0.66 + min((volatility_ratio - 1.2) * 0.12, 0.14) + min(snapshot.volatility / 15.0, 0.10),
                    floor=0.0,
                    ceiling=0.92,
                )
                summary = f"{snapshot.market.capitalize()} futures volatility is running above its 30-day baseline"
            elif unusual_move_ratio >= 1.6 or abs(snapshot.change_percent) >= 1.4:
                score = self._clamp(
                    0.57 + min((unusual_move_ratio - 1.2) * 0.10, 0.14),
                    floor=0.0,
                    ceiling=0.84,
                )
                summary = f"{snapshot.market.capitalize()} futures moves are wider than normal"
            elif avg_volatility > 0 and snapshot.volatility <= avg_volatility * 0.85:
                score = 0.30
                summary = f"{snapshot.market.capitalize()} futures volatility is relatively contained"
            else:
                score = 0.44
                summary = f"{snapshot.market.capitalize()} futures volatility is mildly elevated"

            evidence = [
                f"{snapshot.market.capitalize()} session volatility: {snapshot.volatility:.2f}%",
                f"{snapshot.market.capitalize()} daily move: {snapshot.change_percent:+.2f}%",
            ]
            if avg_volatility > 0:
                evidence.append(f"30-day average volatility: {avg_volatility:.2f}%")
            if avg_abs_change > 0:
                evidence.append(f"30-day average absolute move: {avg_abs_change:.2f}%")

            weight = self.MARKET_WEIGHTS.get(snapshot.market.lower(), 0.5)
            weighted_scores += score * weight
            total_weight += weight

            if score >= lead_score:
                lead_score = score
                lead_summary = summary
                lead_evidence = evidence

        if total_weight == 0:
            return 0.38, "futures volatility visibility is still limited", []

        return round(weighted_scores / total_weight, 4), lead_summary, lead_evidence

    def _futures_pressure(
        self,
        *,
        futures_snapshots: list[HistoricalFuturesSnapshot],
        correlations: MarketCorrelationResponse | None,
    ) -> tuple[float, list[str]]:
        if not futures_snapshots:
            return 0.40, []

        correlation_map = {
            insight.market.lower(): insight
            for insight in (correlations.insights if correlations is not None else [])
        }
        weighted_scores = 0.0
        total_weight = 0.0
        evidence: list[str] = []

        for snapshot in futures_snapshots:
            score = 0.42
            if snapshot.change_percent >= 1.0:
                score += 0.18
            elif snapshot.change_percent >= 0.4:
                score += 0.10
            elif snapshot.change_percent <= -1.0:
                score -= 0.08
            elif snapshot.change_percent <= -0.4:
                score -= 0.04

            insight = correlation_map.get(snapshot.market.lower())
            if insight is not None:
                if insight.direction == "bullish":
                    score += 0.08
                elif insight.direction == "bearish":
                    score -= 0.04
                if insight.anomaly_flag == "above_normal_move":
                    score += 0.05
                elif insight.anomaly_flag == "elevated_volatility":
                    score += 0.03

            score = self._clamp(score, floor=0.16, ceiling=0.84)
            weight = self.MARKET_WEIGHTS.get(snapshot.market.lower(), 0.5)
            weighted_scores += score * weight
            total_weight += weight
            evidence.append(
                f"{snapshot.market.capitalize()} futures are {self._direction_word(snapshot.change_percent)} "
                f"{abs(snapshot.change_percent):.2f}% on the session"
            )

        if total_weight == 0:
            return 0.40, evidence
        return round(weighted_scores / total_weight, 4), evidence

    def _supply_risk(
        self,
        *,
        weather_risk: float,
        news_score: float,
        futures_pressure: float,
        correlations: MarketCorrelationResponse | None,
        futures_evidence: list[str],
        news_evidence: list[str],
    ) -> tuple[float, str, list[str]]:
        score = self._clamp(
            (weather_risk * 0.42) + (news_score * 0.33) + (futures_pressure * 0.25),
            floor=0.0,
            ceiling=0.94,
        )
        if correlations is not None and correlations.insights:
            bullish_alignment = sum(1 for insight in correlations.insights if insight.direction == "bullish")
            bearish_alignment = sum(1 for insight in correlations.insights if insight.direction == "bearish")
            if bullish_alignment and bullish_alignment >= bearish_alignment:
                score = self._clamp(score + 0.04, floor=0.0, ceiling=0.94)

        if score >= 0.72:
            summary = "supply-side risk is elevated as weather, news, and futures are reinforcing tighter availability"
        elif score >= 0.52:
            summary = "supply-side risk is edging higher as weather and market signals firm up"
        else:
            summary = "supply-side risk remains mixed rather than decisively tight"

        evidence = [*futures_evidence[:2], *news_evidence[:2]]
        return round(score, 4), summary, evidence

    def _confidence(
        self,
        *,
        futures_snapshots: list[HistoricalFuturesSnapshot],
        weather_context: dict[str, list],
        news_articles: list[NewsArticle],
        correlations: MarketCorrelationResponse | None,
        scores: list[float],
    ) -> float:
        coverage = 0
        if futures_snapshots:
            coverage += 1
        if any(weather_context.values()) if weather_context else False:
            coverage += 1
        if news_articles:
            coverage += 1
        if correlations is not None and correlations.insights:
            coverage += 1

        alignment = 0.0
        high_scores = sum(1 for score in scores if score >= 0.60)
        if high_scores >= 2:
            alignment += 0.12
        if scores and (max(scores) - min(scores)) <= 0.18:
            alignment += 0.06
        if coverage >= 3:
            alignment += 0.04

        confidence = self._clamp(0.40 + (coverage * 0.09) + alignment, floor=0.25, ceiling=0.95)
        return round(confidence, 2)

    def _build_explanation(self, *, market_risk: str, factors: list[RiskFactorScore]) -> str:
        leading_factors = sorted(
            factors,
            key=lambda factor: factor.score * factor.weight,
            reverse=True,
        )
        reasons = [factor.summary for factor in leading_factors if factor.score >= 0.48][:2]
        if not reasons:
            reasons = [leading_factors[0].summary] if leading_factors else ["signals remain mixed"]

        intro = {
            "HIGH": "Current coffee market risk is elevated",
            "MODERATE": "Current coffee market risk is firming",
            "LOW": "Current coffee market risk is comparatively contained",
        }.get(market_risk, "Current coffee market risk is mixed")

        if len(reasons) >= 2:
            return f"{intro} due to {reasons[0]} and {reasons[1]}."
        return f"{intro} due to {reasons[0]}."

    def _is_relevant_article(self, article: NewsArticle) -> bool:
        lowered = f"{article.title} {article.summary}".lower()
        return any(keyword in lowered for keyword in self.NEWS_KEYWORDS)

    def _risk_label(self, score: float) -> str:
        if score >= 0.72:
            return "HIGH"
        if score >= 0.48:
            return "MODERATE"
        return "LOW"

    def _direction_word(self, change_percent: float) -> str:
        if change_percent > 0.15:
            return "up"
        if change_percent < -0.15:
            return "down"
        return "little changed"

    def _count_terms(self, text: str, terms: tuple[str, ...]) -> int:
        return sum(text.count(term) for term in terms)

    def _average(self, values: list[float]) -> float:
        filtered = [value for value in values if value is not None]
        if not filtered:
            return 0.0
        return sum(filtered) / len(filtered)

    def _clamp(self, value: float, floor: float = 0.0, ceiling: float = 1.0) -> float:
        return min(max(value, floor), ceiling)
