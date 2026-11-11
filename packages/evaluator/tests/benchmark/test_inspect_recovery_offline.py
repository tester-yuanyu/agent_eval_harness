"""实际子进程强制终止；只用 Inspect mockllm，无付费请求。"""

import os
import subprocess
import sys
import time
from pathlib import Path


def test_killed_process_recovers_native_events_without_pass(tmp_path):
    script = tmp_path / "crash.py"
    script.write_text("""import asyncio
import sys
from pathlib import Path
from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.solver import solver
from inspect_ai.log import transcript
@solver
def block():
    async def solve(state, generate):
        transcript().info({"offline_marker": "before-kill"})
        await asyncio.sleep(2)
        Path(sys.argv[2]).write_text("ready")
        await asyncio.sleep(120)
        return state
    return solve
eval(Task(dataset=[Sample(id="interrupted", input="offline only")], solver=block()),
     model="mockllm/model", log_dir=sys.argv[1], log_realtime=True, log_buffer=1,
     display="none", notification=False, ctl_server=False)
""")
    ready = tmp_path / "ready"
    output = (tmp_path / "child.txt").open("w")
    child = subprocess.Popen(
        [sys.executable, str(script), str(tmp_path / "logs"), str(ready)],
        stdout=output,
        stderr=subprocess.STDOUT,
        env={**os.environ, "INSPECT_LOG_SHARED": "0"},
    )
    try:
        deadline = time.monotonic() + 30
        while (
            not ready.exists() and child.poll() is None and time.monotonic() < deadline
        ):
            time.sleep(0.1)
        assert ready.exists(), (tmp_path / "child.txt").read_text()
        child.kill()
        child.wait(timeout=10)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
        output.close()
    from eval_framework.inspect_recovery import recover_interrupted_log

    original = next((tmp_path / "logs").glob("*.eval"))
    original_bytes = original.read_bytes()
    result = recover_interrupted_log(original, output=tmp_path / "recovered.eval")
    assert original.read_bytes() == original_bytes
    assert result["status"] == "error"
    assert result["evidence_complete"] is False
    assert result["samples"][0]["evidence_complete"] is False
    assert result["samples"][0]["status"] == "error"
    assert "before-kill" in str(result["samples"][0]["native_events"])
    assert Path(result["recovered_log"]).is_file()
    assert result["samples"][0]["native_error"]
