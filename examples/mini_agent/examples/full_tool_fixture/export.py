"""Reproducible complete fixture bundle plus separately hash-bound reports."""

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

from capability_snapshot_kit import (
    CapabilitySelection,
    load_capability_bundle,
    resolve_capability_graph,
    validate_capability_bundle,
)
from minimal_agent import build_default_intent_registry, export_capability_bundle
from minimal_agent.runtime.tool_binding import require_complete_tools

from . import create_registry


def _write(path, payload):
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _gaps(tool_ids):
    return [
        {
            "gap_id": "PRODUCTION_BACKENDS_MISSING",
            "affected_snapshot_ids": tool_ids,
            "status": "open",
            "reason": "All six tools bind isolated example fixtures.",
            "required_action": (
                "Provide real handlers and production contracts; "
                "export a separate bundle."
            ),
        },
        {
            "gap_id": "CONFIRMATION_RESUME_UNSUPPORTED",
            "affected_snapshot_ids": [
                "intent.add_backpack_gift",
                "tool.add_gift_to_backpack",
                "chain.end_to_end",
            ],
            "status": "open",
            "reason": (
                "The Agent stops at NEED_CONFIRMATION. "
                "External fixture approval is not Agent resume."
            ),
            "required_action": (
                "Implement confirmation state, acceptance, invalidation and resume."
            ),
        },
        {
            "gap_id": "CONTEXT_UNSUPPORTED",
            "affected_snapshot_ids": [
                "scope.context",
                "module.agent_orchestrator",
                "evidence.context_state",
            ],
            "status": "open",
            "reason": "The runtime does not inherit business state between turns.",
            "required_action": "Implement session state and state evidence.",
        },
        {
            "gap_id": "PREPARE_RESOURCE_POLICY_MISMATCH",
            "affected_snapshot_ids": [
                "intent.prepare_resource",
                "tool.prepare_resource",
            ],
            "status": "open",
            "reason": (
                "Intent uses a read policy; the fixture creates isolated resources."
            ),
            "required_action": (
                "Define real business behavior and confirmation policy "
                "before production binding."
            ),
        },
        {
            "gap_id": "GIFT_ENVIRONMENT_NOT_IN_TOOL_ARGUMENTS",
            "affected_snapshot_ids": [
                "intent.add_backpack_gift",
                "tool.add_gift_to_backpack",
            ],
            "status": "open",
            "reason": (
                "Intent requires environment; the tool model has no such field. "
                "This fixture is isolated only."
            ),
            "required_action": "Define trusted environment binding for real writes.",
        },
        {
            "gap_id": "FULL_DATASET_AND_HUMAN_REVIEW_PENDING",
            "affected_snapshot_ids": [],
            "status": "open",
            "reason": (
                "This delivery contains capability facts and fixtures, "
                "not reviewed evaluation JSONL."
            ),
            "required_action": (
                "Use Builder to author datasets, coverage and review checklists; "
                "evaluate and review before freezing."
            ),
        },
    ]


def export_delivery(output: str | Path) -> Path:
    """Publish a new local artifact directory; never overwrite a prior delivery."""
    output = Path(output)
    if output.exists():
        raise FileExistsError(f"delivery already exists: {output}")
    intents, registry = build_default_intent_registry(), create_registry()
    require_complete_tools(intents, registry)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".tool-delivery-", dir=output.parent
    ) as temp:
        staging = Path(temp) / "delivery"
        staging.mkdir()
        root = staging / "bundle"
        export_capability_bundle(root, intents, registry)
        validation = validate_capability_bundle(root).model_dump(mode="json")
        bundle = load_capability_bundle(root)
        digest = bundle.agent.capability_bundle_sha256
        targets = sorted(
            [
                *bundle.modules.values(),
                *bundle.intents.values(),
                *bundle.chains.values(),
            ],
            key=lambda item: item.snapshot_id,
        )
        resolutions = []
        for target in [*bundle.scopes.values(), *bundle.chains.values()]:
            for intent in bundle.intents.values():
                result = resolve_capability_graph(
                    bundle,
                    CapabilitySelection(
                        scope_or_chain_id=target.snapshot_id,
                        intent_id=intent.snapshot_id,
                        tool_id=(
                            f"tool.{intent.required_tool_name}"
                            if intent.required_tool_name
                            else None
                        ),
                    ),
                )
                resolutions.append(result.model_dump(mode="json"))
        _write(
            staging / "validation_report.json",
            {
                **validation,
                "capability_bundle_sha256": digest,
                "validation_scope": "schema_hash_references_and_capability_resolution",
                "runtime_tests": (
                    "Run repository pytest; export itself does not execute tools."
                ),
                "production_ready": False,
            },
        )
        _write(
            staging / "capability_inventory.json",
            {
                "capability_bundle_sha256": digest,
                "targets": [
                    {
                        "snapshot_id": target.snapshot_id,
                        "snapshot_type": target.snapshot_type,
                        "snapshot_sha256": target.snapshot_sha256,
                    }
                    for target in targets
                ],
                "tools": [
                    {
                        "snapshot_id": tool.snapshot_id,
                        "registered": tool.registered,
                        "implementation_profile": tool.implementation_profile,
                    }
                    for tool in bundle.tools.values()
                ],
                "selections": resolutions,
                "note": (
                    "Resolution checks declarations, not goal attainment. "
                    "See gaps for confirmation, context and production availability."
                ),
            },
        )
        _write(
            staging / "capability_contract_gaps.json",
            {
                "capability_bundle_sha256": digest,
                "gaps": _gaps(sorted(bundle.tools)),
            },
        )
        (staging / "README.md").write_text(
            "# 完整工具评测能力包\n\n"
            "Builder 入口为 `bundle/agent.json`，交付整个 `bundle/` 目录。\n\n"
            "包含 7 Module、7 Intent、6 Tool、5 Scope、2 条关键链路、1 条端到端链路。\n"
            "六个工具均为可执行的 `test_fixture`，不连接生产服务。\n"
            "生成命令：\n`python -m examples.full_tool_fixture.export "
            "--output <新目录>`。\n"
            "普通导出／运行共用 factory：\n"
            "`examples.full_tool_fixture:create_registry`。\n\n"
            "validation_report.json 验证制品；\n"
            "capability_inventory.json 列出能力和组合解析；\n"
            "capability_contract_gaps.json 列出尚未实现的业务和评测交付。\n"
            "生产接入、上下文、确认恢复、JSONL 数据集和人工审核未在本包中完成。\n",
            encoding="utf-8",
        )
        files = {
            path.relative_to(staging).as_posix(): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in sorted(staging.rglob("*"))
            if path.is_file()
        }
        _write(
            staging / "manifest.json",
            {
                "profile": "full_tools_fixture_v1",
                "factory": "examples.full_tool_fixture:create_registry",
                "bundle_path": "bundle",
                "snapshot_format_version": "3.0",
                "capability_bundle_sha256": digest,
                "tool_count": len(bundle.tools),
                "production_ready": False,
                "human_review": "not_performed",
                "files_sha256": files,
            },
        )
        # Refuse even an empty directory that appeared while we were generating.
        output.mkdir(exist_ok=False)
        try:
            for path in staging.iterdir():
                os.replace(path, output / path.name)
        except BaseException:
            # Preserve partial files for diagnosis instead of claiming completion.
            raise
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = export_delivery(args.output)
    print(json.dumps({"output": str(output), "bundle": str(output / "bundle")}))


if __name__ == "__main__":
    main()
