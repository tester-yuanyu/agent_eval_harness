"""原生 DeepEval 指标只回放公开保存证据，不重新执行 Agent。"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from deepeval.models import DeepEvalBaseLLM

from eval_framework.benchmark.agentic_metrics import (
    run_agentic_metrics_worker,
    score_saved_agentic_metrics,
)


@pytest.fixture
def local_openai_judge():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):
            size = int(self.headers["Content-Length"])
            body = json.loads(self.rfile.read(size))
            prompt = body["messages"][0]["content"]
            requests.append(
                {
                    "path": self.path,
                    "authorization": self.headers.get("Authorization"),
                    "body": body,
                }
            )
            if '\"title\": \"EfficiencyVerdict\"' in prompt:
                content = json.dumps(
                    {
                        "score": 0.8,
                        "reason": "Recorded steps make appropriate progress.",
                    }
                )
            else:
                content = json.dumps(
                    {"task": "Read a, write b, then change b."}
                )
            response = json.dumps(
                {
                    "id": f"local-{len(requests)}",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "local-fake-judge",
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": content},
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 2,
                        "total_tokens": 12,
                    },
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, _format, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield requests, f"http://127.0.0.1:{server.server_port}/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class FakeJudge(DeepEvalBaseLLM):
    def __init__(self, *, invalid_efficiency: bool = False):
        self.calls = []
        self.invalid_efficiency = invalid_efficiency
        super().__init__(model="offline-fake")

    def load_model(self):
        return self

    def get_model_name(self) -> str:
        return "offline-fake"

    def generate(self, prompt, schema=None, **_kwargs):
        self.calls.append(
            {
                "input": prompt,
                "schema": schema.__name__,
                "output": None,
                "usage": {
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "cost_usd": None,
                },
            }
        )
        values = {
            "Task": {"task": "Read a, write b, then change b."},
            "EfficiencyVerdict": {
                "score": 1.5 if self.invalid_efficiency else 0.75,
                "reason": "The retry follows an error and later state changes.",
            },
            "TaskAndOutcome": {
                "task": "Read a, write b, then change b.",
                "outcome": "b contains the changed value.",
            },
            "TaskCompletionVerdict": {
                "verdict": 0.9,
                "reason": "The observable final state supports completion.",
            },
            "Verdicts": {
                "verdicts": [
                    {"verdict": "yes", "reason": "Arguments match the request."}
                ]
            },
            "ArgumentCorrectnessScoreReason": {
                "reason": "The recorded arguments are appropriate."
            },
        }
        result = schema(**values[schema.__name__])
        self.calls[-1]["output"] = result.model_dump(mode="json")
        return result

    async def a_generate(self, *args, **kwargs):
        return self.generate(*args, **kwargs)


@pytest.fixture
def saved_evidence():
    task = {
        "id": "saved-agent-case",
        "prompt": "Read a then write b.",
        "followups": ["Now change b."],
        "oracle": {"expected_files": {"b": "PRIVATE_ORACLE"}},
        "checkpoints": [{"secret": "PRIVATE_CHECKPOINT"}],
    }
    events = [
        {
            "id": "t1",
            "type": "turn",
            "turn": 1,
            "input": task["prompt"],
            "output": "Created b.",
            "snapshot": {"b": "first"},
        },
        {
            "id": "g1",
            "type": "generation",
            "parent_id": "t1",
            "input": {"messages": [{"role": "user", "content": task["prompt"]}]},
            "output": {"tool_calls": [{"name": "read_file"}]},
        },
        {
            "id": "r1",
            "type": "tool",
            "parent_id": "t1",
            "name": "read_file",
            "input": {"path": "a"},
            "normalized_input": {"path": "a"},
            "output": "Error: transient",
            "error": "transient",
        },
        {
            "id": "r2",
            "type": "tool",
            "parent_id": "t1",
            "name": "read_file",
            "input": {"path": "a"},
            "normalized_input": {"path": "a"},
            "output": "hello",
        },
        {
            "id": "w1",
            "type": "tool",
            "parent_id": "t1",
            "name": "write_file",
            "input": {"path": "b", "content": "hello"},
            "normalized_input": {"path": "b", "content": "hello"},
            "output": "ok",
        },
        {
            "id": "t2",
            "type": "turn",
            "turn": 2,
            "input": task["followups"][0],
            "output": "Changed b.",
            "snapshot": {"b": "changed"},
        },
        {
            "id": "e1",
            "type": "tool",
            "parent_id": "t2",
            "name": "edit_file",
            "input": {"path": "b", "old_text": "hello", "new_text": "changed"},
            "normalized_input": {
                "path": "b",
                "old_text": "hello",
                "new_text": "changed",
            },
            "output": "ok",
        },
    ]
    observation = {
        "status": "completed",
        "evidence_complete": True,
        "execution_kind": "real_agent",
        "events": events,
        "turns": [
            {
                "input": task["prompt"],
                "output": "Created b.",
                "snapshot": {"b": "first"},
            },
            {
                "input": task["followups"][0],
                "output": "Changed b.",
                "snapshot": {"b": "changed"},
            },
        ],
        "final_files": {"b": "changed"},
    }
    return task, observation


def test_public_replay_runs_native_metrics_without_agent_or_private_evidence(
    saved_evidence, tmp_path, monkeypatch
):
    task, observation = saved_evidence
    original = deepcopy((task, observation))
    judge = FakeJudge()
    network = []

    def block_network(_socket, address):
        network.append(address)
        raise AssertionError("native replay attempted an external request")

    monkeypatch.setattr(socket.socket, "connect", block_network)
    records = score_saved_agentic_metrics(
        task,
        observation,
        judge,
        dimensions=[
            "step_efficiency",
            "task_completion",
            "argument_correctness",
        ],
        max_model_requests=8,
        work_dir=tmp_path,
    )

    assert [record["name"] for record in records] == [
        "step_efficiency",
        "task_completion",
        "argument_correctness",
        "argument_correctness",
    ]
    assert [record["score"] for record in records] == [0.75, 0.9, 1.0, 1.0]
    assert all(
        record["formal"] is False
        and record["threshold"] is None
        and record["success"] is None
        and record["calibration"] == "not_calibrated"
        for record in records
    )
    assert records[0]["implementation"] == "StepEfficiencyMetric"
    assert records[0]["scope"] == "chain"
    assert records[1]["implementation"] == "TaskCompletionMetric"
    assert records[1]["scope"] == "task"
    assert [record["event_id"] for record in records[2:]] == ["t1", "t2"]
    assert records[2]["implementation"] == "ArgumentCorrectnessMetric"
    assert all(len(record["events"]) == 2 for record in records)
    prompts = [call["input"] for call in judge.calls]
    assert "PRIVATE_ORACLE" not in json.dumps(prompts)
    assert "PRIVATE_CHECKPOINT" not in json.dumps(prompts)
    argument_prompts = [
        call["input"] for call in judge.calls if call["schema"] == "Verdicts"
    ]
    assert "Now change b." not in argument_prompts[0]
    assert "changed" not in argument_prompts[0]
    assert "Now change b." in argument_prompts[1]
    assert "first" in argument_prompts[1]
    assert "hello" in argument_prompts[0]
    efficiency_prompt = next(
        call["input"]
        for call in judge.calls
        if call["schema"] == "EfficiencyVerdict"
    )
    assert all(
        name in efficiency_prompt
        for name in ("read_file", "write_file", "edit_file")
    )
    assert not network
    assert (task, observation) == original


def test_two_request_native_metric_does_not_start_with_one_request_budget(
    saved_evidence, tmp_path
):
    judge = FakeJudge()
    records = score_saved_agentic_metrics(
        *saved_evidence,
        judge,
        dimensions=["step_efficiency"],
        max_model_requests=1,
        work_dir=tmp_path,
    )

    assert judge.calls == []
    assert records[0]["status"] == "MISSING"
    assert records[0]["score"] is None
    assert "budget" in records[0]["reason"].lower()


def test_invalid_native_score_is_error_with_empty_score(saved_evidence, tmp_path):
    records = score_saved_agentic_metrics(
        *saved_evidence,
        FakeJudge(invalid_efficiency=True),
        dimensions=["step_efficiency"],
        max_model_requests=2,
        work_dir=tmp_path,
    )

    assert records[0]["status"] == "ERROR"
    assert records[0]["score"] is None
    assert records[0]["success"] is None


def test_incomplete_saved_trace_does_not_call_native_judge(saved_evidence, tmp_path):
    task, observation = saved_evidence
    observation["events"][2]["incomplete"] = True
    judge = FakeJudge()

    records = score_saved_agentic_metrics(
        task,
        observation,
        judge,
        dimensions=["step_efficiency", "task_completion", "argument_correctness"],
        max_model_requests=8,
        work_dir=tmp_path,
    )

    assert judge.calls == []
    assert all(record["status"] == "MISSING" for record in records)
    assert all(record["score"] is None for record in records)


@pytest.mark.parametrize("corruption", ["nested_parent", "turn_order"])
def test_structurally_inconsistent_saved_trace_is_missing_without_judge_calls(
    saved_evidence, tmp_path, corruption
):
    task, observation = saved_evidence
    if corruption == "nested_parent":
        observation["events"][2]["parent_id"] = "g1"
    else:
        observation["events"][0]["turn"] = 2
        observation["events"][5]["turn"] = 1
    judge = FakeJudge()

    records = score_saved_agentic_metrics(
        task,
        observation,
        judge,
        dimensions=["step_efficiency", "task_completion", "argument_correctness"],
        max_model_requests=8,
        work_dir=tmp_path,
    )

    assert judge.calls == []
    assert all(record["status"] == "MISSING" for record in records)
    assert all(record["score"] is None for record in records)


def test_worker_isolates_confident_and_keeps_keys_and_private_task_data_out_of_stdin(
    saved_evidence, monkeypatch
):
    task, observation = saved_evidence
    captured = {}

    def run(command, **kwargs):
        captured.update(command=command, **kwargs)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                [
                    {
                        "name": "step_efficiency",
                        "status": "SCORED",
                        "score": 0.8,
                        "events": [],
                    }
                ]
            ),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", run)
    result = run_agentic_metrics_worker(
        task,
        observation,
        {"model": "judge", "api_key": "MODEL_SECRET"},
        dimensions=["step_efficiency"],
        max_model_requests=2,
    )

    payload = json.loads(captured["input"])
    assert result[0]["score"] == 0.8
    assert captured["command"][-2:] == [
        "-m",
        "eval_framework.benchmark.agentic_metrics_worker",
    ]
    assert payload["task"] == {
        "id": task["id"],
        "prompt": task["prompt"],
        "followups": task["followups"],
    }
    assert "MODEL_SECRET" not in captured["input"]
    assert "PRIVATE_ORACLE" not in captured["input"]
    assert "PRIVATE_CHECKPOINT" not in captured["input"]
    assert payload["model_config"]["api_key_env"] == (
        "AGENT_EVAL_NATIVE_JUDGE_API_KEY"
    )
    worker_env = captured["env"]
    assert worker_env["AGENT_EVAL_NATIVE_JUDGE_API_KEY"] == "MODEL_SECRET"
    assert worker_env["CONFIDENT_API_KEY"] == ""
    assert worker_env["CONFIDENT_TRACING_ENABLED"] == "NO"
    assert worker_env["DEEPEVAL_DISABLE_DOTENV"] == "1"
    assert worker_env["DEEPEVAL_TELEMETRY_OPT_OUT"] == "1"
    assert worker_env["DEEPEVAL_NO_INSPECT_PROMPT"] == "1"


def test_real_worker_preserves_incomplete_event_and_refuses_to_score(saved_evidence):
    task, observation = saved_evidence
    observation["events"][2]["incomplete"] = True

    records = run_agentic_metrics_worker(
        task,
        observation,
        {
            "model": "offline-boundary-test",
            "api_key": "NOT_A_REAL_KEY",
            "base_url": "http://127.0.0.1:1/v1",
            "timeout": 0.2,
        },
        dimensions=["step_efficiency"],
        max_model_requests=2,
    )

    assert len(records) == 1
    assert records[0]["status"] == "MISSING"
    assert records[0]["score"] is None
    assert records[0]["events"] == []
    assert "incomplete" in records[0]["reason"].lower()


def test_real_worker_scores_step_efficiency_with_local_http_judge_only(
    saved_evidence, local_openai_judge, tmp_path, monkeypatch
):
    requests, base_url = local_openai_judge
    socket_log = tmp_path / "worker-sockets.log"
    guard = tmp_path / "guard"
    guard.mkdir()
    (guard / "sitecustomize.py").write_text(
        """
