"Independent, portable Nanobot delivery, with exclusive atomic publication."

import json
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from tempfile import mkdtemp

from ..full_generation.delivery import _publish
from .cases import build_cases
from .delta import compare, make_baseline
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


def generate(
    source: Path, output: Path, expected_hash: str, previous: Path | None = None
):
    output = output.resolve()
    if output.exists():
        raise FileExistsError(output)
    if output.is_relative_to(source.resolve()) or source.resolve().is_relative_to(
        output
    ):
        raise ValueError("output must be independent from source")
    data = load_input(source, expected_hash)
    baseline = None
    if previous is not None:
        checked = verify(previous)
        if not checked["valid"]:
            raise ValueError(
                "invalid previous delivery: " + "; ".join(checked["issues"])
            )
        baseline = make_baseline(previous)
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
        delta = None
        if baseline is not None:
            delta = compare(baseline, data, cases, blockers)
            if delta["blocker_changes"]["unverified_removals"]:
                raise ValueError("contract delta contains unverified blocker removals")
            write_json(staging / "reports/previous_baseline.json", baseline)
            write_json(staging / "reports/contract_delta.json", delta)
            write_text(staging / "CHANGELOG.md", changelog_text(delta))
        policy = {
            "policy_version": "nanobot-full-2.0"
            if "execution_contract" in data
            else "nanobot-full-1.0",
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
                "JSON Schema validity, reviewed explicit execution contracts or "
                "implementation-derived expectations; no inferred business error "
                "codes, retry or idempotency. New contract assertions require "
                "exact source revision."
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
                            "source_basis",
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
        write_text(staging / "GENERATION_CONSTRAINTS.md", constraints_text(data))
        write_text(staging / "README.md", readme_text(data, report, datasets, delta))
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
        if previous is not None and make_baseline(previous) != baseline:
            raise ValueError("previous delivery changed before publication")
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
        delta_names = {"reports/previous_baseline.json", "reports/contract_delta.json"}
        present = delta_names & manifest["files_sha256"].keys()
        if present:
            if present != delta_names:
                raise ValueError("incomplete contract delta binding")
            baseline = json.loads(
                (output / "reports/previous_baseline.json").read_text()
            )
            delta = compare(baseline, data, cases, blockers)
            if delta != json.loads(
                (output / "reports/contract_delta.json").read_text()
            ):
                raise ValueError("contract delta mismatch")
            if delta["blocker_changes"]["unverified_removals"]:
                raise ValueError("contract delta contains unverified blocker removals")
    except Exception as exc:
        issues.append(str(exc))
    return {
        "valid": not issues,
        "issues": issues,
        "runtime_execution": "NOT_RUN",
        "approval": "PENDING",
    }


def constraints_text(data):
    name = "constraints_v3.md" if "execution_contract" in data else "constraints.md"
    return (Path(__file__).parent / name).read_text()


def readme_text(data, report, datasets, delta=None):
    kinds = report["counts_by_kind"]
    revised = "execution_contract" in data
    lines = [
        "# Nanobot 独立评测候选集",
        "",
        f"Agent：nanobot {data['agent_version']}；能力包：`{data['bundle_sha256']}`。",
        "",
        (
            f"{report['snapshot_count']} 个快照、"
            f"{report['primary_target_count']} 个主要目标（8 模块、21 工具、"
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
        *(
            [
                "- [新旧契约与候选差异](CHANGELOG.md)",
                "- [机器可读差异报告](reports/contract_delta.json)",
            ]
            if delta
            else []
        ),
        "",
        "## 阅读方式",
        "",
        (
            "先看 behavior_candidate 文件中的前置fixtur"
            "e、输入和oracle。schema_contract仅检查参数/输"
            "出Schema，不代表实际工具行为。contract_check只核"
            "对声明，blocked_obligation没有足够运行依据。unk"
            "nown执行能力未被升级。条件路径边界冲突和关键链路缺失已显式列出。"
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
            "PYTHONPATH=src ../agent_evaluator/.venv/bin/python "
            "-m dataset_builder.cli validate-nanobot --workspace workspaces/"
            + (
                "nanobot_full_eval_v3_20261024"
                if revised
                else "nanobot_full_eval_20261023"
            )
        ),
        "```",
        "",
        "本目录与mini_agent评测集独立；复验不调用Agent、工具或外部服务。",
        "",
    ]
    if revised:
        lines += [
            "## 本次契约补齐",
            "",
            "31 条显式契约候选覆盖 9 类终止分支与共享工具错误、重试、观测语义，"
            "替代旧版 1 条粗粒度端到端候选；原 70 条工具、19 条模块候选保留。"
            "合计 120 条行为候选，全部仍需 runner/fixture 绑定，"
            "不能直接执行为 EvalCase。",
            "",
            "异常/取消观察器、逐工具成功结果和业务错误码、权限、幂等、批量及副作用仍缺依据。"
            "旧整体边界冲突收窄为配置 MCP 时的条件路径冲突；"
            "本批端到端夹具明确禁用 MCP。"
            "completed 不等于业务成功，异常和取消不要求原生 RunResult。",
            "",
            "再次生成新版本时使用 generate-nanobot 的 --previous 指向旧交付目录；"
            "输出目录必须不存在。差异报告随包复验，无需旧目录仍在原位置。",
            "",
        ]
    return "\n".join(lines)


def changelog_text(delta):
    cases = delta["summary"]["cases"]
    blockers = delta["summary"]["blockers"]
    changes = delta["case_changes"]["updated"]
    oracle_count = sum(c["oracle_changed"] for c in changes)
    input_count = sum(c["input_changed"] for c in changes)
    rebound_only = sum(
        not c["input_changed"] and not c["oracle_changed"] for c in changes
    )
    lines = [
        "# Nanobot v3 契约更新差异",
        "",
        f"旧能力包：`{delta['previous']['bundle_sha256']}`。",
        "",
        f"新能力包：`{delta['current']['bundle_sha256']}`。",
        "",
        "## 候选与断言",
        "",
        f"新增 {cases['added']} 条，移除 {cases['removed']} 条，"
        f"更新 {cases['updated']} 条，"
        f"字节内容不变 {cases['unchanged']} 条。更新中输入语义变化 {input_count} 条，"
        f"断言语义变化 {oracle_count} 条；两者可重叠。"
        f"另 {rebound_only} 条输入与断言语义均不变，"
        "只涉及来源重绑定或其他元数据变化，不能视作新增行为覆盖。",
        "",
        "保留原 70 条工具与 19 条模块源码候选。旧 1 条粗粒度端到端行为候选被替换为 "
        "31 条显式契约候选：13 条 SDK 端到端、2 条输入拒绝、12 条共享调用与错误处理、"
        "4 条观测与恢复状态。新声明涵盖 9 类终止分支。其余记录变动来自 Schema、"
        "静态声明和阻塞义务更新；完整逐条差异见 JSON。",
        "",
        "## 阻塞清单",
        "",
        "| 分类 | 数量 | 含义 |",
        "|---|---:|---|",
        f"| 保留 | {blockers['retained']} | 同一未解决义务，来源位置或 Hash 可变化 |",
        f"| 收窄 | {blockers['narrowed']} | 补充共享语义，仍存在明确剩余缺口 |",
        f"| 显式解除 | {blockers['resolved']} | 只表示来源明确补齐，不代表执行通过 |",
        f"| 新增 | {blockers['added']} | 新契约暴露的观察器或运行绑定依赖 |",
        f"| 被细化分支替代 | {blockers['superseded']} | 旧占位由明确分支描述替换 |",
        f"| 无依据消失 | {blockers['unverified_removals']} | 必须为零才允许发布 |",
        "",
        "21 个工具的结果与重试共 42 项缺口收窄：共享调度行为已明确，逐工具成功 Schema、"
        "稳定业务错误码、内部重试等仍未补齐。"
        "原对话内部模块冲突收窄为配置 MCP 时的条件路径冲突。"
        "旧 normal/error/early_stop 占位被细化分支替代，不代表路径已运行。",
        "",
        "## 仍不能推断",
        "",
        "关键链路定义、真实运行证据、业务验收基准、隔离执行夹具和异常观察器仍需补齐。"
        "未推断业务成功、权限/确认结果、事务回滚、幂等、批量行为或工具内部重试。"
        "所有记录 DRAFT / NOT_RUN / PENDING；兼容当前 EvalCase 的数量仍为 0。",
        "",
        "- [完整逐条差异](reports/contract_delta.json)",
        "- [可移动差异基线](reports/previous_baseline.json)",
        "- [当前阻塞清单](blockers.json)",
        "- [生成约束](GENERATION_CONSTRAINTS.md)",
        "",
    ]
    return "\n".join(lines)
