"""Strict domain adapters call real Inspect scoring functions."""

import pytest


@pytest.mark.parametrize(
    "actual,expected,passed",
    [
        ({"a": [1, " x "]}, {"a": [1, " x "]}, True),
        (" a ", "a", False),
        ("x!", "x", False),
        ("A", "a", False),
        ({"a": None}, {}, False),
        (None, None, True),
        (True, 1, False),
    ],
)
def test_strict_values_use_native_pattern(actual, expected, passed, monkeypatch):
    import eval_framework.native_scoring as scoring

    original = scoring.pattern
    inputs = []

    def tracked(*args, **kwargs):
        metric = original(*args, **kwargs)

        async def measure(state, target):
            inputs.append(state.output.completion)
            return await metric(state, target)

        return measure

    monkeypatch.setattr(scoring, "pattern", tracked)
    assert scoring.exact_value(actual, expected) is passed
    assert len(inputs) == 1
    assert inputs[0] == scoring.canonical_value(actual)


def test_projection_preserves_missing_keys_and_nested_values():
    from eval_framework.native_scoring import subset_value

    assert subset_value({"a": [1], "extra": 2}, {"a": [1]})
    assert not subset_value({}, {"a": None})
    assert not subset_value({"a": [1, 2]}, {"a": [1]})
    assert not subset_value({"a": "x!"}, {"a": "x"})


def test_assertions_report_native_identity_without_precomputed_boolean():
    from conftest import assertion, intent, module_case

    from eval_framework.assertions import run_assertions
    from eval_framework.provider import AdapterOutput
    from eval_framework.schemas import EvalCase

    raw = module_case()
    raw["oracle"]["evaluation"]["checks"] = [assertion("next_action_match")]
    result = run_assertions(
        EvalCase.model_validate(raw),
        AdapterOutput(intent(action="ASK_USER"), [], None, [], None),
        None,
    )[0]
    assert result.passed is False
    assert result.native_scores[0]["scorer"] == "inspect_ai/pattern"
    assert result.native_scores[0]["value"] == "I"


@pytest.mark.parametrize("name", ["params_match", "tool_args_match"])
def test_expected_subset_preserves_strict_nested_values(name):
    from conftest import assertion, intent, module_case

    from eval_framework.assertions import run_assertions
    from eval_framework.provider import AdapterOutput
    from eval_framework.schemas import EvalCase

    raw = module_case()
    raw["oracle"]["evaluation"]["checks"] = [
        assertion(
            name,
            config={
                "expected_subset": True,
                "tool": "query_information",
                "expected": {"nested": {"a": 1}},
            },
        )
    ]
    actual = {"nested": {"a": 1, "unexpected": 2}, "extra": 3}
    output = AdapterOutput(
        intent(parameters=actual),
        [
            {
                "tool_calls": [
                    {"name": "query_information", "arguments": actual, "call_id": "c1"}
                ]
            }
        ],
        None,
        [],
        None,
    )
    result = run_assertions(EvalCase.model_validate(raw), output, None)[0]
    assert result.passed is False
    assert result.native_scores[0]["value"] == "I"
