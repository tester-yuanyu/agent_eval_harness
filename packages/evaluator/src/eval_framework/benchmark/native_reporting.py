"""Deliver saved evidence through Inspect's public, offline viewer API."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

from inspect_ai.log import bundle_log_dir, list_eval_logs, read_eval_log


def native_logs(run_dir: Path) -> list[Path]:
    """Only local logs belonging to this run directory are report inputs."""
    directory = run_dir.resolve() / "inspect"
    if not directory.is_dir():
        return []
    paths = []
    for log in list_eval_logs(str(directory)):
        uri = urlsplit(log.name)
        if uri.scheme not in {"", "file"} or uri.netloc not in {"", "localhost"}:
            raise ValueError("Inspect report inputs must be local files")
        paths.append(Path(unquote(uri.path)).resolve())
    if any(not path.is_relative_to(directory.resolve()) for path in paths):
        raise ValueError("Inspect log is outside the run directory")
    return sorted(paths)


def _log_source(path: Path, run_dir: Path) -> dict:
    return {
        "path": path.relative_to(run_dir.resolve()).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _validated_logs(run_dir: Path, run: dict) -> tuple[list[Path], list[dict]]:
    """Bind viewer logs to the exact result, excluding superseded retry attempts."""
    from .runner import digest

    identity = run.get("identity_hash")
    if not identity or identity != digest(run["identity"]):
        raise ValueError("Native report requires a valid run identity_hash")
    expected = {(row["case_id"], row["trial"]): row for row in run["trials"]}
    if len(expected) != len(run["trials"]):
        raise ValueError("Native report contains duplicate result records")
    strict = run["identity"].get("harness_version") == "file-harness-inspect-v3"
    selected, superseded, candidates, covered = [], [], [], set()
    for path in reversed(native_logs(run_dir)):
        log = read_eval_log(str(path))
        if (log.eval.metadata or {}).get("identity_hash") != identity:
            raise ValueError("Inspect log identity differs from the saved run")
        if not strict:
            # Historical logs contain a task identity but not embedded rows.
            selected.append(path)
            continue
        rows = []
        for sample in log.samples or []:
            for score in (sample.scores or {}).values():
                row = (score.metadata or {}).get("benchmark_record")
                if row is None:
                    continue
                if (
                    str(sample.id) != row.get("case_id")
                    or sample.epoch != row.get("trial")
                    or score.value != row.get("assessment", {}).get("verdict")
                ):
                    raise ValueError("Inspect sample or score differs from its record")
                rows.append(row)
        keys = set()
        matches = bool(rows)
        for row in rows:
            key = (row.get("case_id"), row.get("trial"))
            if row.get("identity_hash") != identity or key not in expected:
                raise ValueError("Inspect benchmark record has a foreign identity")
            if key in keys:
                raise ValueError("Inspect log contains duplicate benchmark records")
            keys.add(key)
            matches = matches and row == expected[key]
        if matches:
            candidates.append((path, keys))
        else:
            superseded.append({
                **_log_source(path, run_dir),
                "reason": "Superseded or overlapping attempt; final records elsewhere",
            })
    # A later interrupted retry may contain fewer rows than a complete log.
    # Prefer the widest exact record coverage, then the newest filename.
    for path, keys in sorted(
        candidates, key=lambda item: (len(item[1]), item[0].name), reverse=True
    ):
        if keys.intersection(covered):
            superseded.append({
                **_log_source(path, run_dir), "reason": "Overlapping saved attempt"
            })
        else:
            selected.append(path)
            covered.update(keys)
    if strict and covered != set(expected):
        raise ValueError("Inspect evidence does not cover the saved result records")
    if not selected:
        raise ValueError("No matching Inspect logs; use --format domain")
    return selected, superseded


def _stage_logs(logs: list[Path], directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for index, path in enumerate(logs):
        target = directory / str(index)
        target.mkdir()
        shutil.copyfile(path, target / path.name)


def write_native_report(run_dir: Path, *, summary: dict) -> Path:
    """Bundle native logs without re-executing or rescoring any sample."""
    logs = native_logs(run_dir)
    if not logs:
        raise ValueError("No saved Inspect logs; use --format domain for legacy runs")
    output = run_dir / "inspect-view"
    if output.is_symlink():
        raise ValueError("Inspect viewer output must not be a symbolic link")
    if output.exists() and not (output / "benchmark-source.json").is_file():
        raise ValueError("Inspect viewer output exists without a benchmark manifest")
    raw = (run_dir / "results.json").read_bytes()
    run = json.loads(raw)
    logs, superseded = _validated_logs(run_dir, run)
    # Absolute local paths cannot be interpreted as hf/<org>/<space> uploads.
    with tempfile.TemporaryDirectory(prefix="inspect-report-") as staging:
        _stage_logs(logs, Path(staging))
        bundle_log_dir(
            log_dir=staging, output_dir=str(output.resolve()),
            overwrite=output.exists(),
        )
    manifest = {
        "version": "inspect-native-report-v1",
        "viewer_backend": "inspect_ai",
        "run_id": run.get("run_id"),
        "results_sha256": hashlib.sha256(raw).hexdigest(),
        "logs": [_log_source(path, run_dir) for path in logs],
        "superseded_logs": superseded,
        "evidence_binding": "identity-and-records"
        if run["identity"].get("harness_version") == "file-harness-inspect-v3"
        else "legacy-identity-only",
        "domain_summary": summary,
        "note": "分层与缺失值统计来自保存结果；Inspect 负责通用轨迹和分数展示。",
    }
    (output / "benchmark-source.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (run_dir / "report.md").write_text(
        "# 评测结果\n\n"
        "[Inspect 原生查看器](inspect-view/index.html) · "
        "[来源与业务分层统计](inspect-view/benchmark-source.json) · "
        "[保存结果](results.json)\n\n"
        "查看器由 Inspect 生成。可在本地用 `inspect view --log-dir "
        + str((run_dir / "inspect").resolve())
        + "` 查看，或用静态 HTTP 服务打开 inspect-view。\n\n"
        "文件集同时包含模块、模型决策和 Agent 时，不将其合成单一模型成功率。"
        "报告不调用模型、不重评分、不上传。\n",
        encoding="utf-8",
    )
    return output / "index.html"


def write_comparison_report(
    baseline_dir: Path, candidate_dir: Path, output_dir: Path
) -> Path:
    """Use Inspect's multi-log viewer after checking business comparability."""
    from .report import evidence_summary
    from .runner import compare_runs

    directories = [Path(baseline_dir), Path(candidate_dir)]
    raw = [(directory / "results.json").read_bytes() for directory in directories]
    runs = [json.loads(value) for value in raw]
    summaries = [evidence_summary(run) for run in runs]
    comparison = compare_runs(*runs)
    bindings = [
        _validated_logs(directory, run)
        for directory, run in zip(directories, runs, strict=True)
    ]
    sources = [binding[0] for binding in bindings]
    output_dir = Path(output_dir).resolve()
    if output_dir.exists():
        raise ValueError("Comparison viewer output already exists; use a new directory")
    with tempfile.TemporaryDirectory(prefix="inspect-comparison-") as staging:
        for role, paths in zip(("baseline", "candidate"), sources, strict=True):
            _stage_logs(paths, Path(staging) / role)
        bundle_log_dir(log_dir=staging, output_dir=str(output_dir))
    (output_dir / "comparison.json").write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    manifest = {
        "version": "inspect-native-comparison-v1",
        "viewer_backend": "inspect_ai",
        "sources": [
            {
                "role": role,
                "run_id": run.get("run_id"),
                "results_sha256": hashlib.sha256(content).hexdigest(),
                "domain_summary": summary,
                "logs": [_log_source(path, directory) for path in binding[0]],
                "superseded_logs": binding[1],
            }
            for role, run, content, summary, directory, binding in zip(
                ("baseline", "candidate"), runs, raw, summaries, directories,
                bindings, strict=True,
            )
        ],
    }
    (output_dir / "benchmark-source.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return output_dir / "index.html"
