"""正式展示交付编排：复用已有看板模板，原执行/评分/回执保持只读。"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import shutil
from pathlib import Path

from .phase_timing import timed_phase
from .report import write_report
from .report_links import load_links
from .runner import save_json


def deliver_dashboard(
    run_dir: Path, *, profile, output: Path | None = None, client=None
) -> dict:
    source = Path(run_dir).resolve()
    output = Path(output).resolve() if output else source / "presentation"
    if output == source:
        raise ValueError("Dashboard workspace must differ from saved source")
    raw = (source / "results.json").read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    target = profile.destination()
    exported = json.loads((source / "langfuse_export.json").read_text())
    verified = json.loads((source / "langfuse_verification.json").read_text())
    if (
        exported["source_hash"] != digest
        or verified.get("source_hash") != digest
        or verified.get("status") != "VERIFIED"
        or exported["destination"] != target
    ):
        raise ValueError("Dashboard requires verified source and explicit destination")
    output.mkdir(parents=True, exist_ok=True)
    with (output / ".dashboard.lock").open("a") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Dashboard delivery already active") from None
        try:
            return _deliver(source, output, raw, digest, target, profile, client)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _deliver(source, output, raw, digest, target, profile, client):
    path = output / "dashboard_delivery.json"
    if path.exists():
        previous = json.loads(path.read_text())
        if previous["source_hash"] != digest or previous["destination"] != target:
            raise ValueError("Dashboard source/destination changed")
    if (output / "results.json").exists() and (
        output / "results.json"
    ).read_bytes() != raw:
        raise ValueError("Dashboard result bytes differ")
    for name in (
        "results.json",
        "langfuse_export.json",
        "langfuse_verification.json",
        "report-links.json",
        "report-pricing.json",
        "report-diagnostics.json",
        "report-dashboard.json",
    ):
        original = source / name
        if original.is_file() and not (output / name).exists():
            shutil.copyfile(original, output / name)
    state = {
        "version": "dashboard-delivery-v1",
        "source_hash": digest,
        "destination": target,
        "source_dir": str(source),
        "presentation_dir": str(output),
        "data_status": "VERIFIED",
        "dashboard_status": "PENDING",
        "delivery_status": "PENDING_DASHBOARD",
        "new_agent_executions": 0,
        "new_judge_requests": 0,
    }
    save_json(path, state)
    try:
        from .langfuse_explorer import (
            _PacedClient,
            sync_explorer,
            verify_display_metrics,
        )
        from .langfuse_presentation import create_dashboard, sync_diagnostics

        count = len(json.loads(raw)["trials"])
        # Legacy links are refreshed only in the presentation copy.
        if (output / "report-links.json").exists() and len(load_links(output)) != count:
            raise ValueError("Dashboard requires complete verified trace links")
        api = client if client is not None else _PacedClient(profile.client())
        with timed_phase(output, "dashboard_diagnostics"):
            annotations = sync_diagnostics(
                output,
                base_url=profile.base_url,
                client=api,
                destination=target,
                project_id=profile.project_id,
            )
        if annotations["status"] != "VERIFIED":
            state["dashboard_status"] = annotations["status"]
            return state
        with timed_phase(output, "dashboard_template"):
            create_dashboard(
                output,
                base_url=profile.base_url,
                client=api,
                destination=target,
                refresh=True,
            )
        with timed_phase(output, "dashboard_statistics"):
            display = sync_explorer(output, [output], client=api, destination=target)
        state["dashboard_status"] = display.get("dashboard_status", display["status"])
        if display.get("dashboard_status") == "VERIFIED":
            with timed_phase(output, "dashboard_metrics_readback"):
                metrics = verify_display_metrics(output, client=api)
            if metrics["status"] != "VERIFIED":
                state["dashboard_status"] = "PENDING_METRICS"
                return state
            state.update(
                delivery_status="COMPLETE", dashboard_url=display["dashboard_url"]
            )
            save_json(path, state)
            with timed_phase(output, "dashboard_report"):
                write_report(output, format="domain")
        return state
    except Exception as error:
        state.update(
            dashboard_status="FAILED",
            delivery_status="PENDING_DASHBOARD",
            error_type=type(error).__name__,
        )
        return state
    finally:
        if (source / "results.json").read_bytes() != raw or (
            output / "results.json"
        ).read_bytes() != raw:
            state.update(
                dashboard_status="FAILED",
                delivery_status="PENDING_DASHBOARD",
                error_type="SourceChanged",
            )
        save_json(path, state)


def main(argv=None):
    from dotenv import load_dotenv

    from .langfuse_delivery import load_profile

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    args = parser.parse_args(argv)
    load_dotenv(args.env_file, override=False)
    result = deliver_dashboard(
        args.run, profile=load_profile(args.profile), output=args.output
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["delivery_status"] == "COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
