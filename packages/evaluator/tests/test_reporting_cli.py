from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from test_execution_scoring import scripts

import eval_framework.reporting as reporting
from eval_framework import EvaluationRunResult, RunConfig, load_dataset, run_evaluation
from eval_framework.cli import main
from eval_framework.providers.mini_agent.provider import (
    model_client_factory_from_env,
)
from eval_framework.reporting import write_report


def test_scenario_type_labels_cover_the_evalcase_protocol():
    assert reporting.SCENARIO_TYPE_LABELS == {
        "normal": "正常指令",
        "valid_boundary": "合法边界",
        "invalid_parameter": "非法参数",
        "missing_parameter": "缺少参数",
        "ambiguous_expression": "表达歧义",
        "multi_condition": "多条件指令",
        "expression_variant": "表达变体",
        "correction_conflict": "更正／参数冲突",
        "unsupported_batch": "不支持批量",
    }


def test_reports_reload_match_summary_and_exclude_key(
    dataset_path, tmp_path, monkeypatch
):
    monkeypatch.setenv("OPENAI_API_KEY", "super-secret-fixture")
    dataset = load_dataset(dataset_path)
    dataset.cases = dataset.cases[:1]
    result = run_evaluation(dataset, RunConfig(run_mode="framework_self_test"), scripts)
    paths = write_report(result, tmp_path / "artifacts")
    restored = EvaluationRunResult.model_validate_json(
        open(paths.results, encoding="utf-8").read()
    )
    assert restored.model_dump(exclude={"run_directory"}) == result.model_dump(
        exclude={"run_directory"}
    )
    assert restored.run_directory == paths.output_dir
    assert restored.summary.framework_completion_rate == 100
    report = open(paths.report, encoding="utf-8").read()
    assert "评测结论：PASSED" in report
    assert "执行完成 | 1/1" in report
    summary = json.loads(open(paths.summary_json, encoding="utf-8").read())
    assert summary["run_verdict"] == "PASSED"
    jsonl_lines = open(paths.results_jsonl, encoding="utf-8").read().splitlines()
    assert len(jsonl_lines) == 1
    assert json.loads(jsonl_lines[0])["case_id"] == "MODULE-1"
    failures = json.loads(open(paths.failures, encoding="utf-8").read())
    assert failures == {"execution_errors": [], "quality_failures": []}
    for path in [
        paths.results,
        paths.manifest,
        paths.report,
        paths.summary_json,
        paths.results_jsonl,
        paths.failures,
        *paths.case_files,
    ]:
        assert "super-secret-fixture" not in open(path, encoding="utf-8").read()


def test_reproduction_section_uses_portable_table_and_manifest_link(
    dataset_path, tmp_path
):
    result = run_evaluation(
        load_dataset(dataset_path), RunConfig(run_mode="framework_self_test"), scripts
    )
    paths = write_report(result, tmp_path / "portable-report")
    report = Path(paths.report).read_text(encoding="utf-8")

    assert "## 运行与复现信息" in report
    assert "| 项目 | 内容 |" in report
    assert "| 运行模式 | `framework_self_test` |" in report
    assert f"| 数据集 | `{Path(result.dataset_path).name}` |" in report
    assert "[查看完整运行配置](run_manifest.json)" in report
    assert "<details>" not in report
    assert "<summary>" not in report
    assert result.dataset_path not in report
    assert result.dataset_hash not in report


def test_results_from_before_report_metadata_upgrade_still_reload(dataset_path):
    result = run_evaluation(
        load_dataset(dataset_path), RunConfig(run_mode="framework_self_test"), scripts
    )
    legacy = result.model_dump(mode="json")
    legacy.pop("dataset_total_cases")
    legacy.pop("dataset_lifecycle_state")
    legacy.pop("dataset_manifest_path")
    legacy.pop("trials_per_case")
    legacy["run_config"].pop("execution_type")

    restored = EvaluationRunResult.model_validate(legacy)

    assert restored.dataset_total_cases == 3
    assert restored.dataset_lifecycle_state == "UNKNOWN"
    assert restored.trials_per_case == 1


def test_legacy_mini_agent_version_migrates_to_agent_version(dataset_path):
    result = run_evaluation(
        load_dataset(dataset_path), RunConfig(run_mode="framework_self_test"), scripts
    )
    legacy = result.model_dump(mode="json")
    expected = legacy.pop("agent_version", None)
    if expected is None:
        expected = legacy["mini_agent_version"]
    legacy["mini_agent_version"] = expected

    restored = EvaluationRunResult.model_validate(legacy)

    assert restored.agent_version == expected


