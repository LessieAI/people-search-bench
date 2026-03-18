# Evaluation Results

This directory contains **aggregated platform-level scores** from the benchmark evaluation.

## Files

Each platform subdirectory contains a `summary.json` with:

```json
{
  "platform": "lessie",
  "total_queries": 119,
  "scores": {
    "relevance_precision": 70.2,
    "effective_coverage": 69.1,
    "information_utility": 56.4,
    "overall": 65.2,
    "task_completion_rate": 100.0,
    "mean_qualified_results": 10.4
  },
  "by_category": { ... }
}
```

## Privacy Notice

Per-person evaluation details (person names, relevance grades, criteria match results) are **excluded** for privacy reasons. Only aggregated scores are published.

See the project [README](../../README.md) for details.
