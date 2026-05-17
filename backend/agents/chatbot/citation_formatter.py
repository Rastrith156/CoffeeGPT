"""
agents/chatbot/citation_formatter.py
======================================
ISSUE #3 FIX — Source group search and citation formatting helpers.

Responsibilities:
  - Find best futures / weather / news / risk source groups
  - Generic source group lookup by type/source name
"""
from __future__ import annotations

from typing import Any


class CitationFormatter:
    """
    Provides structured source-group lookup helpers consumed by FallbackHandler
    and the main CoffeeChatbotAgent answer pipeline.

    All methods are stateless and operate on pre-built source_groups lists.
    """

    # ── Group finders ─────────────────────────────────────────────────────────

    def find_source_group(
        self,
        source_groups: list[dict[str, Any]],
        *,
        source: str | None = None,
        record_type_contains: str | None = None,
    ) -> dict[str, Any] | None:
        """
        Return the first group matching both optional filters.

        Args:
            source_groups:        Ordered list of source-group dicts.
            source:               Exact source name match (case-insensitive).
            record_type_contains: Substring match on record_type.
        """
        for group in source_groups:
            source_name = str(group.get("source") or "").strip().lower()
            record_type = str(group.get("record_type") or "").strip().lower()
            matches_source = source is None or source_name == source.lower()
            matches_type = (
                record_type_contains is None
                or record_type_contains.lower() in record_type
            )
            if matches_source and matches_type:
                return group
        return None

    def find_news_group(
        self, source_groups: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        """Return first group whose source starts with 'news' or is 'bootstrap_news'."""
        for group in source_groups:
            src = str(group.get("source") or "").strip().lower()
            if src.startswith("news") or src == "bootstrap_news":
                return group
        return None

    def find_best_futures_group(
        self, source_groups: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        """
        Return the best futures group.

        Prefers a group with a non-zero price; falls back to the first
        futures group if none have price data.
        """
        futures_groups = [
            g
            for g in source_groups
            if str(g.get("source") or "").strip().lower() == "futures"
        ]
        if not futures_groups:
            return None
        priced = next(
            (g for g in futures_groups if self._coerce_float(g.get("price")) > 0),
            None,
        )
        return priced if priced is not None else futures_groups[0]

    def find_best_weather_group(
        self,
        question: str,
        source_groups: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """
        Return the best weather group for the query.

        Priority:
          1. Region mentioned in the question
          2. Forecast/outlook type
          3. First available weather group
        """
        weather_groups = [
            g
            for g in source_groups
            if str(g.get("source") or "").strip().lower() == "weather"
        ]
        if not weather_groups:
            return None

        lowered_q = question.lower()

        # Priority 1: region match
        region_match = next(
            (
                g
                for g in weather_groups
                if str(g.get("region") or "").strip().lower() in lowered_q
            ),
            None,
        )
        if region_match is not None:
            return region_match

        # Priority 2: forecast/outlook type
        forecast_match = next(
            (
                g
                for g in weather_groups
                if "forecast" in str(g.get("record_type") or "").lower()
                or "outlook" in str(g.get("title") or "").lower()
            ),
            None,
        )
        return forecast_match if forecast_match is not None else weather_groups[0]

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _coerce_float(value: Any) -> float:
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0
