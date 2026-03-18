"""Load Claude Code CSV files (query_id, prompt, results_json) into benchmark models.

Claude Code results contain a markdown report from a general-purpose agent.
An LLM extraction step is needed to pull individual persons from the report.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import sys
from pathlib import Path

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from benchmark.models import AgentSearchResult, PersonResult, Query

logger = logging.getLogger(__name__)

csv.field_size_limit(sys.maxsize)

CATEGORY_HINTS: dict[str, str] = {
    "b2b": "find_customers",
    "recruiting": "find_candidates",
    "influencer": "find_kol",
    "deterministic": "find_experts",
}


def _infer_category_from_filename(filename: str) -> str:
    name_lower = filename.lower()
    for hint, category in CATEGORY_HINTS.items():
        if hint in name_lower:
            return category
    return "unknown"


class ClaudeCodeRawResult(BaseModel):
    query_id: str
    prompt: str
    output_text: str
    status: str = "completed"
    duration_ms: int = 0
    session_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


class ExtractedPerson(BaseModel):
    name: str
    title: str | None = None
    company: str | None = None
    location: str | None = None
    linkedin_url: str | None = None
    email: str | None = None
    bio: str | None = None
    extra_info: dict[str, str] = Field(default_factory=dict)


EXTRACTION_PROMPT = """You are an expert at extracting structured person information from search reports.

Given a search query and a report containing information about people, extract ALL individual
people mentioned in the report. For each person, provide structured information.

Rules:
1. Extract EVERY distinct person mentioned by name in the report.
2. If the report contains tables of people, extract each row as a separate person.
3. If a person has no real name (only a business name or handle), still extract them
   ONLY if they clearly represent an individual person (e.g., an Instagram influencer handle).
4. Do NOT extract companies, organizations, platforms, or brands -- only individual people.
5. Do NOT fabricate information -- only extract what is explicitly stated in the report.
6. Skip generic role descriptions without specific names (e.g., "VP of Marketing" without a name).
7. If the report is a refusal or contains no individual person data, return an empty array.

Return a JSON array wrapped in ```json``` markers:

```json
[
  {
    "name": "Full Name",
    "title": "Job Title or Role",
    "company": "Company or Organization",
    "location": "City, Country",
    "linkedin_url": "URL if available",
    "email": "email if available",
    "bio": "Brief summary of who they are",
    "extra_info": {"key": "value"}
  }
]
```

