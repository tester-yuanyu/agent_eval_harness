"""持久化与取回边界；仅离线模型、真实本地文件和受控 sandbox。"""

import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_business_evidence_exists_before_model_returns(tmp_path):
    from eval_contracts.agent_readiness import agent_plan_for, reference_context

    from eval_framework.benchmark.agent_readiness import (
        AgentReferenceExecutor,
        ReferenceModel,
    )

    from .test_agent_readiness import ROOT, request_fixture

    request = request_fixture()
    case = next(
        c for c in request.cases if c.case_id.startswith("I-intent.query_user.")
    )
    plan = agent_plan_for(case, request)
    path = (
        tmp_path
        / hashlib.sha256(case.case_id.encode()).hexdigest()[:24]
        / "trace.inspect.json"
    )

    class Model(ReferenceModel):
        def classify_intent(self, user_input):
            assert path.is_file(), "evidence must survive without normal finally"
            return super().classify_intent(user_input)

    row = AgentReferenceExecutor(
        reference_context(request), ROOT / "examples/mini_agent", tmp_path
    ).execute(case.case_id, plan, model=Model(plan))
    assert row.evidence_complete, row.errors


@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
def test_failed_worker_evidence_collected_without_promoting_pass(
    monkeypatch, tmp_path, failure
):
    from inspect_ai import log, util

    from eval_framework.benchmark import full_adapter

    class Env:
        files = {}

        async def exec(self, command, **kwargs):
            if "--evidence-root" not in command:
                if "full_worker" not in " ".join(command):
                    return SimpleNamespace(success=True, stdout="{}")
                raise failure("worker stopped")
            root = command[command.index("--evidence-root") + 1]
            self.files[root + "/attempt.json"] = json.dumps(
                {
                    "version": "worker-evidence-v1",
                    "attempt_id": Path(root).name,
                    "case_id": "case-a",
                }
            )
            self.files[root + "/worker-error.json"] = (
                '{"status":"error","evidence_complete":false}'
            )
            raise failure("worker stopped")

        async def read_file(self, path):
            if path not in self.files:
                raise FileNotFoundError(path)
            return self.files[path]

    env = Env()
    monkeypatch.setattr(util, "sandbox", lambda: env)
    monkeypatch.setattr(log, "transcript", lambda: SimpleNamespace(events=[]))
    monkeypatch.setattr(full_adapter, "bind_docker_environment", lambda *args: {})

    async def evidence(*args):
        return []

    monkeypatch.setattr(full_adapter, "model_evidence", evidence)
    adapter = full_adapter.FullBenchmarkAdapter.__new__(
        full_adapter.FullBenchmarkAdapter
    )
    adapter.output = tmp_path
    monkeypatch.setattr(adapter, "runtime_identity", lambda mode: {"mode": mode})
    results = []
    for _ in range(2):
        try:
            result = asyncio.run(
                adapter.execute(
                    {"case_id": "case-a", "live": False},
                    mode="module",
                    config={"_inspect_docker_compose": "test"},
                )
            )
        except asyncio.CancelledError as exc:
            result = exc.benchmark_observation
        results.append(result)
        assert not result["evidence_complete"]
        receipt = result["worker_evidence"]
        assert receipt["status"] == "PARTIAL"
        assert receipt["case_id"] == "case-a"
        saved = tmp_path / receipt["path"]
        assert (saved.parent / "worker-error.json").is_file()
    assert (
        results[0]["worker_evidence"]["path"] != results[1]["worker_evidence"]["path"]
    )


def test_native_harness_saves_bound_checkpoint(tmp_path):
    from eval_contracts.benchmark import TaskInput
    from inspect_ai import Task
    from inspect_ai import eval as inspect_eval
    from inspect_ai.dataset import Sample
    from inspect_ai.log import read_eval_log
    from inspect_ai.model import get_model

    from eval_framework.harness.adapters.inspect_solver import harness_solver

    from .test_native_harness import output

    task = TaskInput(
        task_id="a", prompt="hello", initial_state={"files": {}}, tools=["read_file"]
    )
    logs = inspect_eval(
        Task(
            dataset=[Sample(id="a", input="hello")],
            solver=harness_solver({"a": task}, evidence_root=tmp_path / "evidence"),
            sandbox="local",
        ),
        model=get_model("mockllm/model", custom_outputs=[output("done")]),
        log_dir=str(tmp_path / "logs"),
        display="none",
        notification=False,
        ctl_server=False,
    )
    assert logs[0].status == "success"
    receipts = list((tmp_path / "evidence").glob("*/checkpoint.json"))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text())
    assert receipt["task_id"] == "a" and receipt["evidence_complete"]
    native = receipts[0].parent / "trace.inspect.json"
    assert hashlib.sha256(native.read_bytes()).hexdigest() == receipt["sha256"]
    assert read_eval_log(native, format="json").samples[0].events


