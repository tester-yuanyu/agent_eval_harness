"""受控资格与探索性差异分开，绝不放宽旧 compare_runs。"""

from capability_snapshot_kit.hashing import sha256_json
from eval_contracts.benchmark_analysis import AnalysisPolicy

REQUIRED_CONTROLS = (
    "dataset",
    "scoring",
    "selection",
    "repeats",
    "repeat_protocol",
    "layers",
    "harness",
    "environment",
    "tools",
    "prompt",
    "generation_config",
    "other_identity",
)
MODEL_CONFIG = {"model", "model_name", "base_url", "api_key_env"}
RUNTIME_CONFIG = {"provider", "nanobot_root", "python", "runtime"}


def _repeat_protocol(identity):
    protocol = identity.get("repeat_protocol")
    if protocol is None:
        return None
    try:
        AnalysisPolicy(repeat_protocol=protocol)
    except (ValueError, TypeError):
        return None
    return protocol


def _fields(run):
    identity = run["identity"]
    config = identity.get("config")
    used = {
        "dataset",
        "scoring_identity",
        "scoring_version",
        "case_ids",
        "repeats",
        "config",
        "repeat_protocol",
        "harness_source",
        "harness_version",
        "environment",
        "tools",
        "prompt",
        "runtime",
        "runtime_modes",
        "adapter",
        "source_results_sha256",
    }
    layers = sorted(
        {(r.get("evaluation_level"), r.get("execution_mode")) for r in run["trials"]},
        key=str,
    )
    return {
        "dataset": identity.get("dataset"),
        "scoring": identity.get("scoring_identity", identity.get("scoring_version")),
        "selection": run.get("planned_case_ids"),
        "repeats": run.get("trials_per_case"),
        "repeat_protocol": _repeat_protocol(identity),
        "layers": layers
        if layers and all(all(v is not None for v in layer) for layer in layers)
        else None,
        "harness": identity.get("harness_source", identity.get("harness_version")),
        "environment": identity.get("environment"),
        "tools": identity.get("tools"),
        "prompt": identity.get("prompt"),
        "model": {k: config[k] for k in sorted(MODEL_CONFIG) if k in config}
        if config is not None
        else None,
        "runtime": {
            "identity": {
                k: identity.get(k) for k in ("runtime", "runtime_modes", "adapter")
            },
            "config": {k: config[k] for k in sorted(RUNTIME_CONFIG) if k in config},
        }
        if config is not None and identity.get("runtime") is not None
        else None,
        "generation_config": {
            k: v for k, v in config.items() if k not in MODEL_CONFIG | RUNTIME_CONFIG
        }
        if config is not None
        else None,
        "other_identity": {k: v for k, v in identity.items() if k not in used},
    }


def validate_experiment(
    baseline: dict, candidate: dict, spec: dict | None = None
) -> dict:
    variables = set()
    if spec is not None:
        if not isinstance(spec, dict) or set(spec) != {
            "control_fields",
            "variable_fields",
        }:
            raise ValueError(
                "ExperimentSpec requires control_fields and variable_fields"
            )
        variables = set(spec["variable_fields"])
        controls = set(spec["control_fields"])
        if (
            not variables <= {"model", "runtime"}
            or not set(REQUIRED_CONTROLS) <= controls
            or controls & variables
            or not controls <= set(REQUIRED_CONTROLS) | {"model", "runtime"}
        ):
            raise ValueError("ExperimentSpec cannot relax required controls")
    left, right = _fields(baseline), _fields(candidate)
    unknown = [
        k for k in left if k not in variables and (left[k] is None or right[k] is None)
    ]
    differences = [
        {
            "field": key,
            "baseline_sha256": sha256_json(left[key]),
            "candidate_sha256": sha256_json(right[key]),
            "classification": "variable" if key in variables else "control",
        }
        for key in left
        if left[key] != right[key]
    ]
    mismatches = [d["field"] for d in differences if d["classification"] == "control"]
    same_execution = baseline.get(
        "execution_run_id", baseline["run_id"]
    ) == candidate.get("execution_run_id", candidate["run_id"]) and sha256_json(
        baseline.get("execution_identity", baseline["identity"])
    ) == sha256_json(candidate.get("execution_identity", candidate["identity"]))
    compatible = (
        spec is not None and not mismatches and not unknown and not same_execution
    )
    return {
        "status": "compatible" if compatible else "descriptive_only",
        "comparison_kind": "scoring_only"
        if same_execution
        else "controlled"
        if compatible
        else "exploratory",
        "new_executions": 0,
        "distinct_execution_populations": 1 if same_execution else 2,
        "differences": differences,
        "mismatches": mismatches,
        "unknown_controls": unknown,
        "experiment_spec_sha256": sha256_json(spec) if spec is not None else None,
        "limitations": [
            "探索性对比只展示差异；不作因果或统计显著性声明。",
            "受控资格不证明 ExperimentSpec 的事先登记时间。",
        ],
    }
