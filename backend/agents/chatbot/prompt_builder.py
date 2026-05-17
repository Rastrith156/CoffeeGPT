"""
agents/chatbot/prompt_builder.py
=================================
ISSUE #3 FIX: Extracted prompt construction logic from chatbot_agent.py

Responsibilities:
  - Build user input prompts with context
  - Format retrieved documents into context blocks
  - Handle recency-based sorting
  - Integrate live Redis data
"""
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from core.config import settings
from models.schemas import SourceCitation


RECENCY_KEYWORDS = (
    "today",
    "latest",
    "recent",
    "currently",
    "now",
    "this week",
    "yesterday",
)


class PromptBuilder:
    """Constructs LLM prompts with retrieved context and metadata."""

    def __init__(self) -> None:
        pass

    def build_context(
        self,
        question: str,
        documents: list,
    ) -> tuple[str, list[SourceCitation], list[dict[str, Any]]]:
        """
        Build formatted context from retrieved documents.
        
        Returns:
            (context_string, citations, ordered_source_groups)
        """
        grouped_sources: dict[tuple[str, str | None, str | None, str | None], dict[str, Any]] = {}

        for document in documents:
            source = str(document.metadata.get("source", "unknown")).strip()
            title = self._clean_headline(str(document.metadata.get("title") or "untitled"))
            record_type = str(document.metadata.get("record_type") or "general").strip()
            url = str(document.metadata.get("url") or "").strip() or None
            market = str(document.metadata.get("market") or "").strip() or None
            region = str(document.metadata.get("region") or "").strip() or None
            snapshot_date = str(document.metadata.get("snapshot_date") or "").strip() or None
            key = (source, title, record_type, url or snapshot_date or market or region)

            group = grouped_sources.setdefault(
                key,
                {
                    "source": source,
                    "title": title,
                    "record_type": record_type,
                    "url": url,
                    "market": market,
                    "region": region,
                    "price": document.metadata.get("price"),
                    "currency": document.metadata.get("currency"),
                    "change_percent": document.metadata.get("change_percent"),
                    "volatility_pct": document.metadata.get("volatility_pct"),
                    "snapshot_date": snapshot_date,
                    "published_at": document.metadata.get("published_at"),
                    "rank_score": self._coerce_float(
                        document.metadata.get("rerank_score") or document.metadata.get("score")
                    ),
                    "snippets": [],
                },
            )
            group["rank_score"] = max(
                self._coerce_float(group.get("rank_score")),
                self._coerce_float(document.metadata.get("rerank_score") or document.metadata.get("score")),
            )
            group["published_at"] = self._preferred_date(group.get("published_at"), document.metadata.get("published_at"))

            snippet = self._clean_context_text(document.page_content, title)
            if snippet and snippet not in group["snippets"]:
                group["snippets"].append(snippet)

        recency_first = self._is_recency_question(question)
        ordered_sources = sorted(
            grouped_sources.values(),
            key=lambda g: self._sort_key(
                g.get("published_at"), g.get("rank_score"), recency_first=recency_first
            ),
            reverse=True,
        )[: settings.rag_top_k]

        context_blocks: list[str] = []
        citations: list[SourceCitation] = []
        for index, source_group in enumerate(ordered_sources, start=1):
            source_group["citation_index"] = index
            citations.append(
                SourceCitation(
                    source=str(source_group.get("source") or "unknown"),
                    title=str(source_group.get("title") or "untitled"),
                    record_type=str(source_group.get("record_type") or "general"),
                )
            )

            context_lines = [
                f"[{index}]",
                f"source: {source_group.get('source') or 'unknown'}",
                f"title: {source_group.get('title') or 'untitled'}",
                f"type: {source_group.get('record_type') or 'general'}",
            ]
            market = source_group.get("market")
            if market:
                context_lines.append(f"market: {market}")
            region = source_group.get("region")
            if region:
                context_lines.append(f"region: {region}")
            published_at = source_group.get("published_at")
            if published_at:
                context_lines.append(f"published_at: {published_at}")
            snapshot_date = source_group.get("snapshot_date")
            if snapshot_date:
                context_lines.append(f"snapshot_date: {snapshot_date}")

            price = self._coerce_float(source_group.get("price"))
            change_percent = self._coerce_float(source_group.get("change_percent"))
            volatility_pct = self._coerce_float(source_group.get("volatility_pct"))
            currency = str(source_group.get("currency") or "").strip()
            if price > 0:
                context_lines.append(f"price: {price} {currency}".strip())
            if change_percent != 0.0:
                context_lines.append(f"change_percent: {change_percent:+.2f}")
            if volatility_pct > 0:
                context_lines.append(f"volatility_pct: {volatility_pct:.2f}")
            url = source_group.get("url")
            if url:
                context_lines.append(f"url: {url}")
            snippets = list(source_group.get("snippets") or [])[:2]
            if snippets:
                context_lines.append("evidence:")
                for snippet in snippets:
                    context_lines.append(f"- {snippet}")
            context_blocks.append("\n".join(context_lines))

        return "\n\n".join(context_blocks), citations, ordered_sources

    def build_user_input(
        self,
        question: str,
        context: str,
        prior_context: str = "",
    ) -> str:
        """Build the final user input prompt for the LLM."""
        current_date = datetime.now(timezone.utc).date().isoformat()
        base_input = (
            "Use only the retrieved context below.\n"
            "Rules:\n"
            "- Answer directly in 4-6 sentences.\n"
            "- Sound like a coffee market intelligence analyst, not a generic chatbot.\n"
            "- Base every factual claim on the supplied context only.\n"
            "- Do not mention missing access, missing browsing, training data, or system limitations.\n"
            "- Do not add a Sources or References section.\n"
            "- Cite evidence with bracketed source numbers like [1].\n"
            "- When futures, weather, and news are all present, connect them into one explanation.\n"
            "- Highlight whether the signals are reinforcing each other or are mixed.\n"
            "- For time-sensitive questions, mention exact dates from the context.\n"
            "- If the context is insufficient, say what is not established by the retrieved evidence.\n"
            f"- Current date: {current_date}\n\n"
            f"Retrieved context:\n{context}\n\n"
            f"Question:\n{question}"
        )
        if prior_context:
            return prior_context + "\n\n" + base_input
        return base_input

    def prepare_documents(self, question: str, documents: list) -> list:
        """Sort and limit documents based on question type."""
        recency_first = self._is_recency_question(question)
        prepared = sorted(
            documents,
            key=lambda doc: self._sort_key(
                doc.metadata.get("published_at"),
                doc.metadata.get("rerank_score") or doc.metadata.get("score"),
                recency_first=recency_first,
            ),
            reverse=True,
        )
        return prepared[: max(settings.rag_top_k * settings.rag_retrieval_multiplier, settings.rag_top_k + 3)]

    # ─── Helper Methods ───────────────────────────────────────────────────────

    def _is_recency_question(self, question: str) -> bool:
        lowered = question.lower()
        return any(keyword in lowered for keyword in RECENCY_KEYWORDS)

    def _sort_key(
        self,
        published_at,
        rank_score,
        recency_first: bool,
    ) -> tuple[float, float]:
        """Shared sort key for consistent ordering."""
        ts = self._published_timestamp(published_at)
        score = self._coerce_float(rank_score)
        return (ts, score) if recency_first else (score, ts)

    def _published_timestamp(self, value) -> float:
        if not value:
            return 0.0

        text = str(value).strip()
        if not text:
            return 0.0

        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass

        try:
            return parsedate_to_datetime(text).timestamp()
        except (TypeError, ValueError, IndexError, OverflowError):
            return 0.0

    def _clean_headline(self, title: str) -> str:
        cleaned = " ".join(title.split()).strip()
        if " - " in cleaned:
            cleaned = cleaned.rsplit(" - ", maxsplit=1)[0]
        return cleaned

    def _clean_context_text(self, text: str, title: str | None = None) -> str:
        cleaned_lines: list[str] = []
        normalized_title = " ".join((title or "").split()).strip().casefold()

        for raw_line in text.splitlines():
            line = " ".join(raw_line.split()).strip()
            if not line:
                continue
            lowered = line.casefold()
            if normalized_title and lowered == normalized_title:
                continue
            if lowered.startswith(("published:", "channel:", "source url:", "url:", "source:")):
                continue
            cleaned_lines.append(line)

        cleaned_text = " ".join(cleaned_lines).strip()
        if len(cleaned_text) > 420:
            cleaned_text = cleaned_text[:420].rsplit(" ", maxsplit=1)[0].rstrip(".,;:") + "..."
        return cleaned_text

    def _preferred_date(self, existing_value, candidate_value):
        existing_ts = self._published_timestamp(existing_value)
        candidate_ts = self._published_timestamp(candidate_value)
        return candidate_value if candidate_ts >= existing_ts else existing_value

    def _coerce_float(self, value) -> float:
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0