def test_equal_legacy_and_generic_versions_are_accepted(dataset_path):
    result = run_evaluation(
        load_dataset(dataset_path), RunConfig(run_mode="framework_self_test"), scripts
    )
    payload = result.model_dump(mode="json")
    version = payload.get("agent_version") or payload["mini_agent_version"]
    payload["agent_version"] = version
    payload["mini_agent_version"] = version

    restored = EvaluationRunResult.model_validate(payload)

    assert restored.agent_version == payload["agent_version"]


def test_conflicting_version_fields_are_rejected(dataset_path):
    result = run_evaluation(
        load_dataset(dataset_path), RunConfig(run_mode="framework_self_test"), scripts
    )
    payload = result.model_dump(mode="json")
    payload["mini_agent_version"] = (
        payload.get("agent_version") or payload["mini_agent_version"]
    )
    payload["agent_version"] = "different-version"

    with pytest.raises(ValidationError, match="version fields conflict"):
        EvaluationRunResult.model_validate(payload)


def test_new_results_and_manifest_only_write_agent_version(dataset_path, tmp_path):
    result = run_evaluation(
        load_dataset(dataset_path), RunConfig(run_mode="framework_self_test"), scripts
    )
    paths = write_report(result, tmp_path / "generic-version")
    results = json.loads(Path(paths.results).read_text())
    manifest = json.loads(Path(paths.manifest).read_text())

    assert results["agent_version"] == result.provider_version
    assert manifest["agent_version"] == result.provider_version
    assert "mini_agent_version" not in results
    assert "mini_agent_version" not in manifest


def test_human_report_explains_quality_failures(dataset_path, tmp_path):
    from conftest import intent
    from support.model_client import DeterministicModelClient as ScriptedModelClient

    dataset = load_dataset(dataset_path)
    dataset.cases = dataset.cases[:1]
    result = run_evaluation(
        dataset,
        RunConfig(run_mode="agent_benchmark", allow_non_frozen_dataset=True),
        lambda execution: ScriptedModelClient(
            [intent("unsupported", "REJECTED", "REJECT", {}, [])]
        ),
    )

    paths = write_report(result, tmp_path / "readable")
    report = open(paths.report, encoding="utf-8").read()

    assert "评测结论：FAILED" in report
    assert "严格断言通过 0 条、失败 1 条" in report
    assert "## 主要问题" in report
    assert "意图不匹配" in report
    assert (
        "| Case | 场景 | 场景类型 | 预期行为 | 实际行为 | 结论 | 首个偏差 | 延迟 |"
        in report
    )
    assert "| 正常指令 |" in report
    assert "准备调用工具：`query_information`" in report
    assert "| 得分 |" not in report
    assert "query fixture" in report
    assert "### MODULE-1" in report
    assert "失败断言" in report
    assert "预期" in report and "实际" in report
    assert "cases/MODULE-1/trial_001.json" in report
    assert "## 分组指标" not in report
    assert "中位延迟" in report
    assert "最大延迟" in report
    assert "平均断言得分" in report
    assert "单 Case 通过条件" in report
    assert "- 执行状态：" not in report
    assert paths.evidence_files
    assert all(Path(path).exists() for path in paths.evidence_files)


def test_report_uses_contract_labels_or_raw_fallback(capability_registry):
    assert (
        reporting._module_behavior_summary(
            {
                "intent": "query_user",
                "next_action": "CALL_TOOL",
                "parameters": {"user_id": 9075333},
                "missing_parameters": [],
            },
            capability_registry,
        )
        == "准备调用工具：`query_user`（`user_id=9075333`）"
    )
    assert (
        reporting._module_behavior_summary(
            {
                "intent": "query_user",
                "next_action": "ASK_USER",
                "parameters": {},
                "missing_parameters": ["user_id_or_room_id_or_email_or_phone"],
            },
            capability_registry,
        )
        == "追问：请提供user_id_or_room_id_or_email_or_phone"
    )


def test_missing_display_label_falls_back_to_raw_name(capability_registry):
    assert (
        reporting._module_behavior_summary(
            {
                "intent": "query_user",
                "next_action": "ASK_USER",
                "parameters": {},
                "missing_parameters": ["future_field"],
            },
            capability_registry,
        )
        == "追问：请提供future_field"
    )


