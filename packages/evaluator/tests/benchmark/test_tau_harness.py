"""Exercise real Inspect/DeepEval with only the official execution mocked."""

import hashlib
import json
from importlib import import_module
from importlib.util import find_spec
from pathlib import Path
from types import SimpleNamespace

import pytest

from eval_framework.benchmark.tau_adapter import TAU_COMMIT

MODULE = "eval_framework.benchmark.tau_harness"


def harness():
    assert find_spec(MODULE) is not None, "Missing official-reward Harness bridge"
    return import_module(MODULE)


@pytest.mark.parametrize("reward, verdict", [(1, "PASS"), (0, "FAIL"), (0.25, "FAIL")])
def test_deepeval_preserves_the_official_numeric_reward(reward, verdict):
    result = harness().score_official_reward({"official_reward": reward})
    assert result["verdict"] == verdict and result["validity"] == "VALID"
    metric = result["metrics"][0]
    assert metric["score"] == reward
    assert metric["backend"] == "deepeval" and metric["formal"] is True
    assert metric["implementation"] == "OfficialTauRewardMetric"


@pytest.mark.parametrize("reward", [None, True, "1", float("nan"), 1.1])
def test_unknown_or_malformed_reward_is_invalid_not_zero(reward):
    result = harness().score_official_reward({"official_reward": reward})
    assert result["verdict"] == "INVALID" and result["validity"] == "INVALID"
    assert result["metrics"][0]["score"] is None


def test_execution_error_never_becomes_a_reward_success():
    result = harness().score_official_reward(
        {"official_reward": 1, "error": {"type": "ProviderError"}}
    )
    assert result["verdict"] == "INVALID"
    assert result["metrics"][0]["score"] is None


@pytest.fixture
def config():
    return {
        "source_root": "unused-source",
        "source_commit": TAU_COMMIT,
        "nanobot_root": "unused-agent",
        "python": "unused-python",
        "domain": "retail",
        "task_ids": ["0", "1", "2"],
        "num_trials": 1,
        "agent_model": "offline-stub",
        "user_model": "offline-stub-user",
    }


@pytest.fixture
def official_transport(monkeypatch):
    calls = []

    def run(config, output, *, dry_run=False):
        assert not dry_run
        calls.append(dict(config))
        output.mkdir(parents=True)
        rows = []
        for task_id in config["task_ids"]:
            row = {
                "task_id": task_id,
                "trial": 1,
                "official_reward": {"0": 1, "1": 0, "2": None}[task_id],
                "started_at": "2026-11-01T00:00:00+00:00",
                "finished_at": "2026-11-01T00:00:02+00:00",
            }
            if task_id == "2":
                row.update(
                    error={"type": "ProviderError", "message": "unavailable"},
                    verdict="INVALID",
                    result_path=None,
                )
                rows.append(row)
                continue
            trial = output / f"task-{task_id}-trial-1"
            trial.mkdir()
            reward = {"reward": row["official_reward"], "reward_basis": ["DB"]}
            observation = {
                "execution_kind": "real_agent_official_tau",
                "status": "completed",
                "evidence_complete": True,
                "runtime_identity": {"agent": "nanobot", "model": "offline-stub"},
                "events": [
                    {
                        "id": "generation-" + task_id,
                        "type": "generation",
                        "name": "offline-stub",
                        "model": "offline-stub",
                        "start_time": row["started_at"],
                        "end_time": row["finished_at"],
                        "input": {
                            "messages": [{"role": "user", "content": "Public request"}]
                        },
                        "output": {"content": "Public response"},
                        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                    }
                ],
                "turns": [{"input": "Public request", "output": "Public response"}],
                "errors": [],
                "official_reward": reward,
                "official_messages": [{"role": "user", "content": "Public request"}],
                "final_database_hash": "database-state-hash",
            }
            result_path = trial / "official-result.json"
            observation_path = trial / "benchmark-observation.json"
            result_path.write_text(json.dumps({"reward_info": reward, "messages": []}))
            observation_path.write_text(json.dumps(observation))
            row.update(
                reward_info=reward,
                result_path=str(result_path),
                observation_path=str(observation_path),
                evidence_complete=True,
                termination_reason="user_stop",
            )
            rows.append(row)
        summary = {
            "status": "PARTIAL",
            "domain": "retail",
            "task_ids": config["task_ids"],
            "num_trials": 1,
            "official_leaderboard_result": False,
            "source_identity": {"commit": TAU_COMMIT},
            "agent_runtime_identity": {"agent": "nanobot", "model": "offline-stub"},
            "task_sha256": {key: "task-hash-" + key for key in config["task_ids"]},
            "policy_sha256": "policy-hash",
            "results": rows,
        }
        (output / "summary.json").write_text(json.dumps(summary))
        return summary

    monkeypatch.setattr("eval_framework.benchmark.tau_adapter.run_tau", run)
    return calls


