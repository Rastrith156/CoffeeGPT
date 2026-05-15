"""
evaluation/run_eval.py
=======================
CLI evaluation runner for CoffeeGPT retrieval and grounding quality.

Usage
-----
  python -m evaluation.run_eval                          # default built-in test set
  python -m evaluation.run_eval --questions eval_qs.yaml  # custom YAML
  python -m evaluation.run_eval --output report.json       # save JSON report

YAML format
-----------
  - query: "What is the arabica price?"
    retrieved_ids: [1, 3, 5]
    relevant_ids: [1]
    k: 5

Output JSON
-----------
  {
    "retrieval": { "aggregate": {...}, "cases": [...] },
    "grounding": { "avg_grounding_score": 0.82, ... },
    "generated_at": "..."
  }
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from evaluation.retrieval_evaluator import RetrievalEvaluator, GroundingMetrics


# ─── Default test set (used when no YAML is provided) ────────────────────────

DEFAULT_RETRIEVAL_CASES = [
    {
        "query":        "What is the current arabica coffee price?",
        "retrieved_ids": [1, 2, 3, 4, 5],
        "relevant_ids":  [1],
        "k":            5,
    },
    {
        "query":        "Impact of Vietnam harvest on robusta prices",
        "retrieved_ids": [2, 1, 3],
        "relevant_ids":  [2],
        "k":            3,
    },
    {
        "query":        "Brazil frost warning and arabica futures",
        "retrieved_ids": [1, 4, 2],
        "relevant_ids":  [1, 4],
        "k":            3,
    },
    {
        "query":        "ICO composite indicator coffee market",
        "retrieved_ids": [3, 1, 2],
        "relevant_ids":  [3],
        "k":            3,
    },
    {
        "query":        "Coffee supply chain risk assessment",
        "retrieved_ids": [5, 2, 3, 1],
        "relevant_ids":  [5],
        "k":            4,
    },
]

DEFAULT_GROUNDING_CASES = [
    {
        "answer": (
            "Arabica futures rose 3.2% following a frost warning in Brazil. "
            "Vietnam robusta production hit a record high in Dak Lak province."
        ),
        "sources": [
            "Arabica futures rose 3.2% following a severe frost warning in Brazil's Minas Gerais region.",
            "Vietnam reported a record harvest in Dak Lak province this season.",
        ],
    },
    {
        "answer": (
            "The ICO composite indicator retreated on demand softness. "
            "Prices may recover as supply tightens."
        ),
        "sources": [
            "ICO composite indicator retreated amid global demand softness and currency headwinds.",
        ],
    },
    {
        "answer": (
            "Coffee production will increase by 15% next year due to new farming techniques. "
            "This is entirely unprecedented in the market."
        ),
        "sources": [
            "Arabica futures rose 3.2% following a severe frost warning.",
        ],
    },
]


# ─── Runner ───────────────────────────────────────────────────────────────────

def run_evaluation(
    retrieval_cases: list[dict] | None = None,
    grounding_cases: list[dict] | None = None,
) -> dict:
    evaluator = RetrievalEvaluator()

    # ── Retrieval ─────────────────────────────────────────────────────────────
    r_cases  = retrieval_cases or DEFAULT_RETRIEVAL_CASES
    retrieval_report = evaluator.batch_score(r_cases)

    # ── Grounding ─────────────────────────────────────────────────────────────
    g_cases = grounding_cases or DEFAULT_GROUNDING_CASES
    grounding_results: list[GroundingMetrics] = []
    for case in g_cases:
        gm = evaluator.grounding_check(
            answer=case["answer"],
            source_texts=case["sources"],
        )
        grounding_results.append(gm)

    avg_grounding     = sum(r.grounding_score    for r in grounding_results) / len(grounding_results)
    avg_hallucination = sum(r.hallucination_score for r in grounding_results) / len(grounding_results)

    grounding_report = {
        "avg_grounding_score":     round(avg_grounding, 4),
        "avg_hallucination_score": round(avg_hallucination, 4),
        "total_cases":             len(grounding_results),
        "cases": [r.to_dict() for r in grounding_results],
    }

    report = {
        "retrieval":    retrieval_report,
        "grounding":    grounding_report,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    _print_summary(retrieval_report, grounding_report)
    return report


def _print_summary(retrieval: dict, grounding: dict) -> None:
    agg = retrieval.get("aggregate", {})
    print("\n" + "═" * 60)
    print("  CoffeeGPT Retrieval Evaluation Report")
    print("═" * 60)
    print(f"  Precision@k:         {agg.get('precision_at_k', 0):.4f}")
    print(f"  Recall@k:            {agg.get('recall_at_k', 0):.4f}")
    print(f"  MRR:                 {agg.get('mrr', 0):.4f}")
    print(f"  nDCG@k:              {agg.get('ndcg_at_k', 0):.4f}")
    print()
    print(f"  Grounding Score:     {grounding['avg_grounding_score']:.4f}")
    print(f"  Hallucination Score: {grounding['avg_hallucination_score']:.4f}")
    print("═" * 60)
    print()


# ─── CLI entry ────────────────────────────────────────────────────────────────

def _load_yaml_cases(path: str) -> list[dict]:
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        print("ERROR: PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
        sys.exit(1)
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, list):
        print("ERROR: YAML must be a list of test cases.", file=sys.stderr)
        sys.exit(1)
    return data


def main() -> None:
    parser = argparse.ArgumentParser(
        description="CoffeeGPT retrieval and grounding evaluator",
    )
    parser.add_argument(
        "--questions", "-q",
        default=None,
        help="Path to a YAML file with retrieval test cases",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Path to write JSON evaluation report (default: stdout)",
    )
    args = parser.parse_args()

    retrieval_cases = _load_yaml_cases(args.questions) if args.questions else None
    report = run_evaluation(retrieval_cases=retrieval_cases)

    json_output = json.dumps(report, indent=2, default=str)
    if args.output:
        Path(args.output).write_text(json_output, encoding="utf-8")
        print(f"Report saved to {args.output}")
    else:
        print(json_output)


if __name__ == "__main__":
    main()
