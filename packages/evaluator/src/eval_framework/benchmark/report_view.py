"""把历史证据复制为新报告视图，不覆盖原报告、评分或上传回执。"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from .phase_timing import timed_phase
from .runner import save_json


def create_report_view(source: Path, output: Path) -> Path:
    from .judge_calibration import create_calibration_worksheet
    from .report import write_report

    source, output = Path(source).resolve(), Path(output).resolve()
    if (
        output == source
        or output.is_relative_to(source)
        or (output.exists() and any(output.iterdir()))
    ):
        raise ValueError("Report view requires a new empty directory outside source")
    raw = (source / "results.json").read_bytes()
    run = json.loads(raw)
    output.mkdir(parents=True, exist_ok=True)
    # Only presentation inputs, never credentials or mutable native execution state.
    for name in (
        "results.json",
        "langfuse_export.json",
        "langfuse_verification.json",
        "report-links.json",
        "report-pricing.json",
        "phase-timings.json",
    ):
        path = source / name
        if path.is_file():
            shutil.copyfile(path, output / name)
    save_json(
        output / "view-provenance.json",
        {
            "operation": "report_view",
            "source": str(source),
            "source_results_sha256": hashlib.sha256(raw).hexdigest(),
            "new_agent_executions": 0,
            "new_judge_requests": 0,
        },
    )
    if "judge_summary" in run:
        save_json(
            output / "human-calibration-worksheet.json",
            create_calibration_worksheet(run),
        )
    with timed_phase(output, "report"):
        report = write_report(output, format="domain")
    return report
