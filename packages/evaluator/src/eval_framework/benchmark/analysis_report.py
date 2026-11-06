"""新增分析报告；不修改既有 results.json、summary 或 report。"""

from __future__ import annotations

import html
import json
from pathlib import Path

from capability_snapshot_kit.hashing import sha256_json
from eval_contracts.benchmark_analysis import AnalysisPolicy

from ..aggregator.analysis import analyze_run
from ..aggregator.experiment import validate_experiment
from .analysis_sources import load_analysis_source
from .datasets.annotations import load_annotations
from .datasets.binding import build_dataset_binding
from .datasets.loader import load_dataset


def _sections(analysis: dict):
    sections = []
    sections.append(
        (
            "分层结果",
            ["执行层", "计划", "完成", "有效", "缺失", "PASS / 计划"],
            [
                [
                    layer,
                    *(
                        values[k]
                        for k in (
                            "planned_trials",
                            "completed_trials",
                            "valid_trials",
                            "missing_trials",
                            "pass_rate_planned",
                        )
                    ),
                ]
                for layer, values in analysis.get("layers", {}).items()
            ],
        )
    )
    sections.append(
        (
            "pass^k 一致性",
            ["执行层", "k", "任务 micro", "任务族 macro", "状态", "重复协议"],
            [
                [
                    layer,
                    k,
                    value["micro"],
                    value["family_macro"],
                    value["status"],
                    data["repeat_protocol_status"],
                ]
                for layer, data in analysis.get("reliability", {})
                .get("by_layer", {})
                .items()
                for k, value in data["pass_hat_k"].items()
            ],
        )
    )
    cost_rows = []
    for layer, owners in analysis.get("efficiency", {}).get("by_layer", {}).items():
        for owner, fields in owners.items():
            for field, value in fields.items():
                if field == "latency_by_scope":
                    continue
                if value.get("status") == "mixed_scopes":
                    cost_rows.append(
                        [layer, owner, field, "mixed_scopes", "—", "—", "—", "—"]
                    )
                elif value["planned_count"]:
                    coverage = value["coverage"]
                    cost_rows.append(
                        [
                            layer,
                            owner,
                            field,
                            f"{coverage['known_trials']}/{coverage['planned_trials']}",
                            f"{coverage['complete_tasks']}/{coverage['planned_tasks']}",
                            value["known_subtotal"],
                            value["successful_mean"],
                            value["per_success"],
                        ]
                    )
    sections.append(
        (
            "用量、效率与输出长度",
            [
                "执行层",
                "角色",
                "指标",
                "已知 trial / 计划 trial",
                "完整任务覆盖率",
                "已知小计",
                "成功试次均值",
                "全部尝试 / 成功数",
            ],
            cost_rows,
        )
    )
    sections.append(
        (
            "注释覆盖（仅 reviewed 入桶）",
            ["执行层", "计划任务", "已审", "未审/未标注", "已审难度未知"],
            [
                [
                    layer,
                    *(
                        value[k]
                        for k in (
                            "planned_tasks",
                            "reviewed_tasks",
                            "unlabeled_tasks",
                            "unknown_difficulty_tasks",
                        )
                    ),
                ]
                for layer, value in analysis.get("buckets", {}).items()
            ],
        )
    )
    sections.append(
        (
            "能力与难度桶（桶间不可加总）",
            ["执行层", "维度", "标签", "计划试次", "有效试次", "PASS / 计划"],
            [
                [
                    layer,
                    dimension,
                    label,
                    value["planned_trials"],
                    value["valid_trials"],
                    value["pass_rate_planned"],
                ]
                for layer, data in analysis.get("buckets", {}).items()
                for dimension in ("capabilities", "difficulty")
                for label, value in data[dimension].items()
            ],
        )
    )
    sections.append(
        (
            "失败归因",
            ["类型", "数量"],
            list(analysis.get("failures", {}).get("by_type", {}).items()),
        )
    )
    sections.append(
        (
            "Judge 覆盖（状态可重叠，独立计划分母）",
            ["指标", "数量"],
            list(analysis.get("judge_coverage", {}).items()),
        )
    )
    comparison = analysis.get("comparison", {})
    if comparison:
        sections.append(
            (
                "基线分层结果（独立分母）",
                [
                    "执行层",
                    "范围",
                    "计划试次",
                    "有效试次",
                    "PASS / 计划",
                    "PASS / 有效",
                ],
                [
                    [
                        layer,
                        comparison["baseline"]["scope"],
                        data["planned_trials"],
                        data["valid_trials"],
                        data["pass_rate_planned"],
                        data["pass_rate_valid"],
                    ]
                    for layer, data in comparison.get("baseline", {})
                    .get("layers", {})
                    .items()
                ],
            )
        )
        sections.append(
            (
                "对比资格：" + comparison["comparison_kind"],
                ["字段", "分类", "基线摘要", "候选摘要"],
                [
                    [
                        row["field"],
                        row["classification"],
                        row["baseline_sha256"],
                        row["candidate_sha256"],
                    ]
                    for row in comparison["differences"]
                ],
            )
        )
        sections.append(
            (
                "对比限制",
                ["项目", "值"],
                [
                    ["状态", comparison["status"]],
                    ["控制项差异", comparison["mismatches"]],
                    ["缺失控制项", comparison["unknown_controls"]],
                    ["新增执行", 0],
                ],
            )
        )
    sections.append(
        (
            "逐试次证据",
            ["任务", "试次", "执行层", "判定", "归因域", "主因", "证据 JSON Pointer"],
            [
                [
                    row.get("case_id"),
                    row.get("trial"),
                    row.get("layer"),
                    row.get("verdict"),
                    row.get("failure", {}).get("domain"),
                    row.get("failure", {}).get("primary"),
                    row.get("failure", {}).get("evidence_refs", []),
                ]
                for row in analysis.get("trials", [])
            ],
        )
    )
    return sections


