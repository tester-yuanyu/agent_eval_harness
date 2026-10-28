"""Evaluator-owned tool bindings for a single mini_agent trial."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory

from minimal_agent import build_default_intent_registry
from minimal_agent.capabilities import export_capability_bundle
from minimal_agent.contracts.tools import ToolResult
from minimal_agent.runtime import ToolRegistry
from minimal_agent.testing import (
    QueryUserEvaluationHandler,
    query_user_evaluation_definition,
)

from ...capabilities import CapabilityRegistry
from ...errors import EvaluationPreflightError
from ...provider import ensure_capability_compatibility
from .capability_adapter import load_mini_agent_capability_bundle

QueryUserHandlerFactory = Callable[[], QueryUserEvaluationHandler]


class MiniAgentRuntimeBindingFactory:
    """Build and verify one isolated ToolRegistry for each runtime."""

    def __init__(
        self,
        frozen_capabilities: CapabilityRegistry,
        *,
        query_user_handler_factory: QueryUserHandlerFactory | None = None,
    ) -> None:
        self._frozen = frozen_capabilities
        self._query_user_handler_factory = (
            query_user_handler_factory or _default_query_user_handler_factory
        )

    def __call__(self, allowed_tools: frozenset[str]) -> ToolRegistry:
        unsupported = allowed_tools - {"query_user_info"}
        if unsupported:
            raise EvaluationPreflightError(
                "NATIVE_TOOL_HANDLER_REQUIRED",
                f"native handlers are required for tools {sorted(unsupported)}",
            )
        registry = ToolRegistry()
        if "query_user_info" in allowed_tools:
            registry.register(
                query_user_evaluation_definition(self._query_user_handler_factory())
            )
        self.verify_registry(registry)
        return registry

    def verify_registry(self, registry: ToolRegistry) -> None:
        with TemporaryDirectory(prefix="agent-evaluator-runtime-bundle-") as temp:
            root = Path(temp) / "bundle"
            export_capability_bundle(
                root,
                build_default_intent_registry(),
                registry,
            )
            current = CapabilityRegistry(load_mini_agent_capability_bundle(root))
            current_ids = {
                document.snapshot_id for document in current.bundle.documents
            }
            frozen_projection = CapabilityRegistry(
                self._frozen.bundle.model_copy(
                    update={
                        "documents": tuple(
                            document
                            for document in self._frozen.bundle.documents
                            if document.snapshot_type not in {"tool", "tool_capability"}
                            or document.snapshot_id in current_ids
                        )
                    }
                )
            )
            ensure_capability_compatibility(
                frozen_projection,
                current,
                expected_provider_id="mini_agent",
            )


def _default_query_user_handler_factory() -> QueryUserEvaluationHandler:
    def handler(**_: object) -> ToolResult:
        return ToolResult(
            success=True,
            code="EMPTY",
            message="no evaluator fixture matched the query",
            data={},
        )

    return handler
