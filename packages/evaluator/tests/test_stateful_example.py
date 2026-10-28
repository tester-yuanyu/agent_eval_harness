import json
import subprocess
import sys
from pathlib import Path


def test_stateful_example_compiles_runs_and_reports_actual_native_limits(tmp_path):
    root = Path(__file__).parents[1]
    completed = subprocess.run(
        [
            sys.executable,
            str(root / "examples/stateful_gift.py"),
            "--output-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    paths = json.loads(completed.stdout)
    from eval_framework.result_loader import load_run_result

    result = load_run_result(paths["run_directory"]).result
    assert result.run_config.run_mode == "framework_self_test"
    assert result.compiled_suite_sha256
    assert result.model_metadata["evaluation_environment"] == "gift_sqlite_v1"
    by_case = {case.case_id: case for case in result.cases}
    assert by_case["GIFT-GRANT"].quality_conclusion == "FAIL"
    assert by_case["GIFT-CANCEL"].quality_conclusion == "PASS"
    assert by_case["GIFT-CORRECTION"].quality_conclusion == "FAIL"
    assert by_case["GIFT-LINK"].quality_conclusion == "PASS"
    assert all(case.cleanup_status == "CLEANED" for case in result.cases)
    assert all(case.evaluation_validity == "VALID" for case in result.cases)
    assert all(case.before_snapshot["grant_count"] == 0 for case in result.cases)
    assert len(result.cases) == 8
    assert Path(paths["report"]).is_file()
    assert Path(paths["suite"]).is_file()