def test_inspect_orchestrates_official_batch_and_logs_deepeval_results(
    config, official_transport, tmp_path
):
    output = tmp_path / "run"
    result = harness().run_tau_harness(config, output)
    assert len(official_transport) == 1
    assert official_transport[0] == config
    assert result["execution_backend"] == "inspect_ai"
    assert result["scoring_backend"] == "deepeval"
    assert result["official_leaderboard_result"] is False
    assert result["summary"]["verdicts"] == {"PASS": 1, "FAIL": 1, "INVALID": 1}
    assert list((output / "inspect").glob("*.eval"))
    assert (
        json.loads((output / "results.json").read_text())["identity_hash"]
        == result["identity_hash"]
    )
    row = result["trials"][0]
    assert row["official_reward"] == 1
    assert Path(row["official_observation_path"]).is_file()
    assert Path(row["official_result_path"]).is_file()
    summary_path = Path(result["official_summary_path"])
    assert (
        result["official_summary_sha256"]
        == hashlib.sha256(summary_path.read_bytes()).hexdigest()
    )
    assert all(
        "evaluation_criteria" not in json.dumps(task)
        for task in result["task_descriptors"].values()
    )


def test_normalized_evidence_builds_langfuse_child_observations(
    config, official_transport, tmp_path
):
    pytest.importorskip("langfuse", reason="requires agent-evaluator[langfuse]")
    from eval_framework.benchmark.langfuse_export import build_payload

    result = harness().run_tau_harness(config, tmp_path / "run")
    spans, scores, traces = build_payload(
        result, result["task_descriptors"], "tau-subset", "saved-source-hash"
    )
    assert len(traces) == 3 and len(spans) == 5
    reward_scores = [item for item in scores if item.name == "official_reward"]
    assert sorted(item.value for item in reward_scores) == [0, 1]
    assert all(
        item.observation_id == trace["root_id"]
        for item in reward_scores
        for trace in traces
        if trace["trace_id"] == item.trace_id
    )


def test_transport_failure_preserves_invalid_outcomes_without_invented_calls(
    config, tmp_path, monkeypatch
):
    def fail(*args, **kwargs):
        raise RuntimeError("Environment unavailable")

    monkeypatch.setattr("eval_framework.benchmark.tau_adapter.run_tau", fail)
    result = harness().run_tau_harness(config, tmp_path / "failed")
    assert result["summary"]["verdicts"] == {"INVALID": 3}
    assert result["observed_official_trials"] == 0
    assert all(not row["observation"]["events"] for row in result["trials"])
    assert result["official_summary_path"] is None


def test_existing_output_is_immutable(config, official_transport, tmp_path):
    output = tmp_path / "run"
    harness().run_tau_harness(config, output)
    original = (output / "official/summary.json").read_bytes()
    with pytest.raises(ValueError, match="exist"):
        harness().run_tau_harness(config, output)
    assert (output / "official/summary.json").read_bytes() == original
    assert len(official_transport) == 1


def test_reward_disagreement_is_invalid_and_original_evidence_is_unchanged(
    config, official_transport, tmp_path, monkeypatch
):
    from eval_framework.benchmark import tau_adapter

    config["task_ids"] = ["0"]
    recorded = tau_adapter.run_tau
    original_bytes = []

    def disagreement(settings, output):
        summary = recorded(settings, output)
        path = Path(summary["results"][0]["result_path"])
        document = json.loads(path.read_text())
        document["reward_info"]["reward"] = 0
        path.write_text(json.dumps(document))
        original_bytes.append(path.read_bytes())
        return summary

    monkeypatch.setattr(tau_adapter, "run_tau", disagreement)
    result = harness().run_tau_harness(config, tmp_path / "mismatch")
    row = result["trials"][0]
    assert row["official_reward"] == 1
    assert row["assessment"]["verdict"] == "INVALID"
    assert row["assessment"]["metrics"][0]["score"] is None
    assert Path(row["official_result_path"]).read_bytes() == original_bytes[0]


