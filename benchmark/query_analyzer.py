"""LLM-based query analyzer -- auto-classifies query type and extracts expected criteria."""

from __future__ import annotations

import json
import logging
import os

from langchain_openai import ChatOpenAI
from typing import Any

from pydantic import BaseModel, Field

from benchmark.models import Query

logger = logging.getLogger(__name__)

ANALYZER_PROMPT = """You are an expert at analyzing people search queries.

Given a search query, analyze it and produce a structured evaluation specification.

## Your task

1. **query_type**: Classify the query into one of these types:
   - "deterministic": Queries with verifiable correct answers or that seek specific domain experts (e.g., "Find all co-founders of Y", "List all research scientists at OpenAI", "Top reinforcement learning researchers by publication record")
   - "recruiting": Looking for candidates with specific skills/experience for hiring
   - "b2b_prospecting": Finding potential customers, partners, or business contacts
   - "influencer_search": Finding influencers, KOLs, content creators
   - "general": Anything else

2. **expected_criteria**: Extract the key criteria the search results should match.
   Include whatever is relevant from: role/title, industry, location, company, skills,
   follower count, platform, experience level, etc.

3. **evaluation_focus**: Based on query type, specify which evaluation dimensions
   matter most (weights should sum to 1.0):
   - relevance: Does the person match the query intent?
   - accuracy: Is the person's information factually correct and verifiable?
   - information_completeness: How rich is the profile data?
   - uniqueness: How non-obvious is this result?

   For deterministic queries: accuracy and relevance should be highest (verifiable experts or known roles).
   For recruiting: relevance and completeness should be highest.
   For influencer: relevance should be highest, uniqueness matters.
   For b2b: relevance and accuracy should be balanced.

4. **language**: Detect the primary language of the query (ISO 639-1 code).

Return a JSON object:

```json
{
  "query_type": "<type>",
  "language": "<lang_code>",
  "expected_criteria": {
    "<criterion_key>": "<criterion_value>",
    ...
  },
  "evaluation_focus": {
    "relevance": <0.0-1.0>,
    "accuracy": <0.0-1.0>,
    "information_completeness": <0.0-1.0>,
    "uniqueness": <0.0-1.0>
  }
}
```"""


class QueryAnalysis(BaseModel):
    query_type: str = "general"
    language: str = "en"
    expected_criteria: dict[str, Any] = Field(default_factory=dict)
    evaluation_focus: dict[str, float] = Field(
        default_factory=lambda: {
            "relevance": 0.30,
            "accuracy": 0.30,
            "information_completeness": 0.20,
            "uniqueness": 0.20,
        }
    )


def _create_analyzer_model(
    model_name: str = "google/gemini-3-flash-preview",
) -> ChatOpenAI:
    return ChatOpenAI(
        model=model_name,
        api_key=os.environ.get("OPENROUTER_API_KEY", ""),
        base_url=os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        temperature=0,
        max_tokens=2048,
        max_retries=3,
    )


def _parse_analysis_response(content: str) -> dict:
    if "```json" in content:
        json_str = content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        json_str = content.split("```")[1].split("```")[0].strip()
    else:
        start = content.find("{")
        end = content.rfind("}") + 1
        json_str = content[start:end] if start != -1 else "{}"
    return json.loads(json_str)


async def analyze_query(
    query: Query,
    model_name: str = "google/gemini-3-flash-preview",
) -> QueryAnalysis:
    llm = _create_analyzer_model(model_name=model_name)

    try:
        response = await llm.ainvoke(
            [
                {"role": "system", "content": ANALYZER_PROMPT},
                {
                    "role": "user",
                    "content": f"Analyze this search query:\n\n{query.text}",
                },
            ]
        )

        content = response.content
        if isinstance(content, list):
            content = " ".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in content
            )

        parsed = _parse_analysis_response(content)
        return QueryAnalysis(**parsed)

    except Exception as e:
        logger.warning("Query analysis failed for %s: %s", query.id, e)
        return QueryAnalysis()


async def analyze_queries(
    queries: list[Query],
    model_name: str = "google/gemini-3-flash-preview",
) -> dict[str, QueryAnalysis]:
    import asyncio

    results: dict[str, QueryAnalysis] = {}
    semaphore = asyncio.Semaphore(5)

    async def _analyze_one(q: Query) -> tuple[str, QueryAnalysis]:
        async with semaphore:
            analysis = await analyze_query(q, model_name=model_name)
            logger.info(
                "Analyzed %s: type=%s, lang=%s, criteria=%s",
                q.id,
                analysis.query_type,
                analysis.language,
                list(analysis.expected_criteria.keys()),
            )
            return q.id, analysis

    tasks = [_analyze_one(q) for q in queries]
    for coro in asyncio.as_completed(tasks):
        query_id, analysis = await coro
        results[query_id] = analysis

    return results
