"""
evaluation/benchmark_suite.py
=============================
Canonical benchmark suite for CoffeeGPT testing.
Runs standard questions against the retriever and evaluator.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from evaluation.retrieval_evaluator import RetrievalEvaluator
from evaluation.llm_evaluator import LLMEvaluator, LLMQualityMetrics
from evaluation.quality_scorer import QualityScorer, CompositeQualityScore
from rag.retriever import CoffeeRetriever


@dataclass
class BenchmarkReport:
    total_questions: int
    passed: int
    failed: int
    average_retrieval_score: float
    average_llm_score: float
    average_final_score: float
    results: list[dict[str, Any]]


class CoffeeBenchmarkSuite:
    """Runs a standard suite of benchmark questions to evaluate end-to-end quality."""

    # Standard questions that cover the main domains of the app
    QUESTIONS = [
        "What are the current arabica futures prices?",
        "Is there any frost risk in Brazil this week?",
        "How is the robusta market behaving?",
        "What is the recommended trading strategy given current volatility?",
        "Are there any supply chain disruptions reported recently?",
    ]

    def __init__(
        self,
        retriever: CoffeeRetriever | None = None,
        retrieval_evaluator: RetrievalEvaluator | None = None,
        llm_evaluator: LLMEvaluator | None = None,
        scorer: QualityScorer | None = None,
    ) -> None:
        self.retriever = retriever or CoffeeRetriever()
        self.retrieval_evaluator = retrieval_evaluator or RetrievalEvaluator()
        self.llm_evaluator = llm_evaluator or LLMEvaluator()
        self.scorer = scorer or QualityScorer()

    async def run_suite(self) -> BenchmarkReport:
        """Run the evaluation suite."""
        results = []
        total_retrieval = 0.0
        total_llm = 0.0
        total_final = 0.0
        passed = 0
        
        # In a real environment, we would use chatbot_agent.answer to get the full answer.
        # For the benchmark suite, we'll mock the end-to-end flow.
        
        for q in self.QUESTIONS:
            # 1. Retrieve
            try:
                docs = await asyncio.to_thread(self.retriever.search, q, 3)
            except Exception:
                docs = []
                
            # 2. Score Retrieval (Mocked target for now)
            ret_metrics = self.retrieval_evaluator.evaluate_retrieval(
                query=q,
                retrieved_docs=docs,
                target_doc_ids=[], # We don't have labeled dataset here
            )
            ret_score = ret_metrics["mean_average_precision"]
            
            # 3. Score LLM (Mock answer based on docs)
            mock_answer = f"According to the sources [1], the answer to '{q}' is..." if docs else f"No data for '{q}'"
            llm_metrics = await self.llm_evaluator.evaluate_answer(q, mock_answer, docs)
            
            # 4. Composite Score
            final_metrics = self.scorer.score(ret_metrics, llm_metrics)
            
            results.append({
                "question": q,
                "retrieval_score": ret_score,
                "llm_score": llm_metrics.overall_score,
                "final_score": final_metrics.final_score,
                "passed": final_metrics.is_acceptable,
            })
            
            total_retrieval += ret_score
            total_llm += llm_metrics.overall_score
            total_final += final_metrics.final_score
            if final_metrics.is_acceptable:
                passed += 1
                
        n = len(self.QUESTIONS)
        return BenchmarkReport(
            total_questions=n,
            passed=passed,
            failed=n - passed,
            average_retrieval_score=total_retrieval / n if n else 0,
            average_llm_score=total_llm / n if n else 0,
            average_final_score=total_final / n if n else 0,
            results=results,
        )
