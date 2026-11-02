#!/usr/bin/env python3
"""核对冻结任务、原始结果和覆盖来源，生成不含完整提示的公开组件摘要。

只读取已保存证据；不执行 nanobot、模型、Inspect 或上传。历史结果只绑定
原始身份/Hash，不在当前评分版本下重评分、不升级为当前 profile 的覆盖。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VERSION = "nanobot-coverage-public-report-v1"
DISPUTED_CASE = "core-session_legal_replay-orphan"
VERDICTS = {"PASS", "FAIL", "INVALID", "INCONCLUSIVE"}


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict:
    def reject_constant(value):
        raise ValueError(f"Nonfinite JSON: {value}")

    result = json.loads(path.read_bytes(), parse_constant=reject_constant)
    if not isinstance(result, dict):
        raise ValueError("Evidence file must contain a JSON object")
    return result


def portable_name(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[A-Za-z0-9_.:-]+", value))


def reject_private_paths(value: Any) -> None:
    """Fail closed, rather than redact bytes that participate in identity hashes."""
    if isinstance(value, dict):
        for key, item in value.items():
            reject_private_paths(key)
            reject_private_paths(item)
    elif isinstance(value, list):
        for item in value:
            reject_private_paths(item)
    elif isinstance(value, str):
        if (
            re.search(r"(?:^|[\s\"'(=])/(?:[^\s/]+)", value)
            or re.search(r"(?:^|[\s\"'(=])[A-Za-z]:[\\/]", value)
            or "file://" in value
            or "~/" in value
        ):
            raise ValueError("Public output contains an absolute/private path")


def aggregate_trials(
    rows: list[dict],
    tasks: list[dict],
    planned: list[str],
    repeats: int,
    identity_hash: str,
) -> dict:
    """Recompute denominators from raw trials; saved summary is not authority."""
    by_id = {task["id"]: task for task in tasks}
    if (
        type(repeats) is not int
        or repeats < 1
        or not isinstance(planned, list)
        or not planned
        or len(set(planned)) != len(planned)
        or any(case not in by_id for case in planned)
    ):
        raise ValueError("Invalid planned cases/repeats")
    if any(by_id[case]["split"] != "dev" for case in planned):
        raise ValueError("Reserved holdout must not be executed in this report")
    if not isinstance(rows, list):
        raise ValueError("Trials must be a list")
    seen, public_rows = set(), []
    for row in rows:
        case, trial = row.get("case_id"), row.get("trial")
        if (
            case not in planned
            or type(trial) is not int
            or not 1 <= trial <= repeats
            or (case, trial) in seen
        ):
            raise ValueError("Duplicate, unplanned or invalid trial")
        seen.add((case, trial))
        if row.get("identity_hash") != identity_hash:
            raise ValueError("Trial identity mismatch")
        task = by_id[case]
        if any(row.get(k) != task[k] for k in ("component", "family", "split")):
            raise ValueError("Trial task metadata mismatch")
        assessment = row.get("assessment", {})
        verdict, validity = assessment.get("verdict"), assessment.get("validity")
        if verdict not in VERDICTS or validity != (
            "VALID" if verdict in {"PASS", "FAIL"} else verdict
        ):
            raise ValueError("Invalid verdict/validity pair")
        latency = row.get("latency_seconds")
        if (
            type(latency) not in (int, float)
            or not math.isfinite(latency)
            or latency < 0
        ):
            raise ValueError("Invalid trial latency")
        if not all(portable_name(task[k]) for k in ("id", "family", "component")):
            raise ValueError("Nonportable task identifier")
        public_rows.append(
            {
                "case_id": case,
                "trial": trial,
                "component": task["component"],
                "family": task["family"],
                "split": task["split"],
                "verdict": verdict,
                "validity": validity,
                "latency_seconds": latency,
                "raw_row_sha256": digest(row),
                "oracle_status": (
                    "requires_requirement_review"
                    if case == DISPUTED_CASE
                    else "machine_scored_human_review_pending"
                ),
            }
        )
    public_rows.sort(key=lambda row: (planned.index(row["case_id"]), row["trial"]))

    def counts(cases):
        chosen = [row for row in public_rows if row["case_id"] in cases]
        verdicts = Counter(row["verdict"] for row in chosen)
        valid = sum(row["validity"] == "VALID" for row in chosen)
        planned_count = len(cases) * repeats
        return {
            "planned_cases": len(cases),
            "trials_per_case": repeats,
            "planned_trials": planned_count,
            "observed_trials": len(chosen),
            "missing_trials": planned_count - len(chosen),
            "valid_trials": valid,
            "verdict_counts": {key: verdicts[key] for key in sorted(VERDICTS)},
            "pass_rate_planned": verdicts["PASS"] / planned_count
            if planned_count
            else None,
            "pass_rate_valid": verdicts["PASS"] / valid if valid else None,
            "latency_seconds_total": sum(row["latency_seconds"] for row in chosen),
        }

    cases = []
    for case in planned:
        chosen = [row for row in public_rows if row["case_id"] == case]
        complete = len(chosen) == repeats
        cases.append(
            {
                "case_id": case,
                "component": by_id[case]["component"],
                "expected_trials": repeats,
                "observed_trials": len(chosen),
                "complete": complete,
                "all_trials_valid": complete
                and all(row["validity"] == "VALID" for row in chosen),
                "verdict_consistent": complete
                and len({row["verdict"] for row in chosen}) == 1,
                "all_trials_passed": complete
                and all(row["verdict"] == "PASS" for row in chosen),
                "verdict_counts": dict(Counter(row["verdict"] for row in chosen)),
            }
        )
    summary = counts(planned)
    summary["consistency"] = {
        "planned_cases": len(cases),
        "repeats": repeats,
        "complete_cases": sum(case["complete"] for case in cases),
        "consistent_verdict_cases": sum(case["verdict_consistent"] for case in cases),
        "consistent_valid_cases": sum(
            case["verdict_consistent"] and case["all_trials_valid"] for case in cases
        ),
        "all_repeats_passed_cases": sum(case["all_trials_passed"] for case in cases),
        "scope": "相同输入的组件判定重复性；一致失败不等于通过，也不代表LLM稳定性",
    }
    components = {}
    for component in sorted({by_id[case]["component"] for case in planned}):
        selected = [case for case in planned if by_id[case]["component"] == component]
        components[component] = counts(selected)
        components[component]["all_repeats_passed_cases"] = sum(
            case["all_trials_passed"]
            for case in cases
            if case["component"] == component
        )
    return {
        "trials": public_rows,
        "cases": cases,
        "summary": summary,
        "components": components,
    }


def verified_artifacts(
    run_path: Path,
    coverage_path: Path,
    dataset: Path,
    *,
    file_datasets: list[Path],
    legacy_runs: list[Path],
    catalog_path: Path,
) -> dict:
    """Bind every supplied dataset/run source, then rebuild the full matrix."""
    os.environ["DEEPEVAL_TELEMETRY_OPT_OUT"] = "YES"
    sys.path.insert(0, str(ROOT / "packages/evaluator/src"))
    from eval_framework.benchmark.capability_coverage import build_coverage_report
    from eval_framework.benchmark.core_scoring import score_core_task
    from eval_framework.benchmark.core_tasks import (
        core_dataset_identity,
        load_core_tasks,
    )
    from eval_framework.benchmark.tasks import dataset_identity

    run_file = run_path / "results.json" if run_path.is_dir() else run_path
    coverage_file = (
        coverage_path / "coverage.json" if coverage_path.is_dir() else coverage_path
    )
    run, coverage = read_json(run_file), read_json(coverage_file)
    snapshot_file = coverage_file.parent / "snapshot.json"
    snapshot = read_json(snapshot_file)
    if read_json(run_file.parent / "snapshot.json") != snapshot:
        raise ValueError("Run and coverage snapshots differ")
    identity = run.get("identity")
    if not isinstance(identity, dict) or run.get("identity_hash") != digest(identity):
        raise ValueError("Run identity hash mismatch")
    data_identity = core_dataset_identity(dataset)
    if identity.get("dataset") != data_identity:
        raise ValueError("Run does not bind the supplied frozen core dataset")
    controls = identity.get("controls", {})
    if controls.get("split") != "dev" or controls.get("model_calls") != 0:
        raise ValueError("Run is not an offline dev component run")
    tasks = load_core_tasks(dataset)
    planned, repeats = run.get("planned_case_ids"), run.get("trials_per_case")
    if not isinstance(planned, list) or set(planned) != {
        t["id"] for t in tasks if t["split"] == "dev"
    }:
        raise ValueError("Run must plan the complete dev population")
    if controls.get("repeats") != repeats:
        raise ValueError("Repeat count differs from bound controls")
    run_id = run.get("run_id")
    if not portable_name(run_id):
        raise ValueError("Run identifier is not portable")
    meta = read_json(run_file.parent / "run.json")
    if any(run.get(key) != value for key, value in meta.items()):
        raise ValueError("Run metadata conflicts with results")

    descriptors = [
        {
            "path": dataset,
            "kind": "core",
            "identity": data_identity,
            "identity_hash": digest(data_identity),
            "profile": "core_modules",
        }
    ]
    for path in file_datasets:
        identity_value = dataset_identity(path)
        descriptors.append(
            {
                "path": path,
                "kind": "file_tools",
                "identity": identity_value,
                "identity_hash": digest(identity_value),
                "profile": "file_tools",
            }
        )
    run_descriptors = [
        {"path": run_file, "kind": "current", "sha256": file_hash(run_file)}
    ]
    for path in legacy_runs:
        source = path / "results.json" if path.is_dir() else path
        run_descriptors.append(
            {"path": source, "kind": "legacy", "sha256": file_hash(source)}
        )
    rebuilt = build_coverage_report(
        snapshot, read_json(catalog_path), descriptors, run_descriptors
    )
    if rebuilt != coverage:
        raise ValueError("Coverage differs from fully rebuilt bound source evidence")
    current = coverage["current_runs"]
    if (
        len(current) != 1
        or current[0]["source_sha256"] != file_hash(run_file)
        or current[0]["run_id"] != run_id
    ):
        raise ValueError("Coverage current source does not bind the exact raw results")

    rows = run["trials"]
    aggregation = aggregate_trials(rows, tasks, planned, repeats, run["identity_hash"])
    by_id = {task["id"]: task for task in tasks}
    raw_by_key = {(row["case_id"], row["trial"]): row for row in rows}
    for public_row in aggregation["trials"]:
        key = (public_row["case_id"], public_row["trial"])
        raw_row = raw_by_key[key]
        observation = raw_row["observation"]
        if (
            observation.get("usage") != {}
            or observation.get("execution_backend") != "inspect_ai"
        ):
            raise ValueError("Core trial is not a zero-model Inspect execution")
        scored = score_core_task(by_id[key[0]], observation)
        if scored != raw_row["assessment"]:
            raise ValueError(
                "Full saved assessment differs from deterministic rescoring"
            )
        filename = f"{planned.index(key[0]):04d}-t{key[1]}.json"
        trial_file = run_file.parent / "trials" / filename
        if read_json(trial_file) != raw_row:
            raise ValueError("Original trial file differs from the results row")
        public_row["raw_trial_file_sha256"] = file_hash(trial_file)
        public_row["raw_trial_file"] = "trials/" + filename

    saved = run.get("summary", {})
    computed = aggregation["summary"]
    for key in (
        "planned_cases",
        "trials_per_case",
        "planned_trials",
        "observed_trials",
        "missing_trials",
        "valid_trials",
    ):
        if saved.get(key) != computed[key]:
            raise ValueError("Saved summary denominator mismatch")
    if Counter(saved.get("verdict_counts", {})) != Counter(computed["verdict_counts"]):
        raise ValueError("Saved summary verdict mismatch")
    if saved.get("model_calls") != 0 or saved.get("human_reviewed_cases") != 0:
        raise ValueError("Unverified model/review status")

    legacy = coverage["legacy_runs"]
    summary = {
        "version": VERSION,
        "run_id": run_id,
        "started_at": run.get("started_at"),
        "finished_at": run.get("finished_at"),
        "identity": identity,
        "identity_hash": run["identity_hash"],
        "dataset": data_identity,
        "source_state": {
            key: snapshot["source"][key]
            for key in ("commit", "dirty", "working_tree_sha256")
        },
        **aggregation,
        "holdout": {
            "defined_cases": sum(t["split"] == "holdout" for t in tasks),
            "executed_trials": 0,
            "status": "reserved_schema_validated_only",
            "independently_human_reviewed": False,
        },
        "model_calls": 0,
        "human_reviewed_cases": 0,
        "human_labels": 0,
        "legacy": {
            "runs": legacy,
            "observed_trials": sum(row["observed_trials"] for row in legacy),
            "scoring": "saved_historical_verdicts_not_rescored",
            "binds_current_profile": False,
        },
        "oracle_disputes": [
            {
                "case_id": DISPUTED_CASE,
                "status": "requires_requirement_review",
                "explanation": (
                    "冻结Oracle要求保留孤立tool之前的user；"
                    "当前合法后缀策略丢弃此前缀。原FAIL保留，"
                    "不能直接归因为产品缺陷。"
                ),
            }
        ]
        if DISPUTED_CASE in planned
        else [],
        "sources": {
            "results_raw_sha256": file_hash(run_file),
            "run_metadata_raw_sha256": file_hash(run_file.parent / "run.json"),
            "snapshot_raw_sha256": file_hash(snapshot_file),
            "coverage_raw_sha256": file_hash(coverage_file),
            "catalog_raw_sha256": file_hash(catalog_path),
            "dataset_bytes_sha256": data_identity["sha256"],
            "row_hash_algorithm": (
                "SHA256(canonical JSON: UTF-8,ensure_ascii=false,"
                "sort_keys=true,separators=(',',':'),allow_nan=false)"
            ),
            "trial_file_hash_algorithm": "SHA256(original trial JSON file bytes)",
        },
        "limitations": [
            "仅固定配置和源码下的真实组件行为；不代表模型或完整Agent成功率。",
            "新对象重载不等于进程重启；审计护栏不是OS级恶意代码沙箱。",
            "当前组件与历史文件/决策任务分开统计，不计算nanobot整体覆盖率。",
            "holdout未执行，独立人工设计审核与标签均未完成。",
        ],
    }
    # These documents are already portable identities. Never copy observations,
    # prompts, event bodies, file contents, input envelopes or private oracles.
    for document in (summary, snapshot, coverage):
        reject_private_paths(document)
    return {
        "summary.json": summary,
        "snapshot.json": snapshot,
        "coverage.json": coverage,
    }


def render_readme(summary: dict, coverage: dict) -> str:
    counts = summary["summary"]
    verdicts = counts["verdict_counts"]
    consistency = counts["consistency"]
    lines = [
        "# nanobot 能力覆盖：已保存证据的公开摘要",
        "",
        f"本轮 {counts['planned_cases']} 个 dev 任务，"
        f"计划每条 {counts['trials_per_case']} 次；"
        f"观察到 {counts['observed_trials']}/{counts['planned_trials']} 个 trial。"
        f"PASS {verdicts['PASS']}、FAIL {verdicts['FAIL']}、"
        f"INVALID {verdicts['INVALID']}、INCONCLUSIVE {verdicts['INCONCLUSIVE']}，"
        f"缺失 {counts['missing_trials']}。",
        "",
        "这些是固定源码与配置下的真实组件调用，不是模型或完整 Agent 成绩。"
        "当前 trial 通过完整确定性重评分；历史结果仅核对原始来源/身份，"
        "不用当前评分版本重算。",
        "",
        "| 组件 | 计划任务 | 观察/计划 trial | PASS | FAIL | INVALID | "
        "INCONCLUSIVE | 全部重复通过任务 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, item in summary["components"].items():
        v = item["verdict_counts"]
        lines.append(
            f"| {name} | {item['planned_cases']} | "
            f"{item['observed_trials']}/{item['planned_trials']} | "
            f"{v['PASS']} | {v['FAIL']} | {v['INVALID']} | "
            f"{v['INCONCLUSIVE']} | {item['all_repeats_passed_cases']} |"
        )
    lines.extend(
        [
            "",
            f"{consistency['complete_cases']}/{consistency['planned_cases']} "
            "个任务重复记录齐全；"
            f"{consistency['consistent_verdict_cases']} 个判定一致，"
            f"{consistency['all_repeats_passed_cases']} 个全部重复通过。"
            "一致失败不等于通过，这也不证明 LLM 稳定性。",
            "",
            f"当前 0 次模型调用；{summary['holdout']['defined_cases']} "
            "条 reserved holdout "
            "仅做合同/Hash 校验、未执行；独立人工审核与人工标签均未完成。",
            "",
            "`core-session_legal_replay-orphan` 保留原始失败和冻结 Oracle。"
            "其要求保留孤立 tool 之前的 user 消息，而当前实现采用合法后缀策略；"
            "这是需求/Oracle 待裁定项，不能直接称为产品缺陷。",
            "",
            "被测源码为 dirty 工作树；commit 不能单独重建本次源码，"
            "须核对 snapshot 的逐文件与 working_tree Hash。"
            if summary.get("source_state", {}).get("dirty")
            else "源码身份以 snapshot 中 commit、dirty 与实际文件 Hash 共同确定。",
            "公开产物仅保留源码 Hash，不复制外部 nanobot 源码；"
            "本轮不构成完整产品验收。",
            "",
            "## 历史来源单列",
            "",
            f"绑定 {len(summary['legacy']['runs'])} 个历史运行，共 "
            f"{summary['legacy']['observed_trials']} 条历史 trial。"
            "这些记录保留原有版本和分母，不与本轮组件 trial 相加，"
            "不升级当前 File Tools profile 覆盖。",
            "",
            "| 历史运行 | 观察/计划 trial | 原始结果 SHA256 |",
            "|---|---:|---|",
        ]
    )
    for row in summary["legacy"]["runs"]:
        lines.append(
            f"| {row['run_id']} | {row['observed_trials']}/{row['planned_trials']} | "
            f"`{row['source_sha256']}` |"
        )
    # Use only the already verified matrix. Legacy executions are deliberately
    # absent from current profile split counts and must never be added here.
    domains = {}
    for row in coverage["matrix"]:
        if row["profile"] not in {"file_tools", "core_modules"}:
            continue
        domain = domains.setdefault(
            row["capability"],
            {"title": row["title"], "priority": row["priority"], "profiles": {}},
        )
        splits = list(row["splits"].values())
        domain["profiles"][row["profile"]] = {
            "defined": sum(split["defined_cases"] for split in splits),
            "executed": sum(split["executed_trials"] for split in splits),
        }
    lines.extend(
        [
            "",
            f"## {len(domains)} 个能力域的当前覆盖边界",
            "",
            "定义数以 case 为单位，包含已定义但未执行的 holdout；"
            "执行数以当前 profile 下证据完整的 trial 为单位，包含 FAIL，"
            "不等于通过数。源码存在或被其他组件间接调用，不自动增加任务数。",
            "历史运行仅见上节；不得填入下表的当前执行数。"
            "本表是有限 catalog 的逐域清单，不计算 nanobot 整体覆盖率。",
            "",
            "| 能力域 | File Tools 定义 case | File Tools 当前执行 trial | "
            "Core 定义 case | Core 当前执行 trial | 优先级 |",
            "|---|---:|---:|---:|---:|---|",
        ]
    )
    for domain in domains.values():
        file_tools = domain["profiles"]["file_tools"]
        core = domain["profiles"]["core_modules"]
        lines.append(
            f"| {domain['title']} | {file_tools['defined']} | "
            f"{file_tools['executed']} | {core['defined']} | "
            f"{core['executed']} | {domain['priority']} |"
        )
    lines.extend(["", "### 尚无独立绑定任务的能力域", ""])
    pending = [
        domain
        for domain in domains.values()
        if not any(profile["defined"] for profile in domain["profiles"].values())
    ]
    for priority in sorted({domain["priority"] for domain in pending}):
        names = "、".join(
            domain["title"] for domain in pending if domain["priority"] == priority
        )
        lines.append(f"- **{priority}**：{names}。")
    if not pending:
        lines.append("当前 catalog 的每个能力域已有绑定任务；这不代表场景穷尽或通过。")
    core_holdout = [
        row["splits"].get("holdout", {})
        for row in coverage["matrix"]
        if row["profile"] == "core_modules"
    ]
    held_cases = sum(split.get("defined_cases", 0) for split in core_holdout)
    held_trials = sum(split.get("executed_trials", 0) for split in core_holdout)
    lines.extend(
        [
            "",
            "### 待裁定与未执行项",
            "",
            "- **Oracle 人工裁定**：确认 `core-session_legal_replay-orphan` "
            "应采用保留前缀还是合法后缀语义；保留原 FAIL，不直接称为产品缺陷。",
            f"- **核心 holdout**：定义 {held_cases} 条，执行 {held_trials} 个 trial；"
            "本轮仅校验合同与 Hash，未做执行验收或独立人工审核。",
        ]
    )
    lines.extend(
        [
            "",
            "## 复核",
            "",
            "- [summary.json](summary.json)：逐 trial 的 "
            "case/trial/verdict/validity/耗时、原始 row 与原始 trial 文件 Hash；"
            "含分母与重复一致性。",
            "- [snapshot.json](snapshot.json)：源码逐文件 Hash、"
            "解释器/依赖与有效 profile 身份。",
            "- [coverage.json](coverage.json)：源码存在、启用、场景定义、执行、"
            "通过及人工审核六种状态分开。",
            "- 原始 results.json 字节 SHA256："
            f"`{summary['sources']['results_raw_sha256']}`。",
            f"- 本轮 identity_hash：`{summary['identity_hash']}`。",
            "",
            "摘要未公开原始 observation、完整上下文、文件正文或本机绝对路径。"
            "在原工作区保留 raw results/trials 后，可按 summary 的原始 Hash 复核。"
            "生成命令见仓库 docs/benchmark/nanobot-coverage.md；"
            "使用相同输入再次生成得到相同字节，程序拒绝覆盖不同结果。",
            "",
        ]
    )
    return "\n".join(lines)


def write_artifacts(documents: dict, output: Path) -> None:
    assets = {
        name: (
            json.dumps(
                value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
            )
            + "\n"
        ).encode()
        for name, value in documents.items()
    }
    readme = render_readme(documents["summary.json"], documents["coverage.json"])
    reject_private_paths(readme)
    assets["README.md"] = readme.encode()
    # Validate every existing target before writing anything.
    for name, raw in assets.items():
        target = output / name
        if target.exists() and target.read_bytes() != raw:
            raise ValueError("Refusing to overwrite a different public report")
    output.mkdir(parents=True, exist_ok=True)
    for name, raw in assets.items():
        target = output / name
        if not target.exists():
            target.write_bytes(raw)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run", "coverage", "output", "dataset"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--file-dataset", type=Path, action="append", default=[])
    parser.add_argument("--legacy-run", type=Path, action="append", default=[])
    parser.add_argument(
        "--catalog", type=Path, default=ROOT / "data/coverage/nanobot-v1/catalog.json"
    )
    args = parser.parse_args()
    documents = verified_artifacts(
        args.run,
        args.coverage,
        args.dataset,
        file_datasets=args.file_dataset,
        legacy_runs=args.legacy_run,
        catalog_path=args.catalog,
    )
    write_artifacts(documents, args.output)
    print(json.dumps(documents["summary.json"]["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
