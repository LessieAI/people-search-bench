#!/usr/bin/env python3
"""Recompute platform scores from local evaluation data.

No API keys needed. Uses the pre-computed person_evals.jsonl and
query_metrics.jsonl files to verify the scoring pipeline.

Usage:
    uv run tools/compute_scores.py
    uv run tools/compute_scores.py --platform lessie
    uv run tools/compute_scores.py --category recruiting
    uv run tools/compute_scores.py --demo
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from benchmark.metrics import (  # noqa: E402
    PersonEvaluation,
    CriterionResult,
    compute_query_metrics,
    compute_platform_scores,
    _ndcg,
)


EVAL_DIR = PROJECT_DIR / "data" / "evaluation_details"
QUERIES_DIR = PROJECT_DIR / "data" / "queries"
PLATFORMS = ["lessie", "exa", "juicebox", "claude_code"]

# Map benchmark categories to eval categories
CATEGORY_MAP = {
    "recruiting": "find_candidates",
    "b2b": "find_customers",
    "deterministic": "find_experts",
    "influencer": "find_kol",
}
CATEGORY_REVERSE = {v: k for k, v in CATEGORY_MAP.items()}


def load_benchmark_query_ids() -> set[str]:
    """Load the 119 benchmark query IDs (source_id format) from data/queries/."""
    source_ids = set()
    for f in QUERIES_DIR.glob("*.jsonl"):
        for line in open(f):
            if line.strip():
                d = json.loads(line)
                source_ids.add(d["source_id"])
    return source_ids


def load_person_evals(platform: str) -> list[dict]:
    path = EVAL_DIR / platform / "person_evals.jsonl"
    if not path.exists():
        print(f"  [skip] {path} not found")
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def load_query_metrics(platform: str) -> list[dict]:
    path = EVAL_DIR / platform / "query_metrics.jsonl"
    if not path.exists():
        print(f"  [skip] {path} not found")
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def _to_person_eval(pe: dict) -> PersonEvaluation:
    criteria_results = []
    for cr in pe.get("criteria_results", []):
        criteria_results.append(
            CriterionResult(
                criterion_id=cr.get("criterion_id", cr.get("id", "")),
                description=cr.get("description", ""),
                match=cr.get("match", "not_met"),
                evidence=cr.get("evidence", ""),
            )
        )
    return PersonEvaluation(
        person_name=pe.get("person_name", ""),
        criteria_results=criteria_results,
        relevance_grade=pe.get("relevance_grade", 0),
        structural_score=pe.get("structural_score", 0),
        contextual_score=pe.get("contextual_score", 0),
        utility_score=pe.get("utility_score", 0),
    )


def demo_ndcg():
    """Show how padded nDCG@10 works with a small example."""
    print("=" * 60)
    print("DEMO: Padded nDCG@10 Calculation")
    print("=" * 60)

    grades_a = [1.0, 1.0, 0.5, 1.0, 0.0, 1.0, 0.5, 0.0, 1.0, 0.5]
    grades_b = [1.0, 1.0, 1.0]

    ndcg_a = _ndcg(grades_a, 10)
    ndcg_b = _ndcg(grades_b, 10)

    print(f"\nPlatform A returns 10 results: {grades_a}")
    print(f"  nDCG@10 = {ndcg_a:.4f}")
    print(f"\nPlatform B returns 3 perfect results: {grades_b}")
    print(f"  nDCG@10 = {ndcg_b:.4f}")
    print("\nPlatform A scores higher because padded ideal assumes 10 perfect")
    print("results are achievable. Returning fewer results is penalized.")
    print()


def demo_single_query(platform: str = "lessie"):
    """Walk through scoring for a single query."""
    print("=" * 60)
    print(f"DEMO: Single Query Scoring ({platform})")
    print("=" * 60)

    benchmark_ids = load_benchmark_query_ids()
    evals = load_person_evals(platform)
    if not evals:
        return

    # Pick first query that's in the benchmark set
    query_id = None
    for e in evals:
        qid = e.get("query_id", "")
        if qid in benchmark_ids:
            query_id = qid
            break
    if not query_id:
        print("No matching query found")
        return

    query_evals = [e for e in evals if e.get("query_id") == query_id]

    print(f"\nQuery: {query_id}")
    print(f"Persons returned: {len(query_evals)}")
    print()

    person_objs = []
    for i, pe in enumerate(query_evals[:5]):
        name = pe.get("person_name", "unknown")
        rel = pe.get("relevance_grade", 0)
        struct = pe.get("structural_score", 0)
        ctx = pe.get("contextual_score", 0)
        util = pe.get("utility_score", 0)
        print(
            f"  #{i + 1} {name}: relevance={rel:.2f}, structural={struct:.2f}, contextual={ctx:.2f}, utility={util:.2f}"
        )
        person_objs.append(_to_person_eval(pe))

    if len(query_evals) > 5:
        print(f"  ... ({len(query_evals) - 5} more)")
        for pe in query_evals[5:]:
            person_objs.append(_to_person_eval(pe))

    metrics = compute_query_metrics(
        query_id=query_id,
        platform=platform,
        category="general",
        person_evals=person_objs,
        requested_k=15,
    )

    print("\nQuery metrics:")
    print(f"  nDCG@10      = {metrics.ndcg_10:.4f}")
    print(f"  Qualified    = {metrics.num_qualified} / {metrics.num_results}")
    print(f"  Coverage     = {metrics.coverage_score:.4f}")
    print(f"  Utility      = {metrics.utility_score:.4f}")
    print()


def _compute_platform(
    platform: str, benchmark_ids: set[str], filter_category: str | None = None
):
    """Compute scores for a single platform. Returns (DimensionScores, person_count) or None."""
    metrics_data = load_query_metrics(platform)
    if not metrics_data:
        return None

    metrics_data = [m for m in metrics_data if m.get("query_id") in benchmark_ids]

    if filter_category:
        eval_cat = CATEGORY_MAP.get(filter_category, filter_category)
        metrics_data = [m for m in metrics_data if m.get("category") == eval_cat]

    person_data = load_person_evals(platform)
    persons_by_query: dict[str, list[PersonEvaluation]] = {}
    total_persons = 0
    for pe in person_data:
        qid = pe.get("query_id", "")
        if qid not in benchmark_ids:
            continue
        if qid not in persons_by_query:
            persons_by_query[qid] = []
        persons_by_query[qid].append(_to_person_eval(pe))
        total_persons += 1

    query_metrics_list = []
    for m in metrics_data:
        qid = m["query_id"]
        cat = m.get("category", "general")
        pe_list = persons_by_query.get(qid, [])
        qm = compute_query_metrics(qid, platform, cat, pe_list, requested_k=15)
        query_metrics_list.append(qm)

    scores = compute_platform_scores(platform, query_metrics_list)
    return scores, total_persons


def compute_all_scores(
    filter_platform: str | None = None,
    filter_category: str | None = None,
):
    """Recompute full platform scores from evaluation_details.

    Only uses the 119 benchmark queries (excludes the 18 removed queries).
    """
    print("=" * 60)
    print("FULL SCORE COMPUTATION (119 benchmark queries)")
    print("=" * 60)

    benchmark_ids = load_benchmark_query_ids()
    print(f"Benchmark queries: {len(benchmark_ids)}")

    platforms = [filter_platform] if filter_platform else PLATFORMS

    for platform in platforms:
        result = _compute_platform(platform, benchmark_ids, filter_category)
        if result is None:
            continue
        scores, total_persons = result

        print(f"\n{'─' * 40}")
        print(f"  {platform.upper()}")
        print(f"{'─' * 40}")
        print(f"  Queries:    {scores.total_queries}")
        print(f"  TCR:        {scores.task_completion_rate}%")
        print(f"  Relevance:  {scores.relevance_precision}")
        print(f"  Coverage:   {scores.effective_coverage}")
        print(f"  Utility:    {scores.information_utility}")
        print(f"  Overall:    {scores.overall}")

        if scores.by_category:
            print("\n  By category:")
            for cat, vals in sorted(scores.by_category.items()):
                display_cat = CATEGORY_REVERSE.get(cat, cat)
                overall_cat = round(
                    (
                        vals["relevance_precision"]
                        + vals["effective_coverage"]
                        + vals["information_utility"]
                    )
                    / 3,
                    1,
                )
                print(
                    f"    {display_cat}: Rel={vals['relevance_precision']}, Cov={vals['effective_coverage']}, Util={vals['information_utility']}, Overall={overall_cat}"
                )

    print()


def main():
    parser = argparse.ArgumentParser(
        description="Compute benchmark scores from local data"
    )
    parser.add_argument("--platform", choices=PLATFORMS, help="Filter to one platform")
    parser.add_argument(
        "--category",
        choices=["recruiting", "b2b", "deterministic", "influencer"],
        help="Filter to one category",
    )
    parser.add_argument("--demo", action="store_true", help="Run demo explanations")
    args = parser.parse_args()

    if not EVAL_DIR.exists():
        print(f"Error: evaluation_details not found at {EVAL_DIR}")
        print("This tool requires the local (gitignored) evaluation data.")
        print("Ask your team for the people-search-bench.zip with full data.")
        sys.exit(1)

    if args.demo:
        demo_ndcg()
        demo_single_query(args.platform or "lessie")

    compute_all_scores(args.platform, args.category)


if __name__ == "__main__":
    main()
