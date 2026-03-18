"""Load Juicebox-format CSV files (query_id, prompt, results_json) into benchmark models."""

from __future__ import annotations

import csv
import json
import logging
import sys
from pathlib import Path

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


def _parse_juicebox_person(person_obj: dict) -> PersonResult:
    name = person_obj.get("full_name")
    location = person_obj.get("location_name")
    linkedin_url = person_obj.get("linkedin_url")
    job_title = person_obj.get("job_title")
    job_company = person_obj.get("job_company_name")

    bio_parts: list[str] = []
    if person_obj.get("summary"):
        bio_parts.append(person_obj["summary"])

    experience = person_obj.get("experience", [])
    for job in experience[:3]:
        title = (job.get("title") or {}).get("name", "")
        company = (job.get("company") or {}).get("name", "")
        start = job.get("start_date", "")
        end = job.get("end_date", "") or "present"
        if title or company:
            bio_parts.append(f"  {title} @ {company} ({start} - {end})")

    education = person_obj.get("education", [])
    for edu in education[:2]:
        school = (edu.get("school") or {}).get("name", "")
        degrees = edu.get("degrees", [])
        degree_str = ", ".join(degrees) if degrees else ""
        if school:
            bio_parts.append(
                f"  {degree_str} @ {school}" if degree_str else f"  @ {school}"
            )

    bio = "\n".join(bio_parts) if bio_parts else None

    skills = person_obj.get("skills", [])
    extra: dict[str, str] = {}
    if skills:
        extra["skills"] = ", ".join(skills[:10])
    if person_obj.get("github_url"):
        extra["github_url"] = person_obj["github_url"]
    extra["experience_count"] = str(len(experience))

    raw_text = json.dumps(person_obj, ensure_ascii=False, indent=1)

    return PersonResult(
        raw_text=raw_text,
        name=name,
        title=job_title,
        company=job_company,
        location=location,
        linkedin_url=linkedin_url,
        bio=bio,
        extra=extra,
    )


def load_juicebox_csv(
    path: Path, agent_name: str = "juicebox"
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
            for person_obj in results_json:
                persons.append(_parse_juicebox_person(person_obj))

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
