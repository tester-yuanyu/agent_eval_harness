"""一次运行的依赖与状态；Inspect 依赖延迟到实际执行时加载。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from ..agent_adapter import AgentAdapter
from .domains.presentation import DomainPresentation


@dataclass(frozen=True, kw_only=True)
class RunContext:
    config: dict
    output: Path
    repeats: int
    concurrency: int
    offline: bool
    identity: dict
    identity_hash: str
    adapter: AgentAdapter | None
    reference_observation: Callable[[dict], dict]
    execution_task: Callable[[dict], dict]
    score_task: Callable[[dict, dict], dict]
    source: dict
    presentation: DomainPresentation


@dataclass(frozen=True, kw_only=True)
class InspectRuntime:
    Task: Any
    inspect_eval: Callable[..., Any]
    Sample: Any
    Score: Any
    scorer: Callable[..., Any]
    solver: Callable[..., Any]
    transcript: Callable[..., Any]
    anyio: ModuleType

    @classmethod
    def load(cls) -> InspectRuntime:
        import anyio
        from inspect_ai import Task
        from inspect_ai import eval_set as inspect_eval
        from inspect_ai.dataset import Sample
        from inspect_ai.log import transcript
        from inspect_ai.scorer import Score, scorer
        from inspect_ai.solver import solver

        return cls(
            Task=Task,
            inspect_eval=inspect_eval,
            Sample=Sample,
            Score=Score,
            scorer=scorer,
            solver=solver,
            transcript=transcript,
            anyio=anyio,
        )
