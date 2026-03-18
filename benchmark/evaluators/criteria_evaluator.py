"""Criteria-Grounded Evaluator: extracts verifiable criteria from queries,
then checks each person against those criteria using web search evidence.

This replaces the holistic subjective scoring with structured factual verification.
The AI is asked to check specific facts, not give subjective quality ratings.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re

from langchain.agents import create_agent
from langchain_tavily import TavilySearch
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from benchmark.evaluators.base import BaseEvaluator
from benchmark.metrics import (
    CriterionResult,
    PersonEvaluation,
)
from benchmark.models import AgentSearchResult, EvalScore, PersonResult, Query

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Criteria extraction
# ---------------------------------------------------------------------------


class QueryCriteria(BaseModel):
    """Extracted criteria from a query for evaluation."""

    query_id: str
    query_type: str = "general"
    language: str = "en"
    criteria: list[dict[str, str]] = Field(default_factory=list)
    # Each criterion: {"id": "c1", "description": "...", "field_hint": "title|company|..."}


CRITERIA_EXTRACTION_PROMPT = """You are an expert at analyzing people search queries.

Given a search query, extract ALL verifiable criteria that a returned person should match.
Each criterion should be a specific, checkable condition.

## Rules
1. Extract every explicit condition mentioned in the query.
2. Each criterion should be independently verifiable (can check true/false).
3. Include implicit criteria when they are clearly implied.
   Example: "Find senior ML engineers" implies role seniority AND ML specialization.
4. For location criteria, be specific about the geographic scope.
5. For role criteria, include reasonable synonyms/equivalents.
6. Classify each criterion by which person field it maps to.

## Output format
Return a JSON object:
```json
{
  "query_type": "recruiting|b2b_prospecting|influencer_search|deterministic|general",
  "language": "en|zh|...",
  "criteria": [
    {
      "id": "c1",
      "description": "Person holds a senior-level machine learning engineering role (Senior ML Engineer, Staff ML Engineer, Principal ML Engineer, or equivalent)",
      "field_hint": "title"
    },
    {
      "id": "c2",
      "description": "Person works or has recently worked at Google",
      "field_hint": "company"
    },
    {
      "id": "c3",
      "description": "Person is based in the San Francisco Bay Area",
      "field_hint": "location"
    }
  ]
}
```

Be thorough. Missing a criterion means we cannot properly evaluate results."""


# ---------------------------------------------------------------------------
# Person verification
# ---------------------------------------------------------------------------

VERIFICATION_SYSTEM_PROMPT = """You are a fact-checking assistant for a People Search Benchmark.

Your job: Given a person's data and a list of criteria from the original search query,
verify each criterion using the person's data AND web search.

## Process
1. Read the person's data carefully.
2. For each criterion, determine if it is met, partially met, or not met.
3. Use web search to verify claims when possible (especially name, title, company).
4. Be strict: if information cannot be verified, mark confidence as "low".

## Criterion matching rules
- "met": The person clearly satisfies this criterion based on available evidence.
- "partially_met": The person partially matches (e.g., right field but wrong seniority,
  right region but wrong city, related but not exact role).
- "not_met": No evidence the person matches, or evidence contradicts the criterion.

## For Information Utility assessment
Assess TWO aspects of the returned data:

### A. Data Completeness (structural)
How rich is the person's profile data? Consider what fields are present and populated:
- Identity: name, photo/avatar
- Professional: job title, company/organization, seniority
- Contact: email, phone, LinkedIn URL, other social profiles
- Context: location, bio/summary, work history, education
- Extras: publications, skills, follower counts, etc.
Score 0.0 (only a name) to 1.0 (comprehensive profile with contact info, work history, etc.)

### B. Actionability (contextual)
- Does the data explain WHY this person matches the query?
- Is there enough information for the user to take next steps (contact, shortlist, etc.)?

## Output format
Return a JSON object:
```json
{
  "verification_summary": "Brief summary of what you found when verifying this person",
  "criteria_results": [
    {
      "criterion_id": "c1",
      "match": "met|partially_met|not_met",
      "evidence": "What evidence supports this judgment",
      "confidence": "high|medium|low"
    }
  ],
  "information_utility": {
    "structural_completeness": 0.0-1.0,
    "has_match_explanation": true/false,
    "actionability": 0.0|0.5|1.0,
    "reasoning": "Why these scores"
  }
}
```

