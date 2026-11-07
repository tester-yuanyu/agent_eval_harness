"""Public, evaluator-owned read fixtures; no Oracle, credentials or business I/O."""

from __future__ import annotations

from dataclasses import replace

from minimal_agent.contracts.intent_parameters import QueryGiftInfoArguments
from minimal_agent.contracts.tools import ToolResult
from minimal_agent.runtime import ToolRegistry
from minimal_agent.runtime.tool_registry import ToolDefinition
from minimal_agent.testing.query_user_tool import QUERY_USER_EVALUATION_CONTRACT

GIFT_READ_CONTRACT = replace(
    QUERY_USER_EVALUATION_CONTRACT,
    name="query_gift_info",
    version="query-gift-evaluation-adapter-v1",
    description="Query gifts from an isolated evaluator fixture.",
    arguments_model=QueryGiftInfoArguments,
    parameter_rules={
        "condition_cardinality": "EXACTLY_ONE",
        "accepted_fields": ["gift_id", "gift_ids", "gift_name", "limit"],
    },
    implementation_profile="test_fixture",
)


def read_fixture_registry(
    environment: dict, allowed_tools: frozenset[str]
) -> ToolRegistry:
    contracts = {
        "query_user_info": QUERY_USER_EVALUATION_CONTRACT,
        "query_gift_info": GIFT_READ_CONTRACT,
    }
    if allowed_tools - contracts.keys():
        raise ValueError("unsupported read fixture tool")
    fault = environment.get("fault") or {}
    if fault and (
        set(fault) != {"tool", "mode"}
        or fault["tool"] not in allowed_tools
        or fault["mode"]
        not in {"timeout", "execution_failure", "business_failure", "rate_limit"}
    ):
        raise ValueError("unsupported read fixture fault")

    def handler_for(name):
        def handler(**query):
            mode = fault.get("mode") if fault.get("tool") == name else None
            if mode == "timeout":
                raise TimeoutError("fixture tool timeout")
            if mode == "execution_failure":
                raise RuntimeError("fixture tool execution failure")
            if mode in {"business_failure", "rate_limit"}:
                return ToolResult(
                    success=False,
                    code="BUSINESS_FAILURE"
                    if mode == "business_failure"
                    else "RATE_LIMITED",
                    message="fixture service failure",
                    data={},
                )
            if name == "query_user_info":
                key = "users"
                rows = [
                    row
                    for row in environment.get(key, [])
                    if all(row.get(k) == v for k, v in query.items() if v is not None)
                ]
            else:
                key = "gifts"
                rows = [
                    row
                    for row in environment.get(key, [])
                    if (
                        (
                            query.get("gift_id") is not None
                            and row["gift_id"] == query["gift_id"]
                        )
                        or (
                            query.get("gift_ids") is not None
                            and row["gift_id"] in query["gift_ids"]
                        )
                        or (
                            query.get("gift_name") is not None
                            and row["gift_name"] == query["gift_name"]
                        )
                    )
                ]
                if query.get("limit") is not None:
                    rows = rows[: query["limit"]]
            return ToolResult(
                success=True,
                code="OK" if rows else "EMPTY",
                message="query complete",
                data={key: rows},
            )

        return handler

    registry = ToolRegistry()
    for name in sorted(allowed_tools):
        registry.register(
            ToolDefinition(contract=contracts[name], handler=handler_for(name))
        )
    return registry