If no people can be extracted, return: ```json\n[]\n```"""


def _create_extraction_model(
    model_name: str = "google/gemini-3-flash-preview",
) -> ChatOpenAI:
    return ChatOpenAI(
        model=model_name,
        api_key=os.environ.get("OPENROUTER_API_KEY", ""),
        base_url=os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        temperature=0,
        max_tokens=16384,
        max_retries=3,
    )


def _parse_extraction_response(content: str) -> list[dict]:
    if "```json" in content:
        json_str = content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        json_str = content.split("```")[1].split("```")[0].strip()
    else:
        start = content.find("[")
        end = content.rfind("]") + 1
        json_str = content[start:end] if start != -1 else "[]"
    return json.loads(json_str)


async def extract_persons_from_report(
    query_text: str,
    report_text: str,
    model_name: str = "google/gemini-3-flash-preview",
) -> list[ExtractedPerson]:
    if not report_text or len(report_text.strip()) < 50:
        return []

    llm = _create_extraction_model(model_name=model_name)

    try:
        response = await llm.ainvoke(
            [
                {"role": "system", "content": EXTRACTION_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"## Search Query\n{query_text}\n\n## Report\n{report_text}"
                    ),
                },
            ]
        )

        content = response.content
        if isinstance(content, list):
            content = " ".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in content
            )

        parsed = _parse_extraction_response(content)
        results = []
        for p in parsed:
            if not p.get("name"):
                continue
            extra = p.get("extra_info", {})
            if isinstance(extra, dict):
                p["extra_info"] = {
                    k: str(v) if not isinstance(v, str) else v for k, v in extra.items()
                }
            else:
                p["extra_info"] = {}
            try:
                results.append(ExtractedPerson(**p))
            except Exception as e:
                logger.debug("Skipping malformed person entry: %s", e)
                try:
                    results.append(
                        ExtractedPerson(
                            name=p["name"],
                            title=p.get("title"),
                            company=p.get("company"),
                            location=p.get("location"),
                            linkedin_url=p.get("linkedin_url"),
                            email=p.get("email"),
                            bio=p.get("bio"),
                        )
                    )
                except Exception:
                    pass
        return results

    except Exception as e:
        logger.warning("Person extraction failed for query: %s", e)
        return []


def extracted_to_person_result(
    extracted: ExtractedPerson,
    report_snippet: str = "",
) -> PersonResult:
    raw_text_parts = []
    if extracted.name:
        raw_text_parts.append(f"Name: {extracted.name}")
    if extracted.title:
        raw_text_parts.append(f"Title: {extracted.title}")
    if extracted.company:
        raw_text_parts.append(f"Company: {extracted.company}")
    if extracted.location:
        raw_text_parts.append(f"Location: {extracted.location}")
    if extracted.linkedin_url:
        raw_text_parts.append(f"URL: {extracted.linkedin_url}")
    if extracted.email:
        raw_text_parts.append(f"Email: {extracted.email}")
    if extracted.bio:
        raw_text_parts.append(f"Bio: {extracted.bio}")
    for k, v in extracted.extra_info.items():
        raw_text_parts.append(f"{k}: {v}")

    raw_text = "\n".join(raw_text_parts)

    return PersonResult(
        raw_text=raw_text,
        name=extracted.name,
        title=extracted.title,
        company=extracted.company,
        location=extracted.location,
        linkedin_url=extracted.linkedin_url,
        email=extracted.email,
        bio=extracted.bio if extracted.bio else None,
        extra=extracted.extra_info,
    )


def load_claude_code_csv_raw(path: Path) -> list[ClaudeCodeRawResult]:
    results: list[ClaudeCodeRawResult] = []

    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            query_id = row["query_id"].strip()
            prompt = row["prompt"].strip()

            try:
                results_json = json.loads(row["results_json"])
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("Failed to parse results_json for %s: %s", query_id, e)
                continue

            output_text = results_json.get("output_text", "")
            status = results_json.get("status", "unknown")

            if status != "completed" or not output_text:
                logger.info(
                    "Skipping %s (status=%s, has_output=%s)",
                    query_id,
                    status,
                    bool(output_text),
                )
                continue

            results.append(
                ClaudeCodeRawResult(
                    query_id=query_id,
                    prompt=prompt,
                    output_text=output_text,
                    status=status,
                    duration_ms=results_json.get("duration_ms", 0),
                    session_id=results_json.get("session_id", ""),
                    input_tokens=results_json.get("input_tokens", 0),
                    output_tokens=results_json.get("output_tokens", 0),
                )
            )

    logger.info("Loaded %d valid queries from %s", len(results), path.name)
    return results


def load_claude_code_csv(
    path: Path, agent_name: str = "claude_code"
) -> tuple[list[Query], list[AgentSearchResult]]:
    category_hint = _infer_category_from_filename(path.stem)
    raw_results = load_claude_code_csv_raw(path)

    queries: list[Query] = []
    search_results: list[AgentSearchResult] = []

    for raw in raw_results:
        query = Query(
            id=raw.query_id,
            text=raw.prompt,
            category=category_hint,
            difficulty="medium",
            metadata={
                "duration_ms": raw.duration_ms,
                "output_tokens": raw.output_tokens,
            },
        )
        queries.append(query)

        search_results.append(
            AgentSearchResult(
                agent_name=agent_name,
                query_id=raw.query_id,
                results=[
                    PersonResult(
                        raw_text=raw.output_text,
                        name="(full report -- needs extraction)",
                    )
                ],
            )
        )

    logger.info(
        "Loaded %d queries from %s",
        len(queries),
        path.name,
    )
    return queries, search_results
