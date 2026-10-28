"""Atomic, review-gated delivery of definitions and compatible EvalCase files."""

import json
import os
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from tempfile import mkdtemp

from eval_framework import load_dataset, validate_dataset
from eval_framework.schemas import EvalCase

from .contract_cases import compile_contract_cases
from .intent_cases import compile_intent_cases
from .inventory import digest, load_inventory, verify_sources
from .models import ContractCase, DeliveryReport, GenerationResult
from .planner import plan_coverage
from .runtime_cases import compile_runtime_cases
from .validation import collect_blockers, evaluator_context, validate_generation


def _json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def definition_kind(case):
    if case.execution_readiness == "blocked":
        return "blocked_obligation"
    if case.payload.get("input", {}).get("operation") == "inspect_declared_constraint":
        return "contract_check"
    return "behavior_case"


def _before_publish(staging, result):
    """Verify the staged self-contained artifacts before the atomic rename."""
    report = verify_delivery(staging)
    if not report["valid"]:
        raise ValueError("staged delivery invalid: " + "; ".join(report["issues"][:10]))


def generate_full_dataset(
    bundle: Path, delivery_root: Path, output: Path, expected_hash: str
) -> DeliveryReport:
    output = output.resolve()
    if output.exists():
        raise FileExistsError(output)
    inv = load_inventory(bundle, delivery_root, expected_hash)
    if output == Path(inv.delivery_root) or output.is_relative_to(
        Path(inv.bundle_path)
    ):
        raise ValueError("output cannot modify source bundle")
    slots, blockers = plan_coverage(inv)
    runtime_cases, extra = compile_runtime_cases(inv, slots)
    result = GenerationResult(
        inventory=inv,
        slots=slots,
        cases=compile_contract_cases(inv, slots)
        + compile_intent_cases(inv, slots)
        + runtime_cases,
        blockers=blockers + extra,
    )
    result.blockers = collect_blockers(result)
    report = validate_generation(result)
    if not report["valid"]:
        raise ValueError(
            "generation validation failed: " + "; ".join(report["issues"][:12])
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(mkdtemp(prefix="." + output.name + "-", dir=output.parent))
    try:
        for relative in inv.external_bindings:
            dest = staging / "source_delivery" / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(Path(inv.delivery_root) / relative, dest)
        shutil.copytree(bundle, staging / "capability_bundle")
        # Preserve original input lock for audit; verification uses copied sources.
        _json(staging / "inventory.json", inv)
        _json(staging / "generation_result.json", result)
        _json(
            staging / "coverage_plan.json",
            {"slots": [s.model_dump(mode="json") for s in slots]},
        )
        _json(
            staging / "blockers.json",
            {"blockers": [b.model_dump(mode="json") for b in result.blockers]},
        )
        _json(
            staging / "schemas/contract_case.schema.json",
            ContractCase.model_json_schema(),
        )
        _json(staging / "schemas/eval_case.schema.json", EvalCase.model_json_schema())
        _json(staging / "reports/validation.json", report)
        by_slot = {s.slot_id: s for s in slots}
        groups = defaultdict(list)
        for c in result.cases:
            s = by_slot[c.slot_id]
            groups[(s.layer, s.target_id, c.dataset_format, definition_kind(c))].append(
                c
            )
        tools = sorted(
            a["payload"]["tool_name"]
            for a in inv.artifacts.values()
            if a["payload"]["snapshot_type"] == "tool"
        )
        datasets, locations = [], {}
        for (layer, target, fmt, kind), cases in sorted(groups.items()):
            relative = f"datasets/{layer}/{target}.{fmt}.{kind}.jsonl"
            path = staging / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            cases.sort(key=lambda c: c.payload["case_id"])
            path.write_text(
                "".join(
                    json.dumps(c.payload, ensure_ascii=False, separators=(",", ":"))
                    + "\n"
                    for c in cases
                )
            )
            binding = {
                "path": relative,
                "dataset_format": fmt,
                "definition_kind": kind,
                "target_id": target,
                "layer": layer,
                "case_count": len(cases),
                "sha256": digest(path),
            }
            datasets.append(binding)
            companion = {
                **binding,
                "dataset_sha256": digest(path),
                "state": "DRAFT",
                "dataset_version": "full-fixture-1.0",
                "suite_id": "full_tools_fixture_v1",
                "capability_bundle_sha256": inv.bundle_sha256,
                "execution_profiles": {"full_fixture": {"allowed_tools": tools}},
                "runtime_binding": (
                    "Explicit fixture Provider and v3 catalog a"
                    "dapter required; no production binding."
                ),
            }
            _json(path.with_suffix(".manifest.json"), companion)
            for c in cases:
                locations[c.payload["case_id"]] = relative
        matrix = []
        for s in slots:
            matches = [c for c in result.cases if c.slot_id == s.slot_id]
            matrix.append(
                {
                    **s.model_dump(mode="json"),
                    "cases": [
                        {
                            "case_id": c.payload["case_id"],
                            "path": locations[c.payload["case_id"]],
                            "dataset_format": c.dataset_format,
                            "definition_kind": definition_kind(c),
                            "execution_readiness": c.execution_readiness,
                            "coverage_mode": c.coverage_mode,
                            "blocker_ids": c.blocker_ids,
                        }
                        for c in matches
                    ],
                    "related_gap_ids": [
                        b.blocker_id
                        for b in result.blockers
                        if s.slot_id in b.affected_slot_ids
                    ],
                }
            )
        _json(
            staging / "coverage_matrix.json", {"targets": inv.targets, "rows": matrix}
        )
        counts = dict(Counter(definition_kind(c) for c in result.cases))
        layer_counts = {
            layer: dict(
                Counter(
                    definition_kind(c)
                    for c in result.cases
                    if by_slot[c.slot_id].layer == layer
                )
            )
            for layer in ("modules", "tools", "critical_links", "end_to_end")
        }
        _json(
            staging / "reports/coverage.json",
            {
                "definition_counts": counts,
                "layers": layer_counts,
                "target_count": len(inv.targets),
                "slot_count": len(slots),
                "note": (
                    "Accounting completeness is not runtime cov"
                    "erage; contract checks and blockers are ex"
                    "cluded from behavior case totals."
                ),
            },
        )
        review = [
            "# 全层级评测集审核清单",
            "",
            "状态：DRAFT；未运行 Agent；未批准、未冻结。",
            "确认每条输入、前置条件、Oracle 与快照一致；待适配定义不能标记运行通过。",
            "",
        ]
        for c in sorted(result.cases, key=lambda c: c.payload["case_id"]):
            if definition_kind(c) != "behavior_case":
                continue
            payload = c.payload
            review.extend(
                [
                    (
                        f"- [ ] {payload['case_id']} | "
                        f"{by_slot[c.slot_id].target_id} | {c.execution_readiness}"
                    ),
                    "  - 输入：`"
                    + json.dumps(
                        payload.get("execution", payload.get("input")),
                        ensure_ascii=False,
                    )
                    + "`",
                    "  - 前置：`"
                    + json.dumps(payload.get("preconditions", []), ensure_ascii=False)
                    + "`",
                    "  - 预期：`"
                    + json.dumps(payload["oracle"], ensure_ascii=False)
                    + "`",
                ]
            )
        review.extend(
            [
                "",
                (
                    "契约检查与阻塞义务见 coverage_matri"
                    "x.json 和 blockers.json；不计"
                    "作已可运行的行为案例。"
                ),
            ]
        )
        (staging / "review.md").write_text("\n".join(review) + "\n")
        readme = [
            "# 完整 fixture 能力评测集（待审核）",
            "",
            f"能力包 SHA-256：`{inv.bundle_sha256}`",
            (
                f"23 个目标，{len(slots)} 个覆盖项；"
                f"行为案例 {counts.get('behavior_case', 0)} 条，"
                f"静态契约检查 {counts.get('contract_check', 0)} 条，"
                f"阻塞义务 {counts.get('blocked_obligation', 0)} 条。"
            ),
            "",
            (
                "**这些不是全部已可执行的测试。** "
                "EvalCase 子集通过真实 evaluator 静态校验；"
                "契约案例通过独立 Schema，仍需运行适配。"
                "所有实际执行状态为 NOT_RUN，所有人工批准为 PENDING。"
            ),
            "",
            "| 层级 | 行为案例 | 契约检查 | 阻塞义务 |",
            "|---|---:|---:|---:|",
        ]
        for layer, n in layer_counts.items():
            readme.append(
                f"| {layer} | {n.get('behavior_case', 0)} | "
                f"{n.get('contract_check', 0)} | {n.get('blocked_obligation', 0)} |"
            )
        readme += [
            "",
            "## 文件入口",
            "",
            "- `manifest.json`：分组文件路径、格式、数量与 Hash。",
            "- `datasets/modules/`：模块与七种意图。",
            "- `datasets/tools/`：六个工具。",
            "- `datasets/critical_links/`：两条关键链路。",
            "- `datasets/end_to_end/`：端到端。",
            "- `coverage_matrix.json`：所有目标、覆盖项、来源与 blocker 的映射。",
            "- `review.md`：行为案例的未勾选审核清单。",
            "- `reports/validation.json`：静态校验结果。",
            "- `blockers.json`：能力缺口及尚未映射的语义义务。",
            "",
            "## 消费与限制",
            "",
            (
                "`eval_case` 文件才可传给 evaluator 的 load_datase"
                "t；与其同目录的 Manifest 提供 execution_profiles。"
            ),
            "`capability_contract_case` 是独立定义协议，不能直接传给现有 evaluator。",
            (
                "工具 test_fixture 不是生产后端。各工"
                "具案例需要独立初始化；幂等序列内部共享一次 fix"
                "ture。"
            ),
            (
                "原生工具目录尚不能直接理解 v3 工具快照的 operation/fault 字段；"
                "校验使用 source-derived ToolCatalog，不代表已注册 run"
                "time handler。"
            ),
            (
                "单轮端到端早停仅验证 turns_match 的终"
                "态与零调用，不声称完成确认恢复或业务写入。"
            ),
            (
                "错误分支需要受控故障注入 adapter；当前 n"
                "ative runtime 不支持，故这些是待适配"
                "定义。"
            ),
            (
                "静态契约检查只核对快照声明，不计入行为覆盖率。bl"
                "ocked_obligation 无具体可执行 O"
                "racle，不得作为已生成的有效行为测试运行。"
            ),
            "",
            "## 本地复验",
            "",
            "在 Builder 根目录执行：",
            "```bash",
            (
                "PYTHONPATH=src ../agent_evaluator/.venv/bin/python "
                f'-m dataset_builder.cli validate-full --workspace "{output}"'
            ),
            "```",
            "",
            "复验只检查文件、协议、来源与覆盖，不调用 Agent 或付费模型。",
        ]
        (staging / "README.md").write_text("\n".join(readme) + "\n")
        files = {
            p.relative_to(staging).as_posix(): digest(p)
            for p in sorted(staging.rglob("*"))
            if p.is_file()
        }
        manifest = {
            "schema_version": "1.0",
            "state": "DRAFT",
            "runtime_execution": "NOT_RUN",
            "approval": "PENDING",
            "bundle_sha256": inv.bundle_sha256,
            "definition_counts": counts,
            "case_counts_by_format": report["counts"]["dataset_format"],
            "datasets": datasets,
            "files_sha256": files,
            "generator_files_sha256": {
                p.name: digest(p) for p in Path(__file__).parent.glob("*.py")
            },
        }
        _json(staging / "manifest.json", manifest)
        _before_publish(staging, result)
        verify_sources(inv)
        if output.exists():
            raise FileExistsError(output)
        # Use macOS renamex_np(RENAME_EXCL) where available; fallback checks existence.
        _publish(staging, output)
        return DeliveryReport(
            output_path=str(output),
            file_count=len(files) + 1,
            case_counts=counts,
            blocker_count=len(result.blockers),
            valid=True,
        )
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def _publish(source, dest):
    import ctypes
    import sys

    if sys.platform == "darwin":
        libc = ctypes.CDLL(None, use_errno=True)
        rename = libc.renamex_np
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        if rename(os.fsencode(source), os.fsencode(dest), 0x00000004) != 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), str(dest))
    else:
        if dest.exists():
            raise FileExistsError(dest)
        source.rename(dest)


