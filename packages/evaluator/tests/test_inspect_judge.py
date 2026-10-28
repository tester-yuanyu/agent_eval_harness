"""Exercise the real Inspect model grader without a paid model."""

import asyncio
import json

import pytest
from inspect_ai.model import ModelOutput, ModelUsage, get_model

from eval_framework.judge import JudgeOutputError, JudgeTimeoutError
from eval_framework.phase2_schemas import JudgeDimensionSpec, JudgeRequest


def request():
    return JudgeRequest(
        user_input="Find the gift",
        final_response="Gift 42 is available",
        reference_facts={"gift_id": 42},
        tool_result_summaries=[{"name": "lookup", "output": {"found": True}}],
        dimensions=[JudgeDimensionSpec(name="clarity", weight=1, threshold=80)],
        dimension_instructions={"clarity": "Score response clarity."},
        rubric_id="semantic-response",
        rubric_version="1.0",
        prompt_version="judge-prompt-v1",
    )


def client_for(text, *, capture=None):
    from eval_framework.judges.inspect import InspectJudgeClient

    def output(messages, *_):
        if capture is not None:
            capture.extend(messages)
        output = ModelOutput.from_content(model="mockllm/judge", content=text)
        output.usage = ModelUsage(input_tokens=5, output_tokens=3, total_tokens=8)
        return output

    return InspectJudgeClient(
        get_model("mockllm/judge", custom_outputs=output), timeout_seconds=7
    )


def test_native_grader_preserves_dimension_evidence_and_numeric_grade():
    capture = []
    client = client_for("The response is clear.\nGRADE: 90", capture=capture)
    original = request()
    result = client.evaluate(original)
    assert result["dimensions"][0]["score"] == 90
    assert result["dimensions"][0]["reason"] == "The response is clear.\nGRADE: 90"
    assert result["token_usage"] == {"input_tokens": 5, "output_tokens": 3}
    prompt = "\n".join(m.text for m in capture)
    for fragment in ["Find the gift", "Gift 42", "gift_id", "found", "clarity"]:
        assert fragment in prompt
    assert original == request()
    assert client.metadata()["backend"] == "inspect_ai"
    assert client.metadata()["metric"] == "model_graded_qa"


@pytest.mark.parametrize("grade", [0, 50, 80, 100])
def test_numeric_grades_preserve_threshold_boundaries(grade):
    assert (
        client_for(f"Reason.\nGRADE: {grade}").evaluate(request())["dimensions"][0][
            "score"
        ]
        == grade
    )


@pytest.mark.parametrize(
    "text",
    [
        "no grade",
        "GRADE: 101",
        "GRADE: -1",
        "GRADE: NaN",
        "GRADE: 90\nGRADE: invalid",
        "GRADE: 90 extra",
        "",
    ],
)
def test_unparseable_or_out_of_range_grade_is_not_a_quality_score(text):
    with pytest.raises(JudgeOutputError):
        client_for(text).evaluate(request())


def test_shared_deadline_stops_slow_grader():
    from eval_framework.judges.inspect import InspectJudgeClient

    async def slow(*_):
        await asyncio.sleep(1)
        return ModelOutput.from_content(model="mockllm/judge", content="GRADE: 90")

    client = InspectJudgeClient(
        get_model("mockllm/judge", custom_outputs=slow), timeout_seconds=0.01
    )
    with pytest.raises(JudgeTimeoutError):
        client.evaluate(request())


def test_env_uses_private_judge_credentials_and_never_agent_credentials(monkeypatch):
    import eval_framework.judges.inspect as module

    captured = {}
    real = get_model("mockllm/judge")

    def factory(name, **kwargs):
        captured.update(name=name, **kwargs)
        return real

    monkeypatch.setattr(module, "get_model", factory)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "agent-secret")
    monkeypatch.setenv("DEEPSEEK_JUDGE_API_KEY", "judge-secret")
    monkeypatch.setenv("DEEPSEEK_JUDGE_MODEL", "judge-model")
    monkeypatch.setenv("DEEPSEEK_JUDGE_BASE_URL", "https://judge.example")
    client = module.InspectJudgeClient.from_env()
    assert captured["config"].max_retries == 0
    assert captured["api_key"] == "judge-secret"
    assert captured["name"] == "openai-api/deepseek/judge-model"
    assert captured["base_url"] == "https://judge.example"
    assert "secret" not in json.dumps(client.metadata())
    monkeypatch.delenv("DEEPSEEK_JUDGE_API_KEY")
    with pytest.raises(ValueError, match="DEEPSEEK_JUDGE_API_KEY"):
        module.InspectJudgeClient.from_env()


