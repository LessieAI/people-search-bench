"""Score calculation functions for the three core benchmark dimensions.

Dimension 1: Relevance Precision (nDCG@K)
Dimension 2: Effective Coverage (qualified count + task completion)
Dimension 3: Information Utility (structural + contextual)

All scores are on a 0-100 absolute scale.
"""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, Field


class CriterionResult(BaseModel):
    """Verification result for a single criterion on a single person."""

    criterion_id: str
    description: str
    match: str  # "met" | "partially_met" | "not_met"
    evidence: str = ""
    confidence: str = "medium"  # "high" | "medium" | "low"

    @property
    def score(self) -> float:
        if self.match == "met":
            return 1.0
        elif self.match == "partially_met":
            return 0.5
        return 0.0


class PersonEvaluation(BaseModel):
    """Full evaluation of one person against a query."""

    person_name: str = ""
    person_index: int = 0

    criteria_results: list[CriterionResult] = Field(default_factory=list)
    relevance_grade: float = 0.0  # 0.0-1.0, derived from criteria matching

    # Information utility sub-scores
    structural_score: float = 0.0  # field coverage (0-1)
    contextual_score: float = 0.0  # AI-assessed actionability (0-1)
    utility_score: float = 0.0  # combined (0-1)

    verification_summary: str = ""
    error: str | None = None


class QueryMetrics(BaseModel):
    """Computed metrics for one query across all returned persons."""

    query_id: str
    platform: str
    category: str = ""
    num_results: int = 0
    num_qualified: int = 0  # results with relevance_grade >= threshold
    task_success: bool = False

    ndcg_5: float = 0.0
    ndcg_10: float = 0.0
    ndcg_25: float = 0.0
    precision_5: float = 0.0
    precision_10: float = 0.0
    precision_25: float = 0.0

    coverage_score: float = 0.0
    utility_score: float = 0.0

    person_evaluations: list[PersonEvaluation] = Field(default_factory=list)


class DimensionScores(BaseModel):
    """Final scores for one platform."""

    platform: str
    total_queries: int = 0
    completed_queries: int = 0
    task_completion_rate: float = 0.0

    relevance_precision: float = 0.0  # 0-100, primary: nDCG@10
    effective_coverage: float = 0.0  # 0-100
    information_utility: float = 0.0  # 0-100

    # Detailed breakdowns
    ndcg_at_k: dict[int, float] = Field(default_factory=dict)  # K -> score
    precision_at_k: dict[int, float] = Field(default_factory=dict)
    mean_qualified_results: float = 0.0

    # Per-category scores
    by_category: dict[str, dict[str, float]] = Field(default_factory=dict)
    consistency_score: float = 0.0  # 0-100

    # Speed stats (raw, not scored)
    median_latency_s: float | None = None
    p95_latency_s: float | None = None

    overall: float = 0.0  # equal-weight average of the 3 dimensions


# ---------------------------------------------------------------------------
# nDCG calculation
# ---------------------------------------------------------------------------

RELEVANCE_THRESHOLD = 0.5  # minimum relevance_grade to count as "qualified"


def _dcg(relevance_grades: list[float], k: int) -> float:
    """Discounted Cumulative Gain at position k."""
    total = 0.0
    for i, rel in enumerate(relevance_grades[:k]):
        total += rel / math.log2(i + 2)  # i+2 because positions are 1-indexed
    return total


def _ndcg(relevance_grades: list[float], k: int) -> float:
    """Normalized Discounted Cumulative Gain at position k (padded ideal).

    Uses a padded ideal: the denominator assumes K perfectly relevant results
    are possible, so platforms returning fewer results are penalized. This
    prevents a platform that returns only 1 perfect result from scoring 1.0.
    """
    if not relevance_grades:
        return 0.0

    dcg = _dcg(relevance_grades, k)
    # Padded ideal: assume K perfect (1.0) results are achievable
    idcg = _dcg([1.0] * k, k)

    if idcg == 0:
        return 0.0
    return dcg / idcg


def _precision_at_k(
    relevance_grades: list[float], k: int, threshold: float = RELEVANCE_THRESHOLD
) -> float:
    """Precision@K: fraction of top-K results that are qualified."""
    top_k = relevance_grades[:k]
    if not top_k:
        return 0.0
    qualified = sum(1 for r in top_k if r >= threshold)
    return qualified / len(top_k)


# ---------------------------------------------------------------------------
# Structural field coverage
# ---------------------------------------------------------------------------

