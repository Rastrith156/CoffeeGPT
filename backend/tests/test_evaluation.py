"""
tests/test_evaluation.py
=========================
Tests for the evaluation framework (RetrievalEvaluator + run_eval).

These tests require NO external services — all offline computation.
They verify:
  - Precision@k, Recall@k, MRR, nDCG@k calculations
  - Grounding / hallucination scoring
  - batch_score aggregation
  - Default eval run produces valid output structure
"""
from __future__ import annotations

import pytest
from evaluation.retrieval_evaluator import RetrievalEvaluator


@pytest.fixture
def evaluator() -> RetrievalEvaluator:
    return RetrievalEvaluator()


# ─── Precision@k ─────────────────────────────────────────────────────────────

def test_perfect_precision(evaluator: RetrievalEvaluator):
    metrics = evaluator.score(
        query="arabica price",
        retrieved_ids=[1, 2, 3],
        relevant_ids=[1, 2, 3],
        k=3,
    )
    assert metrics.precision_at_k == pytest.approx(1.0)


def test_zero_precision(evaluator: RetrievalEvaluator):
    metrics = evaluator.score(
        query="arabica price",
        retrieved_ids=[4, 5, 6],
        relevant_ids=[1, 2, 3],
        k=3,
    )
    assert metrics.precision_at_k == pytest.approx(0.0)


def test_partial_precision(evaluator: RetrievalEvaluator):
    # 2 of 4 retrieved are relevant → precision = 0.5
    metrics = evaluator.score(
        query="robusta harvest",
        retrieved_ids=[1, 7, 2, 8],
        relevant_ids=[1, 2],
        k=4,
    )
    assert metrics.precision_at_k == pytest.approx(0.5)


# ─── Recall@k ────────────────────────────────────────────────────────────────

def test_perfect_recall(evaluator: RetrievalEvaluator):
    metrics = evaluator.score(
        query="coffee market",
        retrieved_ids=[1, 2, 3, 4, 5],
        relevant_ids=[1, 2],
        k=5,
    )
    assert metrics.recall_at_k == pytest.approx(1.0)


def test_partial_recall(evaluator: RetrievalEvaluator):
    # Only 1 of 2 relevant docs is in top-3 → recall = 0.5
    metrics = evaluator.score(
        query="coffee market",
        retrieved_ids=[1, 5, 6],
        relevant_ids=[1, 2],
        k=3,
    )
    assert metrics.recall_at_k == pytest.approx(0.5)


# ─── MRR ─────────────────────────────────────────────────────────────────────

def test_mrr_first_hit_rank1(evaluator: RetrievalEvaluator):
    metrics = evaluator.score(
        query="q",
        retrieved_ids=[1, 2, 3],
        relevant_ids=[1],
        k=3,
    )
    assert metrics.mrr == pytest.approx(1.0)


def test_mrr_first_hit_rank3(evaluator: RetrievalEvaluator):
    metrics = evaluator.score(
        query="q",
        retrieved_ids=[5, 6, 1],
        relevant_ids=[1],
        k=3,
    )
    assert metrics.mrr == pytest.approx(1 / 3)


def test_mrr_no_hit(evaluator: RetrievalEvaluator):
    metrics = evaluator.score(
        query="q",
        retrieved_ids=[5, 6, 7],
        relevant_ids=[1],
        k=3,
    )
    assert metrics.mrr == pytest.approx(0.0)


# ─── nDCG ────────────────────────────────────────────────────────────────────

def test_ndcg_perfect(evaluator: RetrievalEvaluator):
    # All relevant docs at top-k → nDCG = 1.0
    metrics = evaluator.score(
        query="q",
        retrieved_ids=[1, 2, 3],
        relevant_ids=[1, 2, 3],
        k=3,
    )
    assert metrics.ndcg_at_k == pytest.approx(1.0)


def test_ndcg_zero(evaluator: RetrievalEvaluator):
    metrics = evaluator.score(
        query="q",
        retrieved_ids=[4, 5, 6],
        relevant_ids=[1, 2, 3],
        k=3,
    )
    assert metrics.ndcg_at_k == pytest.approx(0.0)


# ─── Grounding / hallucination ────────────────────────────────────────────────

def test_fully_grounded_answer(evaluator: RetrievalEvaluator):
    answer  = "Arabica futures rose 3.2% following a severe frost warning in Brazil."
    sources = ["Arabica futures rose 3.2% following a severe frost warning in Brazil's Minas Gerais region."]
    gm = evaluator.grounding_check(answer=answer, source_texts=sources)
    assert gm.grounding_score == pytest.approx(1.0)
    assert gm.hallucination_score == pytest.approx(0.0)


def test_fully_hallucinated_answer(evaluator: RetrievalEvaluator):
    answer  = "Coffee prices will triple next year due to alien crop circles."
    sources = ["Arabica futures fell 1.2% on strong harvest reports."]
    gm = evaluator.grounding_check(answer=answer, source_texts=sources, min_overlap_words=5)
    # No word overlap above threshold → hallucination_score = 1.0
    assert gm.hallucination_score == pytest.approx(1.0)


def test_partial_grounding(evaluator: RetrievalEvaluator):
    answer = (
        "Arabica rose on Brazil frost warnings. "
        "Meanwhile, magic unicorn prices fell dramatically."
    )
    sources = ["Arabica futures rose following Brazil frost warnings."]
    gm = evaluator.grounding_check(answer=answer, source_texts=sources)
    # First sentence is grounded, second is not → grounding = 0.5
    assert 0.0 < gm.grounding_score < 1.0


def test_grounding_empty_answer(evaluator: RetrievalEvaluator):
    gm = evaluator.grounding_check(answer="", source_texts=["anything"])
    assert gm.grounding_score     == pytest.approx(0.0)
    assert gm.hallucination_score == pytest.approx(1.0)
    assert gm.total_sentence_count == 0


# ─── Batch evaluation ────────────────────────────────────────────────────────

def test_batch_score_aggregates_correctly(evaluator: RetrievalEvaluator):
    cases = [
        {"query": "q1", "retrieved_ids": [1], "relevant_ids": [1], "k": 1},  # precision=1.0
        {"query": "q2", "retrieved_ids": [2], "relevant_ids": [1], "k": 1},  # precision=0.0
    ]
    report = evaluator.batch_score(cases)
    assert "aggregate" in report
    agg = report["aggregate"]
    assert agg["precision_at_k"] == pytest.approx(0.5)
    assert len(report["cases"]) == 2


# ─── Default run_eval (smoke test) ───────────────────────────────────────────

def test_default_run_eval_produces_valid_report():
    from evaluation.run_eval import run_evaluation
    report = run_evaluation()
    assert "retrieval" in report
    assert "grounding" in report
    assert "generated_at" in report
    assert report["retrieval"]["aggregate"]["precision_at_k"] >= 0.0
    assert 0.0 <= report["grounding"]["avg_grounding_score"] <= 1.0
