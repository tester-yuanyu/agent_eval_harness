"""The offline demo must exercise Inspect and preserve the Oracle boundary."""

import json
import os
import subprocess
import sys
from pathlib import Path


def test_offline_demo_reports_three_expected_conclusions(tmp_path):
    root = Path(__file__).resolve().parents[2]
    python = root / ".venvs/evaluator/bin/python"
    completed = subprocess.run(
        [
            str(python) if python.exists() else sys.executable,
            str(root / "scripts/demo.py"),
            "--output-dir",
            str(tmp_path),
        ],
        env={
            key: value
            for key, value in os.environ.items()
            if not any(token in key for token in ("API_KEY", "LANGFUSE", "TOKEN"))
        },
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    manifest = json.loads(completed.stdout)
    assert manifest["conclusions"] == {
        "DEMO-PASS": "PASS",
        "DEMO-FAIL": "FAIL",
        "DEMO-INCONCLUSIVE": "INCONCLUSIVE",
    }
    for name in ("report", "results", "inspect_log", "suite"):
        assert Path(manifest[name]).is_file(), name
    result = json.loads(Path(manifest["results"]).read_text())
    assert result["evaluation_backend"]["name"] == "inspect_ai"
    assert len(result["cases"]) == 3
    assert all(case["execution_status"] == "COMPLETED" for case in result["cases"])
    # Missing evidence must never be reported as a passing or zero-scored Agent.
    unknown = next(
        case for case in result["cases"] if case["case_id"] == "DEMO-INCONCLUSIVE"
    )
    assert unknown["score"] is None
    from inspect_ai.log import read_eval_log

    log = read_eval_log(manifest["inspect_log"])
    assert log.status == "success"
    assert len(log.samples) == 3
    for sample in log.samples:
        assert sample.target == ""
        assert "oracle-secret" not in str(sample.messages)