SCENARIO_FIELDS: dict[str, list[tuple[str, float]]] = {
    "find_candidates": [
        ("name", 1.0),
        ("title", 1.0),
        ("company", 1.0),
        ("location", 0.8),
        ("linkedin_url", 0.8),
        ("bio", 0.6),
        ("email", 0.5),
        ("extra", 0.3),
    ],
    "find_customers": [
        ("name", 1.0),
        ("title", 1.0),
        ("company", 1.0),
        ("location", 0.8),
        ("email", 0.8),
        ("linkedin_url", 0.6),
        ("bio", 0.5),
        ("extra", 0.3),
    ],
    "find_kol": [
        ("name", 1.0),
        ("bio", 1.0),
        ("linkedin_url", 0.8),
        ("location", 0.6),
        ("extra", 0.8),
        ("title", 0.3),
        ("company", 0.3),
        ("email", 0.3),
    ],
    "find_experts": [
        ("name", 1.0),
        ("title", 1.0),
        ("company", 0.8),
        ("linkedin_url", 0.8),
        ("bio", 0.8),
        ("location", 0.5),
        ("email", 0.3),
        ("extra", 0.3),
    ],
    "find_partners": [
        ("name", 1.0),
        ("title", 1.0),
        ("company", 1.0),
        ("location", 0.6),
        ("linkedin_url", 0.6),
        ("bio", 0.5),
        ("email", 0.5),
        ("extra", 0.3),
    ],
}

DEFAULT_FIELDS = [
    ("name", 1.0),
    ("title", 1.0),
    ("company", 1.0),
    ("location", 0.8),
    ("linkedin_url", 0.8),
    ("bio", 0.6),
    ("email", 0.5),
    ("extra", 0.3),
]


def compute_structural_score(person_data: dict[str, Any], category: str) -> float:
    """Compute field coverage score for a person, adapted to scenario."""
    fields = SCENARIO_FIELDS.get(category, DEFAULT_FIELDS)
    max_weight = sum(w for _, w in fields)
    if max_weight == 0:
        return 0.0

    earned = 0.0
    for field_name, weight in fields:
        if field_name == "extra":
            extra = person_data.get("extra", {})
            if extra and isinstance(extra, dict) and len(extra) > 0:
                earned += min(len(extra) * 0.1, 1.0) * weight
        else:
            value = person_data.get(field_name)
            if value and str(value).strip() and str(value) != "None":
                earned += weight

    return min(earned / max_weight, 1.0)


# ---------------------------------------------------------------------------
# Aggregate scoring
# ---------------------------------------------------------------------------


def compute_query_metrics(
    query_id: str,
    platform: str,
    category: str,
    person_evals: list[PersonEvaluation],
    requested_k: int = 25,
) -> QueryMetrics:
    """Compute all metrics for one query from person-level evaluations."""
    if not person_evals:
        return QueryMetrics(
            query_id=query_id,
            platform=platform,
            category=category,
            num_results=0,
            task_success=False,
        )

    relevance_grades = [p.relevance_grade for p in person_evals]
    num_qualified = sum(1 for r in relevance_grades if r >= RELEVANCE_THRESHOLD)
    task_success = num_qualified >= 1

    utility_scores = [p.utility_score for p in person_evals if p.error is None]
    avg_utility = sum(utility_scores) / len(utility_scores) if utility_scores else 0.0

    coverage = min(num_qualified / max(requested_k, 1), 1.0) if task_success else 0.0

    return QueryMetrics(
        query_id=query_id,
        platform=platform,
        category=category,
        num_results=len(person_evals),
        num_qualified=num_qualified,
        task_success=task_success,
        ndcg_5=_ndcg(relevance_grades, 5),
        ndcg_10=_ndcg(relevance_grades, 10),
        ndcg_25=_ndcg(relevance_grades, 25),
        precision_5=_precision_at_k(relevance_grades, 5),
        precision_10=_precision_at_k(relevance_grades, 10),
        precision_25=_precision_at_k(relevance_grades, 25),
        coverage_score=coverage,
        utility_score=avg_utility,
        person_evaluations=person_evals,
    )


