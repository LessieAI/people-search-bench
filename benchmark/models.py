from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class QueryCategory(str, Enum):
    FIND_CUSTOMERS = "find_customers"
    FIND_EXPERTS = "find_experts"
    FIND_KOL = "find_kol"
    FIND_CANDIDATES = "find_candidates"
    FIND_PARTNERS = "find_partners"


class QueryDifficulty(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class Query(BaseModel):
    id: str = Field(alias="query_id")
    text: str = Field(alias="prompt")
    category: QueryCategory | str
    difficulty: QueryDifficulty = QueryDifficulty.MEDIUM
    language: str = "en"
    source_id: str | None = None
    expected_criteria: dict[str, Any] = Field(default_factory=dict)
    ground_truth_names: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class PersonResult(BaseModel):
    """One person returned by a platform for a given query."""

    raw_text: str

    name: str | None = None
    title: str | None = None
    company: str | None = None
    location: str | None = None
    linkedin_url: str | None = None
    email: str | None = None
    bio: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    def to_text(self) -> str:
        header_lines: list[str] = []
        if self.name:
            header_lines.append(f"Name: {self.name}")
        if self.title:
            header_lines.append(f"Title: {self.title}")
        if self.company:
            header_lines.append(f"Company: {self.company}")
        if self.location:
            header_lines.append(f"Location: {self.location}")
        if self.linkedin_url:
            header_lines.append(f"LinkedIn: {self.linkedin_url}")
        if self.email:
            header_lines.append(f"Email: {self.email}")
        if self.bio:
            header_lines.append(f"Bio: {self.bio}")
        for k, v in self.extra.items():
            header_lines.append(f"{k}: {v}")

        header = "\n".join(header_lines)

        if header:
            return f"{header}\n\n--- Raw Data ---\n{self.raw_text}"
        return self.raw_text


class AgentSearchResult(BaseModel):
    """All person results from one agent for one query."""

    agent_name: str
    query_id: str
    results: list[PersonResult]

    def person_texts(self) -> list[str]:
        return [p.to_text() for p in self.results]

    def all_results_text(self) -> str:
        if not self.results:
            return "(no results)"
        blocks = []
        for i, person in enumerate(self.results, 1):
            blocks.append(f"=== Result #{i} ===\n{person.to_text()}")
        return "\n\n".join(blocks)


class EvalScore(BaseModel):
    metric_name: str
    score: float  # 0.0 - 1.0, or -1.0 for "skipped"
    details: dict[str, Any] = Field(default_factory=dict)


class QueryEvalResult(BaseModel):
    query_id: str
    agent_name: str
    scores: list[EvalScore]
    weighted_score: float = 0.0


class BenchmarkReport(BaseModel):
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    total_queries: int = 0
    agents: list[str] = Field(default_factory=list)
    results: list[QueryEvalResult] = Field(default_factory=list)
    summary: dict[str, dict[str, float]] = Field(default_factory=dict)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.model_dump(), indent=2, ensure_ascii=False))

    @classmethod
    def load(cls, path: Path) -> BenchmarkReport:
        return cls.model_validate_json(path.read_text())
