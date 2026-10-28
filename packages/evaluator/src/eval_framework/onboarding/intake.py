"""Prepare provisional Suites without executing or modifying source deliveries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..providers.external import RuntimeBinding, snapshot_runtime_binding
from .candidates import STATIC_KINDS, translate
from .delivery import capability_agent_path, read_delivery, sha256, snapshot
from .models import PreparedInput


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def prepare_input(
    source: Path,
    output_dir: Path,
    *,
    binding: dict[str, Any] | None = None,
    agent_root: Path | None = None,
) -> PreparedInput:
    source, output_dir = (
        Path(source).expanduser(),
        Path(output_dir).expanduser().resolve(),
    )
    if binding is not None and agent_root is not None:
        raise ValueError("use either an explicit binding or agent_root")
    root = snapshot(source, output_dir / f"intake_{uuid4().hex}" / "input")
    manifest, records = read_delivery(root)
    agent_path = capability_agent_path(root, manifest)
    if binding is not None:
        runtime = RuntimeBinding.model_validate(binding)
        if runtime.agent_id != manifest.agent_id:
            raise ValueError("runtime binding and candidate agent identity mismatch")
        if runtime.adapter == "static":
            raise ValueError("a static binding cannot execute Agent behavior")
    elif agent_root is not None and manifest.agent_id == "nanobot":
        agent_root = Path(agent_root).expanduser().resolve(strict=True)
        interpreter = agent_root / ".venv/bin/python"
        if not interpreter.is_file():
            raise ValueError(
                "Nanobot runtime requires .venv/bin/python or an explicit binding"
            )
        runtime = RuntimeBinding(
            version="1.0",
            agent_id="nanobot",
            adapter="nanobot_local",
            agent_root=agent_root,
            python=interpreter,
        )
    elif agent_root is not None:
        raise ValueError(
            f"no registered local adapter for {manifest.agent_id}; "
            "provide a stdio binding"
        )
    else:
        runtime = None
    runtime_files = (
        [item.model_dump(mode="json") for item in snapshot_runtime_binding(runtime)]
        if runtime is not None
        else []
    )
    selected: dict[str, list[Any]] = {"static": [], "behavior": []}
    ledger = []
    for row in records:
        case, entry = translate(row, root, manifest, runtime)
        ledger.append(entry)
        if case is not None:
            selected[entry["disposition"]].append(case)
    if len({entry["case_id"] for entry in ledger}) != len(ledger):
        raise ValueError("normalized case ID collision")
    counts = {group: len(cases) for group, cases in selected.items()}
    counts["blocked"] = len(records) - counts["static"] - counts["behavior"]
    source_identity = sha256(root / "manifest.json")
    common = {
        "protocol_version": "1.0",
        "agent_id": manifest.agent_id,
        "source_manifest_sha256": source_identity,
        "source_case_count": len(records),
        "source_state": manifest.state,
        "source_runtime_execution": manifest.runtime_execution,
        "source_approval": manifest.approval,
        "release_eligible": False,
        "release_ineligibility_reasons": [
            "candidate_import_has_no_approved_scoring_contract"
        ],
        "runtime_files": runtime_files,
    }
    dependencies = {"manifest.json": source_identity, **manifest.files_sha256}
    suite_paths = []
    lifecycle = (
        manifest.state
        if manifest.state in {"DRAFT", "VALIDATED", "APPROVED", "FROZEN"}
        else "UNKNOWN"
    )
    for partition, cases in selected.items():
        if not cases:
            continue
        subset = [
            entry
            for entry in ledger
            if (entry["kind"] in STATIC_KINDS) == (partition == "static")
        ]
        suite_id = f"candidate.{manifest.agent_id}.{source_identity[:12]}.{partition}"
        metadata = {
            "dataset_version": f"candidate-1.0-{source_identity[:12]}",
            "lifecycle_state": lifecycle,
            "suite_id": suite_id,
            "provider_id": manifest.agent_id,
            "capability_bundle_sha256": manifest.bundle_sha256,
            "execution_profiles": {"candidate_isolated": {"allowed_tools": []}},
            "execution_profiles_source": "manifest",
            "total_count": len(subset),
            "onboarding": {
                **common,
                "partition": partition,
                "selected_count": len(cases),
                "blocked_count": len(subset) - len(cases),
                "case_mapping": subset,
            },
            "source_dependencies": dependencies,
        }
        normalized = root / "evaluator" / f"{partition}.json"
        _write(
            normalized,
            {
                "metadata": metadata,
                "cases": [case.model_dump(mode="json") for case in cases],
            },
        )
        active = (
            RuntimeBinding(version="1.0", agent_id=manifest.agent_id, adapter="static")
            if partition == "static"
            else runtime
        )
        suite = {
            "schema_version": "1.0",
            "suite_id": suite_id,
            "suite_version": "1.0",
            "lifecycle_state": lifecycle,
            "dataset_loader": {
                "plugin_id": "candidate_delivery_v1",
                "version": "1.0.0",
            },
            "dataset_sources": [
                {
                    "path": normalized.relative_to(root).as_posix(),
                    "sha256": sha256(normalized),
                },
                *[
                    {"path": path, "sha256": digest}
                    for path, digest in dependencies.items()
                ],
            ],
            "provider": {
                "plugin_id": "external_provider_v1",
                "version": "1.0.0",
                "config": {
                    "binding": active.model_dump(mode="json", exclude_none=True),
                    "runtime_files": [] if partition == "static" else runtime_files,
                },
            },
            "capability_bundle": {
                "contract_id": f"capability.{manifest.agent_id}",
                "version": "1.0",
                "path": agent_path,
                "sha256": manifest.files_sha256[agent_path],
            },
            "run_config": {
                "run_mode": "framework_self_test"
                if partition == "static"
                else "agent_benchmark",
                "allow_non_frozen_dataset": True,
            },
        }
        suite_path = root / f"evaluator_{partition}.suite.json"
        _write(suite_path, suite)
        suite_paths.append(suite_path)
    report = {
        **common,
        "counts": counts,
        "cases": ledger,
        "suites": [str(path) for path in suite_paths],
        "runs": [],
    }
    report_path = root.parent / "intake.json"
    _write(report_path, report)
    return PreparedInput(
        root=root, suite_paths=suite_paths, report=report, report_path=report_path
    )