def compute_platform_scores(
    platform: str,
    query_metrics_list: list[QueryMetrics],
    total_queries: int | None = None,
) -> DimensionScores:
    """Aggregate query-level metrics into platform-level dimension scores.

    total_queries: total number of queries INCLUDING failed ones (0-result).
    If None, uses len(query_metrics_list).
    """
    if total_queries is None:
        total_queries = len(query_metrics_list)

    if total_queries == 0:
        return DimensionScores(platform=platform)

    completed = [q for q in query_metrics_list if q.num_results > 0]
    all_qs = query_metrics_list

    # -- Task completion --
    task_completion_rate = sum(1 for q in all_qs if q.task_success) / total_queries

    # -- Relevance Precision (nDCG@K) --
    # Failed queries contribute 0 to the average
    ndcg_5_vals = [q.ndcg_5 for q in all_qs]
    ndcg_10_vals = [q.ndcg_10 for q in all_qs]
    ndcg_25_vals = [q.ndcg_25 for q in all_qs]

    # Pad with zeros for failed queries not in the list
    pad = total_queries - len(all_qs)
    ndcg_10_vals.extend([0.0] * pad)
    ndcg_5_vals.extend([0.0] * pad)
    ndcg_25_vals.extend([0.0] * pad)

    mean_ndcg_5 = sum(ndcg_5_vals) / total_queries
    mean_ndcg_10 = sum(ndcg_10_vals) / total_queries
    mean_ndcg_25 = sum(ndcg_25_vals) / total_queries

    relevance_precision = mean_ndcg_10 * 100

    # -- Effective Coverage --
    qualified_counts = [q.num_qualified for q in all_qs]
    qualified_counts.extend([0] * pad)
    mean_qualified = sum(qualified_counts) / total_queries
    coverage_vals = [q.coverage_score for q in all_qs]
    coverage_vals.extend([0.0] * pad)
    effective_coverage = (
        task_completion_rate * (sum(coverage_vals) / total_queries) * 100
    )

    # -- Information Utility --
    utility_vals = [q.utility_score for q in all_qs if q.utility_score > 0]
    mean_utility = sum(utility_vals) / len(utility_vals) if utility_vals else 0.0
    information_utility = mean_utility * 100

    # -- Per-category breakdown --
    categories = sorted({q.category for q in all_qs if q.category})
    by_category: dict[str, dict[str, float]] = {}

    for cat in categories:
        cat_qs = [q for q in all_qs if q.category == cat]
        cat_total = len(cat_qs)
        if cat_total == 0:
            continue
        cat_ndcg = sum(q.ndcg_10 for q in cat_qs) / cat_total * 100
        cat_qualified = sum(q.num_qualified for q in cat_qs) / cat_total
        cat_coverage = sum(q.coverage_score for q in cat_qs) / cat_total * 100
        cat_utility_vals = [q.utility_score for q in cat_qs if q.utility_score > 0]
        cat_utility = (
            sum(cat_utility_vals) / len(cat_utility_vals) * 100
            if cat_utility_vals
            else 0.0
        )
        cat_success = sum(1 for q in cat_qs if q.task_success) / cat_total * 100

        by_category[cat] = {
            "relevance_precision": round(cat_ndcg, 2),
            "effective_coverage": round(cat_coverage, 2),
            "information_utility": round(cat_utility, 2),
            "task_completion_rate": round(cat_success, 2),
            "mean_qualified_results": round(cat_qualified, 1),
            "num_queries": cat_total,
        }

    # -- Consistency --
    if len(by_category) >= 2:
        cat_relevance_scores = [v["relevance_precision"] for v in by_category.values()]
        mean_cat = sum(cat_relevance_scores) / len(cat_relevance_scores)
        if mean_cat > 0:
            std_cat = (
                sum((s - mean_cat) ** 2 for s in cat_relevance_scores)
                / len(cat_relevance_scores)
            ) ** 0.5
            cv = std_cat / mean_cat
            consistency = max(0, (1 - cv)) * 100
        else:
            consistency = 0.0
    else:
        consistency = 100.0

    # -- Overall (equal weight) --
    overall = (relevance_precision + effective_coverage + information_utility) / 3

    return DimensionScores(
        platform=platform,
        total_queries=total_queries,
        completed_queries=len(completed),
        task_completion_rate=round(task_completion_rate * 100, 2),
        relevance_precision=round(relevance_precision, 2),
        effective_coverage=round(effective_coverage, 2),
        information_utility=round(information_utility, 2),
        ndcg_at_k={
            5: round(mean_ndcg_5 * 100, 2),
            10: round(mean_ndcg_10 * 100, 2),
            25: round(mean_ndcg_25 * 100, 2),
        },
        precision_at_k={
            5: round(sum(q.precision_5 for q in all_qs) / total_queries * 100, 2),
            10: round(sum(q.precision_10 for q in all_qs) / total_queries * 100, 2),
            25: round(sum(q.precision_25 for q in all_qs) / total_queries * 100, 2),
        },
        mean_qualified_results=round(mean_qualified, 1),
        by_category=by_category,
        consistency_score=round(consistency, 2),
        overall=round(overall, 2),
    )
