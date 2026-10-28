"""Conservative candidate translation; never invent missing execution semantics."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from jsonschema.validators import validator_for

from ..observation_assertions import ObservationCheckConfig, validate_schema_references
from ..providers.external import RuntimeBinding, binding_supports
from ..schemas import EvalCase
from .delivery import resolve_reference
from .models import CandidateCase, CandidateManifest, SourceReference

STATIC_KINDS = {"schema_contract", "contract_check"}
_RETURNED_ROOTS = {
    "result",
    "exception",
    "schema_validation",
    "declared_value",
    "serialized_RunResult",
}


class NotExecutable(ValueError):
    def __init__(self, code: str, owner: str, message: str):
        super().__init__(message)
        self.code, self.owner = code, owner


def _subject_pointer(subject: str) -> str:
    if subject.startswith("/"):
        pointer = subject
        root = subject.split("/")[1]
    else:
        normalized = re.sub(r"\[(0|[1-9][0-9]*)\]", r".\1", subject)
        if not re.fullmatch(
            r"[A-Za-z_][A-Za-z_0-9]*(?:\.(?:[A-Za-z_][A-Za-z_0-9]*|0|[1-9][0-9]*))*",
            normalized,
        ):
            raise NotExecutable(
                "ORACLE_SUBJECT_UNSUPPORTED",
                "evaluator",
                f"ambiguous subject: {subject}",
            )
        root = normalized.split(".")[0]
        pointer = "/" + normalized.replace(".", "/")
    if root not in _RETURNED_ROOTS:
        raise NotExecutable(
            "INDEPENDENT_EVIDENCE_REQUIRED",
            "evaluator",
            f"subject requires an independent observer: {subject}",
        )
    return pointer


def translate(
    row: CandidateCase,
    root: Path,
    manifest: CandidateManifest,
    binding: RuntimeBinding | None,
) -> tuple[EvalCase | None, dict[str, Any]]:
    case_id = "case_" + hashlib.sha256(row.case_id.encode()).hexdigest()[:24]
    static = row.kind in STATIC_KINDS
    ledger: dict[str, Any] = {
        "source_case_id": row.case_id,
        "case_id": case_id,
        "target_id": row.target_id,
        "kind": row.kind,
        "layer": row.layer,
        "source_status": {
            "support_status": row.support_status,
            "execution_readiness": row.execution_readiness,
            "runtime_execution": row.runtime_execution,
            "approval": row.approval,
            "source_basis": row.source_basis,
        },
        "blocker_ids": row.blocker_ids,
        "runner_requirements": row.runner_requirements,
    }
    try:
        if row.kind == "blocked_obligation":
            raise NotExecutable(
                "MISSING_EXECUTABLE_CONTRACT",
                "agent_contract",
                "source record is a blocked obligation",
            )
        if row.layer not in {
            "contracts",
            "modules",
            "tools",
            "critical_links",
            "end_to_end",
        }:
            raise NotExecutable(
                "LAYER_UNSUPPORTED", "evaluator", f"unsupported layer: {row.layer}"
            )
        if not static and row.support_status != "supported":
            raise NotExecutable(
                "SUPPORT_UNKNOWN"
                if row.support_status == "unknown"
                else "SUPPORT_UNSUPPORTED",
                "agent_contract",
                f"source support is {row.support_status}",
            )
        if row.blocker_ids:
            raise NotExecutable(
                "UPSTREAM_BLOCKERS",
                "agent_contract",
                "source has unresolved blocker IDs",
            )
        if not static and row.execution_readiness != "needs_runner":
            raise NotExecutable(
                "SOURCE_EXECUTION_BLOCKED",
                "dataset_builder",
                "behavior readiness must be needs_runner, "
                f"got {row.execution_readiness}",
            )
        if static and row.execution_readiness != "static_only":
            raise NotExecutable(
                "SOURCE_EXECUTION_BLOCKED",
                "dataset_builder",
                "static record is not ready for static execution",
            )
        if not row.oracle.checks:
            raise NotExecutable(
                "ORACLE_REQUIRED",
                "dataset_builder",
                "candidate has no executable checks",
            )
        checks = [
            {
                "path": _subject_pointer(check.subject),
                "operator": check.operator,
                "expected": check.expected,
            }
            for check in row.oracle.checks
        ]
        try:
            config = ObservationCheckConfig(checks=checks)
        except ValueError as exc:
            raise NotExecutable(
                "ORACLE_OPERATOR_UNSUPPORTED", "evaluator", str(exc)
            ) from exc
        active_binding = (
            RuntimeBinding(version="1.0", agent_id=row.agent_id, adapter="static")
            if static
            else binding
        )
        if active_binding is None:
            raise NotExecutable(
                "RUNTIME_BINDING_REQUIRED",
                "evaluator",
                "provide an explicit runtime binding or a supported --agent-root",
            )
        operation_input = dict(row.input)
        if static:
            operation = operation_input.get("operation")
            if row.kind == "schema_contract" and operation == "validate_schema":
                ref = SourceReference.model_validate(operation_input.get("schema_ref"))
                schema = resolve_reference(root, manifest, ref)
                try:
                    validate_schema_references(schema)
                    validator_for(schema).check_schema(schema)
                except (ValueError, TypeError) as exc:
                    raise NotExecutable(
                        "SCHEMA_UNSUPPORTED", "dataset_builder", str(exc)
                    ) from exc
                operation_input = {
                    "operation": operation,
                    "schema": schema,
                    "instance": operation_input["instance"],
                }
            elif row.kind == "contract_check" and operation == "inspect_snapshot":
                ref = SourceReference.model_validate(operation_input.get("source_ref"))
                if ref.pointer is None:
                    raise NotExecutable(
                        "SOURCE_POINTER_REQUIRED",
                        "dataset_builder",
                        "snapshot inspection requires an explicit pointer",
                    )
                operation_input = {
                    "operation": operation,
                    "declared_value": resolve_reference(root, manifest, ref),
                }
            else:
                raise NotExecutable(
                    "STATIC_OPERATION_UNSUPPORTED",
                    "evaluator",
                    f"unsupported static operation: {operation}",
                )
        payload: dict[str, Any] = {
            "input": operation_input,
            "preconditions": row.preconditions,
        }
        source_digests = {
            ref.path.removeprefix("sources/"): ref.sha256
            for ref in row.source_refs
            if ref.path.startswith("sources/")
        }
        sources = [
            {"path": path, "sha256": digest} for path, digest in source_digests.items()
        ]
        if sources:
            payload["source_files"] = sources
        if (
            active_binding.adapter == "nanobot_local"
            and "nanobot/runtime_context.py" not in source_digests
        ):
            dependency = "nanobot/runtime_context.py"
            from .delivery import sha256

            # Supplemental runtime bytes come only from the trusted Agent root.
            # The source-declared sdk/types.py digest above is never replaced.
            payload.setdefault("source_files", []).append(
                {
                    "path": dependency,
                    "sha256": sha256(active_binding.agent_root / dependency),
                }
            )
        supported, reason = binding_supports(active_binding, payload)
        if not supported:
            raise NotExecutable(
                "OPERATION_UNSUPPORTED",
                "evaluator",
                reason or "adapter cannot execute operation",
            )
        scope = (
            "end_to_end"
            if row.layer == "end_to_end"
            else ("link" if row.layer in {"tools", "critical_links"} else "module")
        )
        case = EvalCase.model_validate(
            {
                "schema_version": "1.0",
                "case_id": case_id,
                "task_id": row.target_id,
                "scenario_type": {
                    "boundary": "valid_boundary",
                    "error": "invalid_parameter",
                    "schema_invalid": "invalid_parameter",
                }.get(row.category, "normal"),
                "test_scope": scope,
                "target": row.target_id,
                "execution": {
                    "user_input": "Execute declared candidate operation",
                    "adapter_input": payload,
                    "tool_profile": "candidate_isolated",
                    "allowed_tools": [],
                    "timeout_seconds": active_binding.timeout_seconds,
                },
                "oracle": {
                    "evaluation": {
                        "checks": [
                            {
                                "name": "observations_match",
                                "weight": 1.0,
                                "critical": False,
                                "config": config.model_dump(mode="json"),
                            }
                        ]
                    }
                },
                "labels": [
                    f"source_kind:{row.kind}",
                    f"source_layer:{row.layer}",
                    f"source_category:{row.category}",
                    f"source_support:{row.support_status}",
                ],
            }
        )
        ledger.update(
            disposition="static" if static else "behavior",
            reason_code=None,
            owner=None,
            message=None,
        )
        return case, ledger
    except NotExecutable as exc:
        ledger.update(
            disposition="blocked",
            reason_code=exc.code,
            owner=exc.owner,
            message=str(exc),
        )
        return None, ledger