def _text(value):
    if value is None:
        return "—"
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(round(value, 6)) if isinstance(value, float) else str(value)


def render_markdown(analysis: dict) -> str:
    def cell(value):
        text = html.escape(_text(value)).replace("\\", "\\\\").replace("\n", " ")
        for symbol in "|[]*_`!":
            text = text.replace(symbol, "\\" + symbol)
        return text

    lines = ["# Benchmark 本地分析", "", "范围：" + cell(analysis.get("scope")), ""]
    for title, headers, rows in _sections(analysis):
        lines += [
            "## " + title,
            "",
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join(["---"] * len(headers)) + " |",
        ]
        lines.extend("| " + " | ".join(map(cell, row)) + " |" for row in rows)
        lines.append("")
    lines += ["未知用量显示 —，不能解释为 0；已知小计不代表总体总量。", ""]
    lines += analysis.get("limitations", [])
    lines += [
        "",
        "## 复现本分析",
        "",
        "将占位符指向本地资产；使用新的输出目录。",
        "",
        "```sh",
        analysis.get("reproduce_analysis", ""),
        "```",
        "",
    ]
    return "\n".join(lines)


def render_html(analysis: dict) -> str:
    def escape(value):
        return html.escape(_text(value))

    sections = []
    for title, headers, rows in _sections(analysis):
        sections.append(
            "<section><h2>"
            + escape(title)
            + "</h2><div class='scroll'><table><thead><tr>"
            + "".join("<th>" + escape(h) + "</th>" for h in headers)
            + "</tr></thead><tbody>"
            + "".join(
                "<tr>" + "".join("<td>" + escape(v) + "</td>" for v in row) + "</tr>"
                for row in rows
            )
            + "</tbody></table></div></section>"
        )
    return (
        "<!doctype html><html lang='zh-CN'><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Benchmark 本地分析</title><style>"
        "body{font:15px system-ui;max-width:1250px;margin:40px auto;padding:0 24px;"
        "color:#192b36;background:#fcfdfd}h1{font-size:32px}h2{font-size:21px}"
        "section{margin:36px 0}.scroll{overflow-x:auto}table{border-collapse:collapse;"
        "width:100%}td,th{padding:10px;text-align:left;border-bottom:1px solid #dde4e8;"
        "overflow-wrap:anywhere;min-width:65px}th{background:#edf3f5}"
        "pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#edf3f5;padding:20px}"
        ".note{border-left:4px solid #2e7581;padding:12px 18px;background:#edf6f5}"
        "</style><h1>Benchmark 本地分析</h1><p class='note'>范围："
        + escape(analysis.get("scope"))
        + " · 四层独立统计 · 保存证据分析 · 不运行模型</p>"
        + "".join(sections)
        + "<p>未知用量显示 —，不能解释为 0；已知小计不代表总体总量。</p><ul>"
        + "".join("<li>" + escape(v) + "</li>" for v in analysis.get("limitations", []))
        + "</ul><h2>复现本分析</h2><p>将占位符指向本地资产；使用新的输出目录。</p><pre>"
        + escape(analysis.get("reproduce_analysis", ""))
        + "</pre><details><summary>完整统计与来源摘要</summary><pre>"
        + html.escape(json.dumps(analysis, ensure_ascii=False, indent=2))
        + "</pre></details></html>"
    )


