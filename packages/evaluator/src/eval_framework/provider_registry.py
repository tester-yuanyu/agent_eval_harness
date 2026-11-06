"""Explicit registry for evaluator Provider factories."""

from __future__ import annotations

from typing import Any

from .agent_adapter import AgentAdapter, AgentAdapterFactory
from .errors import EvaluationPreflightError
from .provider import EvaluationProvider, ProviderFactory
from .schemas import DatasetBundle


class ProviderRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, ProviderFactory | AgentAdapterFactory] = {}

    def register(
        self, provider_id: str, factory: ProviderFactory | AgentAdapterFactory
    ) -> None:
        if not provider_id:
            raise ValueError("provider_id must be non-empty")
        if provider_id in self._factories:
            raise ValueError(f"provider {provider_id!r} is already registered")
        self._factories[provider_id] = factory

    def create_adapter(
        self, provider_id: str, *, config: dict[str, Any]
    ) -> AgentAdapter:
        """Resolve the optional benchmark interface without changing Suite factories."""
        factory = self._factories.get(provider_id)
        if factory is None:
            raise EvaluationPreflightError(
                "UNKNOWN_PROVIDER", f"unknown evaluation Provider {provider_id!r}"
            )
        create = getattr(factory, "create_adapter", None)
        if not callable(create):
            raise EvaluationPreflightError(
                "UNSUPPORTED_PROVIDER_INTERFACE",
                f"Provider {provider_id!r} does not expose a benchmark adapter",
            )
        adapter = create(config=config)
        if adapter.provider_id != provider_id:
            raise EvaluationPreflightError(
                "CAPABILITY_CONTRACT_MISMATCH",
                f"registered provider {provider_id!r} created {adapter.provider_id!r}",
            )
        return adapter

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
        create = getattr(factory, "create", None)
        if not callable(create):
            raise EvaluationPreflightError(
                "UNSUPPORTED_PROVIDER_INTERFACE",
                f"Provider {provider_id!r} does not expose the Suite interface",
                evidence_path=dataset.manifest_path,
            )
        provider = create(dataset, model_client_factory, **kwargs)
        if provider.provider_id != provider_id:
            raise EvaluationPreflightError(
                "CAPABILITY_CONTRACT_MISMATCH",
                f"registered provider {provider_id!r} created "
                f"{provider.provider_id!r}",
                evidence_path=dataset.manifest_path,
            )
        return provider
