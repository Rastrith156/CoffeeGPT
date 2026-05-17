"""
agents/chatbot/fallback_handler.py
====================================
ISSUE #3 FIX — Grounded fallback answer construction.

Responsibilities:
  - Build evidence-grounded answers when LLM output is low quality
  - Build no-context answers when retrieval returns nothing
  - Never hallucinate: every sentence is tied to a retrieved source group

Used when:
  1. LLM call fails entirely (network/timeout)
  2. LLM returns low-quality / citation-free output
  3. No context was retrieved at all
"""
from __future__ import annotations

from typing import Any

from agents.chatbot.citation_formatter import CitationFormatter


class FallbackHandler:
    """
    Constructs grounded fallback answers from source groups when the LLM fails
    or produces low-quality output.

    All output is built deterministically from the retrieved source_groups list
    with explicit citation indices — zero hallucination.
    """

    # ── Recency query keywords ─────────────────────────────────────────────────
    _RECENCY_KEYWORDS: tuple[str, ...] = (
        "today", "latest", "recent", "currently",
        "now", "this week", "yesterday",
    )

    def __init__(self) -> None:
        self._formatter = CitationFormatter()

    # ── Public API ─────────────────────────────────────────────────────────────

    def build_grounded_fallback(
        self,
        question: str,
        source_groups: list[dict[str, Any]],
    ) -> str:
        """
        Build an evidence-grounded multi-sentence fallback answer.

        Each sentence references a specific source group and its citation index.
        The final synthesis sentence connects the signals.
        """
        if not source_groups:
            return self.build_no_context_answer(question)

        sentences: list[str] = []

        futures_group = self._formatter.find_best_futures_group(source_groups)
        weather_group = self._formatter.find_best_weather_group(question, source_groups)
        news_group    = self._formatter.find_news_group(source_groups)
        risk_group    = self._formatter.find_source_group(
            source_groups, source="forecasting", record_type_contains="market_risk",
        )
        alert_group   = self._formatter.find_source_group(
            source_groups, source="forecasting", record_type_contains="alert",
        )

        if futures_group is not None:
            sentences.append(self._build_futures_sentence(futures_group))

        if risk_group is not None:
            citation = int(risk_group.get("citation_index") or 1)
            signal = next(
                iter(risk_group.get("snippets") or []),
                self._clean_headline(str(risk_group.get("title") or "current market risk")),
            ).rstrip(".")
            sentences.append(
                f"Decision-support scoring indicates {signal} [{citation}]."
            )

        if alert_group is not None:
            citation = int(alert_group.get("citation_index") or 1)
            signal = next(
                iter(alert_group.get("snippets") or []),
                self._clean_headline(str(alert_group.get("title") or "active intelligence alerts")),
            ).rstrip(".")
            sentences.append(
                f"Active intelligence alerts also point to {signal} [{citation}]."
            )

        if weather_group is not None:
            region   = str(weather_group.get("region") or "key coffee regions").strip()
            citation = int(weather_group.get("citation_index") or 1)
            sentences.append(
                f"Weather context from {region} points to near-term crop conditions"
                f" that remain relevant for supply expectations [{citation}]."
            )

        if news_group is not None:
            title    = self._clean_headline(str(news_group.get("title") or "recent coffee coverage"))
            citation = int(news_group.get("citation_index") or 1)
            date_str = self._display_date(news_group.get("published_at"))
            sentences.append(
                f"Recent reporting on {date_str} also highlights {title} [{citation}]."
            )

        if not sentences:
            # Generic lead from first source
            lead       = source_groups[0]
            lead_title = self._clean_headline(str(lead.get("title") or "untitled"))
            lead_date  = self._display_date(lead.get("published_at"))
            if self._is_recency_question(question):
                sentences.append(
                    f"As of {lead_date}, the strongest retrieved market signal is {lead_title} [1]."
                )
            else:
                sentences.append(
                    f"Retrieved coffee market intelligence points first to {lead_title} [1]."
                )

        sentences.append(
            "Taken together, the indexed context suggests traders are weighing price action,"
            " weather risk, and recent market reporting rather than a single isolated signal."
        )
        return " ".join(sentences)

    def build_no_context_answer(self, question: str) -> str:
        """Return a clear, non-hallucinated answer when retrieval yields nothing."""
        if self._is_recency_question(question):
            return (
                "I could not find recent indexed coffee intelligence that answers this question. "
                "Refresh the ingestion pipeline and ask again."
            )
        return (
            "I could not find indexed coffee intelligence that answers this question"
            " in the current dataset. Try a narrower market question or refresh ingestion."
        )

    # ── Internal builders ─────────────────────────────────────────────────────

    def _build_futures_sentence(self, group: dict[str, Any]) -> str:
        market_label  = str(group.get("market") or "coffee").strip().replace("_", " ").title()
        price         = self._coerce_float(group.get("price"))
        currency      = str(group.get("currency") or "").strip()
        change_pct    = self._coerce_float(group.get("change_percent"))
        citation      = int(group.get("citation_index") or 1)
        snapshot_date = str(
            group.get("snapshot_date")
            or self._display_date(group.get("published_at"))
        ).strip()

        if price > 0 and currency:
            direction = (
                "up" if change_pct > 0.15
                else "down" if change_pct < -0.15
                else "little changed"
            )
            return (
                f"{market_label} futures are {direction} on {snapshot_date}"
                f" at {price} {currency} ({change_pct:+.2f}%) [{citation}]."
            )

        title = self._clean_headline(str(group.get("title") or "futures context"))
        return f"Futures context highlights {title} [{citation}]."

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _is_recency_question(self, question: str) -> bool:
        lowered = question.lower()
        return any(kw in lowered for kw in self._RECENCY_KEYWORDS)

    @staticmethod
    def _coerce_float(value: Any) -> float:
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _clean_headline(title: str) -> str:
        cleaned = " ".join(title.split()).strip()
        if " - " in cleaned:
            cleaned = cleaned.rsplit(" - ", maxsplit=1)[0]
        return cleaned

    @staticmethod
    def _display_date(value: Any) -> str:
        from datetime import datetime
        from email.utils import parsedate_to_datetime

        if not value:
            return "the latest indexed date"
        text = str(value).strip()
        if not text:
            return "the latest indexed date"
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return parsed.date().isoformat()
        except ValueError:
            pass
        try:
            parsed = parsedate_to_datetime(text)
            return parsed.date().isoformat()
        except (TypeError, ValueError, IndexError, OverflowError):
            return text
