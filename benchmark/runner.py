from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from pathlib import Path

from benchmark.evaluators.base import BaseEvaluator
from benchmark.models import (
    AgentSearchResult,
    BenchmarkReport,
    EvalScore,
    Query,
    QueryEvalResult,
)

logger = logging.getLogger(__name__)


def load_queries(queries_dir: Path) -> list[Query]:
    queries: list[Query] = []
    for f in sorted(queries_dir.glob("*.jsonl")):
        for line in f.read_text().splitlines():
            line = line.strip()
            if line:
                queries.append(Query.model_validate(json.loads(line)))
    for f in sorted(queries_dir.glob("*.json")):
        data = json.loads(f.read_text())
        if isinstance(data, list):
            queries.extend(Query.model_validate(q) for q in data)
        else:
            queries.append(Query.model_validate(data))
    return queries


def build_query_map(queries: list[Query]) -> dict[str, Query]:
    return {q.id: q for q in queries}


async def evaluate_one(
    query: Query,
    search_result: AgentSearchResult,
    evaluators: list[BaseEvaluator],
) -> QueryEvalResult:
    scores: list[EvalScore] = []
    for evaluator in evaluators:
        try:
            score = await evaluator.evaluate(query, search_result)
            scores.append(score)
        except Exception as e:
            logger.warning(
                "Evaluator %s failed for query %s agent %s: %s",
                evaluator.name,
                query.id,
                search_result.agent_name,
                e,
            )
            scores.append(
                EvalScore(
                    metric_name=evaluator.name,
                    score=0.0,
                    details={"error": str(e)},
                )
            )

    overall = sum(s.score for s in scores if s.score >= 0) / max(
        len([s for s in scores if s.score >= 0]), 1
    )

    return QueryEvalResult(
        query_id=query.id,
        agent_name=search_result.agent_name,
        scores=scores,
        weighted_score=round(overall, 4),
    )


async def run_benchmark(
    search_results: list[AgentSearchResult],
    query_map: dict[str, Query],
    evaluators: list[BaseEvaluator],
    concurrency: int = 3,
) -> BenchmarkReport:
    agent_names = sorted({r.agent_name for r in search_results})
    query_ids = sorted({r.query_id for r in search_results})

    report = BenchmarkReport(
        total_queries=len(query_ids),
        agents=agent_names,
    )

    semaphore = asyncio.Semaphore(concurrency)

    async def process_one(sr: AgentSearchResult) -> QueryEvalResult | None:
        query = query_map.get(sr.query_id)
        if not query:
            logger.warning(
                "No query definition found for query_id=%s, skipping", sr.query_id
            )
            return None

        async with semaphore:
            logger.info(
                "Evaluating %s | %s | %d results ...",
                sr.agent_name,
                sr.query_id,
                len(sr.results),
            )
            result = await evaluate_one(query, sr, evaluators)
            logger.info(
                "  %s | %s | weighted=%.3f",
                sr.agent_name,
                sr.query_id,
                result.weighted_score,
            )
            return result

    tasks = [process_one(sr) for sr in search_results]
    eval_results = await asyncio.gather(*tasks, return_exceptions=True)

    for r in eval_results:
        if isinstance(r, Exception):
            logger.error("Evaluation task failed: %s", r)
        elif r is not None:
            report.results.append(r)

    report.summary = _build_summary(report)
    return report


def _build_summary(report: BenchmarkReport) -> dict[str, dict[str, float]]:
    agent_metric_scores: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    agent_weighted: dict[str, list[float]] = defaultdict(list)

    for r in report.results:
        agent_weighted[r.agent_name].append(r.weighted_score)
        for s in r.scores:
            if s.score >= 0:
                agent_metric_scores[r.agent_name][s.metric_name].append(s.score)

    summary: dict[str, dict[str, float]] = {}
    for agent_name in report.agents:
        metrics: dict[str, float] = {}
        for metric, scores in agent_metric_scores.get(agent_name, {}).items():
            metrics[metric] = round(sum(scores) / len(scores), 4) if scores else 0.0
        ws = agent_weighted.get(agent_name, [])
        metrics["weighted_avg"] = round(sum(ws) / len(ws), 4) if ws else 0.0
        summary[agent_name] = metrics

    return summary
