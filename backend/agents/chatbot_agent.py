from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from core.config import settings
from core.logger import logger
from models.schemas import ChatResponse, SourceCitation
from rag.retriever import CoffeeRetriever
from services.lmstudio_client import LMStudioClient

# Optional hot-layer import — graceful fallback when Redis is unavailable
try:
    from streaming.redis_cache import RedisMarketCache as _RedisMarketCache
    _REDIS_AVAILABLE = True
except ImportError:
    _REDIS_AVAILABLE = False

SYSTEM_PROMPT = """You are CoffeeGPT, a coffee market intelligence analyst.
Use only the retrieved context supplied by the application.
Do not rely on outside knowledge, browsing, or speculation.
Write in a polished market-intelligence tone: direct, concise, and evidence-led.
Never mention missing access, browsing limits, training data, or system limitations.
Lead with the conclusion, then explain the main drivers and near-term implication.
When multiple signal types are present, synthesize futures, weather, news, and historical context into one coherent market view.
Explain whether the signals reinforce each other or conflict.
Cite factual claims with bracketed source numbers like [1] that match the provided context blocks.
Do not append a Sources or References section.
If the retrieved context does not establish an answer, say exactly what is not established.
"""

RECENCY_KEYWORDS = (
    "today",
    "latest",
    "recent",
    "currently",
    "now",
    "this week",
    "yesterday",
)
LOW_QUALITY_PHRASES = (
    "i do not have access to real-time",
    "i don't have access to real-time",
    "real-time information or news updates",
    "i cannot browse",
    "i can't browse",
    "as an ai",
    "please provide more information",
    "please provide more context",
    "check back later",
    "news.google.com/rss/articles",
    "ooooo",
    "roooom",
)
SOURCE_SECTION_PATTERN = re.compile(r"(?:^|\n)(?:sources?|references?)\s*:.*$", re.IGNORECASE | re.DOTALL)
CITATION_PATTERN = re.compile(r"\[(\d+)\]")


