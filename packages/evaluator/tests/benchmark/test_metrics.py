"""Formal scores must come from actual state and complete execution evidence."""

import json
import os
import subprocess
import sys
from copy import deepcopy
from importlib.metadata import version
from pathlib import Path

import httpx
import openai
import pytest

from eval_framework.benchmark.metrics import METRICS_VERSION, score_response, score_task


@pytest.fixture
def task():
    return {
        "id": "edit-config-001",
        "family": "config-edit",
        "category": "file_edit",
        "split": "dev",
        "prompt": "Set config/app.ini to mode=release, preserving README.txt.",
        "followups": [],
        "fixtures": {"config/app.ini": "mode=debug\n", "README.txt": "keep\n"},
        "oracle": {
            "expected_files": {"config/app.ini": "mode=release\n"},
            "absent_files": [],
            "response_contains": [],
            "preserve_other_files": True,
            "forbid_extra_files": True,
        },
        "required_tools": ["read_file", "edit_file"],
        "allowed_tools": ["read_file", "edit_file", "list_dir"],
        "max_steps": 8,
    }


@pytest.fixture
def observation(task):
    return {
        "status": "completed",
        "evidence_complete": True,
        "turns": [{"input": task["prompt"], "output": "Updated config/app.ini."}],
        "before_files": deepcopy(task["fixtures"]),
        "final_files": {"config/app.ini": "mode=release\n", "README.txt": "keep\n"},
        "events": [
            {
                "type": "tool",
                "name": "read_file",
                "input": {"path": "config/app.ini"},
                "output": "mode=debug\n",
            },
            {
                "type": "tool",
                "name": "edit_file",
                "input": {
                    "path": "config/app.ini",
                    "old_text": "debug",
                    "new_text": "release",
                },
                "output": "Edited",
            },
        ],
        "usage": {"input_tokens": 100, "output_tokens": 30, "cost_usd": None},
        "errors": [],
    }


def by_name(result):
    return {metric["name"]: metric for metric in result["metrics"]}


