"""generate-full 制品的 P0 绑定协议；原始 case/Oracle 保持独立。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from .readiness import Hash, RunnerIdentity, StrictRecord, digest_bytes, local_path


def assertion_identity() -> str:
    return digest_bytes(
        Path(__file__).read_bytes()
        + Path(__file__).with_name("operation_readiness.py").read_bytes()
        + Path(__file__).with_name("agent_readiness.py").read_bytes()
        + Path(__file__).with_name("agent_reference_inputs.py").read_bytes()
    )


class FullCase(StrictRecord):
    case_id: str
    source_path: str
    payload: dict[str, Any]

    @model_validator(mode="after")
    def source(self):
        local_path(self.source_path)
        if self.case_id != self.payload.get("case_id"):
            raise ValueError("case identity mismatch")
        return self


class FullRequest(StrictRecord):
    schema_version: Literal[
        "builder-full-readiness-v1",
        "builder-full-readiness-v2",
        "builder-full-readiness-v3",
    ] = "builder-full-readiness-v1"
    source_manifest_sha256: Hash
    bundle_sha256: Hash
    source_files: dict[str, Hash]
    definition_counts: dict[str, int]
    capability_documents: list[dict[str, Any]] = Field(default_factory=list)
    target_schemas: dict[str, dict[str, Any]] = Field(default_factory=dict)
    tool_schema: dict[str, Any]
    cases: list[FullCase] = Field(min_length=1)

    @model_validator(mode="after")
    def unique(self):
        ids = [c.case_id for c in self.cases]
        if len(ids) != len(set(ids)) or self.definition_counts.get(
            "behavior_case"
        ) != len(ids):
            raise ValueError("fixed behavior case set/count mismatch")
        for path in self.source_files:
            local_path(path)
        return self

    def sha256(self) -> str:
        payload = self.model_dump(mode="json")
        if self.schema_version != "builder-full-readiness-v3":
            payload.pop("capability_documents", None)
        if self.schema_version == "builder-full-readiness-v1":
            payload.pop("target_schemas", None)
        return digest_bytes(
            json.dumps(
                payload,
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        )


class ToolExecution(StrictRecord):
    arguments: dict[str, Any]
    users: list[dict[str, Any]]


def execution_for(case: FullCase) -> ToolExecution | None:
    """仅解释明确的执行输入，绝不从 expected 或 result_branch 构造输出。"""
    p = case.payload
    if (
        p.get("dataset_format") != "capability_contract_case"
        or p.get("target_id") != "tool.query_user_info"
    ):
        return None
    inp, pre = p.get("input", {}), p.get("preconditions", [])
    if (
        not isinstance(inp, dict)
        or not isinstance(pre, list)
        or not isinstance(inp.get("arguments"), dict)
        or not all(isinstance(item, dict) for item in pre)
        or set(inp) != {"operation", "tool_name", "arguments"}
        or inp["operation"] != "invoke_tool"
        or inp["tool_name"] != "query_user_info"
        or len(pre) != 1
        or pre[0].get("kind") != "fixture_setup"
        or pre[0].get("fresh_instance") is not True
        or set(pre[0]) - {"kind", "records", "result_branch", "fresh_instance"}
    ):
        return None
    records = pre[0].get("records")
    if not isinstance(records, dict):
        return None
    if set(records) == {"user"} and isinstance(records["user"], dict):
        users = [records["user"]]
    elif records == {"users": [], "gifts": [], "pools": [], "resources": []}:
        users = []
    else:
        return None
    oracle = p.get("oracle")
    if not isinstance(oracle, dict):
        return None
    checks = oracle.get("checks", [])
    if (
        not isinstance(checks, list)
        or not checks
        or any(
            not isinstance(check, dict)
            or (check.get("op"), check.get("actual"))
            not in {
                ("equals", "tool_result.code"),
                ("schema_valid", "tool_result.data"),
            }
            or set(check) != {"op", "actual", "expected"}
            for check in checks
        )
    ):
        return None
    return ToolExecution(arguments=inp["arguments"], users=users)


class ToolEvidence(StrictRecord):
    case_id: str
    status: str
    evidence_complete: bool
    before_state: dict[str, Any]
    after_state: dict[str, Any]
    tool_calls: list[dict[str, Any]]
    tool_result: dict[str, Any]
    errors: list[str]
    execution: dict[str, Any] = Field(default_factory=dict)
    observations: dict[str, Any] = Field(default_factory=dict)


class FullEvidence(StrictRecord):
    schema_version: Literal["builder-full-evidence-v1"] = "builder-full-evidence-v1"
    dataset_sha256: Hash
    runner: RunnerIdentity
    results: list[ToolEvidence]


def reference_checks(case: FullCase, row: ToolEvidence) -> dict[str, bool]:
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError

    execution = execution_for(case)
    if execution is None:
        return {"harness_binding": False}
    checks = {
        "harness_binding": bool(
            row.evidence_complete
            and not row.errors
            and row.before_state == {"users": execution.users}
            and row.tool_calls
            == [{"name": "query_user_info", "arguments": execution.arguments}]
        ),
        "execution_completed": row.status == "completed",
        "fixture_unchanged": row.before_state == row.after_state,
    }
    for i, check in enumerate(case.payload["oracle"]["checks"]):
        if check["op"] == "equals":
            passed = row.tool_result.get("code") == check["expected"]
        else:
            try:
                Draft202012Validator.check_schema(check["expected"])
                passed = "data" in row.tool_result and Draft202012Validator(
                    check["expected"]
                ).is_valid(row.tool_result["data"])
            except (ValueError, TypeError, SchemaError):
                passed = False
        checks[f"oracle_{i}"] = passed
    terminal = case.payload["oracle"].get("declared_terminal_status")
    if terminal is not None:
        checks["declared_terminal_status"] = (
            terminal == "success" and row.tool_result.get("success") is True
        )
    return checks
