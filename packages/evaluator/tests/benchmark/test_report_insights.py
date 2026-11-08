"""报告解释须有证据绑定，估算不得冒充账单或修改历史结果。"""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

from eval_framework.benchmark.report import write_report

from .test_report import saved_run


def failure_run(tmp_path):
    run = saved_run()
    run.pop("summary")
    run["planned_case_ids"] = ["case-one"]
    row = run["trials"][0]
    row["assessment"].update(
        verdict="FAIL",
        metrics=[
            {
                "name": "status_match",
                "success": False,
                "formal": True,
                "reason": json.dumps(
                    {"expected": "NEED_CONFIRMATION", "actual": "NEED_CLARIFICATION"}
                ),
            }
        ],
    )
    row["observation"]["events"] = [
        {
            "id": "gen-1",
            "type": "generation",
            "turn": 1,
            "input": {"messages": [{"role": "user", "content": "给用户42发礼物7"}]},
            "output": {
                "content": json.dumps(
                    {
                        "intent": "add_backpack_gift",
                        "status": "NEED_CONFIRMATION",
                        "parameters": {"user_id": 42, "gift_id": 7, "count": 1},
                    }
                )
            },
        },
        {
            "id": "validate-1",
            "name": "intent_parameter_validation_failed",
            "turn": 1,
            "input": {"intent": "add_backpack_gift", "fields": ["count"]},
        },
        {
            "id": "decision-1",
            "name": "intent_decided",
            "turn": 1,
            "input": {
                "intent": "add_backpack_gift",
                "status": "NEED_CLARIFICATION",
                "missing_parameters": ["count"],
            },
        },
    ]
    contract = {
        "capability_id": "add_backpack_gift",
        "contract_version": "intent-contract-v1",
        "decision_rules": {"execution_mode": "write"},
        "parameters_schema": {
            "additionalProperties": False,
            "properties": {
                "num": {},
                "duration_days": {},
                "user_id": {},
                "gift_id": {},
            },
        },
    }
    bundle = tmp_path / "bundle"
    (bundle / "intents").mkdir(parents=True)
    path = bundle / "intents/add_backpack_gift.json"
    path.write_text(json.dumps(contract))
    run["config"] = {"capability_bundle": str(bundle)}
    run["identity"]["dataset"]["files"] = {
        "capability_bundle/intents/add_backpack_gift.json": hashlib.sha256(
            path.read_bytes()
        ).hexdigest(),
    }
    from eval_framework.benchmark.report_diagnostics import profile_hash

    profile = {
        "schema_version": "report-diagnostics-v1",
        "profile_id": "fixture",
        "profile_version": "1",
        "aliases": {
            "add_backpack_gift": {
                "count": "num",
                "validity_days": "duration_days",
                "valid_days": "duration_days",
            }
        },
    }
    profile["sha256"] = profile_hash(profile)
    (tmp_path / "report-diagnostics.json").write_text(json.dumps(profile))
    return run


def render(tmp_path, run):
    path = tmp_path / "results.json"
    path.write_text(json.dumps(run))
    original = path.read_bytes()
    report = write_report(tmp_path, format="domain").read_text()
    assert path.read_bytes() == original
    return report


def test_failure_explains_rejected_present_field_with_evidence_links(tmp_path):
    report = render(tmp_path, failure_run(tmp_path))
    assert "需要确认" in report and "要求补充参数" in report
    assert "契约未声明的字段" in report and "count=1" in report
    assert "num" in report and "duration_days" in report
    assert "问题摘要" in report and "下一步建议" in report
    assert 'href="#event-' in report
    assert "写操作：0/1 通过" in report
    # Technical reasons stay available, but never as the leading red JSON blob.
    assert '<p class="failure-reason">{&quot;expected&quot;' not in report
    assert "原始评分证据" in report


def test_missing_contract_does_not_claim_schema_mismatch(tmp_path):
    run = failure_run(tmp_path)
    run["config"] = {}
    report = render(tmp_path, run)
    assert "模型已提供字段，但执行校验拒绝" in report
    assert "契约未声明的字段" not in report
    assert "根因待核实" in report


def test_contract_hash_mismatch_cannot_supply_diagnosis(tmp_path):
    run = failure_run(tmp_path)
    (tmp_path / "bundle/intents/add_backpack_gift.json").write_text("{}")
    report = render(tmp_path, run)
    assert "契约未声明的字段" not in report
    assert "Hash 不匹配" in report