def test_corrupt_business_trace_cannot_complete_worker_receipt(tmp_path):
    from eval_framework.benchmark.worker_evidence import WorkerEvidence

    evidence = WorkerEvidence(tmp_path, "case-a")
    trace = hashlib.sha256(b"case-a").hexdigest()[:24] + "/trace.inspect.json"

    class Env:
        async def read_file(self, path):
            name = path.removeprefix(evidence.remote + "/")
            files = {
                "attempt.json": json.dumps(evidence.binding),
                "observation.json": json.dumps(
                    {"observations": {"events": [], "evidence_manifest": {}}}
                ),
                trace: "truncated-invalid-json",
            }
            if name not in files:
                raise FileNotFoundError(path)
            return files[name]

    receipt = asyncio.run(
        evidence.collect(Env(), complete=True, require_business_trace=True)
    )
    assert receipt["status"] == "PARTIAL"
    assert any(e["code"] == "BUSINESS_TRACE_INVALID" for e in receipt["errors"])


@pytest.mark.parametrize(
    "boundary", ["model_start", "model_end", "route_start", "route_end"]
)
def test_sigkill_preserves_partial_native_checkpoint(tmp_path, boundary):
    import os
    import subprocess
    import sys
    import time

    from inspect_ai.log import read_eval_log

    script = tmp_path / "kill_at_boundary.py"
    script.write_text("""
import sys,time
from pathlib import Path
from inspect_ai import Task,eval
from inspect_ai.dataset import Sample
from inspect_ai.model import get_model,ModelOutput,ChatMessageAssistant
from inspect_ai.tool import ToolCall
from inspect_ai.log import transcript
from eval_contracts.benchmark import TaskInput
from eval_framework.harness.adapters.inspect_solver import harness_solver
from eval_framework.harness.trace.evidence_checkpoint import NativeCheckpoint
root=Path(sys.argv[1]); boundary=sys.argv[2]
original=NativeCheckpoint.capture
def capture(self,complete=False):
    original(self,complete)
    event=transcript().events[-1] if transcript().events else None
    if getattr(event,"data",{}).get("kind")==boundary:
        (root/"ready").write_text("ready")
        time.sleep(120)
NativeCheckpoint.capture=capture
task=TaskInput(task_id="crash",prompt="write",initial_state={"files":{}},tools=["write_file"])
result=ModelOutput.from_content("mockllm/model","")
result.choices[0].message=ChatMessageAssistant(content="",tool_calls=[ToolCall(id="call1",function="write_file",arguments={"path":"result.txt","content":"saved"})])
result.choices[0].stop_reason="tool_calls"
eval(Task(dataset=[Sample(id="crash",input="write")],solver=harness_solver({"crash":task},evidence_root=root/"evidence"),sandbox="local"),model=get_model("mockllm/model",custom_outputs=[result]),log_dir=str(root/"logs"),display="none",notification=False,ctl_server=False)
""")
    env = {
        k: v
        for k, v in os.environ.items()
        if not any(
            s in k.upper() for s in ("API_KEY", "SECRET", "TOKEN", "LANGFUSE", "SMOKE")
        )
    }
    env["DEEPEVAL_TELEMETRY_OPT_OUT"] = "YES"
    with (tmp_path / "child.log").open("w") as output:
        child = subprocess.Popen(
            [sys.executable, str(script), str(tmp_path), boundary],
            env=env,
            stdout=output,
            stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 30
            while (
                child.poll() is None
                and not (tmp_path / "ready").exists()
                and time.monotonic() < deadline
            ):
                time.sleep(0.05)
            assert (tmp_path / "ready").exists(), (tmp_path / "child.log").read_text()
            child.kill()
            child.wait(timeout=10)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=10)
    (receipt_file,) = (tmp_path / "evidence").glob("*/checkpoint.json")
    receipt = json.loads(receipt_file.read_text())
    assert receipt["task_id"] == "crash" and receipt["evidence_complete"] is False
    log = read_eval_log(receipt_file.parent / "trace.inspect.json", format="json")
    assert log.samples[0].metadata["evidence_complete"] is False
    info = [
        event.data
        for event in log.samples[0].events
        if getattr(event, "source", None) == "harness.v1"
    ]
    assert info[-1]["kind"] == boundary
    if boundary == "route_end":
        assert info[-1]["after"]["result.txt"] == "saved"