def test_boolean_in_reward_artifact_is_not_corroboration_of_numeric_one(
    config, official_transport, tmp_path, monkeypatch
):
    from eval_framework.benchmark import tau_adapter

    config["task_ids"] = ["0"]
    recorded = tau_adapter.run_tau

    def malformed(settings, output):
        summary = recorded(settings, output)
        path = Path(summary["results"][0]["result_path"])
        document = json.loads(path.read_text())
        document["reward_info"]["reward"] = True
        path.write_text(json.dumps(document))
        return summary

    monkeypatch.setattr(tau_adapter, "run_tau", malformed)
    result = harness().run_tau_harness(config, tmp_path / "malformed")
    assert result["trials"][0]["assessment"]["verdict"] == "INVALID"
    assert result["trials"][0]["assessment"]["metrics"][0]["score"] is None


def test_official_budget_failure_remains_zero_even_with_trace_limit_diagnostic(
    config, official_transport, tmp_path, monkeypatch
):
    from eval_framework.benchmark import tau_adapter

    config["task_ids"] = ["1"]
    recorded = tau_adapter.run_tau

    def limited(settings, output):
        summary = recorded(settings, output)
        row = summary["results"][0]
        row.update(termination_reason="max_steps", evidence_complete=False)
        path = Path(row["observation_path"])
        document = json.loads(path.read_text())
        document.update(
            status="max_steps",
            evidence_complete=False,
            errors=[{"code": "official_termination", "reason": "max_steps"}],
        )
        path.write_text(json.dumps(document))
        (output / "summary.json").write_text(json.dumps(summary))
        return summary

    monkeypatch.setattr(tau_adapter, "run_tau", limited)
    result = harness().run_tau_harness(config, tmp_path / "budget")
    row = result["trials"][0]
    assert row["official_reward"] == 0
    assert row["assessment"]["verdict"] == "FAIL"
    assert row["assessment"]["metrics"][0]["score"] == 0
    assert row["observation"]["evidence_complete"] is False


class SavedLangfuse:
    """In-memory API transport; production export and verification both run."""

    def __init__(self):
        self.spans, self.saved_scores, self.items = [], [], []
        self.dataset = None
        self.datasets = SimpleNamespace(create=self.create_dataset)
        self.dataset_items = SimpleNamespace(create=lambda **kw: self.items.append(kw))
        self.opentelemetry = SimpleNamespace(export_traces=self.save_spans)
        self.scores = SimpleNamespace(create=self.save_scores, get_many=self.score_page)
        self.observations = SimpleNamespace(get_many=self.observation_page)
        self.experiments = SimpleNamespace(list_items=self.experiment_page)

    def create_dataset(self, **kwargs):
        self.dataset = kwargs
        return SimpleNamespace(id="official-tau-dataset")

    def save_spans(self, resource_spans, **kwargs):
        for resource in resource_spans:
            for scope in resource.scope_spans:
                self.spans.extend(scope.spans)
        return SimpleNamespace(model_dump=lambda **kw: {})

    def save_scores(self, request, **kwargs):
        self.saved_scores.extend(request)
        return SimpleNamespace(accepted=len(request), rejected=0, errors=[])

    @staticmethod
    def page(rows):
        return SimpleNamespace(model_dump=lambda **kw: {"data": rows, "meta": {}})

    @staticmethod
    def attrs(span):
        def decode(value):
            try:
                return json.loads(value)
            except (TypeError, ValueError):
                return value

        structured = {
            "langfuse.observation.input",
            "langfuse.observation.output",
            "langfuse.observation.metadata",
            "langfuse.observation.usage_details",
        }
        return {
            a.key: decode(a.value.string_value)
            if a.key in structured
            else a.value.string_value
            for a in span.attributes
        }

    def observation_page(self, **kwargs):
        from datetime import UTC, datetime

        rows = []
        for span in self.spans:
            attrs = self.attrs(span)
            rows.append(
                {
                    "id": span.span_id,
                    "trace_id": span.trace_id,
                    "parent_observation_id": span.parent_span_id,
                    "type": attrs["langfuse.observation.type"],
                    "start_time": datetime.fromtimestamp(
                        int(span.start_time_unix_nano) / 1e9, UTC
                    ),
                    "end_time": datetime.fromtimestamp(
                        int(span.end_time_unix_nano) / 1e9, UTC
                    ),
                    "input": attrs.get("langfuse.observation.input"),
                    "output": attrs.get("langfuse.observation.output"),
                    "metadata": attrs.get("langfuse.observation.metadata"),
                    "model": attrs.get("langfuse.observation.model.name"),
                    "usage_details": attrs.get("langfuse.observation.usage_details"),
                }
            )
        return self.page(rows)

    def score_page(self, **kwargs):
        return self.page(
            [
                {
                    "id": score.id,
                    "value": score.value,
                    "subject": {
                        "kind": "observation",
                        "id": score.observation_id,
                        "trace_id": score.trace_id,
                    },
                }
                for score in self.saved_scores
            ]
        )

    def experiment_page(self, experiment_id, **kwargs):
        return self.page(
            [
                {"id": span.span_id}
                for span in self.spans
                if self.attrs(span).get("langfuse.experiment.id") == experiment_id
                and self.attrs(span).get("langfuse.experiment.item.root_observation_id")
                == span.span_id
            ]
        )