@pytest.mark.parametrize("history_present", [False, True])
def test_confirmation_diagnosis_requires_observed_missing_context(
    tmp_path, history_present
):
    run = failure_run(tmp_path)
    events = run["trials"][0]["observation"]["events"]
    messages = [{"role": "system", "content": "Classify intent."}]
    if history_present:
        messages.append({"role": "user", "content": "给用户42发礼物7"})
    messages.append({"role": "user", "content": "确认发放"})
    events.append(
        {
            "id": "gen-2",
            "type": "generation",
            "turn": 2,
            "input": {"messages": messages},
            "output": {
                "content": json.dumps(
                    {"parameters": {}, "status": "NEED_CLARIFICATION"}
                )
            },
        }
    )
    report = render(tmp_path, run)
    assert ("确认轮请求未携带前轮参数" in report) is not history_present


def test_non_json_reason_and_untrusted_values_remain_escaped(tmp_path):
    run = failure_run(tmp_path)
    attack = '<img src=x onerror="alert(1)">'
    run["trials"][0]["assessment"]["metrics"][0]["reason"] = attack
    report = render(tmp_path, run)
    assert attack not in report
    assert "&lt;img" in report


def test_evidence_links_are_scoped_to_trial_when_event_ids_repeat(tmp_path):
    from bs4 import BeautifulSoup

    run = failure_run(tmp_path)
    row = copy.deepcopy(run["trials"][0])
    row["case_id"] = "case-two"
    run["planned_case_ids"].append("case-two")
    run["trials"].append(row)
    soup = BeautifulSoup(render(tmp_path, run), "html.parser")
    ids = [node["id"] for node in soup.select(".event[id]")]
    assert len(ids) == len(set(ids))
    for trial in soup.select(".trial"):
        for link in trial.select('.finding a[href^="#event-"]'):
            assert trial.select_one(link["href"]) is not None


def test_estimate_handles_inclusive_exclusive_cache_and_missing_usage(tmp_path):
    from eval_framework.benchmark.report_insights import estimate_cost

    pricing = {
        "model": "test-model",
        "base_url": "https://example.test/v1",
        "source": "https://example.test/prices",
        "checked_at": "2026-11-07",
        "kind": "subscription_allowance",
        "rates_per_million": [
            {"label": "low", "input": 0.15, "output": 0.60, "cache_read": 0.003},
            {"label": "high", "input": 0.30, "output": 1.20, "cache_read": 0.006},
        ],
    }
    run = saved_run()
    run["config"] = {"model": "test-model", "base_url": "https://example.test/v1"}
    usage = {
        "input_tokens": 5946,
        "output_tokens": 668,
        "cached_tokens": 1024,
        "total_tokens": 7638,
        "cache_write_tokens": 0,
    }
    estimate = estimate_cost(run, [usage], pricing)
    assert estimate["low"] == pytest.approx(0.001295772)
    assert estimate["high"] == pytest.approx(0.002591544)
    inclusive = {**usage, "input_tokens": 6970}
    assert estimate_cost(run, [inclusive], pricing)["low"] == estimate["low"]
    for field in ("cached_tokens", "input_tokens", "output_tokens"):
        assert estimate_cost(run, [{**usage, field: None}], pricing) is None
    assert estimate_cost(run, [{**usage, "total_tokens": 8000}], pricing) is None
    assert estimate_cost(run, [{**usage, "cache_write_tokens": 10}], pricing) is None
    assert estimate_cost(run, [{**usage, "cache_write_tokens": None}], pricing) is None
    assert (
        estimate_cost(
            run,
            [{**usage, "cache_write_tokens": None}],
            {**pricing, "cache_write_pricing": "not_applicable"},
        )["low"]
        == estimate["low"]
    )
    other = copy.deepcopy(run)
    other["config"]["base_url"] = "https://other.test/v1"
    assert estimate_cost(other, [usage], pricing) is None
    assert (
        estimate_cost(run, [usage], {**pricing, "source": "javascript:alert(1)"})
        is None
    )