def test_python_benchmark_import_disables_implicit_deepeval_network(tmp_path):
    socket_log = tmp_path / "sockets.log"
    guard = tmp_path / "guard"
    guard.mkdir()
    (guard / "sitecustomize.py").write_text(
        """
import os
import socket

_original_connect = socket.socket.connect
open(os.environ["BENCHMARK_IMPORT_SOCKET_LOG"], "w").close()

def _guarded_connect(sock, address):
    if isinstance(address, tuple):
        path = os.environ["BENCHMARK_IMPORT_SOCKET_LOG"]
        with open(path, "a", encoding="utf-8") as log:
            log.write(repr(address) + "\\n")
        raise RuntimeError("network disabled in benchmark import test")
    return _original_connect(sock, address)

socket.socket.connect = _guarded_connect
""".lstrip()
    )
    script = """
import json
import os
from eval_framework.benchmark.metrics import score_task
from deepeval.config.settings import get_settings

task = {
    "id": "offline-import",
    "prompt": "Keep a unchanged.",
    "followups": [],
    "fixtures": {"a": "same"},
    "oracle": {
        "expected_files": {"a": "same"},
        "absent_files": [],
        "response_contains": [],
        "preserve_other_files": True,
        "forbid_extra_files": True,
    },
    "required_tools": [],
    "allowed_tools": [],
}
observation = {
    "status": "completed",
    "evidence_complete": True,
    "turns": [{"input": task["prompt"], "output": "Unchanged."}],
    "before_files": {"a": "same"},
    "final_files": {"a": "same"},
    "events": [],
    "errors": [],
}
result = score_task(task, observation)
settings = get_settings()
print(json.dumps({
    "verdict": result["verdict"],
    "confident_key": os.environ.get("CONFIDENT_API_KEY"),
    "telemetry": os.environ.get("DEEPEVAL_TELEMETRY_OPT_OUT"),
    "dotenv": os.environ.get("DEEPEVAL_DISABLE_DOTENV"),
    "legacy_keyfile": os.environ.get("DEEPEVAL_DISABLE_LEGACY_KEYFILE"),
    "trace_internal": os.environ.get("CONFIDENT_TRACE_INTERNAL"),
    "trace_sample_rate": os.environ.get("CONFIDENT_TRACE_SAMPLE_RATE"),
    "tracing": os.environ.get("CONFIDENT_TRACING_ENABLED"),
    "settings_telemetry": settings.DEEPEVAL_TELEMETRY_OPT_OUT,
    "settings_trace_internal": settings.CONFIDENT_TRACE_INTERNAL,
    "settings_trace_sample_rate": settings.CONFIDENT_TRACE_SAMPLE_RATE,
}))
"""
    packages = Path(__file__).resolve().parents[3]
    pythonpath = [
        guard,
        packages / "evaluator/src",
        packages / "contracts/src",
        packages / "trace-sdk/src",
    ]
    env = dict(os.environ)
    env.update(
        PYTHONPATH=os.pathsep.join(str(path) for path in pythonpath),
        BENCHMARK_IMPORT_SOCKET_LOG=str(socket_log),
        CONFIDENT_API_KEY="FAKE_CONFIDENT_KEY",
        DEEPEVAL_TELEMETRY_OPT_OUT="0",
        DEEPEVAL_DISABLE_DOTENV="0",
        DEEPEVAL_DISABLE_LEGACY_KEYFILE="0",
        CONFIDENT_TRACE_INTERNAL="1",
        CONFIDENT_TRACE_SAMPLE_RATE="1",
        CONFIDENT_TRACING_ENABLED="YES",
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout.splitlines()[-1])
    assert result == {
        "verdict": "PASS",
        "confident_key": "",
        "telemetry": "1",
        "dotenv": "1",
        "legacy_keyfile": "1",
        "trace_internal": "0",
        "trace_sample_rate": "0",
        "tracing": "NO",
        "settings_telemetry": True,
        "settings_trace_internal": False,
        "settings_trace_sample_rate": 0.0,
    }
    assert socket_log.exists()
    assert socket_log.read_text() == ""


def test_default_scoring_leaves_repetition_to_explicit_quality_audit(task, observation):
    task["evaluation_level"] = "chain"
    first = observation["events"][0]
    first.update(
        id="read-1",
        turn=1,
        execution_started=True,
        is_error=False,
        normalized_input=deepcopy(first["input"]),
        before_files=deepcopy(task["fixtures"]),
        after_files=deepcopy(task["fixtures"]),
        start_time="2026-11-01T00:00:00Z",
        end_time="2026-11-01T00:00:01Z",
    )
    second = {
        **deepcopy(first),
        "id": "read-2",
        "start_time": "2026-11-01T00:00:02Z",
        "end_time": "2026-11-01T00:00:03Z",
    }
    observation["events"] = [first, second]

    result = score_task(task, observation)

    assert "tool_nonrepetition" not in by_name(result)
    assert result["verdict"] == "PASS"


def test_actual_correct_state_passes_with_versioned_deepeval_metrics(task, observation):
    result = score_task(task, observation)

    assert result["verdict"] == "PASS"
    assert result["validity"] == "VALID"
    assert result["scoring_backend"] == "deepeval"
    assert set(by_name(result)) == {
        "task_success",
        "workspace_policy",
        "interactive_evidence",
        "tool_correctness",
    }
    assert all(metric["backend"] == "deepeval" for metric in result["metrics"])
    assert all(metric["version"] == METRICS_VERSION for metric in result["metrics"])
    assert all(
        metric["library_version"] == version("deepeval") for metric in result["metrics"]
    )


def test_correct_claim_cannot_hide_wrong_final_state(task, observation):
    observation["final_files"]["config/app.ini"] = "mode=debug\n"

    result = score_task(task, observation)

    assert result["verdict"] == "FAIL"
    assert result["validity"] == "VALID"
    assert by_name(result)["task_success"]["score"] == 0
    assert by_name(result)["tool_correctness"]["score"] == 1


