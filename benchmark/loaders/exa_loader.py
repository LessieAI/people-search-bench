"""Load Exa-format CSV files (query_id, prompt, results_json) into benchmark models."""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path

from benchmark.models import AgentSearchResult, PersonResult, Query

logger = logging.getLogger(__name__)

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


def _exa_entity_to_person(entity: dict, result_obj: dict) -> PersonResult:
    name = entity.get("name")
    location = entity.get("location")
    linkedin_url = result_obj.get("url")

    work_history = entity.get("work_history", [])
    current_title = None
    current_company = None
    if work_history:
        latest = work_history[0]
        current_title = latest.get("title")
        company_obj = latest.get("company")
        if isinstance(company_obj, dict):
            current_company = company_obj.get("name")

    bio_parts: list[str] = []
    if result_obj.get("title"):
        bio_parts.append(result_obj["title"])
    for job in work_history[:3]:
        job_title = job.get("title", "")
        job_company = (job.get("company") or {}).get("name", "")
        dates = job.get("dates", {})
        date_from = dates.get("from", "")
        date_to = dates.get("to", "present") or "present"
        if job_title or job_company:
            bio_parts.append(f"  {job_title} @ {job_company} ({date_from} - {date_to})")
    bio = "\n".join(bio_parts) if bio_parts else None

    raw_text = json.dumps(result_obj, ensure_ascii=False, indent=1)

    return PersonResult(
        raw_text=raw_text,
        name=name,
        title=current_title,
        company=current_company,
        location=location,
        linkedin_url=linkedin_url,
        bio=bio,
        extra={"work_history_count": str(len(work_history))},
    )


def _parse_exa_result(result_obj: dict) -> list[PersonResult]:
    entities = result_obj.get("entities", [])
    person_entities = [e for e in entities if e.get("type") == "person"]

    if person_entities:
        return [_exa_entity_to_person(e, result_obj) for e in person_entities]

    name = result_obj.get("author")
    return [
        PersonResult(
            raw_text=json.dumps(result_obj, ensure_ascii=False, indent=1),
            name=name,
            title=result_obj.get("title"),
            linkedin_url=result_obj.get("url"),
        )
    ]


def load_exa_csv(
    path: Path, agent_name: str = "exa"
) -> tuple[list[Query], list[AgentSearchResult]]:
    category_hint = _infer_category_from_filename(path.stem)

    queries: list[Query] = []
    search_results: list[AgentSearchResult] = []

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

            persons: list[PersonResult] = []
            for result_obj in results_json:
                persons.extend(_parse_exa_result(result_obj))

            query = Query(
                id=query_id,
                text=prompt,
                category=category_hint,
                difficulty="medium",
            )
            queries.append(query)

            search_results.append(
                AgentSearchResult(
                    agent_name=agent_name,
                    query_id=query_id,
                    results=persons,
                )
            )

    logger.info(
        "Loaded %d queries from %s (%d total persons)",
        len(queries),
        path.name,
        sum(len(sr.results) for sr in search_results),
    )
    return queries, search_results