def test_native_cache_recovery_is_bound_to_exact_saved_records(tmp_path, monkeypatch):
    from inspect_ai import Task
    from inspect_ai import eval as inspect_eval
    from inspect_ai.dataset import Sample
    from inspect_ai.model import ModelOutput, ModelUsage, get_model
    from inspect_ai.scorer import Score, scorer
    from inspect_ai.solver import generate

    from eval_framework.benchmark.report_insights import report_usage
    from eval_framework.benchmark.runner import digest

    monkeypatch.setenv("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    run = saved_run()
    run.pop("summary")
    run["planned_case_ids"] = ["case-one"]
    run["identity"]["harness_version"] = "file-harness-inspect-v4"
    run["identity_hash"] = digest(run["identity"])
    row = run["trials"][0]
    row["identity_hash"] = run["identity_hash"]
    row["observation"]["usage"] = {
        "prompt_tokens": 20,
        "completion_tokens": 4,
        "total_tokens": 34,
    }

    @scorer(metrics=[])
    def save():
        async def score(state, target):
            return Score(
                value="PASS", metadata={"benchmark_record": copy.deepcopy(row)}
            )

        return score

    output = ModelOutput.from_content("mockllm/model", "hi")
    output.usage = ModelUsage(
        input_tokens=20, output_tokens=4, total_tokens=34, input_tokens_cache_read=10
    )
    inspect_eval(
        Task(
            dataset=[Sample(id="case-one", input="hi")],
            solver=generate(),
            scorer=save(),
            metadata={"identity_hash": run["identity_hash"]},
        ),
        model=get_model("mockllm/model", custom_outputs=[output]),
        log_dir=str(tmp_path / "inspect"),
        display="none",
        notification=False,
        ctl_server=False,
        log_realtime=False,
    )
    original = copy.deepcopy(run)
    usage, sources, warnings = report_usage(tmp_path, run)
    assert usage[0]["cached_tokens"] == 10
    assert sources and not warnings
    assert run == original
    row["observation"]["usage"]["prompt_tokens"] = 19
    usage, _, warnings = report_usage(tmp_path, run)
    assert usage[0]["cached_tokens"] is None
    assert warnings


def bind_tasks(tmp_path, run, tasks):
    path = tmp_path / "tasks.jsonl"
    path.write_text("\n".join(json.dumps(t) for t in tasks))
    run["identity"]["dataset"]["files"]["tasks.jsonl"] = hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


def test_task_goal_survives_wrong_or_mixed_model_intents(tmp_path):
    run = failure_run(tmp_path)
    bind_tasks(
        tmp_path,
        run,
        [
            {
                "id": "case-one",
                "oracle": {"expected_module_output": {"intent": "add_backpack_gift"}},
            }
        ],
    )
    run["trials"][0]["observation"]["events"][0]["output"]["content"] = (
        '{"intent":"unsupported"}'
    )
    report = render(tmp_path, run)
    assert "写操作：0/1 通过" in report
    assert "按冻结任务目标分组" in report
    # A modified dataset must never silently supply the report classification.
    (tmp_path / "tasks.jsonl").write_text("{}")
    report = render(tmp_path, run)
    assert "写操作：0/1 通过" not in report
    assert "任务文件 Hash 不匹配" in report


def test_repeated_diagnosis_has_one_summary_and_compact_trial_references(tmp_path):
    from bs4 import BeautifulSoup

    run = failure_run(tmp_path)
    row = copy.deepcopy(run["trials"][0])
    row["case_id"] = "case-two"
    run["planned_case_ids"].append("case-two")
    run["trials"].append(row)
    soup = BeautifulSoup(render(tmp_path, run), "html.parser")
    assert [td.get_text() for td in soup.select_one("#issue-1 tbody tr").select("td")] == ["count → num", "2"]
    for trial in soup.select(".trial"):
        finding = trial.select_one(".finding")
        assert "同问题 #1" in finding.get_text()
        assert finding.select_one("details") is not None
        assert finding.select_one('a[href="#issue-1"]') is not None


def test_business_failure_and_restricted_response_get_distinct_diagnoses(tmp_path):
    run = failure_run(tmp_path)
    row = run["trials"][0]
    row["observation"]["events"] = []
    row["observation"]["turns"] = [
        {
            "status": "SUCCESS",
            "tool_calls": [
                {
                    "status": "SUCCESS",
                    "output": {"success": False, "code": "BUSINESS_FAILURE"},
                }
            ],
        }
    ]
    row["assessment"]["metrics"] = [
        {"name": "tool_result_consistent", "success": False, "reason": "{}"}
    ]
    report = render(tmp_path, run)
    assert "业务失败状态传播不一致" in report
    row["observation"]["turns"] = [
        {
            "status": "FAILED",
            "tool_calls": [],
            "final_response": "InvalidModelOutputError: no text",
        }
    ]
    row["assessment"]["metrics"] = [
        {"name": "tool_not_called", "success": True},
        {"name": "response_consistent", "success": False, "reason": "{}"},
    ]
    report = render(tmp_path, run)
    assert "工具未调用，但错误回复不符合预期" in report
    assert "没有观察到越权工具调用" in report


def test_prompt_contract_gap_requires_actual_schema_evidence(tmp_path):
    run = failure_run(tmp_path)
    event = run["trials"][0]["observation"]["events"][0]
    schema = {
        "properties": {"parameters": {"type": "object", "additionalProperties": True}}
    }
    event["input"]["messages"].insert(
        0, {"role": "system", "content": json.dumps(schema)}
    )
    report = render(tmp_path, run)
    assert "parameters 允许任意字段" in report
    schema["properties"]["parameters"]["properties"] = {"num": {}, "duration_days": {}}
    event["input"]["messages"][0]["content"] = json.dumps(schema)
    report = render(tmp_path, run)
    assert "parameters 允许任意字段" not in report


def test_latency_explains_calls_without_claiming_retries(tmp_path):
    run = failure_run(tmp_path)
    row = run["trials"][0]
    row["latency_seconds"] = 83.0
    e = row["observation"]["events"][0]
    e.update(start_time="2026-11-07T00:00:00Z", end_time="2026-11-07T00:01:07Z")
    report = render(tmp_path, run)
    assert "耗时解释" in report
    assert "67.00" in report
    assert "不能仅凭调用次数判定重试" in report


def test_chain_failure_summary_is_not_hidden(tmp_path):
    run = failure_run(tmp_path)
    row = run["trials"][0]
    row["category"] = "read-tool-chain"
    row["evaluation_level"] = "chain"
    assert "read-tool-chain：0/1 通过（0.0%）" in render(tmp_path, run)


def test_zero_expected_tool_calls_still_classify_write_goal(tmp_path):
    from eval_framework.benchmark.report_insights import task_mode

    contracts = {
        "grant": {
            "required_tool_name": "grant_tool",
            "decision_rules": {"execution_mode": "write"},
        }
    }
    task = {"oracle": {"expected_tool_calls": [{"name": "grant_tool", "count": 0}]}}
    assert task_mode(task, contracts) == "write"


def test_alias_counts_deduplicate_turns_and_split_pages_link_to_summary(tmp_path):
    from bs4 import BeautifulSoup

    from eval_framework.benchmark.report import _write_trial_page
    from eval_framework.benchmark.report_insights import diagnose, load_contracts

    run = failure_run(tmp_path)
    row = run["trials"][0]
    extra = copy.deepcopy(row["observation"]["events"][:2])
    for event in extra:
        event["turn"] = 2
        event["id"] += "-second"
    row["observation"]["events"].extend(extra)
    soup = BeautifulSoup(render(tmp_path, run), "html.parser")
    assert [td.get_text() for td in soup.select_one("#issue-1 tbody tr").select("td")] == ["count → num", "1"]
    contracts, _ = load_contracts(run)
    row["_report_findings"] = diagnose(row, contracts)
    for f in row["_report_findings"]:
        f["number"] = 1
    page = _write_trial_page(tmp_path, run, row)
    soup = BeautifulSoup((tmp_path / page).read_text(), "html.parser")
    assert soup.select_one('a[href="../report.html#issue-1"]') is not None


def test_latency_with_incomplete_generation_stays_unknown(tmp_path):
    run = failure_run(tmp_path)
    run["trials"][0]["observation"]["events"][0].update(
        start_time="2026-11-07T00:00:00Z", end_time=None
    )
    report = render(tmp_path, run)
    assert "模型调用耗时累计 未知（时间证据不全）" in report


def test_unknown_trial_latency_does_not_break_report(tmp_path):
    run = failure_run(tmp_path)
    row = copy.deepcopy(run["trials"][0])
    row["case_id"] = "case-two"
    row["latency_seconds"] = 2.0
    run["planned_case_ids"].append("case-two")
    run["trials"].append(row)
    run["trials"][0]["latency_seconds"] = None
    assert "总耗时 未知 秒" in render(tmp_path, run)


def test_issue_links_resolve_to_unique_trial_anchors(tmp_path):
    from bs4 import BeautifulSoup
    run = failure_run(tmp_path)
    duplicate = copy.deepcopy(run['trials'][0])
    duplicate['trial'] = 2
    run['trials_per_case'] = 2
    run['trials'].append(duplicate)
    soup = BeautifulSoup(render(tmp_path, run), 'html.parser')
    trial_ids = {row['id'] for row in soup.select('.trial')}
    assert len(trial_ids) == 2
    targets = {a['href'][1:] for a in soup.select('#issue-1 a[href^="#trial-"]') if a['href'] != '#trial-results'}
    assert targets == trial_ids
    assert all(row['data-issues'] == '1' for row in soup.select('.trial'))
    assert soup.select_one('#issue option[value="1"]')
