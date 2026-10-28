"Independent, portable Nanobot delivery, with exclusive atomic publication."

import json
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from tempfile import mkdtemp

from ..full_generation.delivery import _publish
from .cases import build_cases
from .inputs import load_input, safe_path, sha256
from .models import Candidate
from .validation import validate_cases


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def write_text(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)


def coverage(data, cases, blockers):
    return [
        {
            "target_id": ident,
            "snapshot_type": item["payload"]["snapshot_type"],
            "case_ids": [c["case_id"] for c in cases if c["target_id"] == ident],
            "counts_by_kind": dict(
                Counter(c["kind"] for c in cases if c["target_id"] == ident)
            ),
            "blocker_ids": [
                b["blocker_id"] for b in blockers if b["target_id"] == ident
            ],
        }
        for ident, item in sorted(data["artifacts"].items())
    ]


def generate(source: Path, output: Path, expected_hash: str):
    output = output.resolve()
    if output.exists():
        raise FileExistsError(output)
    if output.is_relative_to(source.resolve()) or source.resolve().is_relative_to(
        output
    ):
        raise ValueError("output must be independent from source")
    data = load_input(source, expected_hash)
    cases, blockers = build_cases(data)
    report = validate_cases(data, cases, blockers)
    if not report["valid"]:
        raise ValueError(
            "candidate validation failed: " + "; ".join(report["issues"][:8])
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(mkdtemp(prefix="." + output.name + "-", dir=output.parent))
    try:
        for relative in data["files_sha256"]:
            target = staging / "source_delivery" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(safe_path(source, relative), target)
        normalized = {**data, "source_root": "source_delivery"}
        write_json(staging / "inventory.json", normalized)
        write_json(staging / "capability_ir.json", data["capability_ir"])
        write_json(
            staging / "schemas/nanobot_candidate.schema.json",
            Candidate.model_json_schema(),
        )
        write_json(staging / "blockers.json", blockers)
        write_json(staging / "coverage_matrix.json", coverage(data, cases, blockers))
        write_json(staging / "reports/validation.json", report)
        policy = {
            "policy_version": "nanobot-full-1.0",
            "state": "DRAFT",
            "source_policy": (
                "Only manifest-bound snapshots, specifications and source evidence."
            ),
            "coverage_policy": (
                "Every snapshot; recursive schema t"
                "ypes, required/optional, nullable,"
                " enum, min/max and additionalPrope"
                "rties; source-backed isolated beha"
                "vior candidates."
            ),
            "combination_policy": (
                "Only declared chains; no arbitrary"
                " module/tool Cartesian product. Ne"
                "sted argument combinations vary on"
                "e constraint at a time; explicit s"
                "equences come from implementation."
            ),
            "oracle_policy": (
                "JSON Schema validity or explicit i"
                "mplementation-derived expectations"
                "; no inferred business error codes"
                ", retry or idempotency."
            ),
            "unknown_policy": (
                "Preserve unknown; block behavior u"
                "ntil contract/runner binding is re"
                "solved."
            ),
            "execution_policy": (
                "Do not execute Agent, tool handlers, external services or paid models."
            ),
            "freeze_policy": ("PENDING review; no automatic approval or freeze."),
            "consumer_protocol": (
                "nanobot_candidate 1.0; not EvalCase; runtime adapter absent."
            ),
        }
        write_json(staging / "generation_policy.json", policy)
        grouped = defaultdict(list)
        for case in cases:
            grouped[(case["layer"], case["target_id"], case["kind"])].append(case)
        datasets = []
        for (layer, target, kind), rows in sorted(grouped.items()):
            relative = f"datasets/{layer}/{target}.{kind}.jsonl"
            write_text(
                staging / relative,
                "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in rows),
            )
            datasets.append(
                {
                    "path": relative,
                    "target_id": target,
                    "layer": layer,
                    "kind": kind,
                    "dataset_format": "nanobot_candidate",
                    "case_count": len(rows),
                    "sha256": sha256(staging / relative),
                }
            )
        write_text(
            staging / "datasets/critical_links/README.md",
            (
                "# 关键链路缺口\n\n输入只声明一条对话端到端链，"
                "没有关键链路定义。此目录仅存缺口义务，"
                "不宣称已生成可执行关键链路。\n"
            ),
        )
        review = [
            "# Nanobot 行为候选审核",
            "",
            "全部未执行；逐条确认源码推导预期与运行前置条件后方可接入 runner。",
            "",
        ]
        for c in cases:
            if c["kind"] != "behavior_candidate":
                continue
            review += [
                f"- [ ] {c['case_id']} — {c['title']}",
                "",
                "```json",
                json.dumps(
                    {
                        k: c[k]
                        for k in (
                            "preconditions",
                            "input",
                            "oracle",
                            "source_refs",
                            "runner_requirements",
                            "execution_readiness",
                        )
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                "```",
                "",
            ]
        write_text(staging / "review.md", "\n".join(review) + "\n")
        write_text(staging / "GENERATION_CONSTRAINTS.md", constraints_text())
        write_text(staging / "README.md", readme_text(data, report, datasets))
        for file in Path(__file__).parent.iterdir():
            if file.is_file() and file.suffix in {".py", ".json", ".md"}:
                dest = staging / "generator_sources" / file.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(file, dest)
        manifest = {
            "schema_version": "1.0",
            "agent_id": "nanobot",
            "agent_version": data["agent_version"],
            "state": "DRAFT",
            "runtime_execution": "NOT_RUN",
            "approval": "PENDING",
            "bundle_sha256": expected_hash,
            "dataset_format": "nanobot_candidate",
            "case_count": len(cases),
            "counts_by_kind": report["counts_by_kind"],
            "datasets": datasets,
            "files_sha256": {
                p.relative_to(staging).as_posix(): sha256(p)
                for p in sorted(staging.rglob("*"))
                if p.is_file()
            },
        }
        write_json(staging / "manifest.json", manifest)
        checked = verify(staging)
        if not checked["valid"]:
            raise ValueError(
                "staged verification failed: " + "; ".join(checked["issues"][:8])
            )
        # Detect a source change during compilation/copy, before publication.
        latest = load_input(source, expected_hash)
        if latest["files_sha256"] != data["files_sha256"]:
            raise ValueError("source changed before publication")
        _publish(staging, output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return {**report, "output_path": str(output), "dataset_file_count": len(datasets)}


def verify(output):
    output = Path(output).resolve()
    issues = []
    try:
        manifest = json.loads((output / "manifest.json").read_text())
        if (
            manifest["agent_id"],
            manifest["state"],
            manifest["runtime_execution"],
            manifest["approval"],
        ) != ("nanobot", "DRAFT", "NOT_RUN", "PENDING"):
            raise ValueError("unexpected manifest identity/state")
        for relative, expected in manifest["files_sha256"].items():
            if sha256(safe_path(output, relative)) != expected:
                raise ValueError("output file hash mismatch: " + relative)
        data = load_input(output / "source_delivery", manifest["bundle_sha256"])
        inventory = json.loads((output / "inventory.json").read_text())
        if inventory != {**data, "source_root": "source_delivery"}:
            raise ValueError("normalized inventory mismatch")
        cases = []
        paths = []
        for ds in manifest["datasets"]:
            path = safe_path(output, ds["path"])
            paths.append(ds["path"])
            if (
                ds["path"] not in manifest["files_sha256"]
                or sha256(path) != ds["sha256"]
            ):
                raise ValueError("unbound dataset")
            rows = [
                json.loads(line)
                for line in path.read_text().splitlines()
                if line.strip()
            ]
            if len(rows) != ds["case_count"]:
                raise ValueError("dataset row count mismatch")
            if any(
                (r["target_id"], r["layer"], r["kind"])
                != (ds["target_id"], ds["layer"], ds["kind"])
                for r in rows
            ):
                raise ValueError("dataset grouping mismatch")
            cases.extend(rows)
        if len(paths) != len(set(paths)):
            raise ValueError("duplicate dataset path")
        actual_paths = {
            p.relative_to(output).as_posix()
            for p in (output / "datasets").rglob("*.jsonl")
        }
        if actual_paths != set(paths):
            raise ValueError("unlisted dataset")
        if (
            len(cases) != manifest["case_count"]
            or dict(Counter(c["kind"] for c in cases)) != manifest["counts_by_kind"]
        ):
            raise ValueError("manifest count mismatch")
        blockers = json.loads((output / "blockers.json").read_text())
        if json.loads((output / "coverage_matrix.json").read_text()) != coverage(
            data, sorted(cases, key=lambda c: c["case_id"]), blockers
        ):
            raise ValueError("coverage matrix mismatch")
        report = validate_cases(data, cases, blockers)
        issues.extend(report["issues"])
        stored = json.loads((output / "reports/validation.json").read_text())
        if report != stored:
            issues.append("validation report mismatch")
    except Exception as exc:
        issues.append(str(exc))
    return {
        "valid": not issues,
        "issues": issues,
        "runtime_execution": "NOT_RUN",
        "approval": "PENDING",
    }


def constraints_text():
    return (Path(__file__).parent / "constraints.md").read_text()


def readme_text(data, report, datasets):
    kinds = report["counts_by_kind"]
    lines = [
        "# Nanobot 独立评测候选集",
        "",
        f"Agent：nanobot {data['agent_version']}；能力包：`{data['bundle_sha256']}`。",
        "",
        (
            "35 个快照、31 个主要目标（8 模块、21 工具、"
            f"1 意图、1 端到端链）；{len(datasets)} 个 JSONL 文件。"
        ),
        "",
        (
            f"参数/输出Schema契约用例 {kinds.get('schema_contract', 0)} 条；"
            f"行为候选 {kinds.get('behavior_candidate', 0)} 条；"
            f"静态声明检查 {kinds.get('contract_check', 0)} 条；"
            f"阻塞义务 {kinds.get('blocked_obligation', 0)} 条。"
        ),
        "",
        (
            "**DRAFT / NOT_RUN / PENDING。现有 Eva"
            "lCase 兼容条数为 0；这是独立候选协议，尚未运行 Agent。"
            "**"
        ),
        "",
        "| 层级 | Schema用例 | 行为候选 | 声明检查 | 阻塞义务 |",
        "|---|---:|---:|---:|---:|",
    ]
    for layer in ("modules", "tools", "critical_links", "end_to_end", "contracts"):
        counts = Counter()
        for ds in datasets:
            if ds["layer"] == layer:
                counts[ds["kind"]] += ds["case_count"]
        lines.append(
            f"| {layer} | {counts['schema_contract']} | "
            f"{counts['behavior_candidate']} | {counts['contract_check']} | "
            f"{counts['blocked_obligation']} |"
        )
    lines += [
        "",
        "## 入口",
        "",
        "- [完整文件清单](manifest.json)",
        "- [生成约束](GENERATION_CONSTRAINTS.md)",
        "- [覆盖矩阵](coverage_matrix.json)",
        "- [能力和适配缺口](blockers.json)",
        "- [静态校验报告](reports/validation.json)",
        "- [行为候选审核清单](review.md)",
        "- [工具用例](datasets/tools/)",
        "- [模块与意图用例](datasets/modules/)",
        "- [关键链路缺口](datasets/critical_links/README.md)",
        "- [端到端定义](datasets/end_to_end/)",
        "",
        "## 阅读方式",
        "",
        (
            "先看 behavior_candidate 文件中的前置fixtur"
            "e、输入和oracle。schema_contract仅检查参数/输"
            "出Schema，不代表实际工具行为。contract_check只核"
            "对声明，blocked_obligation没有足够运行依据。unk"
            "nown执行能力未被升级。端到端边界冲突和关键链路缺失已显式列出。"
        ),
        "",
        (
            "source_delivery/保留完整输入；inventory.j"
            "son含适配后的参数Schema；capability_ir.jso"
            "n是当前对话选择的统一IR，不代表全部工具已归入该链。generat"
            "or_sources/保留本次生成器与候选目录证据。"
        ),
        "",
        "## 复验",
        "",
        "在Builder根目录执行（将目录替换为本交付路径）：",
        "",
        "```bash",
        (
            "PYTHONPATH=src ../agent_evaluator/"
            ".venv/bin/python -m dataset_builde"
            "r.cli validate-nanobot --workspace"
            " workspaces/nanobot_full_eval_2026"
            "1023"
        ),
        "```",
        "",
        "本目录与mini_agent评测集独立；复验不调用Agent、工具或外部服务。",
        "",
    ]
    return "\n".join(lines)
