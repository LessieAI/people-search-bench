"""People Search Benchmark — full evaluation pipeline.

Runs Criteria-Grounded Verification on search results from any platform.
Requires API keys (set in .env or environment):
  - OPENROUTER_API_KEY: LLM for criteria extraction and person verification
  - TAVILY_API_KEY: web search for fact-checking

Usage:
    # Evaluate a single CSV file
    uv run main.py data/raw_results/lessie/recruiting_lessie.csv

    # Evaluate all CSVs in a directory
    uv run main.py data/raw_results/lessie/

    # Filter by category
    uv run main.py data/raw_results/lessie/ --categories recruiting b2b

    # Use a different LLM model
    uv run main.py data/raw_results/lessie/ --model google/gemini-2.0-flash-001

    # For a lightweight example without API keys (uses pre-computed data):
    uv run tools/compute_scores.py --demo

Supports two CSV formats (auto-detected):
  1. Standard: columns (query_id, agent_name, person_data) — one row per person
  2. Raw results: columns (query_id, prompt, results_json) — one row per query,
     agent name inferred from filename (e.g., recruiting_lessie.csv -> lessie)
"""

import argparse
import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from benchmark.data_loader import load_results_file, load_results_dir
from benchmark.evaluators import CriteriaEvaluator
from benchmark.runner import load_queries, build_query_map, run_benchmark

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

PROJECT_DIR = Path(__file__).parent
QUERIES_DIR = PROJECT_DIR / "data" / "queries"
OUTPUT_DIR = PROJECT_DIR / "data" / "results"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="People Search Benchmark - evaluate AI-powered people search agents"
    )
    parser.add_argument(
        "input",
        help="Path to a CSV/Excel file or a directory containing them",
    )
    parser.add_argument(
        "--queries-dir",
        default=str(QUERIES_DIR),
        help="Directory with query JSONL files (default: data/queries/)",
    )
    parser.add_argument(
        "--agents",
        nargs="+",
        default=None,
        help="Only evaluate these agents (filter by agent_name in the data)",
    )
    parser.add_argument(
        "--categories",
        nargs="+",
        default=None,
        help="Only evaluate these query categories",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=3,
        help="Max concurrent LLM judge calls (default: 3)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="google/gemini-3-flash-preview",
        help="LLM model for evaluation (default: google/gemini-3-flash-preview)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output file path for results JSON",
    )
    return parser.parse_args()


def print_summary(summary: dict[str, dict[str, float]]) -> None:
    if not summary:
        print("\nNo results to summarize.")
        return

    agents = list(summary.keys())
    metrics = set()
    for scores in summary.values():
        metrics.update(scores.keys())
    metrics_list = sorted(metrics)

    header = f"{'Metric':<20}" + "".join(f"{a:<15}" for a in agents)
    print("\n" + "=" * len(header))
    print("BENCHMARK RESULTS")
    print("=" * len(header))
    print(header)
    print("-" * len(header))

    for metric in metrics_list:
        row = f"{metric:<20}"
        for agent in agents:
            val = summary.get(agent, {}).get(metric, 0.0)
            row += f"{val:<15.4f}"
        print(row)

    print("=" * len(header))


async def main() -> None:
    args = parse_args()

    queries = load_queries(Path(args.queries_dir))
    if args.categories:
        cat_set = set(args.categories)
        queries = [
            q
            for q in queries
            if q.category in cat_set
            or (hasattr(q.category, "value") and q.category.value in cat_set)
        ]
    query_map = build_query_map(queries)
    logger.info("Loaded %d eval queries from %s", len(queries), args.queries_dir)

    input_path = Path(args.input)
    if input_path.is_dir():
        search_results = load_results_dir(input_path)
    elif input_path.is_file():
        search_results = load_results_file(input_path)
    else:
        logger.error("Input path not found: %s", args.input)
        sys.exit(1)

    if args.agents:
        search_results = [r for r in search_results if r.agent_name in args.agents]

    if not search_results:
        logger.error("No search results loaded. Check input file and column names.")
        sys.exit(1)

    logger.info(
        "Loaded %d (query, agent) result groups across agents: %s",
        len(search_results),
        sorted({r.agent_name for r in search_results}),
    )

    evaluators = [CriteriaEvaluator(model_name=args.model)]

    report = await run_benchmark(
        search_results=search_results,
        query_map=query_map,
        evaluators=evaluators,
        concurrency=args.concurrency,
    )

    print_summary(report.summary)

    if args.output:
        output_path = Path(args.output)
    else:
        OUTPUT_DIR.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = OUTPUT_DIR / f"benchmark_{ts}.json"

    report.save(output_path)
    logger.info("Results saved to %s", output_path)


if __name__ == "__main__":
    asyncio.run(main())
