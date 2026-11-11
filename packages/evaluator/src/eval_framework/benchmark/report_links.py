"""离线验证展示链接；不读取凭据、不依赖 SDK、不联系远端。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import quote, urlsplit


def safe_base(base_url):
    url = urlsplit(base_url)
    if (
        url.scheme not in {"https", "http"}
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise ValueError("unsafe Langfuse URL")
    return base_url.rstrip("/")


def write_links(run_dir, *, base_url, project_id, destination):
    base = safe_base(base_url)
    root = Path(run_dir)
    receipt = json.loads((root / "langfuse_export.json").read_text())
    verification = json.loads((root / "langfuse_verification.json").read_text())
    source = hashlib.sha256((root / "results.json").read_bytes()).hexdigest()
    if (
        receipt.get("destination") != destination
        or receipt.get("source_hash") != source
        or verification.get("source_hash") != source
        or verification.get("status") != "VERIFIED"
    ):
        raise ValueError("unverified Langfuse source/destination")
    result = {
        "version": "report-links-v1",
        "source_hash": source,
        "destination": destination,
        "project_id": project_id,
        "base_url": base,
        "export_receipt_sha256": hashlib.sha256(
            (root / "langfuse_export.json").read_bytes()
        ).hexdigest(),
        "traces": [
            {
                "case_id": t["case_id"],
                "trial": t["trial"],
                "trace_id": t["trace_id"],
                "url": (
                    f"{base}/project/{quote(project_id, safe='')}/traces/"
                    f"{quote(t['trace_id'], safe='')}"
                ),
            }
            for t in receipt["traces"]
        ],
    }
    result.update(_run_entries(receipt, verification, base, project_id))
    (root / "report-links.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    return result


def load_links(run_dir):
    root = Path(run_dir)
    try:
        links = json.loads((root / "report-links.json").read_text())
        receipt = json.loads((root / "langfuse_export.json").read_text())
        verification = json.loads((root / "langfuse_verification.json").read_text())
        source = hashlib.sha256((root / "results.json").read_bytes()).hexdigest()
        if not (
            links["source_hash"]
            == receipt["source_hash"]
            == verification["source_hash"]
            == source
            and links["destination"] == receipt["destination"]
            and verification["status"] == "VERIFIED"
            and links["export_receipt_sha256"]
            == hashlib.sha256((root / "langfuse_export.json").read_bytes()).hexdigest()
        ):
            return {}
        base = safe_base(links["base_url"])
        expected = {
            (t["case_id"], t["trial"]): t["trace_id"] for t in receipt["traces"]
        }
        result = {}
        for t in links["traces"]:
            key = (t["case_id"], t["trial"])
            url = (
                f"{base}/project/{quote(links['project_id'], safe='')}/traces/"
                f"{quote(t['trace_id'], safe='')}"
            )
            if key in result or expected.get(key) != t["trace_id"] or t["url"] != url:
                return {}
            result[key] = url
        return result if set(result) == set(expected) else {}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def _run_entries(receipt, verification, base, project_id):
    """Build run-level entries only when experiment cardinality was read back."""
    prefix = f"{base}/project/{quote(project_id, safe='')}"
    experiments = {}
    for trace in receipt["traces"]:
        identity = trace.get("experiment_id")
        if identity:
            entry = experiments.setdefault(
                identity, {"trial": trace["trial"], "items": 0}
            )
            if entry["trial"] != trace["trial"]:
                return {}
            entry["items"] += 1
    checked = {
        item["experiment_id"]: item for item in verification.get("experiments", [])
    }
    if (
        not receipt.get("dataset_id")
        or not experiments
        or any(
            checked.get(identity, {}).get("items") != entry["items"]
            or checked.get(identity, {}).get("expected") != entry["items"]
            for identity, entry in experiments.items()
        )
    ):
        return {}
    return {
        "dataset": {
            "dataset_id": receipt["dataset_id"],
            "name": receipt.get("dataset_name", receipt["dataset_id"]),
            "url": f"{prefix}/datasets/{quote(receipt['dataset_id'], safe='')}",
        },
        "experiments": [
            {
                "experiment_id": identity,
                **entry,
                "url": (
                    f"{prefix}/experiments/results?baseline={quote(identity, safe='')}"
                ),
            }
            for identity, entry in sorted(experiments.items())
        ],
    }


def load_run_links(run_dir):
    """Keep the historical trace mapping API; expose verified dataset/run entries."""
    root = Path(run_dir)
    if not load_links(root):
        return {}
    try:
        links = json.loads((root / "report-links.json").read_text())
        receipt = json.loads((root / "langfuse_export.json").read_text())
        verification = json.loads((root / "langfuse_verification.json").read_text())
        expected = _run_entries(
            receipt, verification, safe_base(links["base_url"]), links["project_id"]
        )
        legacy = "dataset" not in links and "experiments" not in links
        return (
            expected
            if expected
            and (legacy or all(links.get(k) == v for k, v in expected.items()))
            else {}
        )
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def load_dashboard_link(run_dir) -> str | None:
    """Only publish a dashboard whose layout and real numeric aggregates passed."""
    root = Path(run_dir)
    try:
        if not load_links(root):
            return None
        state = json.loads((root / "dashboard_delivery.json").read_text())
        layout = json.loads((root / "langfuse_explorer_dashboard.json").read_text())
        metrics = json.loads((root / "langfuse_dashboard_metrics.json").read_text())
        links = json.loads((root / "report-links.json").read_text())
        digest = hashlib.sha256((root / "results.json").read_bytes()).hexdigest()
        url = state.get("dashboard_url")
        expected = (
            f"{safe_base(links['base_url'])}/project/"
            f"{quote(links['project_id'], safe='')}"
            f"/dashboards/{quote(layout['dashboard_id'], safe='')}"
        )
        if (
            state["delivery_status"] == "COMPLETE"
            and state["source_hash"] == digest
            and state["destination"] == links["destination"]
            and metrics["status"] == "VERIFIED"
            and metrics["source_hash"] == digest
            and layout["status"] == "VERIFIED"
            and url == layout["url"]
            and isinstance(url, str)
            and url.split("?", 1)[0] == expected
        ):
            return url
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None