def verify_delivery(output: Path) -> dict:
    issues = []
    try:
        manifest = json.loads((output / "manifest.json").read_text())
        for relative, expected in manifest["files_sha256"].items():
            path = (output / relative).resolve()
            if not path.is_relative_to(output.resolve()) or digest(path) != expected:
                issues.append("file hash mismatch: " + relative)
        if issues:
            return {"valid": False, "issues": issues}
        result = GenerationResult.model_validate_json(
            (output / "generation_result.json").read_text()
        )
        inv = load_inventory(
            output / "source_delivery/bundle",
            output / "source_delivery",
            manifest["bundle_sha256"],
        )
        result.inventory = inv
        report = validate_generation(result)
        issues.extend(report["issues"])
        registry, catalog = evaluator_context(inv)
        for ds in manifest["datasets"]:
            path = output / ds["path"]
            rows = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
            if len(rows) != ds["case_count"]:
                issues.append("case count mismatch: " + ds["path"])
            if ds["dataset_format"] == "eval_case":
                r = validate_dataset(
                    load_dataset(path), capabilities=registry, tools=catalog
                )
                issues.extend(f"{i.case_id}: {i.message}" for i in r.issues)
            else:
                for row in rows:
                    ContractCase.model_validate(row)
    except Exception as exc:
        issues.append(str(exc))
    return {
        "valid": not issues,
        "issues": issues,
        "runtime_execution": "NOT_RUN",
        "approval": "PENDING",
    }