class CoffeeChatbotAgent:
    def __init__(
        self,
        retriever: CoffeeRetriever | None = None,
        lmstudio_client: LMStudioClient | None = None,
        redis_cache=None,
        session_memory=None,   # Fix #4: Redis-backed session memory
    ) -> None:
        self.retriever = retriever or CoffeeRetriever()
        self.lmstudio_client = lmstudio_client or LMStudioClient()
        # Fix #4: use Redis-backed session memory instead of in-process dict
        self._session_memory = session_memory
        # Hot-layer cache (Redis) — optional, fails gracefully
        if redis_cache is not None:
            self._cache = redis_cache
        elif _REDIS_AVAILABLE:
            self._cache = _RedisMarketCache()
        else:
            self._cache = None

    def _build_context(self, question: str, documents: list) -> tuple[str, list[SourceCitation], list[dict[str, object]]]:
        grouped_sources: dict[tuple[str, str | None, str | None, str | None], dict[str, object]] = {}

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

        if self._is_recency_question(question):
            ordered_sources = sorted(
                grouped_sources.values(),
                key=lambda group: (
                    self._published_timestamp(group.get("published_at")),
                    self._coerce_float(group.get("rank_score")),
                ),
                reverse=True,
            )[: settings.rag_top_k]
        else:
            ordered_sources = sorted(
                grouped_sources.values(),
                key=lambda group: (
                    self._coerce_float(group.get("rank_score")),
                    self._published_timestamp(group.get("published_at")),
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
            currency = str(source_group.get("currency") or "").strip()
            if price > 0:
                context_lines.append(f"price: {price} {currency}".strip())
            change_percent = source_group.get("change_percent")
            if self._coerce_float(change_percent) != 0.0:
                context_lines.append(f"change_percent: {self._coerce_float(change_percent):+.2f}")
            volatility_pct = source_group.get("volatility_pct")
            if self._coerce_float(volatility_pct) > 0:
                context_lines.append(f"volatility_pct: {self._coerce_float(volatility_pct):.2f}")
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

    async def _get_previous_response_id(self, session_id: str) -> str | None:
        # Fix #4: read from Redis-backed session memory
        if self._session_memory:
            try:
                session = await self._session_memory.load(session_id)
                return session.get("last_response_id")
            except Exception as exc:
                logger.warning("Failed to get previous response ID: {}", exc)
        return None

    async def _remember_response_id(self, session_id: str, response_id: str | None) -> None:
        if not response_id:
            return
        # Fix #4: persist to Redis-backed session memory
        if self._session_memory:
            try:
                session = await self._session_memory.load(session_id)
                session["last_response_id"] = response_id
                await self._session_memory.save(session_id, session)
            except Exception as exc:
                logger.warning("Failed to remember response ID: {}", exc)

    def _prepare_documents(self, question: str, documents: list) -> list:
        if self._is_recency_question(question):
            prepared = sorted(
                documents,
                key=lambda document: (
                    self._published_timestamp(document.metadata.get("published_at")),
                    self._coerce_float(document.metadata.get("rerank_score") or document.metadata.get("score")),
                ),
                reverse=True,
            )
        else:
            prepared = sorted(
                documents,
                key=lambda document: (
                    self._coerce_float(document.metadata.get("rerank_score") or document.metadata.get("score")),
                    self._published_timestamp(document.metadata.get("published_at")),
                ),
                reverse=True,
            )
        return prepared[: max(settings.rag_top_k * settings.rag_retrieval_multiplier, settings.rag_top_k + 3)]

    def _is_recency_question(self, question: str) -> bool:
        lowered = question.lower()
        return any(keyword in lowered for keyword in RECENCY_KEYWORDS)

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

    def _build_user_input(self, question: str, context: str, prior_context: str = "") -> str:
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
        # Fix #23: prepend prior conversation context for multi-turn coherence
        if prior_context:
            return prior_context + "\n\n" + base_input
        return base_input

    def _is_low_quality_answer(self, answer: str, citation_count: int) -> bool:
        lowered = answer.lower().strip()
        if not lowered:
            return True
        if any(phrase in lowered for phrase in LOW_QUALITY_PHRASES):
            return True

        citations = [int(match) for match in CITATION_PATTERN.findall(answer)]
        if citation_count > 0 and not citations:
            return True
        if any(number < 1 or number > citation_count for number in citations):
            return True
        return False

    def _build_grounded_fallback_answer(self, question: str, source_groups: list[dict[str, object]]) -> str:
        if not source_groups:
            return self._build_no_context_answer(question)

        sentences = []
        futures_group = self._find_best_futures_group(source_groups)
        weather_group = self._find_best_weather_group(question, source_groups)
        news_group = self._find_news_group(source_groups)
        risk_group = self._find_source_group(
            source_groups,
            source="forecasting",
            record_type_contains="market_risk",
        )
        alert_group = self._find_source_group(
            source_groups,
            source="forecasting",
            record_type_contains="alert",
        )

        if futures_group is not None:
            market_label = str(futures_group.get("market") or "coffee").strip().replace("_", " ").title()
            price = self._coerce_float(futures_group.get("price"))
            currency = str(futures_group.get("currency") or "").strip()
            change_percent = self._coerce_float(futures_group.get("change_percent"))
            citation = int(futures_group.get("citation_index") or 1)
            snapshot_date = str(
                futures_group.get("snapshot_date")
                or self._display_date(futures_group.get("published_at"))
            ).strip()
            if price > 0 and currency:
                direction = "up" if change_percent > 0.15 else "down" if change_percent < -0.15 else "little changed"
                sentences.append(
                    f"{market_label} futures are {direction} on {snapshot_date} at {price} {currency} "
                    f"({change_percent:+.2f}%) [{citation}]."
                )
            else:
                title = self._clean_headline(str(futures_group.get("title") or "futures context"))
                sentences.append(f"Futures context highlights {title} [{citation}].")

        if risk_group is not None:
            citation = int(risk_group.get("citation_index") or 1)
            risk_signal = next(
                iter(risk_group.get("snippets") or []),
                self._clean_headline(str(risk_group.get("title") or "current market risk")),
            ).rstrip(".")
            sentences.append(f"Decision-support scoring indicates {risk_signal} [{citation}].")

        if alert_group is not None:
            citation = int(alert_group.get("citation_index") or 1)
            alert_signal = next(
                iter(alert_group.get("snippets") or []),
                self._clean_headline(str(alert_group.get("title") or "active intelligence alerts")),
            ).rstrip(".")
            sentences.append(f"Active intelligence alerts also point to {alert_signal} [{citation}].")

        if weather_group is not None:
            region = str(weather_group.get("region") or "key coffee regions").strip()
            citation = int(weather_group.get("citation_index") or 1)
            sentences.append(
                f"Weather context from {region} points to near-term crop conditions that remain relevant for supply expectations [{citation}]."
            )

        if news_group is not None:
            title = self._clean_headline(str(news_group.get("title") or "recent coffee coverage"))
            citation = int(news_group.get("citation_index") or 1)
            date_text = self._display_date(news_group.get("published_at"))
            sentences.append(f"Recent reporting on {date_text} also highlights {title} [{citation}].")

        if not sentences:
            lead = source_groups[0]
            lead_title = self._clean_headline(str(lead.get("title") or "untitled"))
            lead_date = self._display_date(lead.get("published_at"))
            if self._is_recency_question(question):
                sentences.append(f"As of {lead_date}, the strongest retrieved market signal is {lead_title} [1].")
            else:
                sentences.append(f"Retrieved coffee market intelligence points first to {lead_title} [1].")

        sentences.append(
            "Taken together, the indexed context suggests traders are weighing price action, weather risk, and recent market reporting rather than a single isolated signal."
        )
        return " ".join(sentences)

    def _build_no_context_answer(self, question: str) -> str:
        if self._is_recency_question(question):
            return (
                "I could not find recent indexed coffee intelligence that answers this question. "
                "Refresh the ingestion pipeline and ask again."
            )
        return (
            "I could not find indexed coffee intelligence that answers this question in the current dataset. "
            "Try a narrower market question or refresh ingestion."
        )

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

    def _display_date(self, value) -> str:
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

    def _post_process_answer(self, answer: str) -> str:
        cleaned = answer.replace("\r\n", "\n").replace("\r", "\n").strip()
        cleaned = SOURCE_SECTION_PATTERN.sub("", cleaned).strip()
        cleaned = re.sub(r"(\[\d+\])(?:\s+\1)+", r"\1", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        cleaned = re.sub(r"[ \t]+", " ", cleaned)
        return cleaned.strip()

    def _coerce_float(self, value) -> float:
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _find_source_group(
        self,
        source_groups: list[dict[str, object]],
        *,
        source: str | None = None,
        record_type_contains: str | None = None,
    ) -> dict[str, object] | None:
        for group in source_groups:
            source_name = str(group.get("source") or "").strip().lower()
            record_type = str(group.get("record_type") or "").strip().lower()
            matches_source = source is None or source_name == source
            matches_record_type = record_type_contains is None or record_type_contains in record_type
            if matches_source and matches_record_type:
                return group
        return None

    def _find_news_group(self, source_groups: list[dict[str, object]]) -> dict[str, object] | None:
        for group in source_groups:
            source_name = str(group.get("source") or "").strip().lower()
            if source_name.startswith("news") or source_name == "bootstrap_news":
                return group
        return None

    def _find_best_futures_group(self, source_groups: list[dict[str, object]]) -> dict[str, object] | None:
        futures_groups = [
            group for group in source_groups if str(group.get("source") or "").strip().lower() == "futures"
        ]
        if not futures_groups:
            return None
        priced_group = next((group for group in futures_groups if self._coerce_float(group.get("price")) > 0), None)
        if priced_group is not None:
            return priced_group
        return futures_groups[0]

    def _find_best_weather_group(
        self,
        question: str,
        source_groups: list[dict[str, object]],
    ) -> dict[str, object] | None:
        weather_groups = [
            group for group in source_groups if str(group.get("source") or "").strip().lower() == "weather"
        ]
        if not weather_groups:
            return None

        lowered_question = question.lower()
        region_match = next(
            (
                group
                for group in weather_groups
                if str(group.get("region") or "").strip().lower() in lowered_question
            ),
            None,
        )
        if region_match is not None:
            return region_match

        forecast_group = next(
            (
                group
                for group in weather_groups
                if "forecast" in str(group.get("record_type") or "").lower()
                or "outlook" in str(group.get("title") or "").lower()
            ),
            None,
        )
        if forecast_group is not None:
            return forecast_group
        return weather_groups[0]

    # ─── Hot-layer helpers ────────────────────────────────────────────────────

    async def _get_live_context_prefix(self, question: str) -> str:
        """Read Redis hot cache and return a formatted context prefix if relevant."""
        if self._cache is None:
            return ""
        if not self._is_recency_question(question):
            return ""
        try:
            snapshot: dict[str, Any] = await self._cache.get_live_snapshot()
            arabica  = snapshot.get("arabica") or {}
            robusta  = snapshot.get("robusta") or {}
            risk     = await self._cache.get_json("coffee:live:risk") or {}
            spike    = snapshot.get("latest_spike")

            a_price  = float(arabica.get("arabica_price") or 0)
            r_price  = float(robusta.get("robusta_price") or 0)
            if a_price <= 0 and r_price <= 0:
                return ""

            lines = ["[LIVE MARKET STATE — Redis hot cache]",
                     f"source: redis_stream",
                     f"type: live_market_snapshot"]
            if a_price > 0:
                a_change = float(arabica.get("change_percent") or 0)
                lines.append(f"arabica_price: {a_price:.2f} US cents/lb ({a_change:+.2f}%)")
            if r_price > 0:
                r_change = float(robusta.get("change_percent") or 0)
                lines.append(f"robusta_price: {r_price:.0f} USD/tonne ({r_change:+.2f}%)")
            if risk:
                lines.append(f"market_risk: {risk.get('risk_level', 'unknown')} (score {risk.get('risk_score', 0):.0f}/100)")
                rec = risk.get("recommendation", "")
                if rec:
                    lines.append(f"recommendation: {rec}")
            if spike:
                lines.append(f"latest_spike: {spike.get('message', '')}")
            lines.append(f"updated_at: {snapshot.get('snapshot_at', '')}")
            return "\n".join(lines)
        except Exception as exc:
            logger.debug("Live context prefix fetch failed: {}", exc)
            return ""

    async def answer(self, question: str, session_id: str, use_rag: bool = True) -> ChatResponse:
        # ── STEP 5: Check Redis HOT LAYER first ─────────────────────────────
        live_prefix = await self._get_live_context_prefix(question)

        documents = []
        if use_rag:
            retrieval_limit = max(
                settings.rag_top_k * settings.rag_retrieval_multiplier,
                settings.rag_top_k + 3,
            )
            documents = await asyncio.to_thread(self.retriever.search, question, retrieval_limit)
            documents = self._prepare_documents(question, documents)
            if not documents and not live_prefix:
                return ChatResponse(
                    answer=self._build_no_context_answer(question),
                    sources=[],
                    session_id=session_id,
                    model=settings.llm_model,
                    provider="lmstudio",
                    retrieval_mode="no_context",
                )

        context, citations, source_groups = self._build_context(question, documents)
        # Prepend live Redis context if available
        if live_prefix:
            context = live_prefix + ("\n\n" + context if context else "")
        previous_response_id = await self._get_previous_response_id(session_id)
        retrieval_mode_tag = "rag+live" if live_prefix and documents else "live_redis" if live_prefix else "rag"

        # Fix #23: prepend prior conversation context from session memory
        prior_context = ""
        if self._session_memory:
            try:
                prior_context = await self._session_memory.build_context_summary(session_id)
            except Exception as exc:
                logger.warning("Failed to build context summary: {}", exc)

        user_input = self._build_user_input(question, context, prior_context=prior_context)

        try:
            lmstudio_response = await self.lmstudio_client.chat(
                model=settings.llm_model,
                user_input=user_input,
                system_prompt=SYSTEM_PROMPT,
                previous_response_id=previous_response_id,
                store=True,
            )
            answer_text = self._post_process_answer(lmstudio_response.text)
            retrieval_mode = retrieval_mode_tag if documents or live_prefix else "llm_only"

            if documents and self._is_low_quality_answer(answer_text, len(citations)):
                logger.warning("LM Studio returned low-quality output, using grounded RAG fallback")
                answer_text = self._build_grounded_fallback_answer(question, source_groups)
                retrieval_mode = "retrieval_fallback"
            else:
                await self._remember_response_id(session_id, lmstudio_response.response_id)

            # Fix #24: persist exchange to session memory for multi-turn context
            if self._session_memory:
                try:
                    await self._session_memory.append_exchange(
                        session_id=session_id,
                        user_message=question,
                        assistant_message=answer_text,
                    )
                except Exception as exc:
                    logger.warning("Failed to append exchange to session memory: {}", exc)

            return ChatResponse(
                answer=answer_text,
                sources=citations,
                session_id=session_id,
                model=lmstudio_response.model_instance_id or settings.llm_model,
                provider="lmstudio",
                response_id=lmstudio_response.response_id,
                retrieval_mode=retrieval_mode,
            )
        except Exception as exc:
            logger.warning("LLM response failed, using retrieval fallback: {}", exc)
            if documents:
                return ChatResponse(
                    answer=self._build_grounded_fallback_answer(question, source_groups),
                    sources=citations,
                    session_id=session_id,
                    model=settings.llm_model,
                    provider="lmstudio",
                    retrieval_mode="retrieval_fallback",
                )
            return ChatResponse(
                answer=self._build_no_context_answer(question),
                sources=[],
                session_id=session_id,
                model=settings.llm_model,
                provider="lmstudio",
                retrieval_mode="no_context",
            )
