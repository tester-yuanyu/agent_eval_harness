"""Deliver immutable evaluation artifacts to an explicitly configured local target.

This adapter owns presentation checkpoints only. Inspect's results and the existing
intake/gate records remain authoritative. No Agent execution or scoring occurs here.
"""

from __future__ import annotations

import fcntl
import hashlib
import ipaddress
import json
import os
import tempfile
import time
from collections import Counter
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import httpx
from langfuse.api.client import LangfuseAPI
from langfuse.api.unstable.dashboards.types.dashboard_definition import (
    DashboardDefinition,
)
from langfuse.api.unstable.dashboards.types.dashboard_placement import (
    DashboardPlacement_Widget,
)

from .dashboard_style import presentation_scores
from .dashboard_style import widgets as _widgets
from .evidence import atomic_json
from .observability import export_run, stable_id
from .result_loader import load_run_result

REQUEST_OPTIONS = {"max_retries": 0}
MAX_PENDING = 3
DELIVERY_SECONDS = 45


def _config(path: str | Path | None) -> dict[str, Any] | None:
    selected = path or os.getenv("AGENT_EVALUATOR_LOCAL_LANGFUSE_CONFIG")
    candidate = Path(selected or ".env.langfuse.local.json").expanduser().resolve()
    if not selected and not candidate.is_file():
        return None
    data = json.loads(candidate.read_text())
    if data.get("enabled") is not True:
        return None
    parsed = urlsplit(data["base_url"])
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("Local target must be an unambiguous loopback URL")
    host = parsed.hostname
    if host == "localhost":
        host = "127.0.0.1"  # Avoid DNS and proxy-dependent interpretation.
    if not host or not ipaddress.ip_address(host).is_loopback:
        raise ValueError("Local target must be loopback")
    address = f"[{host}]" if ":" in host else host
    if parsed.port is not None:
        address += f":{parsed.port}"
    data["base_url"] = urlunsplit((parsed.scheme, address, "", "", ""))
    for key in ("project_id", "public_key", "secret_key"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError("Incomplete local target configuration")
    if not isinstance(data.get("include_content", False), bool):
        raise ValueError("Content mode must be boolean")
    state = Path(data.get("state_dir", ".local_langfuse")).expanduser()
    data["state_dir"] = state if state.is_absolute() else candidate.parent / state
    data["target"] = stable_id(data["base_url"], data["project_id"], data["public_key"])
    return data


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError("Expected saved artifact object")
    return value


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source(source: str | Path) -> dict[str, Any]:
    path = Path(source).expanduser().resolve()
    if path.is_dir():
        path = next(
            (
                path / name
                for name in ("results.json", "intake.json", "invalid_run.json")
                if (path / name).is_file()
            ),
            path / "invalid_run.json",
        )
    data = _json(path)
    hashes = {str(path): _digest(path)}
    runs = []
    failed = []
    kind = "run" if path.name == "results.json" else "intake"
    if path.name == "invalid_run.json" or data.get("verdict") == "INVALID_RUN":
        kind = "invalid"
    items = [{"partition": "run", "paths": {"output_dir": str(path.parent)}}]
    if kind != "run":
        items = data.get("runs", [])
    for item in items:
        partition = str(item.get("partition", "run"))
        if item.get("error"):
            failed.append(
                {
                    "partition": partition,
                    "error_type": item["error"].get("error_type", "ERROR"),
                }
            )
            continue
        paths = item.get("paths", {})
        directory = Path(paths.get("output_dir") or paths["results"]).expanduser()
        if not directory.is_absolute():
            directory = path.parent / directory
        directory = directory.resolve()
        if directory.is_file():
            directory = directory.parent
        loaded = load_run_result(directory)
        hashes[loaded.source_path] = loaded.sha256
        summary_path = directory / "summary.json"
        display = _json(summary_path) if summary_path.is_file() else {}
        if summary_path.is_file():
            hashes[str(summary_path)] = _digest(summary_path)
        gate_path = directory / "gate.json"
        gate = _json(gate_path) if gate_path.is_file() else item.get("gate")
        if gate_path.is_file():
            hashes[str(gate_path)] = _digest(gate_path)
        if gate and gate.get("candidate_sha256") != loaded.sha256:
            gate = None
        runs.append(
            {
                "partition": partition,
                "directory": str(directory),
                "loaded": loaded,
                "provisional": display.get("provisional"),
                "gate": gate,
            }
        )
    # Some historical intake deliveries retain an independently evaluated gate in
    # verification.json. Accept only an explicitly matching intake and result hash.
    if kind == "intake":
        for parent in list(path.parents)[:5]:
            verification = parent / "verification.json"
            if not verification.is_file():
                continue
            saved = _json(verification)
            if saved.get("intake_path") != str(path):
                continue
            hashes[str(verification)] = _digest(verification)
            for run in runs:
                for entry in saved.get("runs", []):
                    gate = entry.get("gate", {})
                    if gate.get("candidate_sha256") == run["loaded"].sha256:
                        run["gate"] = gate
            break
    context = {
        key: data[key]
        for key in (
            "agent_id",
            "counts",
            "source_state",
            "source_approval",
            "release_eligible",
            "release_ineligibility_reasons",
            "error_code",
            "verdict",
        )
        if key in data
    }
    if kind == "intake":
        context["blocked_reasons"] = dict(
            Counter(
                str(case.get("reason_code") or "UNSPECIFIED")
                for case in data.get("cases", [])
                if case.get("disposition") == "blocked"
            )
        )
    context["failed_partitions"] = failed
    context["runs"] = [
        {
            "partition": run["partition"],
            "run_id": run["loaded"].result.evaluator_run_id,
            "results_sha256": run["loaded"].sha256,
            "saved_summary": run["loaded"].result.summary.model_dump(),
            "provisional": run["provisional"],
            "gate": run["gate"],
        }
        for run in runs
    ]
    identity = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    return {
        "path": path,
        "hashes": hashes,
        "source_sha256": identity,
        "kind": kind,
        "runs": runs,
        "context": context,
    }


def _description(snapshot: dict[str, Any]) -> str:
    context = snapshot["context"]
    parts = ["Saved authoritative results; no combined pass rate."]
    if context.get("counts") is not None:
        parts.append("Intake counts: " + json.dumps(context["counts"], sort_keys=True))
    for key in (
        "source_state",
        "source_approval",
        "release_eligible",
        "error_code",
        "verdict",
    ):
        if key in context:
            parts.append(f"{key}=" + json.dumps(context[key]))
    if context.get("blocked_reasons"):
        parts.append("Unexecuted reasons: " + json.dumps(context["blocked_reasons"]))
    for run in context["runs"]:
        summary = run["saved_summary"]
        parts.append(
            f"{run['partition']}: executed={summary.get('total_cases')}; "
            f"provisional={json.dumps(run['provisional'])}; "
            "strict pass rate="
            + (
                "not applicable"
                if summary.get("strict_assertion_pass_rate") is None
                else str(summary["strict_assertion_pass_rate"]) + "%"
            )
        )
        if run["gate"]:
            gate = run["gate"]
            codes = [
                check["code"]
                for check in gate.get("checks", [])
                if check.get("state") != "PASS"
            ]
            parts.append(
                f"{run['partition']} saved gate={gate.get('conclusion')}; "
                + ", ".join(codes)
            )
    for failed in context["failed_partitions"]:
        parts.append(f"{failed['partition']}: execution error ({failed['error_type']})")
    if not context["runs"]:
        parts.append("No executed Trials; quality pass rate not applicable.")
    if not any(run["gate"] for run in context["runs"]):
        parts.append(
            "Formal gate: not recorded; release eligibility is shown separately."
        )
    return " ".join(parts)


def _dashboard_date_range(snapshot: dict[str, Any]) -> str | None:
    """Pin the UI to saved run bounds; never substitute the current date."""
    bounds = []
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    millisecond = timedelta(milliseconds=1)
    for run in snapshot["runs"]:
        result = run["loaded"].result
        try:
            start, end = (
                datetime.fromisoformat(value.replace("Z", "+00:00"))
                for value in (result.started_at, result.finished_at)
            )
            if start.utcoffset() is None or end.utcoffset() is None or start > end:
                return None
            bounds.append(
                ((start - epoch) // millisecond, (end - epoch) // millisecond)
            )
        except (ValueError, TypeError, AttributeError, OverflowError):
            return None
    if not bounds:
        return None
    # Root observations span run bounds and saved summary Scores use finished_at.
    # A small margin avoids dropping boundary timestamps in native UI filtering.
    start_ms = min(start for start, _ in bounds) - 1000
    end_ms = max(end for _, end in bounds) + 1000
    return f"{start_ms}-{end_ms}"


def _atomic_text(path: Path, text: str) -> None:
    fd, temporary = tempfile.mkstemp(prefix=".delivery-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(text)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def _lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def _report(receipt: dict[str, Any], snapshot: dict[str, Any]) -> None:
    lines = [
        "# Local Langfuse delivery",
        "",
        f"Status: **{receipt['status']}**",
        "",
        _description(snapshot),
        "",
        f"Source SHA256: `{receipt['source_sha256']}`",
        "",
    ]
    if receipt.get("error"):
        lines.extend([receipt["error"], ""])
    if receipt.get("dashboard_url"):
        lines.append(f"- [Native dashboard]({receipt['dashboard_url']})")
    for url in receipt.get("experiment_urls", []):
        lines.append(f"- [Experiment]({url})")
    for run in snapshot["runs"]:
        report = Path(run["directory"]) / "report.md"
        if report.is_file():
            lines.append(f"- [{run['partition']} formal report](<{report}>)")
    if not snapshot["runs"] and (snapshot["path"].parent / "report.md").is_file():
        lines.append(f"- [Formal report](<{snapshot['path'].parent / 'report.md'}>)")
    lines.append(f"- [Delivery receipt](<{receipt['receipt_path']}>)")
    _atomic_text(Path(receipt["report_path"]), "\n".join(lines) + "\n")


def _deliver(
    source: str | Path,
    config: dict[str, Any],
    *,
    expected_hash: str | None = None,
    time_budget: float = DELIVERY_SECONDS,
) -> dict[str, Any]:
    snapshot = _source(source)
    path = snapshot["path"]
    target = config["target"]
    directory = path.parent / "local_langfuse" / target
    directory.mkdir(parents=True, exist_ok=True)
    record = directory / f"delivery-{snapshot['source_sha256']}.json"
    queue_dir = Path(config["state_dir"]) / target
    queue_dir.mkdir(parents=True, exist_ok=True)
    queue = queue_dir / f"pending-{stable_id(str(path))}.json"
    with _lock(queue_dir / f"{stable_id(str(path))}.lock"):
        receipt = (
            _json(record)
            if record.is_file()
            else {
                "version": "local-delivery-v1",
                "status": "PENDING",
                "target": target,
                "source": str(path),
                "source_sha256": snapshot["source_sha256"],
                "source_hashes": snapshot["hashes"],
                "include_content": config.get("include_content", False),
                "receipt_path": str(record),
                "report_path": str(directory / "REPORT.md"),
                "context": snapshot["context"],
                "widgets": {},
                "experiment_urls": [],
            }
        )

        def save():
            atomic_json(record, receipt)

        def pending():
            atomic_json(
                queue,
                {
                    "source": str(path),
                    "source_sha256": receipt["source_sha256"],
                    "receipt_path": str(record),
                    "status": receipt["status"],
                },
            )

        if expected_hash is not None and expected_hash != snapshot["source_sha256"]:
            return {
                "status": "SOURCE_CHANGED",
                "error": "Pending source changed; sync the saved source explicitly.",
            }
        if receipt["include_content"] != config.get("include_content", False):
            return {
                "status": "CONFIG_ERROR",
                "error": "Delivery content mode must remain immutable.",
            }
        if (
            receipt.get("inflight_create")
            or receipt["status"] == "RECONCILIATION_REQUIRED"
        ):
            receipt["status"] = "RECONCILIATION_REQUIRED"
            receipt["error"] = (
                "Acceptance is uncertain; reconcile recorded IDs before retrying. "
                "Nothing was replayed."
            )
            save()
            pending()
            _report(receipt, snapshot)
            return receipt
        receipt["status"] = "PENDING"
        receipt.pop("error", None)
        receipt.pop("error_type", None)
        # Rebuild native routes for the current runs, replacing older URL formats.
        receipt["experiment_urls"] = []
        save()
        pending()
        deadline = time.monotonic() + time_budget

        def local_request(request: httpx.Request) -> None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise httpx.ConnectTimeout(
                    "Local delivery time budget exhausted", request=request
                )
            # Enforce target origin even if an SDK method builds an absolute URL.
            configured_url = httpx.URL(config["base_url"])
            if (request.url.scheme, request.url.host, request.url.port) != (
                configured_url.scheme,
                configured_url.host,
                configured_url.port,
            ):
                raise httpx.ConnectError("Non-local request refused", request=request)
            request.extensions["timeout"] = dict.fromkeys(
                ("connect", "read", "write", "pool"), min(5.0, remaining)
            )

        try:
            with httpx.Client(
                timeout=5,
                follow_redirects=False,
                trust_env=False,
                event_hooks={"request": [local_request]},
            ) as http:
                client = LangfuseAPI(
                    base_url=config["base_url"],
                    username=config["public_key"],
                    password=config["secret_key"],
                    headers={"x-langfuse-ingestion-version": "4"},
                    httpx_client=http,
                )
                project = client.projects.get(request_options=REQUEST_OPTIONS)
                if config["project_id"] not in {item.id for item in project.data}:
                    raise ValueError(
                        "Local project credentials do not match configured project"
                    )
                if any(
                    _digest(Path(source_path)) != sha
                    for source_path, sha in snapshot["hashes"].items()
                ):
                    raise ValueError("Delivery source changed before export")
                exports = {}
                for run in snapshot["runs"]:
                    export_path = (
                        Path(run["directory"]) / f"langfuse_export.{target}.json"
                    )
                    # Run and intake delivery can reference the same observations.
                    with _lock(export_path.with_suffix(".lock")):
                        exported = export_run(
                            run["directory"],
                            include_content=config.get("include_content", False),
                            client=client,
                            target_identity=target,
                            receipt_path=export_path,
                            expected_results_sha256=run["loaded"].sha256,
                            refresh_scores=False,
                        )
                    exports[run["loaded"].sha256] = exported
                    project_url = (
                        f"{config['base_url']}/project/"
                        f"{quote(config['project_id'], safe='')}"
                    )
                    # Langfuse calls the selected display experiment "baseline".
                    # This does not select any Evaluator release-gate baseline.
                    url = (
                        project_url
                        + "/experiments/results?baseline="
                        + quote(exported["experiment_id"], safe="")
                    )
                    if url not in receipt["experiment_urls"]:
                        receipt["experiment_urls"].append(url)
                    save()
                confirmed = set(receipt.get("accepted_presentation_score_ids", []))
                pending_scores = [
                    s
                    for s in presentation_scores(snapshot, exports)
                    if s.id not in confirmed
                ]
                for offset in range(0, len(pending_scores), 100):
                    batch = pending_scores[offset : offset + 100]
                    response = client.scores.create(
                        request=batch, request_options=REQUEST_OPTIONS
                    )
                    if (
                        getattr(response, "rejected", 0)
                        or getattr(response, "errors", [])
                        or getattr(response, "accepted", len(batch)) != len(batch)
                    ):
                        raise ValueError("Display labels rejected; retry saved labels")
                    confirmed.update(s.id for s in batch)
                    receipt["accepted_presentation_score_ids"] = sorted(confirmed)
                    save()
                placements = []
                for widget in _widgets(snapshot):
                    key = widget["key"]
                    existing = receipt["widgets"].get(key)
                    if existing:
                        client.unstable.dashboard_widgets.update(
                            existing, **widget["spec"], request_options=REQUEST_OPTIONS
                        )
                        widget_id = existing
                    else:
                        receipt["inflight_create"] = {"kind": "widget", "key": key}
                        save()
                        created = client.unstable.dashboard_widgets.create(
                            **widget["spec"], request_options=REQUEST_OPTIONS
                        )
                        widget_id = created.id
                        receipt["widgets"][key] = widget_id
                        receipt.pop("inflight_create", None)
                        save()
                    x, y, width, height = widget["layout"]
                    placements.append(
                        DashboardPlacement_Widget(
                            id=stable_id(target, snapshot["source_sha256"], key),
                            widget_id=widget_id,
                            x=x,
                            y=y,
                            width=width,
                            height=height,
                        )
                    )
                context = snapshot["context"]
                display_name = context.get("agent_id", path.parent.name)
                title = ["Evaluator", display_name]
                if any(run["provisional"] is True for run in context["runs"]):
                    title.append("PROVISIONAL")
                blocked = context.get("counts", {}).get("blocked")
                if (
                    isinstance(blocked, int)
                    and not isinstance(blocked, bool)
                    and blocked > 0
                ):
                    title.append(f"blocked {blocked}")
                title.append(snapshot["source_sha256"][:8])
                kwargs = {
                    "name": " · ".join(title),
                    "description": _description(snapshot),
                    "definition": DashboardDefinition(widgets=placements),
                    "request_options": REQUEST_OPTIONS,
                }
                if receipt.get("dashboard_id"):
                    client.unstable.dashboards.update(receipt["dashboard_id"], **kwargs)
                else:
                    receipt["inflight_create"] = {"kind": "dashboard"}
                    save()
                    receipt["dashboard_id"] = client.unstable.dashboards.create(
                        **kwargs
                    ).id
                    receipt.pop("inflight_create", None)
                    save()
                receipt["dashboard_url"] = (
                    f"{config['base_url']}/project/"
                    f"{quote(config['project_id'], safe='')}/dashboards/"
                    f"{quote(receipt['dashboard_id'], safe='')}"
                )
                date_range = _dashboard_date_range(snapshot)
                if date_range is not None:
                    receipt["dashboard_url"] += f"?dateRange={date_range}"
                receipt["status"] = "ACCEPTED"
        except Exception as exc:
            # Response bodies and exception strings can contain credentials or
            # source content. Persist only a fixed classification and exception type.
            if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
                receipt.pop("inflight_create", None)
            uncertain = bool(receipt.get("inflight_create"))
            for run in snapshot["runs"]:
                checkpoint = Path(run["directory"]) / f"langfuse_export.{target}.json"
                if checkpoint.is_file():
                    uncertain |= bool(_json(checkpoint).get("inflight_observation_ids"))
            receipt["status"] = "RECONCILIATION_REQUIRED" if uncertain else "PENDING"
            receipt["error"] = (
                "Acceptance is uncertain; reconcile recorded IDs before retrying."
                if uncertain
                else "Local display synchronization is pending; retry saved artifacts."
            )
            receipt["error_type"] = type(exc).__name__
        save()
        _report(receipt, snapshot)
        if receipt["status"] == "ACCEPTED":
            queue.unlink(missing_ok=True)
        else:
            pending()
        return receipt


def finalize_delivery(
    source: str | Path,
    *,
    config_path: str | Path | None = None,
    retry_pending: bool = True,
) -> dict[str, Any]:
    """Best-effort local presentation; never alter formal evaluation outcomes."""
    try:
        config = _config(config_path)
    except Exception:
        return {
            "status": "CONFIG_ERROR",
            "error": (
                "Invalid local Langfuse configuration; use an explicit loopback target."
            ),
        }
    if config is None:
        return {"status": "DISABLED"}
    try:
        result = _deliver(source, config)
        # A down service need not be contacted again for each queued delivery.
        if retry_pending and result["status"] == "ACCEPTED":
            directory = Path(config["state_dir"]) / config["target"]
            deadline = time.monotonic() + 15
            attempted = 0
            for pending in sorted(directory.glob("pending-*.json")):
                if time.monotonic() >= deadline or attempted >= MAX_PENDING:
                    break
                try:
                    item = _json(pending)
                    if item["status"] != "PENDING":
                        continue
                    attempted += 1
                    retried = _deliver(
                        item["source"],
                        config,
                        expected_hash=item["source_sha256"],
                        time_budget=max(0, deadline - time.monotonic()),
                    )
                    if retried["status"] == "SOURCE_CHANGED":
                        item["status"] = "SOURCE_CHANGED"
                        atomic_json(pending, item)
                        continue
                    if retried["status"] != "ACCEPTED":
                        break
                except Exception:
                    # One stale queue entry cannot downgrade the current delivery.
                    continue
        public_keys = {
            "status",
            "source",
            "source_sha256",
            "target",
            "report_path",
            "receipt_path",
            "dashboard_url",
            "experiment_urls",
            "error",
            "error_type",
        }
        return {key: value for key, value in result.items() if key in public_keys}
    except Exception as exc:
        return {
            "status": "PENDING",
            "error": (
                "Local delivery could not read or persist its presentation artifacts."
            ),
            "error_type": type(exc).__name__,
        }
