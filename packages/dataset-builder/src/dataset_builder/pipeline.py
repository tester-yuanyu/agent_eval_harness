"""Public, suite-neutral authoring pipeline."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import uuid4

from .candidate_parser import parse_candidates
from .capability_bundle import load_validated_bundle
from .capability_profiles import canonical_sha256, load_trusted_profile
from .freezing import freeze
from .generation_client import GenerationClient
from .orchestration import (
    PipelineEngine,
    PolicyBinding,
    StageInput,
    StageLedger,
)
from .plugins import PluginKey
from .prompt_builder import build_prompt
from .resources import resource_root
from .schemas import (
    Approval,
    GenerationRequest,
    RawGeneration,
    ValidationSummary,
)
from .source_pack import build_source_pack, sha256_bytes, sha256_file
from .suite_definition import SuiteDefinition
from .validation import dump_report, validate_draft_file, write_jsonl


def _write_json(value: Any, path: Path) -> None:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _workspace_bound_suite(suite: SuiteDefinition, workspace: Path) -> SuiteDefinition:
    return replace(suite, capability_bundle_path=workspace / "capability_bundle")


def _materialize_request_snapshots(request: GenerationRequest, workspace: Path) -> None:
    if not request.capability_bundle_files:
        return
    bundle_dir = workspace / "capability_bundle"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    for item in request.capability_bundle_files:
        source = Path(item["path"])
        if not source.is_file():
            raise ValueError(f"prepared capability bundle file missing: {source}")
        if sha256_file(source) != item["sha256"]:
            raise ValueError(
                f"prepared capability bundle file hash mismatch: {source}"
            )
        destination = bundle_dir / item["relative_path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.resolve() != destination.resolve():
            shutil.copyfile(source, destination)
    profile_binding = request.profile_binding
    profile = load_trusted_profile(
        profile_binding["profile_id"],
        profile_binding["profile_version"],
        resource_root()
        / "protocol_profiles"
        / "trust_store.json",
    )
    if profile.sha256 != profile_binding["sha256"]:
        raise ValueError("prepared trusted Profile hash mismatch")
    copied = load_validated_bundle(bundle_dir, profile)
    if copied.capability_bundle_sha256 != request.capability_bundle_sha256:
        raise ValueError("materialized capability bundle does not match request")


_PLUGIN_ROLES = (
    "capability_adapter",
    "snapshot_loader",
    "capability_resolver",
    "source_pack_compiler",
    "coverage_planner",
    "case_generator",
    "validation_gate",
    "review_renderer",
    "dataset_freezer",
)


def _plugin_bindings(suite: SuiteDefinition) -> list[dict[str, str]]:
    core = [
        {
            "role": role,
            "protocol": "dataset-builder-core",
            "version": "1.0",
        }
        for role in _PLUGIN_ROLES
        if role != "capability_adapter"
    ]
    registration = suite.capability_adapter_registration
    return [
        {
            "role": "capability_adapter",
            "protocol": registration.key.protocol,
            "version": registration.key.version,
            "implementation_sha256": registration.implementation_sha256,
        },
        *core,
    ]


def _stage_policy_bindings(
    values: list[dict[str, str]],
) -> tuple[PolicyBinding, ...]:
    return tuple(PolicyBinding(**item) for item in values)


def _prepare_generation_impl(
    suite: SuiteDefinition, workspace: Path
) -> GenerationRequest:
    workspace.mkdir(parents=True, exist_ok=True)
    current_bundle = suite.validated_capability_bundle
    capability_ir = suite.capability_ir
    profile = suite.capability_profile
    adapter_registration = suite.capability_adapter_registration
    capability_bundle_files: list[dict[str, str]] = []
    bundle_dir = workspace / "capability_bundle"
    if bundle_dir.exists():
        existing_bundle = load_validated_bundle(bundle_dir, profile)
        if (
            existing_bundle.capability_bundle_sha256
            != current_bundle.capability_bundle_sha256
        ):
            raise FileExistsError("workspace contains a different capability bundle")
    else:
        bundle_dir.mkdir(parents=True)
        for relative_path, source in current_bundle.validated_files:
            destination = bundle_dir / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
    copied_bundle = load_validated_bundle(bundle_dir, profile)
    if (
        current_bundle.capability_bundle_sha256
        != copied_bundle.capability_bundle_sha256
    ):
        raise ValueError("copied capability bundle does not match source")
    for relative_path, path in copied_bundle.validated_files:
        capability_bundle_files.append(
            {
                "path": str(path),
                "relative_path": relative_path,
                "sha256": sha256_file(path),
            }
        )
    source_pack, source_manifest = build_source_pack(suite)
    prompt = build_prompt(suite, source_pack)
    request = GenerationRequest(
        request_id=str(uuid4()),
        suite_id=suite.suite_id,
        prompt_version=suite.prompt_version,
        prompt_sha256=sha256_bytes(prompt.encode()),
        suite_definition_version=suite.config.schema_version,
        suite_config_sha256=sha256_file(suite.suite_dir / "suite.json"),
        prompt=prompt,
        candidate_schema=suite.batch_type.model_json_schema(),
        source_manifest=source_manifest,
        execution_profiles=suite.config.execution_profiles,
        profile_binding={
            "profile_id": profile.profile.profile_id,
            "profile_version": profile.profile.protocol_version,
            "path": str(profile.path),
            "sha256": profile.sha256,
        },
        trusted_schema_bindings=[
            {
                "schema_id": item.schema_id,
                "relative_path": item.relative_path,
                "sha256": item.sha256,
            }
            for item in copied_bundle.schema_bindings
        ],
        adapter_binding={
            "protocol": adapter_registration.key.protocol,
            "version": adapter_registration.key.version,
            "implementation_sha256": adapter_registration.implementation_sha256,
        },
        capability_ir_binding={
            "schema_version": capability_ir.schema_version,
            "sha256": capability_ir.canonical_sha256,
        },
        capability_selection=capability_ir.selection.model_dump(mode="json"),
        capability_source_artifacts=[
            item.model_dump(mode="json") for item in capability_ir.source_artifacts
        ],
        capability_bundle_files=capability_bundle_files,
        agent_snapshot_sha256=copied_bundle.root.snapshot_sha256,
        capability_bundle_sha256=copied_bundle.capability_bundle_sha256,
        coverage_plan_sha256=sha256_file(suite.coverage_plan_path),
        policy_bindings=list(suite.policy_bindings),
        plugin_bindings=_plugin_bindings(suite),
        created_at=datetime.now(UTC),
    )
    (workspace / "prompt.md").write_text(prompt)
    _write_json(capability_ir, workspace / "capability_ir.json")
    _write_json(source_manifest, workspace / "source_manifest.json")
    _write_json(request, workspace / "generation_request.json")
    return request


def prepare_generation(suite: SuiteDefinition, workspace: Path) -> GenerationRequest:
    inputs = [
        StageInput(
            name="suite_config",
            sha256=sha256_file(suite.suite_dir / "suite.json"),
        ),
        StageInput(
            name="coverage_plan",
            sha256=sha256_file(suite.coverage_plan_path),
        ),
    ]
    inputs.extend(
        (
            StageInput(
                name="capability_bundle",
                sha256=suite.validated_capability_bundle.capability_bundle_sha256,
            ),
            StageInput(
                name="capability_ir",
                sha256=suite.capability_ir.canonical_sha256,
            ),
        )
    )
    engine = PipelineEngine(StageLedger(workspace / "stage_ledger.jsonl"))
    output = engine.run_stage(
        "prepare",
        PluginKey(
            "source_pack_compiler", "dataset-builder-core", "1.0"
        ),
        tuple(inputs),
        _stage_policy_bindings(list(suite.policy_bindings)),
        lambda: _prepare_generation_impl(suite, workspace).model_dump(
            mode="json"
        ),
    )
    return GenerationRequest.model_validate(output.value)


def _generate_candidates_impl(
    request: GenerationRequest,
    client: GenerationClient,
    workspace: Path | None = None,
) -> RawGeneration:
    if workspace is None:
        with TemporaryDirectory(prefix="dataset-builder-bundle-") as directory:
            _materialize_request_snapshots(request, Path(directory))
    else:
        workspace.mkdir(parents=True, exist_ok=True)
        _materialize_request_snapshots(request, workspace)
    try:
        raw = client.generate(request)
    except ValueError as exc:
        from .deepeval_generation import SynthesisBlocked, SynthesisRejected

        if workspace is not None and isinstance(exc, SynthesisRejected):
            payload = {
                "request_id": request.request_id,
                "status": "REJECTED",
                "attempt_audit": exc.attempt_audit,
            }
            if isinstance(exc, SynthesisBlocked):
                payload.update(
                    status="CONTRACT_BLOCKED",
                    partial_generation=exc.partial_generation.model_dump(mode="json"),
                )
            _write_json(
                payload,
                workspace / "generation_failure.json",
            )
        raise
    if raw.request_id != request.request_id:
        raise ValueError("generation response request_id mismatch")
    if workspace is not None:
        _write_json(request, workspace / "generation_request.json")
        _write_json(raw, workspace / "raw_response.json")
    return raw


def generate_candidates(
    request: GenerationRequest,
    client: GenerationClient,
    workspace: Path | None = None,
) -> RawGeneration:
    if workspace is None:
        return _generate_candidates_impl(request, client, workspace)
    result: list[RawGeneration] = []

    def operation() -> dict[str, Any]:
        raw = _generate_candidates_impl(request, client, workspace)
        result.append(raw)
        return raw.model_dump(mode="json")

    PipelineEngine(StageLedger(workspace / "stage_ledger.jsonl")).run_stage(
        "generate",
        PluginKey("case_generator", "dataset-builder-core", "1.0"),
        (
            StageInput(
                name="generation_request",
                sha256=canonical_sha256(request.model_dump(mode="json")),
            ),
        ),
        _stage_policy_bindings(request.policy_bindings),
        operation,
    )
    return result[0]


def ingest_response(
    request: GenerationRequest, response_path: Path, workspace: Path
) -> RawGeneration:
    raw_bytes = response_path.read_bytes()
    try:
        response = json.loads(raw_bytes)
    except json.JSONDecodeError:
        response = raw_bytes.decode()
    raw = RawGeneration(
        request_id=request.request_id,
        mode="external",
        model=None,
        prompt_version=request.prompt_version,
        created_at=datetime.now(UTC),
        attempts=1,
        response=response,
    )
    workspace.mkdir(parents=True, exist_ok=True)
    _materialize_request_snapshots(request, workspace)
    _write_json(request, workspace / "generation_request.json")
    _write_json(raw, workspace / "raw_response.json")
    return raw


def _compile_candidates_impl(
    suite: SuiteDefinition,
    raw_generation: RawGeneration,
    workspace: Path | None = None,
):
    if workspace is not None:
        saved_raw = RawGeneration.model_validate_json(
            (workspace / "raw_response.json").read_text()
        )
        if saved_raw != raw_generation:
            raise ValueError("compile input differs from saved raw response")
    batch = parse_candidates(suite, raw_generation)
    compiler_suite = (
        _workspace_bound_suite(suite, workspace) if workspace is not None else suite
    )
    cases = suite.compiler(batch.candidates, compiler_suite)
    if workspace is not None:
        _write_json(batch, workspace / "candidates.json")
        write_jsonl(cases, workspace / "draft.jsonl")
        _write_generation_manifest(suite, raw_generation, workspace)
    return cases


def compile_candidates(
    suite: SuiteDefinition,
    raw_generation: RawGeneration,
    workspace: Path | None = None,
):
    if workspace is None:
        return _compile_candidates_impl(suite, raw_generation, workspace)
    result: list[Any] = []

    def operation() -> list[dict[str, Any]]:
        cases = _compile_candidates_impl(suite, raw_generation, workspace)
        result.extend(cases)
        return [case.model_dump(mode="json") for case in cases]

    request = GenerationRequest.model_validate_json(
        (workspace / "generation_request.json").read_text()
    )
    PipelineEngine(StageLedger(workspace / "stage_ledger.jsonl")).run_stage(
        "compile",
        PluginKey("case_generator", "dataset-builder-core", "1.0"),
        (
            StageInput(
                name="raw_generation",
                sha256=canonical_sha256(raw_generation.model_dump(mode="json")),
            ),
        ),
        _stage_policy_bindings(request.policy_bindings),
        operation,
    )
    return result


def _write_generation_manifest(
    suite: SuiteDefinition, raw: RawGeneration, workspace: Path
) -> None:
    request = GenerationRequest.model_validate_json(
        (workspace / "generation_request.json").read_text()
    )
    manifest = {
        "suite_id": suite.suite_id,
        "dataset_version": suite.dataset_version,
        "state": "DRAFT",
        "generation_mode": raw.mode,
        "model": raw.model,
        "generator_metadata": {
            key: value for key, value in raw.metadata.items() if key != "goldens"
        },
        "raw_response_sha256": sha256_file(workspace / "raw_response.json"),
        "prompt_version": raw.prompt_version,
        "prompt_sha256": request.prompt_sha256,
        "suite_definition_version": request.suite_definition_version,
        "suite_config_sha256": request.suite_config_sha256,
        "source_manifest": request.source_manifest,
        "execution_profiles": {
            name: profile.model_dump(mode="json")
            for name, profile in request.execution_profiles.items()
        },
        "profile_binding": request.profile_binding,
        "trusted_schema_bindings": request.trusted_schema_bindings,
        "adapter_binding": request.adapter_binding,
        "capability_ir_binding": request.capability_ir_binding,
        "capability_selection": request.capability_selection,
        "capability_source_artifacts": request.capability_source_artifacts,
        "capability_bundle_files": [
            {
                "relative_path": item["relative_path"],
                "sha256": item["sha256"],
            }
            for item in request.capability_bundle_files
        ],
        "agent_snapshot_sha256": request.agent_snapshot_sha256,
        "capability_bundle_sha256": request.capability_bundle_sha256,
        "coverage_plan_sha256": request.coverage_plan_sha256,
        "policy_bindings": request.policy_bindings,
        "plugin_bindings": request.plugin_bindings,
        "created_at": raw.created_at.isoformat(),
        "attempts": raw.attempts,
    }
    _write_json(manifest, workspace / "generation_manifest.json")


def _validate_draft_impl(
    suite: SuiteDefinition, draft: Path, workspace: Path | None = None
) -> ValidationSummary:
    report = validate_draft_file(suite, draft)
    if workspace is not None:
        dump_report(report, workspace / "validation_report.json")
        for gate, filename in {
            "coverage": "coverage_report.json",
            "duplicate": "duplicate_report.json",
            "leakage": "leakage_report.json",
        }.items():
            found = next((item for item in report.gates if item.name == gate), None)
            if found is not None:
                _write_json(found, workspace / filename)
        manifest_path = workspace / "generation_manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            manifest.update(
                {
                    "state": report.state,
                    "draft_sha256": report.draft_sha256,
                    "validation_valid": report.valid,
                    "case_count": report.case_count,
                }
            )
            _write_json(manifest, manifest_path)
    return report


def validate_draft(
    suite: SuiteDefinition, draft: Path, workspace: Path | None = None
) -> ValidationSummary:
    if workspace is None:
        return _validate_draft_impl(suite, draft, workspace)
    result: list[ValidationSummary] = []

    def operation() -> dict[str, Any]:
        report = _validate_draft_impl(suite, draft, workspace)
        result.append(report)
        return report.model_dump(mode="json")

    request_path = workspace / "generation_request.json"
    policy_bindings: tuple[PolicyBinding, ...] = ()
    if request_path.is_file():
        request = GenerationRequest.model_validate_json(request_path.read_text())
        policy_bindings = _stage_policy_bindings(request.policy_bindings)
    PipelineEngine(StageLedger(workspace / "stage_ledger.jsonl")).run_stage(
        "validate",
        PluginKey("validation_gate", "dataset-builder-core", "1.0"),
        (StageInput(name="draft", sha256=sha256_file(draft)),),
        policy_bindings,
        operation,
    )
    return result[0]


def _build_review_impl(
    suite: SuiteDefinition,
    draft: Path,
    reports: ValidationSummary,
    output: Path,
) -> Path:
    from eval_contracts import load_dataset

    cases = load_dataset(draft).cases
    gate_names = {
        "evaluator": "评测器校验",
        "contract": "能力契约校验",
        "coverage": "覆盖校验",
        "duplicate": "重复校验",
        "leakage": "泄漏校验",
        "quality": "质量校验",
        "capability_snapshot": "能力快照一致性校验",
    }
    snapshot_gate = next(
        (item for item in reports.gates if item.name == "capability_snapshot"),
        None,
    )
    lines = [
        f"# 人工审核清单：{suite.suite_id}",
        "",
        f"- 数据集版本：{suite.dataset_version}",
        f"- 草案 SHA-256：`{reports.draft_sha256}`",
        f"- 自动校验总结果：{'PASS' if reports.valid else 'FAIL'}",
        f"- 数据集状态：{reports.state}",
        "- 生命周期状态：本文档最多对应 VALIDATED；本文档不代表数据集已获批准。",
        f"- 是否可批准：{'是' if reports.valid else '否'}",
        "- 审核人：____________________",
        "- 批准时间（UTC）：____________________",
        "",
        "## 自动校验结果",
        "",
    ]
    lines.extend(
        f"- {gate_names.get(gate.name, gate.name)}（`{gate.name}`）："
        f"{'PASS' if gate.passed else 'FAIL'}"
        + (f" — 原始错误：{'; '.join(gate.issues)}" if gate.issues else "")
        for gate in reports.gates
    )
    if snapshot_gate is not None:
        details = snapshot_gate.details
        lines.extend(
            [
                "",
                "## 能力快照绑定",
                "",
                f"- 生成时 Bundle SHA-256：`{details.get('generated_bundle_sha256')}`",
                f"- 当前 Bundle SHA-256：`{details.get('current_bundle_sha256')}`",
                f"- 是否一致：{'是' if snapshot_gate.passed else '否'}",
            ]
        )
        if details.get("changes"):
            lines.append(
                "- 结构化差异：" + json.dumps(details["changes"], ensure_ascii=False)
            )
        if details.get("impacted_slots"):
            lines.append(
                "- 受影响 Coverage Slot：" + "、".join(details["impacted_slots"])
            )
        if details.get("impacted_seeds"):
            lines.append("- 受影响 Seed Case：" + "、".join(details["impacted_seeds"]))
        generated_bindings = details.get("generated_snapshots", [])
        current_bindings = details.get("current_snapshots", [])
        if generated_bindings:
            lines.append(
                "- 生成时快照：" + json.dumps(generated_bindings, ensure_ascii=False)
            )
        if current_bindings:
            lines.append(
                "- 当前快照：" + json.dumps(current_bindings, ensure_ascii=False)
            )
    lines.extend(["", "## 案例审核清单", ""])
    for case in cases:
        expected = case.oracle.expected_module_output
        parameters = json.dumps(
            expected["parameters"],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        missing = json.dumps(
            expected["missing_parameters"],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        lines.append(
            f"- [ ] {case.case_id} | 意图：{expected['intent']} | "
            f"主场景类型：{case.scenario_type} | "
            f"状态：{expected['status']} | "
            f"后续动作：{expected['next_action']} | "
            f"参数：`{parameters}` | 待补参数：`{missing}` | "
            f"用户输入：{case.execution.user_input}"
        )
    lines.extend(
        [
            "",
            "## 人工审核声明",
            "",
            "请逐项确认：每条输入自然且无歧义；每个预期结果只能由冻结的"
            "能力契约唯一推出；当前被测智能体的实际输出没有影响判定标准；"
            "数据集不包含个人隐私、生产数据或隐藏推理。",
        ]
    )
    output.write_text("\n".join(lines) + "\n")
    return output


def build_review(
    suite: SuiteDefinition,
    draft: Path,
    reports: ValidationSummary,
    output: Path,
) -> Path:
    result: list[Path] = []

    def operation() -> dict[str, str]:
        review = _build_review_impl(suite, draft, reports, output)
        result.append(review)
        return {"path": str(review), "sha256": sha256_file(review)}

    request_path = draft.parent / "generation_request.json"
    policy_bindings: tuple[PolicyBinding, ...] = ()
    if request_path.is_file():
        request = GenerationRequest.model_validate_json(request_path.read_text())
        policy_bindings = _stage_policy_bindings(request.policy_bindings)
    PipelineEngine(StageLedger(draft.parent / "stage_ledger.jsonl")).run_stage(
        "review",
        PluginKey("review_renderer", "dataset-builder-core", "1.0"),
        (
            StageInput(name="draft", sha256=sha256_file(draft)),
            StageInput(
                name="validation",
                sha256=canonical_sha256(reports.model_dump(mode="json")),
            ),
        ),
        policy_bindings,
        operation,
    )
    return result[0]


def approval_from_review(
    draft: Path,
    review_file: Path,
    reviewer: str,
) -> Approval:
    """Create hash-bound approval only from a fully checked review artifact."""

    from eval_contracts import load_dataset

    review_text = review_file.read_text()
    if "数据集状态：STALE" in review_text:
        raise ValueError("stale or invalid review cannot be approved")
    draft_hash_match = re.search(
        r"^- 草案 SHA-256：`([0-9a-f]{64})`$",
        review_text,
        flags=re.MULTILINE,
    )
    if draft_hash_match is None or draft_hash_match.group(1) != sha256_file(draft):
        raise ValueError("review draft hash does not match current draft")

    case_ids = [case.case_id for case in load_dataset(draft).cases]
    checked_ids = re.findall(
        r"^- \[[xX]\] ([A-Za-z0-9_-]+)\s*\|",
        review_text,
        flags=re.MULTILINE,
    )
    if len(checked_ids) != len(set(checked_ids)) or set(checked_ids) != set(case_ids):
        raise ValueError("review must review every case exactly once")
    return Approval(
        reviewer=reviewer,
        approved_at=datetime.now(UTC),
        draft_sha256=sha256_file(draft),
        review_artifact_sha256=sha256_file(review_file),
        reviewed_case_ids=checked_ids,
    )


def _freeze_dataset_impl(
    suite: SuiteDefinition,
    draft: Path,
    approval: Approval,
    output_path: Path,
    generation_metadata: dict[str, object] | None = None,
):
    report = validate_draft_file(suite, draft)
    manifest_path = draft.parent / "generation_manifest.json"
    workspace_metadata = (
        json.loads(manifest_path.read_text()) if manifest_path.exists() else None
    )
    if generation_metadata is not None and generation_metadata != workspace_metadata:
        raise ValueError("generation metadata does not match validated workspace")
    generation_metadata = workspace_metadata or generation_metadata
    return freeze(
        suite,
        draft,
        approval,
        output_path,
        report,
        generation_metadata,
    )


def freeze_dataset(
    suite: SuiteDefinition,
    draft: Path,
    approval: Approval,
    output_path: Path,
    generation_metadata: dict[str, object] | None = None,
):
    result: list[Any] = []

    def operation() -> list[str]:
        paths = _freeze_dataset_impl(
            suite,
            draft,
            approval,
            output_path,
            generation_metadata,
        )
        result.extend(paths)
        return [str(path) for path in paths]

    request_path = draft.parent / "generation_request.json"
    policy_bindings: tuple[PolicyBinding, ...] = ()
    if request_path.is_file():
        request = GenerationRequest.model_validate_json(request_path.read_text())
        policy_bindings = _stage_policy_bindings(request.policy_bindings)
    PipelineEngine(StageLedger(draft.parent / "stage_ledger.jsonl")).run_stage(
        "freeze",
        PluginKey("dataset_freezer", "dataset-builder-core", "1.0"),
        (
            StageInput(name="draft", sha256=sha256_file(draft)),
            StageInput(
                name="approval",
                sha256=canonical_sha256(approval.model_dump(mode="json")),
            ),
        ),
        policy_bindings,
        operation,
    )
    return tuple(result)
