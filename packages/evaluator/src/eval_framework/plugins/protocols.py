"""Behavioral protocols implemented by trusted evaluator plugins."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

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
