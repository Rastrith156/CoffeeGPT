from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from core.config import settings
from models.schemas import (
    AlertFeedResponse,
    HistoricalFuturesSnapshot,
    IntelligenceAlert,
    MarketCorrelationResponse,
    MarketRiskAssessmentResponse,
    NewsArticle,
)


class AlertEngine:
    MARKET_HISTORY_DIRNAME = "futures_history"
    ALERT_HISTORY_DIRNAME = "decision_support_alerts"
    MARKET_LABELS = {
        "arabica": "Arabica",
        "robusta": "Robusta",
    }

    def __init__(
        self,
        *,
        futures_history_root: Path | None = None,
        alert_history_root: Path | None = None,
    ) -> None:
        self.futures_history_root = futures_history_root or (settings.processed_data_dir / self.MARKET_HISTORY_DIRNAME)
        self.alert_history_root = alert_history_root or (settings.processed_data_dir / self.ALERT_HISTORY_DIRNAME)

    def generate(
        self,
        *,
        futures_snapshots: list[HistoricalFuturesSnapshot],
        weather_context: dict[str, list],
        news_articles: list[NewsArticle],
        risk_assessment: MarketRiskAssessmentResponse | None = None,
        correlations: MarketCorrelationResponse | None = None,
        generated_at: datetime | None = None,
    ) -> AlertFeedResponse:
        generated_at = generated_at or datetime.now(timezone.utc)
        history_map = self._load_history(limit=120)

        alerts: list[IntelligenceAlert] = []
        alerts.extend(self._weather_alerts(weather_context=weather_context, generated_at=generated_at))
        alerts.extend(
            self._volatility_alerts(
                futures_snapshots=futures_snapshots,
                history_map=history_map,
                generated_at=generated_at,
            )
        )
        alerts.extend(
            self._momentum_alerts(
                futures_snapshots=futures_snapshots,
                correlations=correlations,
                generated_at=generated_at,
            )
        )
        alerts.extend(
            self._news_supply_alerts(
                news_articles=news_articles,
                generated_at=generated_at,
            )
        )
        if risk_assessment is not None:
            alerts.extend(self._risk_regime_alerts(risk_assessment=risk_assessment, generated_at=generated_at))

        alerts = self._deduplicate(alerts)
        alerts.sort(key=lambda alert: (self._severity_rank(alert.severity), alert.confidence), reverse=True)
        alerts = alerts[:6]

        return AlertFeedResponse(
            generated_at=generated_at,
            summary=self._summary(alerts, risk_assessment),
            count=len(alerts),
            alerts=alerts,
            service_mode="heuristic_alert_engine",
        )

    def build_retrieval_records(
        self,
        *,
        risk_assessment: MarketRiskAssessmentResponse | None,
        alert_feed: AlertFeedResponse | None,
    ) -> list[dict]:
        records: list[dict] = []

        if risk_assessment is not None:
            snapshot_date = risk_assessment.generated_at.date().isoformat()
            records.append(
                {
                    "title": "Coffee market risk assessment",
                    "content": "\n".join(
                        (
                            risk_assessment.explanation,
                            f"Market risk: {risk_assessment.market_risk} ({risk_assessment.market_risk_score:.2f})",
                            f"Weather risk: {risk_assessment.weather_risk:.2f}",
                            f"Supply risk: {risk_assessment.supply_risk:.2f}",
                            f"Volatility risk: {risk_assessment.volatility_risk:.2f}",
                            f"Confidence: {risk_assessment.confidence:.2f}",
                        )
                    ),
                    "record_type": "market_risk_assessment",
                    "raw": risk_assessment.model_dump(mode="json"),
                    "metadata": {
                        "source": "forecasting",
                        "title": "Coffee market risk assessment",
                        "document_id": f"market_risk::global::{snapshot_date}",
                        "market": "global",
                        "published_at": risk_assessment.generated_at.isoformat(),
                        "snapshot_date": snapshot_date,
                        "risk_level": risk_assessment.market_risk,
                        "confidence": risk_assessment.confidence,
                    },
                }
            )

        if alert_feed is None:
            return records

        for alert in alert_feed.alerts:
            snapshot_date = alert.triggered_at.date().isoformat()
            market = alert.market or "global"
            records.append(
                {
                    "title": alert.title,
                    "content": "\n".join(
                        (
                            alert.title,
                            alert.message,
                            f"Severity: {alert.severity}",
                            f"Category: {alert.category}",
                            f"Confidence: {alert.confidence:.2f}",
                        )
                    ),
                    "record_type": "market_intelligence_alert",
                    "raw": alert.model_dump(mode="json"),
                    "metadata": {
                        "source": "forecasting",
                        "title": alert.title,
                        "document_id": f"market_alert::{alert.alert_id}",
                        "market": market,
                        "region": alert.region,
                        "published_at": alert.triggered_at.isoformat(),
                        "snapshot_date": snapshot_date,
                        "severity": alert.severity,
                        "category": alert.category,
                    },
                }
            )

        return records

    def persist_alert_memory(self, alert_feed: AlertFeedResponse) -> dict[str, int | list[str]]:
        settings.ensure_directories()
        daily_dir = self.alert_history_root / "daily"
        market_dir = self.alert_history_root / "markets"
        daily_dir.mkdir(parents=True, exist_ok=True)
        market_dir.mkdir(parents=True, exist_ok=True)

        additions_by_date: dict[str, list[dict]] = {}
        existing_market_ids: dict[str, set[str]] = {}
        persisted = 0
        skipped = 0
        updated_market_files: set[str] = set()

        for alert in alert_feed.alerts:
            market_key = (alert.market or "global").strip().lower() or "global"
            market_path = market_dir / f"{market_key}.jsonl"
            seen_ids = existing_market_ids.setdefault(market_key, self._existing_alert_ids(market_path))
            if alert.alert_id in seen_ids:
                skipped += 1
                continue

            payload = alert.model_dump(mode="json")
            with market_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload) + "\n")

            seen_ids.add(alert.alert_id)
            snapshot_date = alert.triggered_at.date().isoformat()
            additions_by_date.setdefault(snapshot_date, []).append(payload)
            updated_market_files.add(market_path.name)
            persisted += 1

        updated_daily_files: list[str] = []
        for snapshot_date, entries in sorted(additions_by_date.items()):
            daily_path = daily_dir / f"{snapshot_date}.json"
            existing_entries = self._load_daily_entries(daily_path)
            existing_ids = {str(item.get("alert_id") or "").strip() for item in existing_entries}
            merged_entries = list(existing_entries)
            for entry in entries:
                alert_id = str(entry.get("alert_id") or "").strip()
                if not alert_id or alert_id in existing_ids:
                    continue
                existing_ids.add(alert_id)
                merged_entries.append(entry)

            merged_entries.sort(
                key=lambda item: (
                    self._severity_rank(str(item.get("severity") or "LOW")),
                    self._coerce_float(item.get("confidence")),
                ),
                reverse=True,
            )
            daily_path.write_text(json.dumps(merged_entries, indent=2), encoding="utf-8")
            updated_daily_files.append(daily_path.name)

        return {
            "alerts_detected": len(alert_feed.alerts),
            "alerts_persisted": persisted,
            "alerts_skipped": skipped,
            "daily_files_updated": updated_daily_files,
            "market_files_updated": sorted(updated_market_files),
        }

    def _weather_alerts(
        self,
        *,
        weather_context: dict[str, list],
        generated_at: datetime,
    ) -> list[IntelligenceAlert]:
        alerts: list[IntelligenceAlert] = []
        for market, snapshots in weather_context.items():
            if not snapshots:
                continue

            rainfall_values: list[float] = []
            humidity_values: list[float] = []
            probability_values: list[float] = []
            temperatures: list[float] = []
            regions: list[str] = []

            for snapshot in snapshots:
                rainfall_values.append(sum(point.rainfall_mm for point in snapshot.forecast.forecast[:3]))
                humidity_values.append(snapshot.current.humidity_pct)
                probability_values.append(
                    max((point.precipitation_probability_pct for point in snapshot.forecast.forecast[:3]), default=0.0)
                )
                temperatures.append(
                    min([snapshot.current.temperature_c, *[point.temp_c for point in snapshot.forecast.forecast[:3]]])
                )
                regions.append(snapshot.profile.name)

            avg_rainfall = self._average(rainfall_values)
            avg_humidity = self._average(humidity_values)
            avg_probability = self._average(probability_values)
            min_temp = min(temperatures) if temperatures else 0.0

            if market == "arabica" and min_temp <= 4:
                alerts.append(
                    self._alert(
                        title="Frost risk may hit Brazil Arabica zones.",
                        message=(
                            f"Minimum projected temperatures near {min_temp:.1f} C across {', '.join(regions)} "
                            "could tighten nearby Arabica availability."
                        ),
                        severity="HIGH",
                        category="weather",
                        market=market,
                        region=regions[0] if regions else None,
                        confidence=0.89,
                        supporting_signals={"min_temp_c": round(min_temp, 1)},
                        triggered_at=generated_at,
                    )
                )
                continue

            if avg_rainfall >= 18 or avg_probability >= 72:
                origin = "Brazil" if market == "arabica" else "Vietnam" if market == "robusta" else market.title()
                crop_label = "harvest conditions" if market == "arabica" else "harvest and drying conditions"
                severity = "HIGH" if avg_rainfall >= 22 or avg_probability >= 82 else "MEDIUM"
                alerts.append(
                    self._alert(
                        title=f"Heavy rainfall may disrupt {origin} {crop_label}.",
                        message=(
                            f"Average three-day rainfall is {avg_rainfall:.1f} mm with precipitation probability near "
                            f"{avg_probability:.0f}% across {', '.join(regions)}."
                        ),
                        severity=severity,
                        category="weather",
                        market=market,
                        region=regions[0] if regions else None,
                        confidence=0.84 if severity == "HIGH" else 0.73,
                        supporting_signals={
                            "rainfall_mm_3d": round(avg_rainfall, 2),
                            "precip_probability_pct": round(avg_probability, 1),
                            "humidity_pct": round(avg_humidity, 1),
                        },
                        triggered_at=generated_at,
                    )
                )
            elif avg_rainfall <= 2.5 and avg_humidity <= 68:
                origin = "Brazil" if market == "arabica" else "Vietnam" if market == "robusta" else market.title()
                alerts.append(
                    self._alert(
                        title=f"Dry spell may stress {origin} coffee conditions.",
                        message=(
                            f"Average three-day rainfall is only {avg_rainfall:.1f} mm with humidity near "
                            f"{avg_humidity:.0f}% across {', '.join(regions)}."
                        ),
                        severity="MEDIUM",
                        category="weather",
                        market=market,
                        region=regions[0] if regions else None,
                        confidence=0.69,
                        supporting_signals={
                            "rainfall_mm_3d": round(avg_rainfall, 2),
                            "humidity_pct": round(avg_humidity, 1),
                        },
                        triggered_at=generated_at,
                    )
                )
        return alerts

    def _volatility_alerts(
        self,
        *,
        futures_snapshots: list[HistoricalFuturesSnapshot],
        history_map: dict[str, list[HistoricalFuturesSnapshot]],
        generated_at: datetime,
    ) -> list[IntelligenceAlert]:
        alerts: list[IntelligenceAlert] = []
        for snapshot in futures_snapshots:
            history = [
                item
                for item in history_map.get(snapshot.market.lower(), [])
                if item.snapshot_date and item.snapshot_date != snapshot.snapshot_date
            ][-30:]
            avg_volatility = self._average([item.volatility for item in history])
            avg_abs_change = self._average([abs(item.change_percent) for item in history])
            volatility_ratio = snapshot.volatility / avg_volatility if avg_volatility > 0 else 0.0
            unusual_move_ratio = abs(snapshot.change_percent) / avg_abs_change if avg_abs_change > 0 else 0.0
            market_label = self.MARKET_LABELS.get(snapshot.market.lower(), snapshot.market.capitalize())

            if volatility_ratio >= 1.25 or snapshot.volatility >= 2.2:
                alerts.append(
                    self._alert(
                        title=f"{market_label} volatility exceeds the 30-day average.",
                        message=(
                            f"{market_label} session volatility is {snapshot.volatility:.2f}% versus a recent average "
                            f"near {avg_volatility:.2f}%."
                        ),
                        severity="HIGH" if volatility_ratio >= 1.45 or snapshot.volatility >= 2.5 else "MEDIUM",
                        category="volatility",
                        market=snapshot.market,
                        confidence=0.82 if volatility_ratio >= 1.45 else 0.72,
                        supporting_signals={
                            "volatility_pct": round(snapshot.volatility, 2),
                            "volatility_ratio": round(volatility_ratio, 2),
                        },
                        triggered_at=generated_at,
                    )
                )
            elif unusual_move_ratio >= 1.6 or abs(snapshot.change_percent) >= 1.4:
                alerts.append(
                    self._alert(
                        title=f"{market_label} futures move is running above normal daily range.",
                        message=(
                            f"{market_label} moved {snapshot.change_percent:+.2f}% against a recent average absolute "
                            f"move near {avg_abs_change:.2f}%."
                        ),
                        severity="MEDIUM",
                        category="volatility",
                        market=snapshot.market,
                        confidence=0.70,
                        supporting_signals={
                            "change_percent": round(snapshot.change_percent, 2),
                            "unusual_move_ratio": round(unusual_move_ratio, 2),
                        },
                        triggered_at=generated_at,
                    )
                )
        return alerts

    def _momentum_alerts(
        self,
        *,
        futures_snapshots: list[HistoricalFuturesSnapshot],
        correlations: MarketCorrelationResponse | None,
        generated_at: datetime,
    ) -> list[IntelligenceAlert]:
        alerts: list[IntelligenceAlert] = []
        insight_map = {
            insight.market.lower(): insight
            for insight in (correlations.insights if correlations is not None else [])
        }

        for snapshot in futures_snapshots:
            insight = insight_map.get(snapshot.market.lower())
            if insight is None:
                continue

            market_label = self.MARKET_LABELS.get(snapshot.market.lower(), snapshot.market.capitalize())
            if insight.direction == "bullish" and snapshot.change_percent >= 0.7:
                alerts.append(
                    self._alert(
                        title=f"{market_label} futures momentum is turning bullish.",
                        message=(
                            f"{market_label} is up {snapshot.change_percent:+.2f}% with causal signals pointing to "
                            f"{insight.causal_summary.lower()}"
                        ),
                        severity="MEDIUM" if snapshot.change_percent < 1.4 else "HIGH",
                        category="momentum",
                        market=snapshot.market,
                        confidence=min(0.9, max(0.68, insight.confidence)),
                        supporting_signals={
                            "change_percent": round(snapshot.change_percent, 2),
                            "direction": insight.direction,
                        },
                        triggered_at=generated_at,
                    )
                )
            elif insight.direction == "bearish" and snapshot.change_percent <= -0.7:
                alerts.append(
                    self._alert(
                        title=f"{market_label} futures momentum is turning defensive.",
                        message=(
                            f"{market_label} is down {snapshot.change_percent:+.2f}% while the causal signal set "
                            "leans bearish."
                        ),
                        severity="MEDIUM",
                        category="momentum",
                        market=snapshot.market,
                        confidence=min(0.85, max(0.66, insight.confidence)),
                        supporting_signals={
                            "change_percent": round(snapshot.change_percent, 2),
                            "direction": insight.direction,
                        },
                        triggered_at=generated_at,
                    )
                )

        return alerts

    def _news_supply_alerts(
        self,
        *,
        news_articles: list[NewsArticle],
        generated_at: datetime,
    ) -> list[IntelligenceAlert]:
        for article in news_articles[:5]:
            lowered = f"{article.title} {article.summary}".lower()
            if any(term in lowered for term in ("rainfall", "delay", "delays", "tight", "shortfall", "disruption")):
                return [
                    self._alert(
                        title="Supply headlines are reinforcing upside coffee risk.",
                        message=article.title,
                        severity="MEDIUM",
                        category="news",
                        market="global",
                        confidence=0.68,
                        supporting_signals={"headline": article.title},
                        triggered_at=generated_at,
                    )
                ]
        return []

    def _risk_regime_alerts(
        self,
        *,
        risk_assessment: MarketRiskAssessmentResponse,
        generated_at: datetime,
    ) -> list[IntelligenceAlert]:
        if risk_assessment.market_risk == "HIGH":
            return [
                self._alert(
                    title="Coffee market risk regime has shifted higher.",
                    message=risk_assessment.explanation,
                    severity="HIGH",
                    category="risk_regime",
                    market="global",
                    confidence=risk_assessment.confidence,
                    supporting_signals={"market_risk_score": risk_assessment.market_risk_score},
                    triggered_at=generated_at,
                )
            ]
        if risk_assessment.market_risk == "MODERATE" and risk_assessment.market_risk_score >= 0.60:
            return [
                self._alert(
                    title="Coffee market risk is trending firmer.",
                    message=risk_assessment.explanation,
                    severity="MEDIUM",
                    category="risk_regime",
                    market="global",
                    confidence=risk_assessment.confidence,
                    supporting_signals={"market_risk_score": risk_assessment.market_risk_score},
                    triggered_at=generated_at,
                )
            ]
        return []

    def _summary(
        self,
        alerts: list[IntelligenceAlert],
        risk_assessment: MarketRiskAssessmentResponse | None,
    ) -> str:
        if not alerts:
            if risk_assessment is None:
                return "No proactive market intelligence alerts are active."
            return (
                f"No active threshold alerts were triggered, though headline market risk remains "
                f"{risk_assessment.market_risk.lower()}."
            )

        dominant_category = max(
            alerts,
            key=lambda alert: (self._severity_rank(alert.severity), alert.confidence),
        ).category
        return (
            f"{len(alerts)} active intelligence alerts are on the board, led by "
            f"{dominant_category.replace('_', ' ')} signals."
        )

    def _load_history(
        self,
        *,
        market: str | None = None,
        limit: int = 90,
    ) -> dict[str, list[HistoricalFuturesSnapshot]]:
        markets = [market.lower()] if market else ("arabica", "robusta")
        history: dict[str, list[HistoricalFuturesSnapshot]] = {}

        for market_key in markets:
            path = self.futures_history_root / "markets" / f"{market_key}.jsonl"
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

    def _existing_alert_ids(self, market_path: Path) -> set[str]:
        if not market_path.exists():
            return set()

        alert_ids: set[str] = set()
        try:
            for line in market_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                payload = json.loads(line)
                alert_id = str(payload.get("alert_id") or "").strip()
                if alert_id:
                    alert_ids.add(alert_id)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return set()
        return alert_ids

    def _load_daily_entries(self, daily_path: Path) -> list[dict]:
        if not daily_path.exists():
            return []
        try:
            payload = json.loads(daily_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return payload if isinstance(payload, list) else []

    def _alert(
        self,
        *,
        title: str,
        message: str,
        severity: str,
        category: str,
        market: str | None = None,
        region: str | None = None,
        confidence: float,
        supporting_signals: dict[str, str | float] | None = None,
        triggered_at: datetime,
    ) -> IntelligenceAlert:
        market_key = (market or "global").strip().lower() or "global"
        seed = "\n".join(
            [
                triggered_at.date().isoformat(),
                market_key,
                category,
                title,
            ]
        )
        return IntelligenceAlert(
            alert_id=str(uuid5(NAMESPACE_URL, seed)),
            title=title,
            message=message,
            severity=severity,
            category=category,
            market=market,
            region=region,
            confidence=round(confidence, 2),
            supporting_signals=supporting_signals or {},
            triggered_at=triggered_at,
            service_mode="heuristic_alert_engine",
        )

    def _deduplicate(self, alerts: list[IntelligenceAlert]) -> list[IntelligenceAlert]:
        deduped: list[IntelligenceAlert] = []
        seen_ids: set[str] = set()
        for alert in alerts:
            if alert.alert_id in seen_ids:
                continue
            seen_ids.add(alert.alert_id)
            deduped.append(alert)
        return deduped

    def _severity_rank(self, severity: str) -> int:
        normalized = str(severity or "").strip().upper()
        return {
            "HIGH": 3,
            "MEDIUM": 2,
            "LOW": 1,
        }.get(normalized, 0)

    def _average(self, values: list[float]) -> float:
        filtered = [value for value in values if value is not None]
        if not filtered:
            return 0.0
        return sum(filtered) / len(filtered)

    def _coerce_float(self, value) -> float:
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0