import os
import socket

_original_connect = socket.socket.connect

def _guarded_connect(sock, address):
    if isinstance(address, tuple):
        host = str(address[0])
        with open(os.environ["AGENT_EVAL_SOCKET_LOG"], "a", encoding="utf-8") as log:
            log.write(host + "\\n")
        if host not in {"127.0.0.1", "::1"}:
            raise RuntimeError("external network disabled in worker test")
    return _original_connect(sock, address)

socket.socket.connect = _guarded_connect
""".lstrip()
    )
    existing_pythonpath = os.environ.get("PYTHONPATH", "")
    monkeypatch.setenv(
        "PYTHONPATH",
        str(guard)
        + (os.pathsep + existing_pythonpath if existing_pythonpath else ""),
    )
    monkeypatch.setenv("AGENT_EVAL_SOCKET_LOG", str(socket_log))
    monkeypatch.setenv("CONFIDENT_API_KEY", "PARENT_CONFIDENT_SECRET")

    records = run_agentic_metrics_worker(
        *saved_evidence,
        {
            "model": "local-fake-judge",
            "api_key": "LOCAL_ONLY_SECRET",
            "base_url": base_url,
            "timeout": 2,
        },
        dimensions=["step_efficiency"],
        max_model_requests=2,
    )

    assert len(records) == 1
    assert records[0]["status"] == "SCORED"
    assert records[0]["score"] == pytest.approx(0.8)
    assert len(records[0]["events"]) == 2
    assert len(requests) == 2
    assert {request["path"] for request in requests} == {"/v1/chat/completions"}
    assert all(
        request["authorization"] == "Bearer LOCAL_ONLY_SECRET"
        for request in requests
    )
    assert "LOCAL_ONLY_SECRET" not in json.dumps([r["body"] for r in requests])
    assert "LOCAL_ONLY_SECRET" not in json.dumps(records)
    assert "PARENT_CONFIDENT_SECRET" not in json.dumps(records)
    connected_hosts = socket_log.read_text().splitlines()
    assert connected_hosts
    assert set(connected_hosts) <= {"127.0.0.1", "::1"}
