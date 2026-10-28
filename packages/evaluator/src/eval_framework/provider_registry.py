"""Explicit registry for evaluator Provider factories."""

from __future__ import annotations

from typing import Any

from .errors import EvaluationPreflightError
from .provider import EvaluationProvider, ProviderFactory
from .schemas import DatasetBundle


class ProviderRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, ProviderFactory] = {}

    def register(self, provider_id: str, factory: ProviderFactory) -> None:
        if not provider_id:
            raise ValueError("provider_id must be non-empty")
        if provider_id in self._factories:
            raise ValueError(f"provider {provider_id!r} is already registered")
        self._factories[provider_id] = factory

    def create(
        self,
        provider_id: str,
        *,
        dataset: DatasetBundle,
        model_client_factory: Any = None,
        **kwargs: Any,
    ) -> EvaluationProvider:
        try:
            factory = self._factories[provider_id]
        except KeyError as exc:
            raise EvaluationPreflightError(
                "UNKNOWN_PROVIDER",
                f"unknown evaluation Provider {provider_id!r}",
                evidence_path=dataset.manifest_path,
            ) from exc
        if dataset.provider_id not in {"unknown", provider_id}:
            raise EvaluationPreflightError(
                "CAPABILITY_CONTRACT_MISMATCH",
                f"dataset provider {dataset.provider_id!r} != {provider_id!r}",
                evidence_path=dataset.manifest_path,
            )
        provider = factory.create(dataset, model_client_factory, **kwargs)
        if provider.provider_id != provider_id:
            raise EvaluationPreflightError(
                "CAPABILITY_CONTRACT_MISMATCH",
                f"registered provider {provider_id!r} created "
                f"{provider.provider_id!r}",
                evidence_path=dataset.manifest_path,
            )
        return provider