def test_checkpoint_write_failure_marks_all_evidence_incomplete(monkeypatch, tmp_path):
    from eval_framework.harness.trace import evidence_checkpoint as module

    monkeypatch.setattr(module, "transcript", lambda: SimpleNamespace(events=[]))
    checkpoint = module.NativeCheckpoint(tmp_path / "attempt", "case-a")
    checkpoint.capture()

    def fail(*args, **kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr(module, "write_eval_log", fail)
    row = {"evidence_complete": True, "trace": {"evidence_complete": True}}
    checkpoint.finish(row)
    assert row["evidence_complete"] is False
    assert row["trace"]["evidence_complete"] is False
    assert row["native_evidence"]["evidence_complete"] is False
    assert row["errors"][0]["code"] == "CHECKPOINT_WRITE_FAILED"


@pytest.mark.parametrize("bad_binding", [False, True])
def test_worker_collection_validates_real_sdk_roundtrip(tmp_path, bad_binding):
    from eval_contracts.agent_readiness import agent_plan_for, reference_context

    from eval_framework.benchmark.agent_readiness import (
        AgentReferenceExecutor,
        ReferenceModel,
    )
    from eval_framework.benchmark.worker_evidence import WorkerEvidence

    from .test_agent_readiness import ROOT, request_fixture

    request = request_fixture()
    case = next(
        c for c in request.cases if c.case_id.startswith("I-intent.query_user.")
    )
    plan = agent_plan_for(case, request)
    evidence = WorkerEvidence(tmp_path / "host", case.case_id)
    remote = tmp_path / "worker"
    row = AgentReferenceExecutor(
        reference_context(request), ROOT / "examples/mini_agent", remote
    ).execute(case.case_id, plan, model=ReferenceModel(plan))
    assert row.evidence_complete, row.errors
    (remote / "observation.json").write_text(row.model_dump_json())
    binding = (
        {**evidence.binding, "attempt_id": "other"} if bad_binding else evidence.binding
    )
    (remote / "attempt.json").write_text(json.dumps(binding))

    class Env:
        async def read_file(self, path):
            return (remote / path.removeprefix(evidence.remote + "/")).read_text()

    receipt = asyncio.run(
        evidence.collect(Env(), complete=True, require_business_trace=True)
    )
    assert receipt["status"] == ("PARTIAL" if bad_binding else "COMPLETE"), receipt
    if bad_binding:
        assert {"code": "ATTEMPT_MISMATCH"} in receipt["errors"]


@pytest.mark.parametrize("failure", [RuntimeError, KeyboardInterrupt])
def test_worker_error_receipt_failure_preserves_original_exception(
    monkeypatch, tmp_path, failure
):
    import io
    import sys

    from eval_framework.benchmark import full_worker

    original_error = failure("original execution error")

    def execute(*args, **kwargs):
        raise original_error

    original_write = Path.write_text

    def write(path, *args, **kwargs):
        if path.name == "worker-error.json":
            raise OSError("disk full")
        return original_write(path, *args, **kwargs)

    monkeypatch.setattr(full_worker, "execute_public", execute)
    monkeypatch.setattr(Path, "write_text", write)
    monkeypatch.setattr(
        sys, "argv", ["full_worker", "--evidence-root", str(tmp_path / "attempt")]
    )
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"task": {"case_id": "case-a", "live": False}})),
    )
    with pytest.raises(failure) as caught:
        full_worker.main()
    assert caught.value is original_error
