"""新增分析报告；不修改既有 results.json、summary 或 report。"""

from __future__ import annotations

import html
import json
from pathlib import Path

from capability_snapshot_kit.hashing import sha256_json
from eval_contracts.benchmark_analysis import AnalysisPolicy

from ..aggregator.analysis import analyze_run
from .analysis_sources import load_analysis_source
from .datasets.annotations import load_annotations
from .datasets.binding import build_dataset_binding
from .datasets.loader import load_dataset


def render_markdown(analysis: dict) -> str:
    lines = [
        "# Benchmark 本地分析",
        "",
        f"范围：{analysis.get('scope', 'unknown')}",
        "",
        "| 执行层 | 计划 | 完成 | 有效 | 缺失 | PASS / 计划 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for layer, values in analysis.get("layers", {}).items():
        lines.append(
            f"| {layer} | {values['planned_trials']} | "
            f"{values['completed_trials']} | {values['valid_trials']} | "
            f"{values['missing_trials']} | {values['pass_rate_planned']} |"
        )
    lines += [
        "",
        "## 失败与覆盖",
        "",
        "```json",
        json.dumps(
            {
                k: analysis.get(k)
                for k in ("failures", "judge_coverage", "availability")
            },
            ensure_ascii=False,
            indent=2,
        ),
        "```",
        "",
    ]
    lines += analysis.get("limitations", [])
    return "\n".join(lines) + "\n"


def render_html(analysis: dict) -> str:
    # 只展示白名单分析对象，不嵌入可执行脚本或外部资源。
    rows = "".join(
        "<tr>"
        + "".join(
            f"<td>{html.escape(str(v))}</td>"
            for v in (
                layer,
                data["planned_trials"],
                data["completed_trials"],
                data["valid_trials"],
                data["missing_trials"],
                data["pass_rate_planned"],
            )
        )
        + "</tr>"
        for layer, data in analysis.get("layers", {}).items()
    )
    return (
        "<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>Be"
        "nchmark 本地分析</title>"
        "<style>body{font:16px system-ui;max-width:1100px;margin:40px auto"
        ";padding:0 20px;color:#192b36}td,th{padding:10px;border-bottom:1p"
        "x solid #ccd}table{border-collapse:collapse;width:100%}pre{white-"
        "space:pre-wrap;overflow-wrap:anywhere;background:#f3f6f8;padding:"
        "20px}</style>"
        "<h1>Benchmark 本地分析</h1><p>四层独立统计；保存证据分析，不运行模型。</p>"
        "<table><tr><th>执行层</th><th>计划</th><th>完成</th><th>有效</th><th>缺失</t"
        "h><th>PASS / 计划</th></tr>" + rows + "</table>"
        "<h2>统计与逐项证据引用</h2><pre>"
        + html.escape(json.dumps(analysis, ensure_ascii=False, indent=2))
        + "</pre></html>"
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
) -> dict[str, Path]:
    output = Path(output).resolve()
    inputs = [Path(run_dir), *map(Path, source_artifacts)] + (
        [Path(judge_dir)] if judge_dir else []
    )
    if output.exists() or any(
        output.is_relative_to((p if p.is_dir() else p.parent).resolve()) for p in inputs
    ):
        raise ValueError(
            "analysis output must be a new directory outside source evidence"
        )
    if dataset_path is None:
        raise ValueError("explicit dataset path required to verify planned population")
    source = load_analysis_source(
        run_dir, source_artifacts=source_artifacts, judge_dir=judge_dir
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
                    "verified_source_hashes": source["verified_source_hashes"],
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