def test_tau_export_and_readback_use_official_descriptors_and_provenance(
    config, official_transport, tmp_path, monkeypatch
):
    pytest.importorskip("langfuse", reason="requires agent-evaluator[langfuse]")
    from eval_framework.benchmark import langfuse_export

    output = tmp_path / "export"
    result = harness().run_tau_harness(config, output)
    summary = Path(result["official_summary_path"])
    client = SavedLangfuse()
    monkeypatch.setattr(
        langfuse_export, "destination_fingerprint", lambda: "offline-destination"
    )
    receipt = langfuse_export.export_run(output, summary, client=client)
    assert receipt["status"] == "ACCEPTED"
    assert "official" in client.dataset["description"].lower()
    assert "file-tool" not in client.dataset["description"].lower()
    assert {item["metadata"]["official_task_id"] for item in client.items} == {
        "0",
        "1",
        "2",
    }
    assert all(item["input"]["fixtures"] == {} for item in client.items)
    assert all(
        item["metadata"]["official_summary_sha256"] == result["official_summary_sha256"]
        for item in client.items
    )
    assert (
        langfuse_export.verify_run(output, summary, client=client)["status"]
        == "VERIFIED"
    )


def test_native_whole_trace_scores_and_missing_records_export_and_read_back(
    config, official_transport, tmp_path, monkeypatch
):
    pytest.importorskip("langfuse", reason="requires agent-evaluator[langfuse]")
    from eval_framework.benchmark import langfuse_export
    from eval_framework.benchmark.agentic_metrics import (
        _record_specs,
        unscored_agentic_metric_records,
    )

    config["task_ids"] = ["0", "1"]
    output = tmp_path / "native-chain-export"
    result = harness().run_tau_harness(config, output)
    scored_row, missing_row = result["trials"]
    scored_task = result["task_descriptors"][scored_row["case_id"]]
    missing_task = result["task_descriptors"][missing_row["case_id"]]
    scored_record, target = _record_specs(
        scored_task, scored_row["observation"], ["step_efficiency"]
    )[0]
    assert target is None
    scored_record.update(
        score=0.75,
        status="SCORED",
        reason="Recorded trace is efficient.",
    )
    missing_record = unscored_agentic_metric_records(
        missing_task,
        missing_row["observation"],
        ["step_efficiency"],
        status="MISSING",
        reason="Judge request budget was unavailable.",
    )[0]
    scored_row["assessment"]["metrics"].append(scored_record)
    missing_row["assessment"]["metrics"].append(missing_record)
    (output / "results.json").write_text(json.dumps(result))

    client = SavedLangfuse()
    monkeypatch.setattr(
        langfuse_export, "destination_fingerprint", lambda: "offline-destination"
    )
    summary = Path(result["official_summary_path"])
    receipt = langfuse_export.export_run(output, summary, client=client)
    assert receipt["status"] == "ACCEPTED"

    native_scores = [
        score for score in client.saved_scores if score.name == "step_efficiency"
    ]
    assert len(native_scores) == 1
    root_spans = [
        span
        for span in client.spans
        if SavedLangfuse.attrs(span).get("langfuse.experiment.item.root_observation_id")
        == span.span_id
    ]
    roots_by_case = {
        SavedLangfuse.attrs(span)["langfuse.observation.metadata"]["case_id"]: span
        for span in root_spans
    }
    scored_root = roots_by_case[scored_row["case_id"]]
    missing_root = roots_by_case[missing_row["case_id"]]
    assert native_scores[0].observation_id == scored_root.span_id
    assert missing_record["status"] == "MISSING" and missing_record["score"] is None
    missing_metadata = SavedLangfuse.attrs(missing_root)[
        "langfuse.observation.metadata"
    ]
    assert missing_metadata["assessment"]["metrics"][-1] == missing_record
    assert (
        langfuse_export.verify_run(output, summary, client=client)["status"]
        == "VERIFIED"
    )


