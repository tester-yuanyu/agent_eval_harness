"""安装命令与 python -m 必须均实际执行 CLI。"""

import json
import subprocess
import sys


def test_module_cli_runs_schema_command():
    result = subprocess.run(
        [sys.executable, "-m", "capability_snapshot_kit.ingestion.cli", "schema"],
        capture_output=True,
        text=True,
        check=True,
    )
    schema = json.loads(result.stdout)
    assert schema["title"] == "FactDocument"
    assert "agent" in schema["properties"]
