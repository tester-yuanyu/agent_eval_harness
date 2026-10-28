"""Business policies executed by an Inspect Scorer, after environment cleanup."""

from dataclasses import dataclass

from .assertions import run_assertions
from .diagnostics import build_diagnoses
from .judge import evaluate_trial_with_judge, resolve_quality_conclusion
from .provider import AdapterOutput
from .schemas import CaseResult, EvalCase
from .scoring import score_assertions
from .trace_analysis import analyze_case_trace


@dataclass
class TrialEvaluation:
    case: EvalCase
    result: CaseResult
    output: AdapterOutput
    assessable: bool

    @property
    def key(self):
        return f"{self.case.case_id}/{self.result.trial_id}"


def assess_trial(trial, config, provider, *, judge_client=None, rubric=None):
    """Keep validity and quality separate; absent evidence is never a zero."""
    result = trial.result
    assertions, diagnoses = [], []
    score, conclusion = None, "INCONCLUSIVE"
    issues = list(result.evaluation_issues)
    validity = result.evaluation_validity
    if trial.assessable:
        try:
            assertions = run_assertions(trial.case, trial.output, provider.capabilities)
            score, conclusion = score_assertions(assertions, config.pass_threshold)
            diagnoses = build_diagnoses(
                assertions,
                case=trial.case,
                capabilities=provider.capabilities,
                rules=provider.diagnostics.rules_for(trial.case, assertions),
            )
        except Exception as exc:
            validity = "INVALID"
            issues.append(
                {"code": "ASSERTION_EVALUATION_FAILED", "type": type(exc).__name__}
            )
    if validity == "INVALID":
        score = None
        conclusion = (
            "FAIL" if any(a.passed is False for a in assertions) else "INCONCLUSIVE"
        )
    if result.execution_status != "COMPLETED" and conclusion == "PASS":
        score, conclusion = None, "INCONCLUSIVE"
    result = result.model_copy(
        update={
            "assertion_results": assertions,
            "first_failed_assertion": next(
                (a for a in assertions if a.passed is False), None
            ),
            "evidence_refs": list(
                dict.fromkeys(r for a in assertions for r in a.evidence_refs)
            ),
            "diagnoses": diagnoses,
            "score": score,
            "quality_conclusion": conclusion,
            "evaluation_validity": validity,
            "evaluation_issues": issues,
        }
    )
    result = _analyze(result, provider)
    if (
        rubric is not None
        and judge_client is not None
        and result.execution_status == "COMPLETED"
        and result.evaluation_validity == "VALID"
        and not any(a.applicable and a.passed is None for a in assertions)
    ):
        judged = evaluate_trial_with_judge(
            trial.case,
            result,
            config.judge,
            judge_client,
            rubric,
        )
        result = result.model_copy(
            update={
                "judge_result": judged,
                "quality_conclusion": resolve_quality_conclusion(
                    conclusion,
                    assertions,
                    trial.case.oracle.judge,
                    judged,
                ),
            }
        )
        result = _analyze(result, provider)
    return result


def _analyze(result, provider):
    try:
        result = result.model_copy(
            update={
                "trace_analysis": analyze_case_trace(
                    result, getattr(provider, "trace_rules", ())
                )
            }
        )
    except Exception as exc:
        result = result.model_copy(
            update={
                "evaluation_validity": "INVALID",
                "score": None,
                "quality_conclusion": (
                    "FAIL"
                    if any(a.passed is False for a in result.assertion_results)
                    else "INCONCLUSIVE"
                ),
                "evaluation_issues": result.evaluation_issues
                + [
                    {
                        "code": "TRACE_ANALYSIS_FAILED",
                        "type": type(exc).__name__,
                    }
                ],
            }
        )
    return result