@pytest.mark.parametrize("field", ["final_files", "before_files", "events", "turns"])
def test_missing_evidence_is_inconclusive_not_zero_or_pass(task, observation, field):
    observation.pop(field)

    result = score_task(task, observation)

    assert result["verdict"] == "INCONCLUSIVE"
    assert result["metrics"] == []
    assert result["errors"]


def test_forbidden_tool_fails_even_when_file_state_is_correct(task, observation):
    observation["events"].append(
        {"type": "tool", "name": "exec", "input": {"command": "true"}, "output": ""}
    )

    result = score_task(task, observation)

    assert result["verdict"] == "FAIL"
    assert by_name(result)["workspace_policy"]["score"] == 0
    assert "exec" in by_name(result)["workspace_policy"]["reason"]


@pytest.mark.parametrize(
    "path, content", [("README.txt", "damaged\n"), ("surprise.txt", "created\n")]
)
def test_unintended_writes_are_critical_failures(task, observation, path, content):
    observation["final_files"][path] = content

    result = score_task(task, observation)

    assert result["verdict"] == "FAIL"
    assert by_name(result)["workspace_policy"]["score"] == 0


def test_required_tool_coverage_ignores_order_and_extra_allowed_calls(
    task, observation
):
    observation["events"].reverse()
    observation["events"].append(
        {
            "type": "tool",
            "name": "list_dir",
            "input": {"path": "."},
            "output": "config/ README.txt",
        }
    )

    result = score_task(task, observation)

    assert result["verdict"] == "PASS"
    assert by_name(result)["tool_correctness"]["score"] == 1


def test_reference_tool_coverage_is_diagnostic_when_final_state_is_correct(
    task, observation
):
    observation["events"] = observation["events"][:1]

    result = score_task(task, observation)

    assert result["verdict"] == "PASS"
    assert by_name(result)["tool_correctness"]["score"] < 1
    assert by_name(result)["tool_correctness"]["formal"] is False


def test_equivalent_allowed_write_tool_is_not_failed_by_reference_path(
    task, observation
):
    task["allowed_tools"].append("write_file")
    observation["events"][1]["name"] = "write_file"
    observation["events"][1]["input"] = {
        "path": "config/app.ini",
        "content": "mode=release\n",
    }

    result = score_task(task, observation)

    assert result["verdict"] == "PASS"
    assert by_name(result)["task_success"]["success"] is True
    assert by_name(result)["workspace_policy"]["success"] is True
    assert by_name(result)["tool_correctness"]["success"] is False


def test_setup_mismatch_is_invalid_not_agent_failure(task, observation):
    observation["before_files"]["README.txt"] = "wrong fixture"

    result = score_task(task, observation)

    assert result["verdict"] == "INVALID"
    assert result["validity"] == "INVALID"
    assert result["metrics"] == []


@pytest.mark.parametrize("kind", ["environment", "provider"])
def test_infrastructure_errors_are_invalid(task, observation, kind):
    observation["status"] = "error"
    observation["errors"] = [
        {"kind": kind, "code": "UNAVAILABLE", "message": "Unavailable"}
    ]

    result = score_task(task, observation)

    assert result["verdict"] == "INVALID"
    assert result["validity"] == "INVALID"


def test_agent_timeout_with_state_evidence_is_valid_failure(task, observation):
    observation["status"] = "timeout"
    observation["stop_reason"] = "timeout"

    result = score_task(task, observation)

    assert result["verdict"] == "FAIL"
    assert result["validity"] == "VALID"


def test_task_input_mismatch_is_invalid(task, observation):
    observation["turns"][0]["input"] = "A different task"

    assert score_task(task, observation)["verdict"] == "INVALID"


def test_incomplete_tool_event_is_inconclusive(task, observation):
    del observation["events"][0]["output"]

    assert score_task(task, observation)["verdict"] == "INCONCLUSIVE"


def test_scoring_does_not_mutate_observation_or_task(task, observation):
    original = deepcopy((task, observation))

    score_task(task, observation)

    assert (task, observation) == original


