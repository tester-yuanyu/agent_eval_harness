"""Optional Inspect/DeepEval presentation of a bounded official τ execution.

Inspect orchestrates one explicitly selected official batch; τ still owns its
inner simulations, tools, user simulator, and reward calculation. DeepEval
faithfully exposes that saved reward, without a replacement oracle or GEval.
Task descriptors are presentation metadata, never Agent inputs or private task
criteria. The original summary and per-trial files remain authoritative evidence.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
from datetime import datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase

from .runner import code_identity, digest, now, save_json, summarize

TAU_HARNESS_VERSION = "tau-inspect-official-reward-v1"


class OfficialTauRewardMetric(BaseMetric):
    """Transport the official number through DeepEval without recomputing it."""

    threshold = 1.0
    async_mode = False
    strict_mode = False
    include_reason = True
    verbose_mode = False
    evaluation_model = "official_tau_EvaluationType.ALL"

    @property
    def __name__(self) -> str:
        return "official_reward"

    def measure(self, test_case: LLMTestCase, **_kwargs: Any) -> float:
        reward = (test_case.metadata or {}).get("official_reward")
        if (
            type(reward) not in (int, float)
            or not math.isfinite(reward)
            or not 0 <= reward <= 1
        ):
            raise ValueError("A finite official numeric reward in [0, 1] is required")
        self.score = reward
        self.success = reward == 1
        self.reason = (
            "Official τ EvaluationType.ALL reward, preserved without recomputation"
        )
        return reward

    async def a_measure(self, test_case: LLMTestCase, **kwargs: Any) -> float:
        return self.measure(test_case, **kwargs)


def score_official_reward(row: dict[str, Any]) -> dict[str, Any]:
    """Unknown rewards and execution/evidence errors are invalid, never zero."""
    metric = {
        "name": "official_reward",
        "backend": "deepeval",
        "library_version": version("deepeval"),
        "version": TAU_HARNESS_VERSION,
        "implementation": "OfficialTauRewardMetric",
        "formal": True,
        "scope": "task",
        "event_id": None,
        "threshold": 1.0,
        "score": None,
        "success": None,
        "status": "MISSING",
        "reason": "Official reward is unavailable or its execution evidence is invalid",
        "reward_owner": "official_tau_EvaluationType.ALL",
    }
    result = {
        "verdict": "INVALID",
        "validity": "INVALID",
        "metrics": [metric],
        "scoring_backend": "deepeval",
        "metrics_version": TAU_HARNESS_VERSION,
        "errors": [],
    }
    try:
        if row.get("error"):
            raise ValueError("Official execution or evidence has a recorded error")
        measured = OfficialTauRewardMetric()
        measured.measure(
            LLMTestCase(
                input="Saved official τ reward",
                actual_output="No reward recomputation",
                metadata={"official_reward": row.get("official_reward")},
            )
        )
        metric.update(
            score=measured.score,
            success=measured.is_successful(),
            status="SCORED",
            reason=measured.reason,
        )
        result.update(
            verdict="PASS" if measured.is_successful() else "FAIL", validity="VALID"
        )
    except ValueError as exc:
        result["errors"].append(
            {
                "kind": "scoring",
                "code": "OFFICIAL_REWARD_UNAVAILABLE",
                "message": str(exc),
            }
        )
    return result


def _read_evidence(value: Any, official_dir: Path) -> tuple[dict, str, str]:
    if not isinstance(value, str):
        raise ValueError("Official evidence path is missing")
    path = Path(value).resolve(strict=True)
    if not path.is_relative_to(official_dir.resolve()):
        raise ValueError("Official evidence path escapes the current run")
    raw = path.read_bytes()
    document = json.loads(raw)
    if not isinstance(document, dict):
        raise ValueError("Official evidence must be a JSON object")
    return document, str(path), hashlib.sha256(raw).hexdigest()


def _usage(events: list[dict]) -> dict:
    generations = [event for event in events if event.get("type") == "generation"]
    result = {}
    for key, alias in (
        ("input_tokens", "prompt_tokens"),
        ("output_tokens", "completion_tokens"),
        ("total_tokens", "total_tokens"),
        ("cost_usd", "cost_usd"),
    ):
        values = [
            (event.get("usage") or {}).get(key, (event.get("usage") or {}).get(alias))
            for event in generations
        ]
        known = [value for value in values if type(value) in (int, float)]
        result[key] = sum(known) if known and len(known) == len(values) else None
    return result


def _normalize(
    summary: dict,
    config: dict,
    output: Path,
    started: str,
    finished: str,
    transport_error: dict | None,
    sources: dict,
) -> dict:
    official_dir = output / "official"
    summary_path = official_dir / "summary.json"
    summary_hash = (
        hashlib.sha256(summary_path.read_bytes()).hexdigest()
        if summary_path.exists()
        else None
    )
    prefix = "tau-retail-v1.0.1/"
    descriptors = {
        prefix + task_id: {
            "id": prefix + task_id,
            "official_task_id": task_id,
            "family": "tau/retail",
            "category": "retail",
            "split": "official_subset",
            "prompt": (
                f"Official τ retail task {task_id}; conversation supplied "
                "by the official user simulator."
            ),
            "followups": [],
            "oracle": {"official_reward": 1},
            "evaluation_level": "e2e",
            "execution_mode": "agent",
            "synthetic_presentation_descriptor_only": True,
        }
        for task_id in config["task_ids"]
    }
    identity = {
        "dataset": {
            "dataset_id": "tau-retail-v1.0.1-selected-subset",
            "source_identity": summary.get("source_identity"),
            "task_sha256": summary.get("task_sha256"),
            "policy_sha256": summary.get("policy_sha256"),
        },
        "runtime": summary.get("agent_runtime_identity"),
        "config": config,
        "harness_version": TAU_HARNESS_VERSION,
        "harness_source": sources,
        "inspect_ai": version("inspect_ai"),
        "deepeval": version("deepeval"),
        "scoring_version": TAU_HARNESS_VERSION,
        "official_summary_sha256": summary_hash,
        "offline": False,
        "case_ids": list(descriptors),
        "repeats": config.get("num_trials", 1),
    }
    identity_hash = digest(identity)
    original_rows = summary.get("results", [])
    expected = {
        (task_id, trial)
        for task_id in config["task_ids"]
        for trial in range(1, config.get("num_trials", 1) + 1)
    }
    keyed = {}
    for row in original_rows:
        key = row.get("task_id"), row.get("trial")
        if key not in expected or key in keyed:
            raise ValueError("Official summary has an unexpected or duplicate trial")
        keyed[key] = row
    rows = []
    for task_id in config["task_ids"]:
        for trial in range(1, config.get("num_trials", 1) + 1):
            original = copy.deepcopy(keyed.get((task_id, trial), {}))
            problems = [transport_error] if transport_error else []
            if original.get("error"):
                problems.append(original["error"])
            if not original:
                problems.append(
                    {
                        "code": "MISSING_OFFICIAL_TRIAL",
                        "message": "No official result was recorded",
                    }
                )
            observation = {
                "status": "error",
                "execution_kind": "execution_unavailable",
                "evidence_complete": False,
                "events": [],
                "turns": [],
                "errors": [],
                "runtime_identity": summary.get("agent_runtime_identity") or {},
            }
            provenance = {
                "summary_path": str(summary_path) if summary_hash else None,
                "summary_sha256": summary_hash,
                "observation_path": None,
                "observation_sha256": None,
                "result_path": None,
                "result_sha256": None,
            }
            if original.get("official_reward") is not None:
                try:
                    observation, path, checksum = _read_evidence(
                        original.get("observation_path"), official_dir
                    )
                    provenance.update(
                        observation_path=path, observation_sha256=checksum
                    )
                    official_result, path, checksum = _read_evidence(
                        original.get("result_path"), official_dir
                    )
                    provenance.update(result_path=path, result_sha256=checksum)
                    reward = original["official_reward"]
                    if any(
                        type(value) not in (int, float) or value != reward
                        for value in (
                            original.get("reward_info", {}).get("reward"),
                            observation.get("official_reward", {}).get("reward"),
                            official_result.get("reward_info", {}).get("reward"),
                        )
                    ):
                        raise ValueError(
                            "Official reward disagrees across saved evidence"
                        )
                    # Trace completeness is reported separately. A corroborated
                    # official reward must not become a different outcome merely
                    # because instrumentation is incomplete or a tool recovered
                    # from an error. Adapter/trial execution errors above remain
                    # invalid; no missing reward artifact can imply success.
                except (OSError, ValueError, TypeError, AttributeError) as exc:
                    problems.append(
                        {"code": "OFFICIAL_EVIDENCE_INVALID", "message": str(exc)}
                    )
            assessment = score_official_reward({**original, "error": problems})
            assessment["metrics"][0]["provenance"] = provenance
            observation = copy.deepcopy(observation)
            observation["usage"] = _usage(observation.get("events", []))
            observation["usage_scope"] = (
                "Recorded Agent and user-simulator generations; "
                "unrecorded official judge usage is unknown"
            )
            began = original.get("started_at", started)
            ended = original.get("finished_at", finished)
            row = {
                "identity_hash": identity_hash,
                "case_id": prefix + task_id,
                "trial": trial,
                "family": "tau/retail",
                "category": "retail",
                "split": "official_subset",
                "evaluation_level": "e2e",
                "execution_mode": "agent",
                "started_at": began,
                "finished_at": ended,
                "latency_seconds": max(
                    0,
                    (
                        datetime.fromisoformat(ended) - datetime.fromisoformat(began)
                    ).total_seconds(),
                ),
                "assessment": assessment,
                "observation": observation,
                "official_task_id": task_id,
                "official_reward": original.get("official_reward"),
                "trace_evidence_complete": observation.get("evidence_complete"),
                "trace_errors": copy.deepcopy(observation.get("errors", [])),
                "official_observation_path": provenance["observation_path"],
                "official_result_path": provenance["result_path"],
                "official_termination_reason": original.get("termination_reason"),
                "normalization_errors": problems,
            }
            save_json(output / "trials" / f"{len(rows) + 1:04d}.json", row)
            rows.append(row)
    return {
        "run_id": output.name + "-" + identity_hash[:12],
        "identity": identity,
        "identity_hash": identity_hash,
        "config": config,
        "started_at": started,
        "finished_at": finished,
        "mode": "real_agent_official_tau",
        "execution_backend": "inspect_ai",
        "scoring_backend": "deepeval",
        "official_reward_owner": "official_tau_EvaluationType.ALL",
        "official_leaderboard_result": False,
        "inspect_sample_unit": "bounded_official_batch",
        "planned_case_ids": list(descriptors),
        "trials_per_case": config.get("num_trials", 1),
        "task_descriptors": descriptors,
        "trials": rows,
        "summary": summarize(rows, list(descriptors), config.get("num_trials", 1)),
        "observed_official_trials": len(original_rows),
        "official_summary_path": str(summary_path) if summary_hash else None,
        "official_summary_sha256": summary_hash,
        "limitations": [
            "Explicit official task subset; not an official leaderboard result",
            "Inspect orchestrates the batch; official τ owns individual "
            "simulations and reward",
            "DeepEval transports official reward unchanged; "
            "no independent replacement oracle",
        ],
    }


def run_tau_harness(config: dict[str, Any], output: Path) -> dict[str, Any]:
    """Run an explicit official selection once, recording real Inspect logs."""
    import anyio
    from inspect_ai import Task
    from inspect_ai import eval as inspect_eval
    from inspect_ai.dataset import Sample
    from inspect_ai.log import transcript
    from inspect_ai.scorer import Score, scorer
    from inspect_ai.solver import solver

    from . import tau_adapter

    tau_adapter.validate_config(config)
    for key in config:
        if ("api_key" in key.lower() or "secret" in key.lower()) and not key.endswith(
            "_env"
        ):
            raise ValueError(
                "Use credential environment-variable names, not secret config values"
            )
    output = Path(output).expanduser().resolve()
    if output.exists():
        raise ValueError(
            "τ Harness output already exists; preserve evidence in a new directory"
        )
    output.mkdir(parents=True, exist_ok=False)
    config = copy.deepcopy(config)
    sources = code_identity(["tau_harness.py", "tau_adapter.py", "tau_worker.py"])
    pending: dict[str, Any] = {}
    started = now()

    @solver
    def official_execution():
        async def solve(state, generate):
            try:
                pending["official"] = await anyio.to_thread.run_sync(
                    lambda: tau_adapter.run_tau(config, output / "official")
                )
            except Exception as exc:
                pending["error"] = tau_adapter.redact_secrets(
                    {"type": type(exc).__name__, "message": str(exc)}, config
                )
                save_json(output / "adapter-error.json", pending["error"])
                pending["official"] = {}
            pending["finished"] = now()
            transcript().info(
                {
                    "official_summary_path": str(output / "official/summary.json"),
                    "recorded_trials": len(pending["official"].get("results", [])),
                    "error": pending.get("error"),
                },
                source="official_tau_execution",
            )
            state.output.completion = json.dumps(
                {"status": pending["official"].get("status", "ERROR")}
            )
            state.completed = True
            return state

        return solve

    @scorer(metrics=[])
    def official_deepeval_bridge():
        async def score(state, target):
            result = _normalize(
                pending["official"],
                config,
                output,
                started,
                pending["finished"],
                pending.get("error"),
                sources,
            )
            pending["result"] = result
            counts = result["summary"]["verdicts"]
            verdict = (
                "INVALID"
                if counts.get("INVALID")
                else "FAIL"
                if counts.get("FAIL")
                else "PASS"
            )
            return Score(
                value=verdict,
                explanation=json.dumps(result["summary"], ensure_ascii=False),
                metadata={
                    "per_trial_results": "results.json",
                    "reward_owner": "official_tau_EvaluationType.ALL",
                },
            )

        return score

    task = Task(
        name="official_tau_bounded_batch",
        version=TAU_HARNESS_VERSION,
        dataset=[
            Sample(
                id="official-batch",
                input="Execute the explicitly configured official τ selection.",
                target="",
                metadata={"domain": config["domain"], "task_ids": config["task_ids"]},
            )
        ],
        solver=official_execution(),
        scorer=official_deepeval_bridge(),
        metadata={
            "execution_owner": "official_tau_orchestrator",
            "scoring_backend": "deepeval",
            "reward_owner": "official_tau_EvaluationType.ALL",
        },
    )
    logs = inspect_eval(
        task,
        model="mockllm/model",
        display="none",
        ctl_server=False,
        notification=False,
        log_dir=str(output / "inspect"),
        max_samples=1,
        retry_on_error=0,
        fail_on_error=True,
        log_realtime=False,
        log_samples=True,
    )
    if not logs or logs[0].status != "success" or "result" not in pending:
        raise RuntimeError(
            "Inspect τ orchestration failed; "
            "retained official artifacts must be inspected"
        )
    if sources != code_identity(["tau_harness.py", "tau_adapter.py", "tau_worker.py"]):
        raise ValueError("τ Harness implementation changed during execution")
    result = pending["result"]
    result["inspect_logs"] = [str(log.location) for log in logs]
    save_json(output / "results.json", result)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--env-file", action="append", default=[], type=Path)
    args = parser.parse_args(argv)
    os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
    if args.env_file:
        from dotenv import load_dotenv

        for path in args.env_file:
            if not path.is_file():
                parser.error("Explicit env file does not exist")
            load_dotenv(path, override=False)
    result = run_tau_harness(json.loads(args.config.read_text()), args.output)
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 1 if result["summary"]["verdicts"].get("INVALID") else 0


if __name__ == "__main__":
    raise SystemExit(main())
