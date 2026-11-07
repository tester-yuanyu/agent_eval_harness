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
