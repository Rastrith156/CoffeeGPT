"""
evaluation/quality_scorer.py
============================
Computes a composite quality score across retrieval metrics and LLM metrics.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from evaluation.retrieval_evaluator import RetrievalMetrics
from evaluation.llm_evaluator import LLMQualityMetrics


@dataclass
class CompositeQualityScore:
    retrieval_score: float
    llm_score: float
    signal_correctness: float
    recommendation_usefulness: float
    final_score: float
    is_acceptable: bool


class QualityScorer:
    """Combines retrieval and generation metrics into a final quality score."""

    def score(
        self,
        retrieval_metrics: RetrievalMetrics | dict[str, float],
        llm_metrics: LLMQualityMetrics,
    ) -> CompositeQualityScore:
        """Calculate the composite quality score."""
        
        # Handle dict or dataclass for retrieval metrics (backward compatibility)
        if isinstance(retrieval_metrics, dict):
            ret_score = retrieval_metrics.get("mean_average_precision", 0.0)
        else:
            ret_score = getattr(retrieval_metrics, "mean_average_precision", 0.0)
            
        llm_score = llm_metrics.overall_score
        
        # Derived domain scores
        signal_correctness = (ret_score * 0.6) + (llm_metrics.factual_consistency_score * 0.4)
        recommendation_usefulness = (llm_metrics.answer_completeness * 0.7) + (llm_score * 0.3)
        
        final_score = (ret_score * 0.3) + (llm_score * 0.4) + (signal_correctness * 0.3)
        
        return CompositeQualityScore(
            retrieval_score=ret_score,
            llm_score=llm_score,
            signal_correctness=signal_correctness,
            recommendation_usefulness=recommendation_usefulness,
            final_score=final_score,
            is_acceptable=final_score >= 0.7,
        )
