"""Langfuse 可选展示：历史诊断注释、新导出标签、固定运行 Dashboard。"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from langfuse.api import CreateScoreRequest, OtelAttribute, OtelAttributeValue

from ..observability import client_from_env, destination_fingerprint, stable_id
from .report_diagnostics import write_diagnostics
from .report_links import write_links

VERSION = "langfuse-presentation-v1"


def annotation_payload(run, analysis, receipt):
    if (
        analysis["source_hash"] != receipt["source_hash"]
        or analysis["run_id"] != run["run_id"]
    ):
        raise ValueError("diagnostic source mismatch")
    rows = {(r["case_id"], r["trial"]): r for r in run["trials"]}
    traces = {(t["case_id"], t["trial"]): t for t in receipt["traces"]}
    suffix = analysis["analysis_id"][:12]
    payload = []
    for trial in analysis["trials"]:
        key = (trial["case_id"], trial["trial"])
        trace = traces[key]
        groups = {}
        for f in trial["findings"]:
            groups.setdefault(f["kind"], []).append(f)
        entries = [
            ("operation_verdict", trial["operation"] + ":" + trial["verdict"], [])
        ]
        entries += [
            ("issue", kind, findings) for kind, findings in sorted(groups.items())
        ]
        for kind, value, findings in entries:
            payload.append(
                CreateScoreRequest(
                    id=stable_id(
                        VERSION, analysis["analysis_id"], trace["trace_id"], kind, value
                    ),
                    name=f"diagnostic.{kind}.{suffix}",
                    value=value,
                    data_type="CATEGORICAL",
                    trace_id=trace["trace_id"],
                    observation_id=trace["root_id"],
                    timestamp=datetime.fromisoformat(
                        rows[key]["finished_at"].replace("Z", "+00:00")
                    ),
                    metadata={
                        "formal": False,
                        "purpose": "saved_evidence_diagnostic_annotation",
                        "source_hash": analysis["source_hash"],
                        "analysis_id": analysis["analysis_id"],
                        "rules_version": analysis["rules_version"],
                        "case_id": trial["case_id"],
                        "trial": trial["trial"],
                        "operation": trial["operation"],
                        "category": trial["category"],
                        "findings": findings,
                    },
                    comment="非正式诊断注释；不改变 DeepEval 判定。"
                    + (
                        " | ".join(f["description"] for f in findings)
                        if findings
                        else "按冻结任务目标分组，复用保存的 verdict；"
                        "未检测到问题不等于该能力通过。"
                    ),
                )
            )
    return payload


def enrich_spans(spans, run, analysis, traces):
    """仅首次入库前调用；不重发或修改已入库观察记录。"""
    result = [s.model_copy(deep=True) for s in spans]
    rows = {(r["case_id"], r["trial"]): r for r in analysis["trials"]}
    by_trace = {t["trace_id"]: (t, rows[(t["case_id"], t["trial"])]) for t in traces}
    dataset = run.get("identity", {}).get("dataset", {}).get("dataset_id", "benchmark")
    for index, span in enumerate(result):
        trace, row = by_trace[span.trace_id]
        name = f"{dataset} / {row['category']} / {row['case_id']}"
        tags = [
            f"operation:{row['operation']}",
            f"task_group:{row['category']}",
        ] + sorted({f"diagnosis:{f['kind']}" for f in row["findings"]})
        if span.span_id == trace["root_id"]:
            span = span.model_copy(update={"name": name})
        attrs = []
        for attr in span.attributes:
            if attr.key == "langfuse.observation.metadata":
                data = json.loads(attr.value.string_value or "{}")
                data["report_diagnostics"] = {
                    "analysis_id": analysis["analysis_id"],
                    "formal": False,
                    "operation": row["operation"],
                    "kinds": sorted({f["kind"] for f in row["findings"]}),
                }
                attr = OtelAttribute(
                    key=attr.key,
                    value=OtelAttributeValue(string_value=json.dumps(data)),
                )
            attrs.append(attr)
        attrs.extend(
            [
                OtelAttribute(
                    key="langfuse.trace.name",
                    value=OtelAttributeValue(string_value=name),
                ),
                OtelAttribute(
                    key="langfuse.trace.tags",
                    value=OtelAttributeValue(
                        arrayValue={"values": [{"stringValue": t} for t in tags]}
                    ),
                ),
            ]
        )
        result[index] = span.model_copy(update={"attributes": attrs})
    return result


def dashboard_widgets(run, analysis, receipt):
    if analysis["source_hash"] != receipt["source_hash"]:
        raise ValueError("dashboard source mismatch")
    scope = {
        "column": "metadata",
        "key": "source_hash",
        "operator": "=",
        "type": "stringObject",
        "value": analysis["source_hash"],
    }
    counts = Counter(t["verdict"] for t in analysis["trials"])
    total = len(analysis["trials"])
    groups = []
    for mode in ("read", "write", "mixed", "unknown"):
        rows = [t for t in analysis["trials"] if t["operation"] == mode]
        if rows:
            passed = sum(t["verdict"] == "PASS" for t in rows)
            groups.append(
                f"{mode} {passed}/{len(rows)} ({100 * passed / len(rows):.1f}%)"
            )
    specs = [
        (
            f"总通过率 {100 * counts['PASS'] / total if total else 0:.1f}%"
            f" · {counts['PASS']}/{total}",
            "verdict",
            "PIE",
            "保存的正式 verdict；分母含本次所有 trial，不合并补跑。",
        ),
        (
            "按任务目标 · " + " / ".join(groups),
            f"diagnostic.operation_verdict.{analysis['analysis_id'][:12]}",
            "HORIZONTAL_BAR",
            "非正式分组视图，复制正式 verdict；写场景保护路径通过不等于成功写入。",
        ),
        (
            "失败诊断分布 · 可重叠，不是正式评分",
            f"diagnostic.issue.{analysis['analysis_id'][:12]}",
            "HORIZONTAL_BAR",
            "按问题种类统计受影响 trial；一个 trial 可命中多类，未命中不代表能力通过。",
        ),
    ]
    return [
        dict(
            name=name,
            description=desc + " 固定 run=" + run["run_id"],
            view="scores-categorical",
            dimensions=[{"field": "stringValue"}],
            metrics=[{"measure": "count", "agg": "count"}],
            filters=[
                {
                    **scope,
                    "key": "results_sha256" if score == "verdict" else "source_hash",
                },
                {"column": "name", "operator": "=", "type": "string", "value": score},
            ],
            chart_type=chart,
            chart_config={"type": chart, "show_value_labels": True},
        )
        for name, score, chart, desc in specs
    ]


def _save(path, value):
    path.parent.mkdir(exist_ok=True, parents=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n")


def _remote_scores(client, ids):
    found = {}
    for start in range(0, len(ids), 40):
        cursor = None
        while True:
            args = {
                "id": ",".join(ids[start : start + 40]),
                "limit": 100,
                "fields": "subject,details",
            }
            if cursor:
                args["cursor"] = cursor
            response = client.scores.get_many(**args)
            for row in response.data:
                data = row.model_dump()
                if data["id"] in found:
                    raise ValueError("duplicate remote score ID")
                found[data["id"]] = data
            meta = response.meta.model_dump() if response.meta is not None else {}
            cursor = meta.get("next_cursor")
            if not cursor:
                break
    return found


def sync_diagnostics(run_dir, *, base_url, client=None):
    root = Path(run_dir)
    client = client or client_from_env()
    analysis = json.loads(write_diagnostics(root).read_text())
    run = json.loads((root / "results.json").read_text())
    receipt = json.loads((root / "langfuse_export.json").read_text())
    destination = destination_fingerprint()
    projects = client.projects.get().data
    if len(projects) != 1:
        raise ValueError("ambiguous Langfuse project")
    project_id = projects[0].id
    # Link creation also checks original export/read-back source and destination.
    links = write_links(
        root, base_url=base_url, project_id=project_id, destination=destination
    )
    payload = annotation_payload(run, analysis, receipt)
    out = root / "langfuse-diagnostics" / f"{analysis['analysis_id']}.json"
    state = (
        json.loads(out.read_text())
        if out.exists()
        else {
            "version": VERSION,
            "analysis_id": analysis["analysis_id"],
            "source_hash": analysis["source_hash"],
            "destination": destination,
            "project_id": project_id,
            "status": "PENDING",
            "submitted": [],
        }
    )
    if (
        state["destination"] != destination
        or state["source_hash"] != analysis["source_hash"]
    ):
        raise ValueError("presentation source/destination changed")
    ids = [s.id for s in payload]
    found = _remote_scores(client, ids)
    missing = [s for s in payload if s.id not in found]
    # Reconcile uncertain writes before resending.
    if any(s.id in state["submitted"] for s in missing):
        state["status"] = "AWAITING_READBACK"
        _save(out, state)
        return state
    if missing:
        state["submitted"] = ids
        _save(out, state)
        response = client.scores.create(
            request=missing, request_options={"max_retries": 0}
        )
        if (
            getattr(response, "errors", None)
            or getattr(response, "rejected", 0)
            or getattr(response, "accepted", len(missing)) != len(missing)
        ):
            raise ValueError("diagnostic annotation rejected")
        found = _remote_scores(client, ids)
    errors = []
    for score in payload:
        remote = found.get(score.id)
        if remote is None:
            errors.append(score.id + ":not_visible")
            continue
        subject = remote.get("subject") or {}
        metadata = remote.get("metadata") or {}
        if (
            remote.get("name") != score.name
            or remote.get("value") != score.value
            or subject.get("id") != score.observation_id
            or subject.get("trace_id") != score.trace_id
            or metadata.get("analysis_id") != analysis["analysis_id"]
            or metadata.get("formal") is not False
        ):
            errors.append(score.id + ":mismatch")
    state.update(
        status="VERIFIED" if not errors else "AWAITING_READBACK",
        errors=errors,
        score_ids=ids,
        trace_count=len(links["traces"]),
        annotation_count=len(payload),
    )
    _save(out, state)
    _save(root / "langfuse_diagnostics_export.json", state)
    return state


def create_dashboard(run_dir, *, base_url, client=None):
    root = Path(run_dir)
    client = client or client_from_env()
    analysis = json.loads((root / "diagnostics.json").read_text())
    run = json.loads((root / "results.json").read_text())
    receipt = json.loads((root / "langfuse_export.json").read_text())
    annotations = json.loads((root / "langfuse_diagnostics_export.json").read_text())
    if (
        annotations.get("status") != "VERIFIED"
        or annotations.get("analysis_id") != analysis["analysis_id"]
        or annotations.get("destination") != destination_fingerprint()
    ):
        raise ValueError("dashboard requires verified current annotations")
    out = root / "langfuse_dashboard.json"
    state = (
        json.loads(out.read_text())
        if out.exists()
        else {
            "analysis_id": analysis["analysis_id"],
            "destination": destination_fingerprint(),
            "widgets": [],
        }
    )
    if (
        state["analysis_id"] != analysis["analysis_id"]
        or state["destination"] != destination_fingerprint()
    ):
        raise ValueError("dashboard identity changed; archive receipt first")
    definitions = dashboard_widgets(run, analysis, receipt)
    # Names contain the immutable run, allowing reconciliation after uncertain creates.
    name = f"{run['run_id']} · 评测与诊断"
    listed = client.unstable.dashboards.list(limit=100).data
    matches = [d for d in listed if d.name == name]
    if len(matches) > 1:
        raise ValueError("duplicate dashboard names require reconciliation")
    if not state.get("dashboard_id"):
        dash = (
            matches[0]
            if matches
            else client.unstable.dashboards.create(
                name=name,
                description=(
                    "固定主集；正式判定来自 DeepEval，诊断为非正式注释。"
                    "当前只有一组可比运行，不展示跨版本趋势。"
                ),
                request_options={"max_retries": 0},
            )
        )
        state["dashboard_id"] = dash.id
        _save(out, state)
    available = client.unstable.dashboard_widgets.list(limit=100).data
    for i, definition in enumerate(definitions):
        if len(state["widgets"]) > i:
            continue
        definition = {**definition, "name": definition["name"] + " · " + run["run_id"]}
        matches = [w for w in available if w.name == definition["name"]]
        if len(matches) > 1:
            raise ValueError("duplicate widgets require reconciliation")
        widget = (
            matches[0]
            if matches
            else client.unstable.dashboard_widgets.create(
                **definition, request_options={"max_retries": 0}
            )
        )
        state["widgets"].append(widget.id)
        _save(out, state)
    definition = {
        "widgets": [
            {
                "type": "widget",
                "id": stable_id(VERSION, state["dashboard_id"], wid),
                "widget_id": wid,
                "x": 0 if i == 0 else (i - 1) * 6,
                "y": 0 if i == 0 else 6,
                "width": 12 if i == 0 else 6,
                "height": 6,
            }
            for i, wid in enumerate(state["widgets"])
        ]
    }
    from langfuse.api.unstable.dashboards.types.dashboard_definition import (
        DashboardDefinition,
    )

    client.unstable.dashboards.update(
        state["dashboard_id"],
        definition=DashboardDefinition.model_validate(definition),
        request_options={"max_retries": 0},
    )
    remote = client.unstable.dashboards.get(state["dashboard_id"])
    expected = DashboardDefinition.model_validate(definition)
    if remote.definition.model_dump() != expected.model_dump():
        raise ValueError("dashboard readback mismatch")
    times = [
        datetime.fromisoformat(t[key].replace("Z", "+00:00")).timestamp()
        for t in run["trials"]
        for key in ("started_at", "finished_at")
        if t.get(key)
    ]
    date_query = (
        f"?dateRange={int(min(times) * 1000) - 1000}-{int(max(times) * 1000) + 1000}"
        if times
        else ""
    )
    state.update(
        status="VERIFIED",
        url=f"{base_url.rstrip('/')}/project/{annotations['project_id']}/dashboards/{state['dashboard_id']}{date_query}",
        definitions=definitions,
    )
    _save(out, state)
    return state