def test_tau_export_rejects_changed_authoritative_summary(
    config, official_transport, tmp_path
):
    pytest.importorskip("langfuse", reason="requires agent-evaluator[langfuse]")
    from eval_framework.benchmark.langfuse_export import _source

    output = tmp_path / "export"
    result = harness().run_tau_harness(config, output)
    summary = Path(result["official_summary_path"])
    summary.write_bytes(summary.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="summary.*(SHA|hash)|SHA.*summary"):
        _source(output, summary)


def test_tau_export_rejects_descriptors_outside_official_selection(
    config, official_transport, tmp_path
):
    pytest.importorskip("langfuse", reason="requires agent-evaluator[langfuse]")
    from eval_framework.benchmark.langfuse_export import _source

    output = tmp_path / "export"
    result = harness().run_tau_harness(config, output)
    result["task_descriptors"][result["planned_case_ids"][0]]["official_task_id"] = (
        "unselected"
    )
    (output / "results.json").write_text(json.dumps(result))
    with pytest.raises(ValueError, match="task|selection|descriptor"):
        _source(output, Path(result["official_summary_path"]))


def test_verify_expands_flat_metadata_and_still_rejects_unexpected_file(
    config, official_transport, tmp_path, monkeypatch
):
    pytest.importorskip("langfuse", reason="requires agent-evaluator[langfuse]")
    from eval_framework.benchmark import langfuse_export

    config["task_ids"] = ["0"]
    output = tmp_path / "flat-export"
    result = harness().run_tau_harness(config, output)
    # Add recorded event metadata to exercise serialization/readback independently
    # of official reward. This never changes the authoritative official artifacts.
    result["trials"][0]["observation"]["events"][0]["snapshot"] = {
        "docs/a.v1.txt": "long content " * 50,
        "docs/string.txt": "null",
    }
    (output / "results.json").write_text(json.dumps(result))
    client = SavedLangfuse()
    calls = []
    extra = False

    def flattened_page(**kwargs):
        calls.append(kwargs)
        rows = client.observation_page(**kwargs).model_dump()["data"]
        expanded = kwargs.get("expand_metadata", "").split(",")
        for row in rows:
            flat = langfuse_export._flatten_metadata(row["metadata"])
            row["metadata"] = {
                key: value[:200]
                if isinstance(value, str) and key not in expanded
                else value
                for key, value in flat.items()
            }
            if extra and "snapshot.docs/a.v1.txt" in flat:
                row["metadata"]["snapshot.unexpected.txt"] = "unexpected"
        return client.page(rows)

    client.observations.get_many = flattened_page
    monkeypatch.setattr(langfuse_export, "destination_fingerprint", lambda: "offline")
    summary = Path(result["official_summary_path"])
    langfuse_export.export_run(output, summary, client=client)
    assert (
        langfuse_export.verify_run(output, summary, client=client)["status"]
        == "VERIFIED"
    )
    assert any(
        "snapshot.docs/a.v1.txt" in call.get("expand_metadata", "") for call in calls
    )
    extra = True
    mismatch = langfuse_export.verify_run(output, summary, client=client)
    assert mismatch["status"] == "MISMATCH"
    assert any(
        "metadata_snapshot_mismatch" in error
        for row in mismatch["failed_checks"]
        for error in row["errors"]
    )


