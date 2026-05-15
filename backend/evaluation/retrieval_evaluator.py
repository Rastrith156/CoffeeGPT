"""
evaluation/retrieval_evaluator.py
==================================
Retrieval quality and answer grounding evaluation for CoffeeGPT.

Metrics implemented
-------------------
  precision_at_k   — fraction of top-k results that are relevant
  recall_at_k      — fraction of relevant docs found in top-k
  mrr              — mean reciprocal rank of first relevant result
  ndcg_at_k        — normalised discounted cumulative gain
  hallucination_score — 1 - citation_coverage (0 = fully grounded)
  grounding_score     — fraction of sentences with at least one source citation

Usage
-----
  from evaluation.retrieval_evaluator import RetrievalEvaluator

  evaluator = RetrievalEvaluator()

  # Score retrieval
  metrics = evaluator.score(
      query="What is the arabica price?",
      retrieved_ids=[3, 1, 2, 5, 7],
      relevant_ids=[1, 2],
      k=5,
  )

  # Check answer grounding against source texts
  grounding = evaluator.grounding_check(
      answer="Arabica rose 3% due to frost in Brazil.",
      source_texts=["Arabica futures rose 3.2% following a severe frost warning."],
  )
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Sequence


# ─── Result dataclasses ───────────────────────────────────────────────────────

@dataclass
class RetrievalMetrics:
    query:          str
    k:              int
    precision_at_k: float
    recall_at_k:    float
    mrr:            float
    ndcg_at_k:      float
    retrieved_ids:  list[int | str]
    relevant_ids:   list[int | str]
    evaluated_at:   str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "query":          self.query,
            "k":              self.k,
            "precision_at_k": round(self.precision_at_k, 4),
            "recall_at_k":    round(self.recall_at_k, 4),
            "mrr":            round(self.mrr, 4),
            "ndcg_at_k":      round(self.ndcg_at_k, 4),
            "evaluated_at":   self.evaluated_at,
        }


@dataclass
class GroundingMetrics:
    answer:               str
    grounding_score:      float   # fraction of sentences with at least one citation match
    hallucination_score:  float   # 1 - grounding_score  (0 = fully grounded)
    cited_sentence_count: int
    total_sentence_count: int
    source_count:         int
    evaluated_at:         str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "grounding_score":      round(self.grounding_score, 4),
            "hallucination_score":  round(self.hallucination_score, 4),
            "cited_sentence_count": self.cited_sentence_count,
            "total_sentence_count": self.total_sentence_count,
            "source_count":         self.source_count,
            "evaluated_at":         self.evaluated_at,
        }


# ─── Evaluator ────────────────────────────────────────────────────────────────

class RetrievalEvaluator:
    """
    Offline retrieval and grounding quality evaluator.

    Designed to run against a YAML/JSON test set of (query, relevant_ids) pairs
    without requiring a live model or external API.
    """

    # ── Retrieval metrics ─────────────────────────────────────────────────────

    def score(
        self,
        query: str,
        retrieved_ids: Sequence[int | str],
        relevant_ids: Sequence[int | str],
        k: int | None = None,
    ) -> RetrievalMetrics:
        """
        Compute retrieval quality metrics.

        Args:
            query:         The user query string (for logging only).
            retrieved_ids: Ordered list of retrieved document IDs (ranked).
            relevant_ids:  Ground-truth set of relevant document IDs.
            k:             Cutoff rank. Defaults to len(retrieved_ids).

        Returns:
            RetrievalMetrics dataclass with all scores.
        """
        k = k or len(retrieved_ids)
        top_k    = list(retrieved_ids[:k])
        rel_set  = set(relevant_ids)

        precision = self._precision_at_k(top_k, rel_set)
        recall    = self._recall_at_k(top_k, rel_set)
        mrr       = self._mrr(top_k, rel_set)
        ndcg      = self._ndcg_at_k(top_k, rel_set, k)

        return RetrievalMetrics(
            query=query,
            k=k,
            precision_at_k=precision,
            recall_at_k=recall,
            mrr=mrr,
            ndcg_at_k=ndcg,
            retrieved_ids=list(retrieved_ids),
            relevant_ids=list(relevant_ids),
        )

    def batch_score(
        self,
        cases: list[dict],
    ) -> dict:
        """
        Score a list of test cases.

        Each case dict must have keys:
          query, retrieved_ids, relevant_ids, [k]

        Returns aggregated averages plus per-case details.
        """
        results = []
        for case in cases:
            metrics = self.score(
                query=case["query"],
                retrieved_ids=case["retrieved_ids"],
                relevant_ids=case["relevant_ids"],
                k=case.get("k"),
            )
            results.append(metrics)

        if not results:
            return {"error": "no cases provided"}

        avg = {
            "precision_at_k": sum(r.precision_at_k for r in results) / len(results),
            "recall_at_k":    sum(r.recall_at_k    for r in results) / len(results),
            "mrr":            sum(r.mrr            for r in results) / len(results),
            "ndcg_at_k":      sum(r.ndcg_at_k      for r in results) / len(results),
        }
        return {
            "aggregate": {k: round(v, 4) for k, v in avg.items()},
            "cases":     [r.to_dict() for r in results],
            "total_cases": len(results),
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        }

    # ── Grounding / hallucination check ──────────────────────────────────────

    def grounding_check(
        self,
        answer: str,
        source_texts: list[str],
        min_overlap_words: int = 3,
    ) -> GroundingMetrics:
        """
        Estimate answer grounding against retrieved source texts.

        Strategy:
          1. Split answer into sentences.
          2. For each sentence, check whether ≥ min_overlap_words appear
             verbatim in any source text (case-insensitive).
          3. grounding_score = cited_sentences / total_sentences
          4. hallucination_score = 1 - grounding_score

        Args:
            answer:            The LLM-generated answer text.
            source_texts:      List of retrieved source document texts.
            min_overlap_words: Minimum number of common words to count as cited.

        Returns:
            GroundingMetrics dataclass.
        """
        sentences = self._split_sentences(answer)
        total     = len(sentences)
        if total == 0:
            return GroundingMetrics(
                answer=answer,
                grounding_score=0.0,
                hallucination_score=1.0,
                cited_sentence_count=0,
                total_sentence_count=0,
                source_count=len(source_texts),
            )

        source_words = [
            set(self._tokenise(src)) for src in source_texts
        ]

        cited = 0
        for sentence in sentences:
            s_words = set(self._tokenise(sentence))
            for src_word_set in source_words:
                if len(s_words & src_word_set) >= min_overlap_words:
                    cited += 1
                    break

        grounding  = cited / total
        return GroundingMetrics(
            answer=answer,
            grounding_score=grounding,
            hallucination_score=1.0 - grounding,
            cited_sentence_count=cited,
            total_sentence_count=total,
            source_count=len(source_texts),
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _precision_at_k(top_k: list, rel_set: set) -> float:
        if not top_k:
            return 0.0
        hits = sum(1 for doc_id in top_k if doc_id in rel_set)
        return hits / len(top_k)

    @staticmethod
    def _recall_at_k(top_k: list, rel_set: set) -> float:
        if not rel_set:
            return 1.0  # nothing to recall
        hits = sum(1 for doc_id in top_k if doc_id in rel_set)
        return hits / len(rel_set)

    @staticmethod
    def _mrr(top_k: list, rel_set: set) -> float:
        for rank, doc_id in enumerate(top_k, start=1):
            if doc_id in rel_set:
                return 1.0 / rank
        return 0.0

    @staticmethod
    def _ndcg_at_k(top_k: list, rel_set: set, k: int) -> float:
        """Binary relevance NDCG (relevant=1, not-relevant=0)."""
        def dcg(ids: list) -> float:
            return sum(
                1.0 / math.log2(rank + 1)
                for rank, doc_id in enumerate(ids, start=1)
                if doc_id in rel_set
            )

        actual_dcg = dcg(top_k[:k])
        # Ideal: put all relevant docs at the top
        ideal_hits = min(len(rel_set), k)
        ideal_dcg  = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
        if ideal_dcg == 0:
            return 0.0
        return actual_dcg / ideal_dcg

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """Split on sentence-ending punctuation (. ! ?)."""
        raw = re.split(r"(?<=[.!?])\s+", text.strip())
        return [s.strip() for s in raw if s.strip()]

    @staticmethod
    def _tokenise(text: str) -> list[str]:
        """Lower-case word tokenisation (alphanum only)."""
        return re.findall(r"\b[a-z0-9]+\b", text.lower())