def test_empty_expected_tools_does_not_penalize_optional_allowed_tools(
    task, observation
):
    task["required_tools"] = []

    result = score_task(task, observation)

    assert result["verdict"] == "PASS"
    assert "tool_correctness" not in by_name(result)


def test_claim_without_any_real_tool_interaction_cannot_pass(task, observation):
    observation["events"] = []

    result = score_task(task, observation)

    assert result["verdict"] == "FAIL"
    assert by_name(result)["interactive_evidence"]["score"] == 0
    assert by_name(result)["interactive_evidence"]["formal"] is True


@pytest.mark.parametrize("complete", [False, None])
def test_completed_execution_requires_explicit_complete_evidence(
    task, observation, complete
):
    if complete is None:
        observation.pop("evidence_complete")
    else:
        observation["evidence_complete"] = complete

    result = score_task(task, observation)

    assert result["verdict"] == "INCONCLUSIVE"
    assert result["metrics"] == []


@pytest.mark.parametrize("event_type", ["tool", "generation"])
def test_completed_execution_rejects_incomplete_critical_events(
    task, observation, event_type
):
    observation["events"].append(
        {
            "type": event_type,
            "name": "read_file",
            "input": {},
            "output": "",
            "incomplete": True,
        }
    )

    assert score_task(task, observation)["verdict"] == "INCONCLUSIVE"


def test_timeout_with_complete_state_and_partial_call_is_still_valid_failure(
    task, observation
):
    observation["status"] = "timeout"
    observation["evidence_complete"] = False
    observation["events"][0].pop("output")
    observation["events"][0]["incomplete"] = True

    result = score_task(task, observation)

    assert result["verdict"] == "FAIL"
    assert result["validity"] == "VALID"


def test_explicit_reference_smoke_does_not_require_real_agent_tool_calls(
    task, observation
):
    observation["execution_kind"] = "deterministic_reference_not_agent"
    observation["events"] = []

    result = score_task(task, observation)

    assert result["verdict"] == "PASS"
    assert "interactive_evidence" not in by_name(result)


def test_geval_diagnostic_uses_real_evidence_and_preserves_unknown_price(
    task, observation, monkeypatch
):
    task["oracle"]["expected_files"]["private-only.txt"] = "PRIVATE_ORACLE_SENTINEL"
    requests = []
    original_client = openai.OpenAI

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "judge-response",
                "object": "chat.completion",
                "created": 0,
                "model": "test-judge",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": '{"score": 3, "reason": "Partly unsupported."}',
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 137,
                    "completion_tokens": 23,
                    "total_tokens": 160,
                },
            },
        )

    def client_factory(**kwargs):
        return original_client(
            **kwargs, http_client=httpx.Client(transport=httpx.MockTransport(respond))
        )

    monkeypatch.setattr(openai, "OpenAI", client_factory)

    result = score_response(
        task,
        observation,
        {
            "model": "test-judge",
            "api_key": "PRIVATE_KEY_SENTINEL",
            "base_url": "https://judge.invalid/v1",
        },
    )

    assert result["errors"] == []
    assert result["score"] == pytest.approx(0.3)
    assert result["formal"] is False
    assert result["calibration"] == "not_calibrated"
    assert result["threshold"] is None
    assert result["success"] is None
    assert len(requests) == 1
    assert "PRIVATE_ORACLE_SENTINEL" not in json.dumps(requests)
    assert "PRIVATE_KEY_SENTINEL" not in json.dumps(result)
    assert result["events"][0]["usage"] == {
        "input_tokens": 137,
        "output_tokens": 23,
        "cost_usd": None,
    }


def test_judge_configuration_error_stays_unscored(task, observation, monkeypatch):
    monkeypatch.delenv("MISSING_BENCHMARK_JUDGE_KEY", raising=False)

    result = score_response(
        task,
        observation,
        {"model": "test-judge", "api_key_env": "MISSING_BENCHMARK_JUDGE_KEY"},
    )

    assert result["score"] is None
    assert result["success"] is None
    assert result["errors"][0]["code"] == "JUDGE_ERROR"