@pytest.mark.parametrize(
    "corruption", [None, "missing", "parent", "payload", "sha", "original"]
)
def test_lossless_supplement_requires_exact_proof_and_original_values(
    config, official_transport, tmp_path, monkeypatch, corruption
):
    pytest.importorskip("langfuse", reason="requires agent-evaluator[langfuse]")
    from eval_framework.benchmark import langfuse_export

    config["task_ids"] = ["0"]
    output = tmp_path / "lossless-export"
    result = harness().run_tau_harness(config, output)
    result["trials"][0]["observation"]["events"][0]["snapshot"] = {
        "input.txt": '{\n  "count": 1,\n  "status": "review"\n}\n',
        "keep.txt": "unchanged\n",
    }
    source = json.dumps(result).encode()
    (output / "results.json").write_bytes(source)
    client = SavedLangfuse()
    corrupt_original = False
    corrupt_proof = None

    def parsed_page(**kwargs):
        rows = client.observation_page(**kwargs).model_dump()["data"]
        for row in rows:
            row["metadata"] = langfuse_export._flatten_metadata(
                langfuse_export._metadata_with_json_values(row["metadata"])
            )
            if corrupt_original and "snapshot.input.txt.count" in row["metadata"]:
                row["metadata"]["snapshot.input.txt.count"] = 999
            if row["metadata"].get("is_export_evidence"):
                if corrupt_proof == "parent":
                    row["parent_observation_id"] = "wrong-parent"
                elif corrupt_proof in ("payload", "sha"):
                    key = (
                        "exact_metadata_base64"
                        if corrupt_proof == "payload"
                        else "exact_metadata_sha256"
                    )
                    row["metadata"][key] += "tampered"
        return client.page(rows)

    client.observations.get_many = parsed_page
    monkeypatch.setattr(langfuse_export, "destination_fingerprint", lambda: "offline")
    summary = Path(result["official_summary_path"])
    langfuse_export.export_run(output, summary, client=client)
    original_receipt = (output / "langfuse_export.json").read_bytes()
    assert (
        langfuse_export.verify_run(output, summary, client=client)["status"]
        == "MISMATCH"
    )
    original_spans = [span.model_dump() for span in client.spans]
    receipt = langfuse_export.export_metadata_evidence(output, summary, client=client)
    assert receipt["observations"] == 1
    assert [span.model_dump() for span in client.spans[:-1]] == original_spans
    langfuse_export.export_metadata_evidence(output, summary, client=client)
    assert len(client.spans) == len(original_spans) + 1
    corrupt_proof = corruption
    if corruption == "missing":
        client.spans.pop()
    elif corruption == "original":
        corrupt_original = True
    verification = langfuse_export.verify_run(output, summary, client=client)
    assert verification["status"] == ("VERIFIED" if corruption is None else "MISMATCH")
    assert (output / "results.json").read_bytes() == source
    assert (output / "langfuse_export.json").read_bytes() == original_receipt
    saved = json.loads((output / "langfuse_verification.json").read_text())
    assert saved["supplemental_evidence"]["status"] == verification["status"]
    assert saved["supplemental_evidence"]["observations"] == 1


def test_tau_identity_covers_runtime_source_hash_implementation(
    config, official_transport, tmp_path
):
    from eval_framework.benchmark.runner import code_identity

    result = harness().run_tau_harness(config, tmp_path / "bound-source")
    assert result["identity"]["harness_source"] == code_identity(
        [
            "tau_harness.py",
            "tau_adapter.py",
            "tau_worker.py",
            "nanobot_runtime.py",
            "inspect_docker.py",
        ]
    )


@pytest.mark.parametrize("changed_file", ["nanobot_runtime.py", "inspect_docker.py"])
def test_tau_source_hash_dependency_drift_aborts_export(
    config, official_transport, tmp_path, monkeypatch, changed_file
):
    module = harness()
    calls = 0

    def identity(names):
        nonlocal calls
        calls += 1
        return "changed" if calls > 1 and changed_file in names else "initial"

    monkeypatch.setattr(module, "code_identity", identity)
    output = tmp_path / "source-drift"
    with pytest.raises(ValueError, match="implementation changed"):
        module.run_tau_harness(config, output)
    assert not (output / "results.json").exists()
    assert (output / "official/summary.json").exists()


@pytest.mark.parametrize("span_id", ["1234567890123456", "5347207e68077799"])
def test_saved_langfuse_keeps_numeric_looking_identifiers_as_strings(span_id):
    client = SavedLangfuse()
    client.spans = [
        SimpleNamespace(
            span_id=span_id,
            attributes=[
                SimpleNamespace(
                    key="langfuse.experiment.id",
                    value=SimpleNamespace(string_value="experiment"),
                ),
                SimpleNamespace(
                    key="langfuse.experiment.item.root_observation_id",
                    value=SimpleNamespace(string_value=span_id),
                ),
                SimpleNamespace(
                    key="langfuse.observation.input",
                    value=SimpleNamespace(string_value='{"tool":"read_file"}'),
                ),
            ],
        )
    ]
    assert client.experiment_page("experiment").model_dump()["data"] == [
        {"id": span_id}
    ]
    assert client.attrs(client.spans[0])["langfuse.observation.input"] == {
        "tool": "read_file"
    }
