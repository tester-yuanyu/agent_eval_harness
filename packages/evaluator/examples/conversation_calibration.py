"""Native Inspect calibration of fixed dialogues; references await human review.

This example evaluates a Judge, not an Agent. No Agent or release verdict is
created. DeepEval's existing diagnostic adapter supplies the algorithm.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from inspect_ai import Epochs, Task
from inspect_ai import eval as inspect_eval
from inspect_ai.dataset import Sample
from inspect_ai.log import EvalLog
from inspect_ai.model import ChatMessageAssistant, ChatMessageUser
from inspect_ai.scorer import Metric, SampleScore, Score, Scorer, Target, metric, scorer
from inspect_ai.solver import Generate, Solver, TaskState, solver

from eval_framework.diagnostic_metrics import (
    ConversationMetricConfig,
    evaluate_conversation,
)
from eval_framework.inspect_metrics import category_counts, native_mean
from eval_framework.judges.conversation import ConversationMetricClient


def load_corpus(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    corpus = json.loads(raw)
    if (
        corpus["scope"] != "judge_calibration_only"
        or corpus["review_state"] != "PENDING_HUMAN_REVIEW"
        or corpus["human_approved_cases"] != 0
    ):
        raise ValueError("Calibration fixture labels must remain unreviewed")
    ids = [c["id"] for c in corpus["cases"]]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("Calibration IDs must be nonempty and unique")
    for case in corpus["cases"]:
        if case["review_state"] != "PENDING_HUMAN_REVIEW" or not case["turns"]:
            raise ValueError("Expected pending-review conversations")
        for turn in case["turns"]:
            if not isinstance(turn["user"], str) or not turn["user"].strip():
                raise ValueError("User messages must be nonempty text")
            if turn["assistant"] is not None and not isinstance(turn["assistant"], str):
                raise ValueError(
                    "Assistant messages must be text or explicitly missing"
                )
        draft = case["draft"]
        bounds = draft["score_interval"]
        if draft["status"] not in {"SUCCESS", "ERROR", "NOT_APPLICABLE"}:
            raise ValueError("Invalid draft status")
        if draft["status"] == "SUCCESS":
            if (
                bounds is None
                or len(bounds) != 2
                or not 0 <= bounds[0] <= bounds[1] <= 1
            ):
                raise ValueError("Invalid draft score interval")
        elif bounds is not None:
            raise ValueError("Unknown draft status cannot have a numeric score")
    corpus["source_sha256"] = hashlib.sha256(raw).hexdigest()
    return corpus


def calibration_task(corpus: dict[str, Any], client: Any, *, epochs: int) -> Task:
    if epochs < 1:
        raise ValueError("epochs must be positive")
    # References remain only in this trusted local mapping. Neither the Sample
    # target nor the Judge model receives draft labels or business evidence.
    by_id = {case["id"]: case for case in corpus["cases"]}

    @solver
    def recorded_dialogue() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            state.messages = []
            for turn in by_id[str(state.sample_id)]["turns"]:
                state.messages.append(ChatMessageUser(content=turn["user"]))
                if turn["assistant"] is not None:
                    state.messages.append(
                        ChatMessageAssistant(content=turn["assistant"])
                    )
            state.completed = True
            return state

        return solve

    @metric
    def diagnostic_summary() -> Metric:
        def calculate(scores: list[SampleScore]) -> dict[str, float]:
            values = [s.score.metadata["diagnostic"] for s in scores]
            result = {
                f"status.{k}": float(v)
                for k, v in category_counts([v["status"] for v in values]).items()
            }
            numeric = [v["score"] for v in values if v["status"] == "SUCCESS"]
            result["scored_trials"] = float(len(numeric))
            if numeric:
                result["mean_score"] = native_mean(numeric)
            return result

        return calculate

    @scorer(metrics=[diagnostic_summary()])
    def conversation_diagnostic() -> Scorer:
        async def score(state: TaskState, target: Target) -> Score:
            record = by_id[str(state.sample_id)]
            turns = record["turns"]
            execution = SimpleNamespace(
                user_input=turns[0]["user"],
                user_responses=[t["user"] for t in turns[1:]],
            )
            result = SimpleNamespace(
                test_scope="end_to_end",
                execution_status="COMPLETED",
                evaluation_validity="VALID",
                turn_results=[
                    {
                        "final_response": t["assistant"],
                        "status": record["terminal_status"]
                        if i == len(turns) - 1
                        else "INTERMEDIATE",
                    }
                    for i, t in enumerate(turns)
                ],
            )
            diagnostic = await evaluate_conversation(
                SimpleNamespace(case=SimpleNamespace(execution=execution)),
                result,
                client,
            )
            return Score(
                value=diagnostic.score if diagnostic.score is not None else "N",
                metadata={"diagnostic": diagnostic.model_dump(mode="json")},
            )

        return score

    return Task(
        name="conversation_judge_calibration",
        version="1",
        dataset=[
            Sample(
                id=c["id"],
                input=c["turns"][0]["user"],
                target="",
                metadata={"category": c["category"], "synthetic": True},
            )
            for c in corpus["cases"]
        ],
        solver=recorded_dialogue(),
        scorer=conversation_diagnostic(),
        epochs=Epochs(epochs, []),
        metadata={
            "purpose": "judge_calibration_only",
            "gate_eligible": False,
            "reference_status": "PENDING_HUMAN_REVIEW",
            "corpus_sha256": corpus["source_sha256"],
            "selected_case_ids": list(by_id),
            "judge": client.metadata() if hasattr(client, "metadata") else {},
        },
    )


def project_log(log: EvalLog, corpus: dict[str, Any]) -> dict[str, Any]:
    if log.status != "success":
        raise ValueError(
            "Inspect run did not complete; retain failed log for diagnosis"
        )
    if log.eval.metadata.get("corpus_sha256") != corpus["source_sha256"]:
        raise ValueError("Inspect log and reference corpus must match")
    epochs = log.eval.config.epochs or 1
    expected = {(c["id"], e) for c in corpus["cases"] for e in range(1, epochs + 1)}
    rows = [
        {
            "case_id": str(s.id),
            "epoch": s.epoch,
            "diagnostic": s.scores["conversation_diagnostic"].metadata["diagnostic"],
        }
        for s in log.samples
    ]
    if (
        len(rows) != len(expected)
        or {(r["case_id"], r["epoch"]) for r in rows} != expected
    ):
        raise ValueError("Inspect repetition set is incomplete")
    return {
        "run_id": log.eval.run_id,
        "epochs": epochs,
        "planned_trials": len(expected),
        "purpose": "judge_calibration_only",
        "corpus_sha256": corpus["source_sha256"],
        "started_at": log.stats.started_at,
        "completed_at": log.stats.completed_at,
        "judge": log.eval.metadata.get("judge", {}),
        "native_metrics": {
            k: m.value for k, m in log.results.scores[0].metrics.items()
        },
        "trials": rows,
    }


def analyze(projection: dict[str, Any], corpus: dict[str, Any]) -> dict[str, Any]:
    expected = {
        (c["id"], e)
        for c in corpus["cases"]
        for e in range(1, projection["epochs"] + 1)
    }
    rows = projection["trials"]
    if (
        len(rows) != len(expected)
        or {(r["case_id"], r["epoch"]) for r in rows} != expected
    ):
        raise ValueError("Stored repetition set is incomplete")
    if projection.get("corpus_sha256") != corpus["source_sha256"]:
        raise ValueError("Stored results and reference corpus must match")
    cases = []
    for case in corpus["cases"]:
        samples = [r for r in rows if r["case_id"] == case["id"]]
        values = [r["diagnostic"]["score"] for r in samples]
        numeric = [v for v in values if v is not None]
        draft = case["draft"]
        matches = []
        for row in samples:
            d = row["diagnostic"]
            match = d["status"] == draft["status"]
            if match and draft["status"] == "SUCCESS":
                match = (
                    d["score"] is not None
                    and draft["score_interval"][0]
                    <= d["score"]
                    <= draft["score_interval"][1]
                )
            matches.append(match)
        cases.append(
            {
                "case_id": case["id"],
                "category": case.get("category"),
                "scores": values,
                "statuses": [r["diagnostic"]["status"] for r in samples],
                "numeric_repeats": len(numeric),
                "score_range": max(numeric) - min(numeric) if numeric else None,
                "all_repeats_numeric": len(numeric) == projection["epochs"],
                "matches_draft": matches,
            }
        )
    return {
        "human_approved_cases": 0,
        "gate_eligible": False,
        "reference_status": "PENDING_HUMAN_REVIEW",
        "cases": cases,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--judge-env", type=Path)
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--case-id", action="append")
    args = parser.parse_args()
    corpus = load_corpus(args.corpus)
    if args.case_id:
        if set(args.case_id) - {c["id"] for c in corpus["cases"]}:
            raise ValueError("Unknown case IDs")
        corpus["cases"] = [c for c in corpus["cases"] if c["id"] in args.case_id]
    if args.judge_env:
        from dotenv import dotenv_values

        values = dotenv_values(args.judge_env)
        for key in (
            "DEEPSEEK_JUDGE_API_KEY",
            "DEEPSEEK_JUDGE_MODEL",
            "DEEPSEEK_JUDGE_BASE_URL",
        ):
            if values.get(key):
                os.environ[key] = values[key]
    client = ConversationMetricClient.from_env(ConversationMetricConfig())
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / "corpus.snapshot.json").write_text(
        json.dumps(corpus, ensure_ascii=False, indent=2)
    )
    logs = inspect_eval(
        calibration_task(corpus, client, epochs=args.epochs),
        model="mockllm/model",
        display="none",
        ctl_server=False,
        notification=False,
        log_dir=str(args.output_dir / "inspect"),
        max_samples=3,
        fail_on_error=True,
        retry_on_error=0,
        log_realtime=False,
    )
    projection = project_log(logs[0], corpus)
    native_path = Path(logs[0].location).resolve()
    projection["native_log"] = str(native_path)
    projection["native_log_sha256"] = hashlib.sha256(
        native_path.read_bytes()
    ).hexdigest()
    projection["example_sha256"] = hashlib.sha256(
        Path(__file__).read_bytes()
    ).hexdigest()
    for name, data in [
        ("projection.json", projection),
        ("analysis.json", analyze(projection, corpus)),
    ]:
        (args.output_dir / name).write_text(
            json.dumps(data, ensure_ascii=False, indent=2)
        )
    print(
        json.dumps(
            {
                "run_id": projection["run_id"],
                "planned_trials": projection["planned_trials"],
                "metrics": projection["native_metrics"],
                "output_dir": str(args.output_dir),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
