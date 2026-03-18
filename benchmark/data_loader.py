"""Load search results from Excel / CSV files into AgentSearchResult objects.

Supports two CSV formats:
1. Standard format: columns (query_id, agent_name, person_data) — one row per person
2. Raw results format: columns (query_id, prompt, results_json) — one row per query,
   results_json is a JSON array of person objects. Agent name is inferred from filename.
"""

from __future__ import annotations

import csv
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

from benchmark.models import AgentSearchResult, PersonResult

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = {"query_id", "agent_name", "person_data"}
RAW_RESULTS_COLUMNS = {"query_id", "prompt", "results_json"}
KNOWN_COLUMNS = {
    "query_id",
    "query_text",
    "agent_name",
    "person_data",
    "name",
    "title",
    "company",
    "location",
    "linkedin_url",
    "email",
    "bio",
}


def _try_parse_json_fields(raw_text: str) -> dict:
    try:
        data = json.loads(raw_text)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, TypeError):
        pass
    return {}


def _row_to_person(row: pd.Series) -> PersonResult:
    raw_text = str(row.get("person_data", ""))

    name = _str_or_none(row.get("name"))
    title = _str_or_none(row.get("title"))
    company = _str_or_none(row.get("company"))
    location = _str_or_none(row.get("location"))
    linkedin_url = _str_or_none(row.get("linkedin_url"))
    email = _str_or_none(row.get("email"))
    bio = _str_or_none(row.get("bio"))

    if not name:
        parsed = _try_parse_json_fields(raw_text)
        name = name or parsed.get("name")
        title = title or parsed.get("title")
        company = company or parsed.get("company")
        location = location or parsed.get("location")
        linkedin_url = linkedin_url or parsed.get("linkedin_url")
        email = email or parsed.get("email")
        bio = bio or parsed.get("bio")

    extra_cols = set(row.index) - KNOWN_COLUMNS
    extra = {}
    for col in extra_cols:
        val = row.get(col)
        if pd.notna(val) and str(val).strip():
            extra[col] = str(val)

    return PersonResult(
        raw_text=raw_text,
        name=name,
        title=title,
        company=company,
        location=location,
        linkedin_url=linkedin_url,
        email=email,
        bio=bio,
        extra=extra,
    )


def _str_or_none(val) -> str | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip()
    return s if s else None


def _extract_person_from_raw(person_data: dict) -> PersonResult:
    """Convert a raw results JSON person object into a PersonResult."""
    name = person_data.get("name") or person_data.get("person_name") or ""
    headline = person_data.get("headline") or ""
    match_reason = person_data.get("match_reason") or ""

    # Extract from person_detail if available
    detail = person_data.get("person_detail", {})
    if isinstance(detail, str):
        try:
            detail = json.loads(detail)
        except (json.JSONDecodeError, TypeError):
            detail = {}

    # Extract profile links
    linkedin_url = None
    profile_links = person_data.get("profile_links") or []
    if isinstance(profile_links, str):
        try:
            profile_links = json.loads(profile_links)
        except (json.JSONDecodeError, TypeError):
            profile_links = []
    for link in profile_links:
        if isinstance(link, dict) and link.get("value") == "linkedin":
            linkedin_url = link.get("url")
            break

    # Build raw text for the evaluator
    raw_text = json.dumps(person_data, ensure_ascii=False, default=str)

    bio = headline or match_reason or ""

    return PersonResult(
        raw_text=raw_text,
        name=name if name else None,
        bio=bio if bio else None,
        linkedin_url=linkedin_url,
    )


def _infer_agent_name(path: Path) -> str:
    """Infer agent/platform name from filename like 'recruiting_lessie.csv'."""
    stem = path.stem.lower()
    for platform in ["lessie", "exa", "juicebox", "claude_code"]:
        if platform in stem:
            return platform
    # Fallback: use parent directory name
    return path.parent.name


def load_raw_results_file(path: Path) -> list[AgentSearchResult]:
    """Load raw results CSV (query_id, prompt, results_json) format."""
    csv.field_size_limit(sys.maxsize)

    agent_name = _infer_agent_name(path)
    results: list[AgentSearchResult] = []

    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            query_id = row.get("query_id", "").strip()
            results_json = row.get("results_json", "[]")

            try:
                persons_data = json.loads(results_json)
            except json.JSONDecodeError:
                logger.warning("Invalid JSON in results_json for query %s", query_id)
                persons_data = []

            if not isinstance(persons_data, list):
                persons_data = [persons_data]

            persons = [_extract_person_from_raw(p) for p in persons_data]

            results.append(
                AgentSearchResult(
                    agent_name=agent_name,
                    query_id=query_id,
                    results=persons,
                )
            )

    logger.info(
        "Loaded %d queries from %s (agent: %s, raw format)",
        len(results),
        path.name,
        agent_name,
    )
    return results


def load_results_file(path: Path) -> list[AgentSearchResult]:
    """Load results from CSV/Excel. Auto-detects standard vs raw format."""
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xls"):
        df = pd.read_excel(path, dtype=str)
    elif suffix == ".csv":
        # Peek at columns to detect format
        with open(path, encoding="utf-8-sig") as f:
            header = f.readline().strip().lower()
        cols = {c.strip() for c in header.split(",")}

        if RAW_RESULTS_COLUMNS.issubset(cols):
            logger.info("Detected raw results format in %s", path.name)
            return load_raw_results_file(path)

        df = pd.read_csv(path, dtype=str)
    else:
        raise ValueError(f"Unsupported file format: {suffix}. Use .xlsx, .xls, or .csv")

    df.columns = df.columns.str.strip().str.lower()

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(
            f"Missing required columns in {path.name}: {missing}. "
            f"Required: {REQUIRED_COLUMNS}. "
            f"If this is a raw results file (query_id, prompt, results_json), "
            f"it should be auto-detected."
        )

    grouped: dict[tuple[str, str], list[PersonResult]] = defaultdict(list)
    for _, row in df.iterrows():
        query_id = str(row["query_id"]).strip()
        agent_name = str(row["agent_name"]).strip()
        person = _row_to_person(row)
        grouped[(query_id, agent_name)].append(person)

    results: list[AgentSearchResult] = []
    for (query_id, agent_name), persons in grouped.items():
        results.append(
            AgentSearchResult(
                agent_name=agent_name,
                query_id=query_id,
                results=persons,
            )
        )

    logger.info(
        "Loaded %d rows from %s -> %d (query, agent) groups",
        len(df),
        path.name,
        len(results),
    )
    return results


def load_results_dir(directory: Path) -> list[AgentSearchResult]:
    all_results: list[AgentSearchResult] = []
    for f in sorted(directory.iterdir()):
        if f.suffix.lower() in (".xlsx", ".xls", ".csv"):
            all_results.extend(load_results_file(f))
    return all_results