def test_real_backend_results_survive_report_and_old_backend_cannot_compare(
    dataset_path,
    tmp_path,
):
    from dataclasses import replace

    from test_compiled_execution import FixtureProvider
    from test_judge import judged_case, rubric_file

    from eval_framework import load_dataset, load_run_result, write_report
    from eval_framework.comparison import check_comparability
    from eval_framework.phase2_schemas import JudgeRunConfig
    from eval_framework.runner import run_provider_evaluation
    from eval_framework.schemas import RunConfig

    dataset = load_dataset(dataset_path)
    dataset.cases = [judged_case()]

    class RespondingProvider(FixtureProvider):
        def run_module(self, runtime, execution):
            return replace(
                super().run_module(runtime, execution),
                turns=[
                    {
                        "run_id": "fixture-run",
                        "status": "SUCCESS",
                        "tool_calls": [],
                        "events": [],
                        "final_response": "fixture found",
                    }
                ],
            )

    client = client_for("clear and complete.\nGRADE: 90")
    config = RunConfig(
        run_mode="framework_self_test",
        judge=JudgeRunConfig(rubric_path=str(rubric_file(tmp_path)), max_retries=0),
    )
    result = run_provider_evaluation(
        dataset,
        config,
        RespondingProvider(dataset),
        judge_client=client,
        output_dir=tmp_path / "run",
    )
    paths = write_report(result, tmp_path / "run")
    saved = load_run_result(paths.output_dir)
    assert saved.result.cases[0].judge_result.score == 90
    assert saved.result.judge_metadata["backend"] == "inspect_ai"
    assert saved.result.judge_metadata["rubric_sha256"]
    old_metadata = dict(saved.result.judge_metadata)
    for key in ("backend", "backend_version", "adapter_version", "metric"):
        old_metadata.pop(key)
    from eval_framework.result_loader import LoadedRunResult

    old = LoadedRunResult(
        result=saved.result.model_copy(update={"judge_metadata": old_metadata}),
        source_path=saved.source_path,
        sha256="legacy",
    )
    comparison = check_comparability(old, saved)
    assert "JUDGE_FINGERPRINT_MISMATCH" in {x.code for x in comparison.issues}


def test_native_judge_retries_whole_attempt_without_mixing_dimensions(
    tmp_path, case_result_factory
):
    from inspect_ai.model import GenerateConfig
    from test_judge import case_result, judged_case, rubric_file

    from eval_framework.judge import evaluate_trial_with_judge, load_judge_rubric
    from eval_framework.judges.inspect import InspectJudgeClient
    from eval_framework.phase2_schemas import JudgeRunConfig

    calls = []
    temporary_error = type("APIConnectionError", (Exception,), {})

    def output(messages, *_):
        calls.append(messages)
        if len(calls) == 2:
            raise temporary_error("controlled transient failure")
        grade = 60 if len(calls) == 3 else 90
        return ModelOutput.from_content(
            model="mockllm/retry", content=f"GRADE: {grade}"
        )

    client = InspectJudgeClient(get_model(
        "mockllm/retry", custom_outputs=output, config=GenerateConfig(max_retries=0),
    ))
    path = rubric_file(tmp_path)
    result = evaluate_trial_with_judge(
        judged_case(), case_result(case_result_factory),
        JudgeRunConfig(rubric_path=str(path), max_retries=1), client,
        load_judge_rubric(path),
    )
    assert len(calls) == 4
    assert [attempt.status for attempt in result.attempts] == [
        "MODEL_INVOCATION_ERROR", "COMPLETED",
    ]
    assert [dimension.score for dimension in result.dimensions] == [60, 90]
    assert result.passed is False
    assert client.metadata()["retry_scope"] == "whole_judge_attempt"
