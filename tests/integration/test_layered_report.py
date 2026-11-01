"""The portfolio report summarizes saved evidence without executing an Agent."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/build_layered_report.py"


def module():
    spec = importlib.util.spec_from_file_location("layered_report", SCRIPT)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def save_run(tmp_path, name, mode, level, *, repeat=1, judge=False):
    identity = {"dataset": {"dataset_id": "v2"}, "offline": False}
    identity_hash = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    rows = []
    for trial in range(1, repeat + 1):
        rows.append(
            {
                "case_id": name,
                "family": "family-" + name,
                "trial": trial,
                "execution_mode": mode,
                "evaluation_level": level,
                "split": "dev",
                "category": "demo",
                "assessment": {
                    "verdict": "PASS" if trial == 1 else "FAIL",
                    "validity": "VALID",
                    "metrics": [
                        {
                            "name": "tool_schema",
                            "scope": "tool",
                            "event_id": "tool1",
                            "score": 1,
                            "status": "SCORED",
                            "formal": False,
                            "version": "v1",
                            "reason": "DO_NOT_PUBLISH_REASON",
                        }
                    ],
                },
                "observation": {
                    "events": [{"input": "DO_NOT_PUBLISH_PROMPT"}],
                    "usage": {"input_tokens": 10, "output_tokens": 2, "cost_usd": None},
                },
            }
        )
    run = {
        "run_id": name,
        "identity": identity,
        "identity_hash": identity_hash,
        "mode": "real_module"
        if mode == "module"
        else "real_model_decision"
        if mode == "decision"
        else "real_agent",
        "planned_case_ids": [name],
        "trials_per_case": repeat,
        "trials": rows,
        "config": {"api_key": "DO_NOT_PUBLISH_KEY"},
        "finished_at": "2026-11-01T00:00:00Z",
    }
    if judge:
        run["provenance"] = {
            "operation": "judge_saved_evidence",
            "source_results_sha256": "sourcehash",
            "new_agent_executions": 0,
            "judge_repeats": 2,
        }
        for row in rows:
            for r, score in [(1, 0.2), (2, 0.8)]:
                row["assessment"]["metrics"].append(
                    {
                        "metric_id": "quality",
                        "name": "response_groundedness",
                        "scope": "turn",
                        "event_id": "turn1",
                        "score": score,
                        "status": "SCORED",
                        "formal": False,
                        "version": "v1",
                        "judge_repeat": r,
                        "events": [
                            {
                                "usage": {
                                    "input_tokens": 4,
                                    "output_tokens": 1,
                                    "cost_usd": None,
                                },
                                "input": "DO_NOT_PUBLISH_JUDGE_PROMPT",
                            }
                        ],
                    }
                )
            row["assessment"]["metrics"].append(
                {
                    "metric_id": "recovery",
                    "name": "recovery_appropriateness",
                    "scope": "task",
                    "score": None,
                    "status": "NOT_APPLICABLE",
                    "formal": False,
                    "version": "v1",
                    "judge_repeat": 1,
                    "events": [],
                }
            )
    path = tmp_path / name
    path.mkdir()
    (path / "results.json").write_text(json.dumps(run))
    return path


def test_four_populations_and_judge_reannotations_are_separate(tmp_path):
    builder = module()
    runs = [
        save_run(tmp_path, "modules", "module", "module"),
        save_run(tmp_path, "decisions", "decision", "module", repeat=3),
        save_run(tmp_path, "chains", "agent", "chain", repeat=3),
        save_run(tmp_path, "e2e", "agent", "e2e"),
    ]
    judged = save_run(tmp_path, "judged", "agent", "chain", judge=True)
    summary = builder.build_report(runs, [judged], tmp_path / "public")
    assert summary["executions"]["trials"] == 8
    assert summary["executions"]["instances"] == 4
    assert set(summary["populations"]) == {
        "program_module",
        "model_decision",
        "critical_chain",
        "end_to_end",
    }
    assert summary["populations"]["critical_chain"]["all_repeats_pass_tasks"] == 0
    assert summary["populations"]["program_module"]["model_success_rate"] is None
    assert summary["judge"]["new_agent_executions"] == 0
    assert summary["judge"]["scored"] == 2
    assert summary["judge"]["applicable"] == 2
    assert summary["judge"]["not_applicable"] == 1
    assert summary["judge"]["coverage"] == 1
    assert summary["judge"]["stability"]["mean_range"] == pytest.approx(0.6)
    assert summary["judge"]["usage"]["input_tokens"] == 8
    assert summary["judge"]["human_calibration"] == "pending_independent_labels"
    assert summary["tau"]["status"] == "not_supplied"
    assert len(summary["questions"]) == 7


def test_public_outputs_do_not_copy_prompts_credentials_or_absolute_source_paths(
    tmp_path,
):
    run = save_run(tmp_path, "e2e", "agent", "e2e")
    judged = save_run(tmp_path, "judged", "agent", "e2e", judge=True)
    output = tmp_path / "public"
    summary = module().build_report([run], [judged], output)
    for filename in ["summary.json", "results.jsonl", "index.html", "README.md"]:
        text = (output / filename).read_text()
        assert "DO_NOT_PUBLISH" not in text
        assert str(tmp_path) not in text
    page = (output / "index.html").read_text()
    assert "<script src=" not in page
    assert "fetch(" not in page
    assert "tool_schema" in page
    assert "数据流" in page
    assert (
        summary["sources"][0]["sha256"]
        == hashlib.sha256((run / "results.json").read_bytes()).hexdigest()
    )
    assert summary["sources"][0]["file"] == "e2e/results.json"


def test_incomplete_or_duplicate_execution_is_rejected(tmp_path):
    run = save_run(tmp_path, "chain", "agent", "chain", repeat=3)
    source = json.loads((run / "results.json").read_text())
    source["trials"].pop()
    (run / "results.json").write_text(json.dumps(source))
    with pytest.raises(ValueError, match="complete"):
        module().build_report([run], [], tmp_path / "public")
    assert not (tmp_path / "public/summary.json").exists()


def test_reannotations_cannot_be_counted_as_execution_runs(tmp_path):
    run = save_run(tmp_path, "judged", "agent", "e2e", judge=True)
    with pytest.raises(ValueError, match="annotation"):
        module().build_report([run], [], tmp_path / "public")


def test_duplicate_input_run_cannot_inflate_executions(tmp_path):
    run = save_run(tmp_path, "e2e", "agent", "e2e")
    with pytest.raises(ValueError, match="duplicate"):
        module().build_report([run, run], [], tmp_path / "public")


def test_tau_status_without_trial_evidence_is_unverified(tmp_path):
    run = save_run(tmp_path, "e2e", "agent", "e2e")
    tau = tmp_path / "tau.json"
    tau.write_text(
        json.dumps({"status": "complete", "config": {"api_key": "DO_NOT_PUBLISH_KEY"}})
    )
    result = module().build_report([run], [], tmp_path / "public", tau_run=tau)
    assert result["tau"]["status"] == "pending_or_unverified"
    assert "DO_NOT_PUBLISH" not in (tmp_path / "public/summary.json").read_text()


def test_official_tau_rewards_keep_valid_and_planned_denominators(tmp_path):
    run = save_run(tmp_path, "e2e", "agent", "e2e")
    tau = tmp_path / "tau"
    tau.mkdir()
    (tau / "summary.json").write_text(
        json.dumps(
            {
                "status": "PARTIAL",
                "task_ids": ["a", "b"],
                "num_trials": 1,
                "source_identity": {
                    "repository": "https://github.com/sierra-research/tau2-bench",
                    "commit": "abc",
                    "local_path": "DO_NOT_PUBLISH_PATH",
                },
                "results": [
                    {"task_id": "a", "trial": 1, "official_reward": 0.5},
                    {
                        "task_id": "b",
                        "trial": 1,
                        "official_reward": None,
                        "verdict": "INVALID",
                    },
                ],
            }
        )
    )
    result = module().build_report([run], [], tmp_path / "public", tau_run=tau)
    assert result["tau"]["status"] == "pilot_partial"
    assert result["tau"]["planned_trials"] == 2
    assert result["tau"]["valid_reward_trials"] == 1
    assert result["tau"]["mean_official_reward"] == 0.5
    assert result["tau"]["official_leaderboard_result"] is False
    assert "DO_NOT_PUBLISH_PATH" not in (tmp_path / "public/summary.json").read_text()


def test_trace_receipt_is_source_bound_and_query_credentials_are_removed(tmp_path):
    run = save_run(tmp_path, "e2e", "agent", "e2e")
    receipt = {
        "source_hash": hashlib.sha256((run / "results.json").read_bytes()).hexdigest(),
        "status": "VERIFIED",
        "counts": {"trials": 1},
        "traces": [
            {
                "case_id": "e2e",
                "trial": 1,
                "trace_id": "trace1",
                "trace_url": "https://trace.example/project/test/traces/trace1?token=DO_NOT_PUBLISH_TOKEN",
            }
        ],
    }
    (run / "langfuse_export.json").write_text(json.dumps(receipt))
    output = tmp_path / "public"
    summary = module().build_report([run], [], output)
    assert summary["runs"][0]["langfuse"]["status"] == "VERIFIED"
    assert len(summary["sources"]) == 2
    assert "DO_NOT_PUBLISH_TOKEN" not in (output / "index.html").read_text()
    assert (
        json.loads((output / "results.jsonl").read_text())["trace_link"]
        == "https://trace.example/project/test/traces/trace1"
    )
    receipt["source_hash"] = "wrong-source"
    (run / "langfuse_export.json").write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="receipt"):
        module().build_report([run], [], tmp_path / "wrong")


def test_raw_execution_and_regrade_cannot_double_count_same_trials(tmp_path):
    raw = save_run(tmp_path, "e2e", "agent", "e2e", repeat=3)
    regraded = json.loads((raw / "results.json").read_text())
    regraded["run_id"] = "e2e-regraded-v2.1"
    regraded["execution_run_id"] = "e2e"
    regraded["regrade"] = {
        "operation": "regrade_saved_evidence",
        "source_run_id": "e2e",
        "new_agent_executions": 0,
    }
    directory = tmp_path / "regraded"
    directory.mkdir()
    (directory / "results.json").write_text(json.dumps(regraded))
    with pytest.raises(ValueError, match="duplicate execution"):
        module().build_report([raw, directory], [], tmp_path / "public")
    assert not (tmp_path / "public/summary.json").exists()
    result = module().build_report([directory], [], tmp_path / "only-regraded")
    assert result["executions"]["trials"] == 3
    assert result["executions"]["instances"] == 1


def test_calibration_starter_survives_regeneration_and_judge_run_counts_are_explicit(
    tmp_path,
):
    primary = save_run(tmp_path, "e2e", "agent", "e2e")
    judged = save_run(tmp_path, "judged", "agent", "e2e", judge=True)
    output = tmp_path / "public"
    output.mkdir()
    sample = output / "calibration-sample.json"
    original = (
        '{"status":"awaiting_independent_human_labels","rows":[{"human_score":null}]}\n'
    )
    sample.write_text(original)
    result = module().build_report([primary], [judged], output)
    assert sample.read_text() == original
    assert result["judge"]["by_run"][0]["scored"] == 2
    assert result["judge"]["by_run"][0]["configured_repeats"] == 2
    assert result["judge"]["stability"]["max_range"] == pytest.approx(0.6)
    assert (
        result["calibration_starter"]["sha256"]
        == hashlib.sha256(original.encode()).hexdigest()
    )
    assert 'href="calibration-sample.json"' in (output / "index.html").read_text()
    assert "含重复评审" in (output / "index.html").read_text()
    assert "calibration-sample.json" in (output / "README.md").read_text()


def test_existing_screenshot_is_linked_and_preserved_without_claiming_full_verification(
    tmp_path,
):
    primary = save_run(tmp_path, "e2e", "agent", "e2e")
    output = tmp_path / "public"
    builder = module()
    first = builder.build_report([primary], [], output)
    assert "langfuse_screenshot" not in first
    assert "langfuse-step-scores.png" not in (output / "index.html").read_text()
    screenshot = output / "langfuse-step-scores.png"
    original = b"existing-screenshot-fixture"
    screenshot.write_bytes(original)
    result = builder.build_report([primary], [], output)
    assert screenshot.read_bytes() == original
    assert result["langfuse_screenshot"]["sha256"] == hashlib.sha256(
        original
    ).hexdigest()
    assert result["langfuse_screenshot"]["scope"] == "single_ui_example"
    page = (output / "index.html").read_text()
    assert 'src="langfuse-step-scores.png"' in page
    assert "界面抽查与服务端回读分别说明各自覆盖范围" in page
    assert "读回验收已完成" not in page
    assert "langfuse-step-scores.png" in (output / "README.md").read_text()


def save_tau_with_verified_receipt(tmp_path):
    root = tmp_path / "tau-pilot"
    official = root / "official"
    official.mkdir(parents=True)
    summary = official / "summary.json"
    summary.write_text(
        json.dumps(
            {
                "status": "COMPLETED",
                "task_ids": ["0"],
                "num_trials": 1,
                "results": [{"task_id": "0", "trial": 1, "official_reward": 1.0}],
            }
        )
    )
    results = root / "results.json"
    results.write_text(
        json.dumps(
            {
                "mode": "real_agent_official_tau",
                "identity": {
                    "official_summary_sha256": hashlib.sha256(
                        summary.read_bytes()
                    ).hexdigest()
                },
                "config": {"api_key": "DO_NOT_PUBLISH_KEY"},
            }
        )
    )
    checksum = hashlib.sha256(results.read_bytes()).hexdigest()
    (root / "langfuse_export.json").write_text(
        json.dumps(
            {
                "source_hash": checksum,
                "status": "VERIFIED",
                "counts": {"trials": 1, "observations": 23, "scores": 2},
                "traces": [],
            }
        )
    )
    (root / "langfuse_verification.json").write_text(
        json.dumps(
            {
                "source_hash": checksum,
                "status": "VERIFIED",
                "trial_checks": [
                    {
                        "case_id": "tau/0",
                        "trial": 1,
                        "observations": 23,
                        "scores": 2,
                        "errors": [],
                    }
                ],
                "scope": "DO_NOT_PUBLISH_UNVALIDATED_METADATA",
            }
        )
    )
    return summary


def test_tau_verification_is_bound_to_official_summary_and_not_counted_as_file_trials(
    tmp_path,
):
    primary = save_run(tmp_path, "e2e", "agent", "e2e")
    tau = save_tau_with_verified_receipt(tmp_path)
    output = tmp_path / "public"
    summary = module().build_report([primary], [], output, tau_run=tau)
    assert summary["executions"]["trials"] == 1
    assert summary["executions"]["instances"] == 1
    receipt = summary["tau"]["langfuse"]
    assert receipt["status"] == "VERIFIED"
    assert receipt["verification_status"] == "VERIFIED"
    assert receipt["counts"]["observations"] == 23
    assert receipt["source_hash"] == hashlib.sha256(
        (tau.parent.parent / "results.json").read_bytes()
    ).hexdigest()
    assert receipt["official_summary_sha256"] == hashlib.sha256(
        tau.read_bytes()
    ).hexdigest()
    assert {item["file"] for item in summary["sources"]} >= {
        "official/summary.json",
        "tau-pilot/results.json",
        "tau-pilot/langfuse_export.json",
        "tau-pilot/langfuse_verification.json",
    }
    for filename in ["summary.json", "results.jsonl", "index.html", "README.md"]:
        text = (output / filename).read_text()
        assert "DO_NOT_PUBLISH" not in text
        assert str(tmp_path) not in text
    assert "Langfuse 已验证（VERIFIED）" in (output / "index.html").read_text()
    assert "Langfuse 已验证（VERIFIED）" in (output / "README.md").read_text()


@pytest.mark.parametrize("changed", ["summary", "receipt", "verification"])
def test_tau_rejects_unbound_summary_receipt_or_verification(tmp_path, changed):
    primary = save_run(tmp_path, "e2e", "agent", "e2e")
    tau = save_tau_with_verified_receipt(tmp_path)
    if changed == "summary":
        tau.write_text(tau.read_text() + "\n")
    else:
        kind = "export" if changed == "receipt" else "verification"
        filename = f"langfuse_{kind}.json"
        path = tau.parent.parent / filename
        data = json.loads(path.read_text())
        data["source_hash"] = "not-current-results"
        path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="(summary|receipt|verification)"):
        module().build_report([primary], [], tmp_path / "public", tau_run=tau)
    assert not (tmp_path / "public/summary.json").exists()


def save_verified_supplement(run):
    result_path = run / "results.json"
    result = json.loads(result_path.read_text())
    result["run_id"] += "-different-from-directory"
    result_path.write_text(json.dumps(result))
    checksum = hashlib.sha256(result_path.read_bytes()).hexdigest()
    original = run / "langfuse_export.json"
    original.write_text(
        json.dumps({"source_hash": checksum, "status": "ACCEPTED", "traces": []})
    )
    supplement = run / "langfuse_exact_metadata_export.json"
    supplement.write_text(
        json.dumps(
            {"source_hash": checksum, "status": "VERIFIED", "observations": 2}
        )
    )
    verification = run / "langfuse_verification.json"
    verification.write_text(
        json.dumps(
            {
                "source_hash": checksum,
                "status": "VERIFIED",
                "supplemental_evidence": {
                    "source_hash": checksum,
                    "status": "VERIFIED",
                    "observations": 2,
                    "receipt_path": str(supplement),
                    "receipt_sha256": hashlib.sha256(
                        supplement.read_bytes()
                    ).hexdigest(),
                },
            }
        )
    )
    return original, verification, supplement


def test_readback_supersedes_display_status_and_preserves_immutable_receipts(tmp_path):
    run = save_run(tmp_path, "chains", "agent", "chain")
    original, verification, supplement = save_verified_supplement(run)
    before = {p: p.read_bytes() for p in (original, verification, supplement)}
    output = tmp_path / "public"
    result = module().build_report([run], [], output)
    shown = result["runs"][0]["langfuse"]
    assert shown["status"] == "VERIFIED"
    assert shown["export_status"] == "ACCEPTED"
    assert shown["verification_status"] == "VERIFIED"
    assert shown["supplemental_evidence"]["status"] == "VERIFIED"
    assert {item["file"] for item in result["sources"]} >= {
        "chains/langfuse_export.json",
        "chains/langfuse_verification.json",
        "chains/langfuse_exact_metadata_export.json",
    }
    assert result["executions"]["trials"] == 1
    assert "Langfuse 已验证（VERIFIED）" in (output / "index.html").read_text()
    assert str(tmp_path) not in (output / "summary.json").read_text()
    assert all(p.read_bytes() == raw for p, raw in before.items())


@pytest.mark.parametrize(
    "changed",
    [
        "verification_source",
        "declared_source",
        "receipt_sha",
        "receipt_source",
        "status",
    ],
)
def test_readback_rejects_unbound_or_unverified_supplement(tmp_path, changed):
    run = save_run(tmp_path, "chains", "agent", "chain")
    _, verification, supplement = save_verified_supplement(run)
    data = json.loads(verification.read_text())
    if changed == "verification_source":
        data["source_hash"] = "wrong"
    elif changed == "declared_source":
        data["supplemental_evidence"]["source_hash"] = "wrong"
    elif changed == "receipt_sha":
        data["supplemental_evidence"]["receipt_sha256"] = "wrong"
    else:
        saved = json.loads(supplement.read_text())
        saved["source_hash" if changed == "receipt_source" else "status"] = "wrong"
        supplement.write_text(json.dumps(saved))
        data["supplemental_evidence"]["receipt_sha256"] = hashlib.sha256(
            supplement.read_bytes()
        ).hexdigest()
    verification.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="(verification|supplement)"):
        module().build_report([run], [], tmp_path / "public")
