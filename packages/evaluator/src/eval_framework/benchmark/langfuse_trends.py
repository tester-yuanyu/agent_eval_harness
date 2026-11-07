"""可选 Langfuse 运行汇总；从保存 verdict 聚合，不新增正式判定。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from langfuse.api import CreateScoreRequest

from ..observability import client_from_env, destination_fingerprint, stable_id
from .langfuse_presentation import _remote_scores, _save
from .report_trends import VERSION, load_trend


def trend_payload(trend):
    scores = []
    for run in trend["runs"]:
        for mode, group in run["groups"].items():
            scores.append(
                CreateScoreRequest(
                    id=stable_id(VERSION, trend["cohort_id"], run["source_hash"], mode),
                    name=f"summary.pass_rate.{mode}",
                    value=group["pass_rate_percent"],
                    data_type="NUMERIC",
                    dataset_run_id=run["experiment_id"],
                    timestamp=datetime.fromisoformat(
                        run["finished_at"].replace("Z", "+00:00")
                    ),
                    comment=(
                        "保存 verdict 的运行汇总；非正式指标，不重新评分。"
                        "INVALID 保留在分母。"
                    ),
                    metadata={
                        "formal": False,
                        "scope": "run_summary",
                        "run_id": run["run_id"],
                        "cohort_id": trend["cohort_id"],
                        "source_hash": run["source_hash"],
                        "operation": mode,
                        **group,
                    },
                )
            )
    return scores


def trend_widget(trend):
    n = len(trend["runs"])
    return dict(
        name=f"读 / 写通过率趋势 · {n} 个 run" + (" · 仅基线" if n == 1 else ""),
        description="同口径保存结果；INVALID 留在分母，写保护路径 PASS 不等于成功写入。"
        "按时间分桶，同桶各 run 比率等权平均；逐 run 明细见趋势数据文件。"
        "空桶的 n/a/0 为无运行数据，不是通过率 0%。"
        "模型/运行实现可变化，不作因果或显著性结论。",
        view="scores-numeric",
        dimensions=[{"field": "name"}],
        metrics=[{"measure": "value", "agg": "avg"}],
        filters=[
            {
                "column": "metadata",
                "key": "cohort_id",
                "type": "stringObject",
                "operator": "=",
                "value": trend["cohort_id"],
            },
            {
                "column": "name",
                "type": "stringOptions",
                "operator": "any of",
                "value": ["summary.pass_rate.read", "summary.pass_rate.write"],
            },
        ],
        chart_type="LINE_TIME_SERIES",
        chart_config={"type": "LINE_TIME_SERIES"},
    )


def sync_trends(output_dir, run_dirs, *, client=None):
    root = Path(output_dir)
    trend = load_trend(run_dirs)
    destination = destination_fingerprint()
    for directory in run_dirs:
        receipt = json.loads((Path(directory) / "langfuse_export.json").read_text())
        if receipt["destination"] != destination:
            raise ValueError("trend destination mismatch")
    _save(root / "trend.json", trend)
    out = root / "langfuse-trends" / f"{trend['cohort_id']}.json"
    state = (
        json.loads(out.read_text())
        if out.exists()
        else {
            "version": VERSION,
            "cohort_id": trend["cohort_id"],
            "destination": destination,
            "submitted": [],
        }
    )
    if state["destination"] != destination:
        raise ValueError("trend destination changed")
    client = client or client_from_env()
    payload = trend_payload(trend)
    ids = [s.id for s in payload]
    found = _remote_scores(client, ids)
    missing = [s for s in payload if s.id not in found]
    if not any(s.id in state["submitted"] for s in missing):
        for start in range(0, len(missing), 100):
            batch = missing[start : start + 100]
            state["submitted"] = sorted(set(state["submitted"]) | {s.id for s in batch})
            state["status"] = "AWAITING_READBACK"
            _save(out, state)
            response = client.scores.create(
                request=batch, request_options={"max_retries": 0}
            )
            if (
                getattr(response, "errors", None)
                or getattr(response, "rejected", 0)
                or getattr(response, "accepted", len(batch)) != len(batch)
            ):
                raise ValueError("run summary rejected")
        found = _remote_scores(client, ids)
    errors = []
    for score in payload:
        remote = found.get(score.id, {})
        metadata = remote.get("metadata") or {}
        subject = remote.get("subject") or {}
        if (
            remote.get("name") != score.name
            or remote.get("value") != score.value
            or subject.get("kind") != "experiment"
            or subject.get("id") != score.dataset_run_id
            or any(metadata.get(k) != v for k, v in score.metadata.items())
        ):
            errors.append(score.id)
    state.update(
        status="VERIFIED" if not errors else "AWAITING_READBACK",
        errors=errors,
        score_ids=ids,
        run_ids=[r["run_id"] for r in trend["runs"]],
        summary_count=len(payload),
    )
    _save(out, state)
    _save(root / "langfuse_trends_export.json", state)
    return state
