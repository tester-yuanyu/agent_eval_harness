"""Behavioral protocols implemented by trusted evaluator plugins."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol, runtime_checkable

from ..contracts.models import ResolvedSource
from ..schemas import DatasetBundle, DatasetFilters, ValidationReport


class DatasetLoaderPlugin(Protocol):
    def load(
        self,
        sources: Sequence[ResolvedSource],
        *,
        filters: DatasetFilters | None,
        config: Mapping[str, Any],
    ) -> DatasetBundle: ...


class DatasetPreflightPlugin(Protocol):
    """Optional Provider-owned semantic validation performed before runtime."""

    def validate_dataset(
        self,
        dataset: DatasetBundle,
        **config: Any,
    ) -> ValidationReport: ...


@runtime_checkable
class EnvironmentPlugin(Protocol):
    """One isolated world per task; state contains no scoring expectations."""

    def reset(self, initial_state: dict[str, Any]) -> None: ...

    def step(self, action: dict[str, Any]) -> Any: ...

    def snapshot(self) -> dict[str, Any]: ...

    def final_state(self) -> dict[str, Any]: ...

    def teardown(self) -> None: ...


@runtime_checkable
class ToolRouterPlugin(Protocol):
    def parse(self, model_output: dict[str, Any]) -> dict[str, Any]: ...

    def validate_args(self, call: dict[str, Any]) -> list[str]: ...

    def dispatch(
        self, call: dict[str, Any], env: EnvironmentPlugin
    ) -> Any: ...


@runtime_checkable
class UserSimulatorPlugin(Protocol):
    def next_message(
        self, history: list[dict[str, Any]]
    ) -> dict[str, Any] | None: ...

    def should_terminate(self, history: list[dict[str, Any]]) -> bool: ...


@runtime_checkable
class ScorerPlugin(Protocol):
    """Private scoring boundary; final_state may include trusted evidence metadata.

    File-tools scorers use a complete observation envelope, not only a file map,
    so execution errors and missing measurements remain distinguishable.
    """

    def score(
        self,
        trace: list[dict[str, Any]],
        final_state: dict[str, Any],
        task: dict[str, Any],
    ) -> dict[str, Any]: ...