Be honest and strict. Do not inflate results."""


def _create_llm(
    model_name: str = "google/gemini-3-flash-preview",
    temperature: float = 0,
    max_tokens: int = 8192,
) -> ChatOpenAI:
    return ChatOpenAI(
        model=model_name,
        api_key=os.environ.get("OPENROUTER_API_KEY", ""),
        base_url=os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        temperature=temperature,
        max_tokens=max_tokens,
        max_retries=3,
    )


def _parse_json_response(content: str) -> dict:
    """Extract JSON from LLM response, handling various formats."""
    if "```json" in content:
        json_str = content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        json_str = content.split("```")[1].split("```")[0].strip()
    else:
        start = content.find("{")
        end = content.rfind("}") + 1
        json_str = content[start:end] if start != -1 else "{}"

    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        cleaned = re.sub(r",\s*}", "}", json_str)
        cleaned = re.sub(r",\s*]", "]", cleaned)
        return json.loads(cleaned)


# ---------------------------------------------------------------------------
# CriteriaEvaluator
# ---------------------------------------------------------------------------


class CriteriaEvaluator(BaseEvaluator):
    """Evaluates search results using criteria-grounded factual verification."""

    name: str = "criteria"

    def __init__(
        self,
        model_name: str = "google/gemini-3-flash-preview",
        max_search_results: int = 3,
    ) -> None:
        self.model_name = model_name
        self.max_search_results = max_search_results
        self._llm = None
        self._agent = None

    async def evaluate(
        self, query: Query, search_result: AgentSearchResult
    ) -> EvalScore:
        """Run criteria-grounded verification on all persons in a search result."""
        criteria = await self.extract_criteria(query)

        person_evals: list[PersonEvaluation] = []
        for person in search_result.results:
            pe = await self.verify_person(person, query, criteria)
            person_evals.append(pe)

        if person_evals:
            avg_relevance = sum(pe.relevance_grade for pe in person_evals) / len(
                person_evals
            )
        else:
            avg_relevance = 0.0

        return EvalScore(
            metric_name=self.name,
            score=round(avg_relevance, 4),
            details={
                "num_persons": len(person_evals),
                "criteria_count": len(criteria.criteria),
                "person_evaluations": [pe.model_dump() for pe in person_evals],
            },
        )

    def _get_llm(self) -> ChatOpenAI:
        if self._llm is None:
            self._llm = _create_llm(model_name=self.model_name)
        return self._llm

    def _get_verification_agent(self):
        if self._agent is None:
            llm = _create_llm(
                model_name=self.model_name,
                max_tokens=4096,
            )
            tavily_tool = TavilySearch(
                max_results=self.max_search_results,
                search_depth="advanced",
                include_answer=True,
            )
            self._agent = create_agent(
                model=llm,
                tools=[tavily_tool],
                system_prompt=VERIFICATION_SYSTEM_PROMPT,
            ).with_config(RunnableConfig(recursion_limit=30))
        return self._agent

    async def extract_criteria(self, query: Query) -> QueryCriteria:
        """Extract verifiable criteria from a query using LLM."""
        llm = self._get_llm()

        try:
            response = await llm.ainvoke(
                [
                    {"role": "system", "content": CRITERIA_EXTRACTION_PROMPT},
                    {
                        "role": "user",
                        "content": f"Extract criteria from this search query:\n\n{query.text}",
                    },
                ]
            )

            content = response.content
            if isinstance(content, list):
                content = " ".join(
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in content
                )

            parsed = _parse_json_response(content)
            return QueryCriteria(
                query_id=query.id,
                query_type=parsed.get("query_type", "general"),
                language=parsed.get("language", "en"),
                criteria=parsed.get("criteria", []),
            )
        except Exception as e:
            logger.warning("Criteria extraction failed for %s: %s", query.id, e)
            return QueryCriteria(query_id=query.id)

    async def verify_person(
        self,
        person: PersonResult,
        query: Query,
        criteria: QueryCriteria,
        timeout: float = 120,
    ) -> PersonEvaluation:
        """Verify one person against extracted criteria using web search."""
        agent = self._get_verification_agent()

        criteria_text = json.dumps(criteria.criteria, indent=2, ensure_ascii=False)

        user_message = f"""## Original Search Query
{query.text}

## Criteria to Verify
{criteria_text}

## Person Data to Evaluate
{person.to_text()}

Verify each criterion against this person's data. Use web search to fact-check.
Then assess the information utility (actionability) of this result."""

        try:
            result = await asyncio.wait_for(
                agent.ainvoke(
                    {"messages": [{"role": "user", "content": user_message}]}
                ),
                timeout=timeout,
            )

            final_message = result["messages"][-1]
            content = final_message.content
            if isinstance(content, list):
                content = " ".join(
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in content
                )

            parsed = _parse_json_response(content)

            # Build criterion results
            criteria_results = []
            for cr in parsed.get("criteria_results", []):
                criteria_results.append(
                    CriterionResult(
                        criterion_id=cr.get("criterion_id", ""),
                        description=_find_criterion_desc(
                            cr.get("criterion_id", ""), criteria
                        ),
                        match=cr.get("match", "not_met"),
                        evidence=cr.get("evidence", ""),
                        confidence=cr.get("confidence", "medium"),
                    )
                )

            # Compute relevance grade from criteria
            if criteria_results:
                relevance_grade = sum(cr.score for cr in criteria_results) / len(
                    criteria_results
                )
            else:
                relevance_grade = 0.0

            # Information utility from AI response (both structural and contextual)
            iu = parsed.get("information_utility", parsed.get("contextual_utility", {}))
            structural = float(iu.get("structural_completeness", 0.5))
            has_explanation = iu.get("has_match_explanation", False)
            actionability = float(iu.get("actionability", 0.5))
            contextual = (0.3 if has_explanation else 0.0) + 0.7 * actionability

            utility = 0.5 * structural + 0.5 * contextual

            return PersonEvaluation(
                person_name=person.name or "(unknown)",
                criteria_results=criteria_results,
                relevance_grade=round(relevance_grade, 4),
                structural_score=round(structural, 4),
                contextual_score=round(contextual, 4),
                utility_score=round(utility, 4),
                verification_summary=parsed.get("verification_summary", ""),
            )

        except TimeoutError:
            logger.warning("Verification timed out for %s", person.name)
            return PersonEvaluation(
                person_name=person.name or "(unknown)",
                error=f"timeout after {timeout}s",
            )
        except Exception as e:
            logger.warning("Verification failed for %s: %s", person.name, e)
            return PersonEvaluation(
                person_name=person.name or "(unknown)",
                error=str(e),
            )


def _find_criterion_desc(criterion_id: str, criteria: QueryCriteria) -> str:
    """Look up criterion description by ID."""
    for c in criteria.criteria:
        if c.get("id") == criterion_id:
            return c.get("description", "")
    return ""
