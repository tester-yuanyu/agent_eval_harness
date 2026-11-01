import json

import pytest
from eval_framework.benchmark.langfuse_export import build_payload


def test_real_children_keep_timing_io_and_experiment_identity():
    record = {
        "case_id": "c1",
        "trial": 2,
        "category": "read_search",
        "split": "dev",
        "started_at": "2026-11-01T00:00:00Z",
        "finished_at": "2026-11-01T00:00:04Z",
        "observation": {
            "turns": [{"input": "read", "output": "ok"}],
            "final_files": {"a": "b"},
            "before_files": {"a": "b"},
            "runtime_identity": {"model": "model"},
            "events": [
                {
                    "id": "gen1",
                    "type": "generation",
                    "name": "llm",
                    "start_time": "2026-11-01T00:00:01Z",
                    "end_time": "2026-11-01T00:00:03Z",
                    "input": ["read"],
                    "output": "ok",
                    "model": "requested-alias",
                    "response_model": "resolved-model-version",
                    "usage": {"input_tokens": 10, "output_tokens": 1},
                },
                {
                    "id": "denied-tool",
                    "type": "tool",
                    "name": "exec",
                    "tool_call_id": "call-from-model",
                    "start_time": "2026-11-01T00:00:03Z",
                    "end_time": "2026-11-01T00:00:03Z",
                    "input": {"command": "never-executed"},
                    "output": "Tool not found: exec",
                    "error": "Tool not found: exec",
                    "execution_started": False,
                },
            ],
        },
        "assessment": {
            "verdict": "PASS",
            "metrics": [
                {
                    "name": "TaskSuccess",
                    "score": 1.0,
                    "reason": "correct",
                    "version": "v1",
                }
            ],
        },
    }
    run = {
        "run_id": "run1",
        "identity_hash": "hash",
        "trials": [record],
        "mode": "real_agent",
    }
    tasks = {
        "c1": {
            "id": "c1",
            "prompt": "read",
            "followups": [],
            "oracle": {"response_contains": ["ok"]},
        }
    }
    spans, scores, traces = build_payload(run, tasks, "dataset1", "sourcehash")
    assert len(spans) == 3
    attrs = [{a.key: a.value.string_value for a in s.attributes} for s in spans]
    assert attrs[0]["langfuse.experiment.id"] == attrs[1]["langfuse.experiment.id"]
    assert (
        attrs[0]["langfuse.experiment.item.id"]
        == attrs[1]["langfuse.experiment.item.id"]
    )
    assert spans[1].parent_span_id == spans[0].span_id
    assert spans[1].end_time_unix_nano != spans[1].start_time_unix_nano
    assert attrs[1]["langfuse.observation.output"] == "ok"
    assert scores[0].observation_id == spans[0].span_id
    assert traces[0]["trial"] == 2
    generation = json.loads(attrs[1]["langfuse.observation.metadata"])
    denied_tool = json.loads(attrs[2]["langfuse.observation.metadata"])
    assert generation["requested_model"] == "requested-alias"
    assert generation["response_model"] == "resolved-model-version"
    assert denied_tool["execution_started"] is False
    assert denied_tool["tool_call_id"] == "call-from-model"
    assert denied_tool["complete"] is True
    assert spans[2].parent_span_id == spans[0].span_id


@pytest.mark.parametrize("status, expected_exit", [("VERIFIED", 0), ("MISMATCH", 1)])
def test_verify_cli_exit_status_reflects_remote_evidence(
    status, expected_exit, tmp_path, monkeypatch, capsys
):
    from eval_framework.benchmark.cli import main

    monkeypatch.setattr(
        "eval_framework.benchmark.langfuse_export.verify_run",
        lambda *_args, **_kwargs: {"status": status},
    )
    assert main(["verify-langfuse", "--run", str(tmp_path)]) == expected_exit
    assert json.loads(capsys.readouterr().out)["status"] == status


def test_connection_retry_never_replays_an_uncertain_delivered_request(monkeypatch):
    import httpx
    import pytest
    from eval_framework.benchmark.langfuse_export import _connect_retry

    monkeypatch.setattr(
        "eval_framework.benchmark.langfuse_export.time.sleep", lambda _: None
    )
    attempts = []

    def before_delivery():
        attempts.append(1)
        if len(attempts) < 3:
            raise httpx.ConnectTimeout("connection never established")
        return "accepted"

    assert _connect_retry(before_delivery) == "accepted"
    assert len(attempts) == 3
    attempts.clear()

    def uncertain_delivery():
        attempts.append(1)
        raise httpx.ReadTimeout("server may already have accepted the batch")

    with pytest.raises(httpx.ReadTimeout):
        _connect_retry(uncertain_delivery)
    assert len(attempts) == 1


def test_evidence_export_has_explicit_cli_dispatch(tmp_path, monkeypatch, capsys):
    from eval_framework.benchmark.cli import main

    def export(run, dataset):
        assert run == tmp_path and dataset == tmp_path / "tasks.jsonl"
        return {"status": "ACCEPTED", "observations": 3}

    monkeypatch.setattr(
        "eval_framework.benchmark.langfuse_export.export_metadata_evidence", export
    )
    assert (
        main(
            [
                "export-langfuse-evidence",
                "--run",
                str(tmp_path),
                "--dataset",
                str(tmp_path / "tasks.jsonl"),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["observations"] == 3
