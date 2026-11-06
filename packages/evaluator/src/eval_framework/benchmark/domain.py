"""Trusted domain projections; runtime adapters never receive private truth."""

from typing import Any, Protocol


class BenchmarkDomain(Protocol):
    def identity(self) -> dict[str, Any]: ...

    def execution_task(self, task: dict[str, Any]) -> dict[str, Any]: ...

    def score_task(
        self, task: dict[str, Any], observation: dict[str, Any]
    ) -> dict[str, Any]: ...