def test_report_identifies_targeted_subset_lifecycle_and_single_trial(
    dataset_path, tmp_path
):
    dataset = load_dataset(dataset_path)
    dataset.lifecycle_state = "VALIDATED"
    dataset.cases = dataset.cases[:1]
    result = run_evaluation(
        dataset,
        RunConfig(
            run_mode="agent_benchmark",
            execution_type="targeted_smoke",
            allow_non_frozen_dataset=True,
        ),
        scripts,
    )

    paths = write_report(result, tmp_path / "subset")
    report = open(paths.report, encoding="utf-8").read()

    assert "数据集状态 | VALIDATED" in report
    assert "执行案例 | 1/3" in report
    assert "执行类型 | 定向冒烟" in report
    assert "每 Case Trial 数 | 1" in report
    assert "临时质量观察" in report


def test_validate_cli_success_and_invalid_exit(dataset_path, tmp_path):
    assert main(["validate", "--dataset", str(dataset_path)]) == 0
    bad = tmp_path / "bad.jsonl"
    bad.write_text("{}")
    assert main(["validate", "--dataset", str(bad)]) != 0


def test_manifest_has_required_reproducibility_fields(dataset_path, tmp_path):
    result = run_evaluation(
        load_dataset(dataset_path), RunConfig(run_mode="framework_self_test"), scripts
    )
    paths = write_report(result, tmp_path)
    manifest = json.loads(open(paths.manifest, encoding="utf-8").read())
    assert manifest["dataset"]["sha256"] == result.dataset_hash
    assert manifest["dataset"]["sample_count"] == 3
    assert manifest["dataset"]["total_case_count"] == 3
    assert manifest["dataset"]["executed_case_count"] == 3
    assert manifest["assertion_registry_version"] == "inspect-assertions-v1"
    assert manifest["core_behavior_policy_version"] == "core-behavior-v1"
    assert manifest["python_version"]


def test_model_client_factory_selects_deepseek(monkeypatch):
    marker = object()
    monkeypatch.setenv("MODEL_PROVIDER", "deepseek")
    monkeypatch.setattr(
        "eval_framework.providers.mini_agent.provider.DeepSeekModelClient.from_env",
        lambda *, timeout_seconds: (marker, timeout_seconds),
    )

    factory = model_client_factory_from_env()

    assert factory(SimpleNamespace(timeout_seconds=7)) == (marker, 7)


def test_model_client_factory_rejects_unknown_provider(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "unknown")

    try:
        model_client_factory_from_env()
    except ValueError as exc:
        assert "MODEL_PROVIDER" in str(exc)
    else:
        raise AssertionError("unknown provider must be rejected")


def _rehash_dataset_manifest(dataset_path):
    manifest_path = dataset_path.with_suffix(".manifest.json")
    manifest = json.loads(manifest_path.read_text())
    manifest["dataset_sha256"] = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))


@pytest.mark.parametrize(
    "failure", ["corrupt_bundle", "unknown_intent", "unknown_profile"]
)
def test_preflight_failure_writes_invalid_run_without_model_client(
    dataset_path, tmp_path, monkeypatch, failure
):
    created = False

    def forbidden_client(*args, **kwargs):
        nonlocal created
        created = True
        raise AssertionError("model client must not be created during preflight")

    monkeypatch.setattr(
        "eval_framework.providers.mini_agent.provider.DeepSeekModelClient.from_env",
        forbidden_client,
    )
    monkeypatch.setenv("MODEL_PROVIDER", "deepseek")
    if failure == "corrupt_bundle":
        dataset = load_dataset(dataset_path)
        bundle_file = Path(dataset.capability_bundle_path) / "intents/query_user.json"
        bundle_file.write_text("{}")
    else:
        rows = [json.loads(line) for line in dataset_path.read_text().splitlines()]
        if failure == "unknown_intent":
            rows[0]["oracle"]["expected_module_output"]["intent"] = "future_intent"
        else:
            rows[0]["execution"]["tool_profile"] = "future_profile"
        dataset_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        _rehash_dataset_manifest(dataset_path)

    output = tmp_path / "invalid-artifacts"
    code = main(
        [
            "run",
            "--dataset",
            str(dataset_path),
            "--output-dir",
            str(output),
            "--allow-non-frozen-dataset",
        ]
    )

    assert code == 2
    assert created is False
    records = list(output.glob("*/invalid_run.json"))
    reports = list(output.glob("*/report.md"))
    assert len(records) == len(reports) == 1
    assert json.loads(records[0].read_text())["verdict"] == "INVALID_RUN"
    report = reports[0].read_text()
    assert "评测结论：INVALID_RUN" in report
    assert "Agent 通过率" not in report
