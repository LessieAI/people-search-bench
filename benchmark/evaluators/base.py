from __future__ import annotations

from abc import ABC, abstractmethod

from benchmark.models import AgentSearchResult, EvalScore, Query


class BaseEvaluator(ABC):
    name: str = "base"

    @abstractmethod
    async def evaluate(
        self, query: Query, search_result: AgentSearchResult
    ) -> EvalScore: ...