def write_analysis(
    run_dir: Path,
    *,
    dataset_path: Path | None = None,
    annotations_path: Path | None = None,
    output: Path,
    policy: AnalysisPolicy,
    source_artifacts: tuple[Path, ...] = (),
    judge_dir: Path | None = None,
    compare_with: Path | None = None,
    experiment_spec: dict | None = None,
    comparison_dataset_path: Path | None = None,
) -> dict[str, Path]:
    output = Path(output).resolve()
    inputs = [Path(run_dir), *map(Path, source_artifacts)] + (
        [Path(judge_dir)] if judge_dir else []
    )
    if compare_with:
        inputs.append(Path(compare_with))
    if (
        experiment_spec is not None or comparison_dataset_path is not None
    ) and compare_with is None:
        raise ValueError("ExperimentSpec requires --compare-with")
    if output.exists() or any(
        output.is_relative_to((p if p.is_dir() else p.parent).resolve()) for p in inputs
    ):
        raise ValueError(
            "analysis output must be a new directory outside source evidence"
        )
    if dataset_path is None:
        raise ValueError("explicit dataset path required to verify planned population")
    source = load_analysis_source(
        run_dir,
        source_artifacts=(
            *source_artifacts,
            *((compare_with,) if compare_with else ()),
        ),
        judge_dir=judge_dir,
    )
    dataset = load_dataset(dataset_path)
    binding = build_dataset_binding(dataset_path)
    dataset.update(binding)
    annotations = (
        load_annotations(
            annotations_path,
            dataset_binding=binding,
            case_ids={t["id"] for t in dataset["tasks"]},
        )
        if annotations_path is not None
        else None
    )
    analysis = analyze_run(
        source, dataset=dataset, annotations=annotations, policy=policy
    )
    command = (
        'python -m agent_eval_suite benchmark analyze --run "$RUN_DIR" '
        '--dataset "$DATASET_DIR" --output "$NEW_OUTPUT_DIR" --k '
        + " ".join(map(str, policy.ks))
    )
    for flag, present in (
        ("annotations", annotations_path),
        ("judge-source", judge_dir),
        ("repeat-protocol", policy.repeat_protocol),
        ("compare-with", compare_with),
        ("experiment-spec", experiment_spec),
        ("comparison-dataset", comparison_dataset_path),
    ):
        if present is not None:
            command += f' --{flag} "${flag.upper().replace("-", "_")}"'
    source_hashes = set(source["verified_source_hashes"])
    if compare_with is not None:
        baseline = load_analysis_source(
            compare_with, source_artifacts=(*source_artifacts, run_dir)
        )
        analysis["comparison"] = validate_experiment(
            baseline["selected_result"], source["selected_result"], experiment_spec
        )
        baseline_dataset = load_dataset(comparison_dataset_path or dataset_path)
        baseline_binding = build_dataset_binding(
            comparison_dataset_path or dataset_path
        )
        baseline_dataset.update(baseline_binding)
        if (
            baseline["execution_result"]["identity"]["dataset"]
            != baseline_dataset["legacy_identity"]
        ):
            raise ValueError("baseline dataset differs; provide --comparison-dataset")
        baseline_analysis = analyze_run(
            baseline,
            dataset=baseline_dataset,
            annotations=annotations if baseline_binding == binding else None,
            policy=policy,
        )
        analysis["comparison"]["baseline"] = {
            k: baseline_analysis[k]
            for k in (
                "scope",
                "execution_run_id",
                "execution_identity_hash",
                "layers",
                "reliability",
                "efficiency",
                "buckets",
            )
        }
        analysis["identity"]["comparison_analysis_identity_hash"] = baseline_analysis[
            "identity_hash"
        ]
        analysis["identity"]["comparison_source_hashes"] = baseline[
            "verified_source_hashes"
        ]
        analysis["identity"]["comparison_selected_sha256"] = baseline["selected_sha256"]
        analysis["identity"]["experiment_spec_sha256"] = analysis["comparison"][
            "experiment_spec_sha256"
        ]
        analysis["identity_hash"] = sha256_json(analysis["identity"])
        source_hashes.update(baseline["verified_source_hashes"])
    # 列出内容摘要占位符，不复制本地路径；未使用的输入不改变报告。
    for digest in sorted(source_hashes - {source["selected_sha256"]}):
        command += f' --source-artifact "$SOURCE_{digest}"'
    analysis["reproduce_analysis"] = command
    encoded = (
        json.dumps(
            analysis, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
        )
        + "\n"
    )
    payloads = {
        "json": ("analysis.json", encoded),
        "markdown": ("analysis.md", render_markdown(analysis)),
        "html": ("analysis.html", render_html(analysis)),
        "provenance": (
            "provenance.json",
            json.dumps(
                {
                    "analysis_identity_hash": analysis["identity_hash"],
                    "content_sha256": sha256_json(analysis),
                    "verified_source_hashes": sorted(source_hashes),
                },
                sort_keys=True,
                indent=2,
            )
            + "\n",
        ),
    }
    output.mkdir(parents=True, exist_ok=False)
    for filename, text in payloads.values():
        (output / filename).write_text(text, encoding="utf-8")
    return {key: output / filename for key, (filename, _) in payloads.items()}
