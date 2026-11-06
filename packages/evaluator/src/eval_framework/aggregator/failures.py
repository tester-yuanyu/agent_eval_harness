"""基于已保存结构化证据归因；不重评分，不从错误文本猜根因。"""

from __future__ import annotations

from collections import Counter

RULE_VERSION = "failure-rules-v1"
CHECK_RULES = (
    ("unknown_tool", "unknown_tool"),
    ("decision_tool", "tool_selection_error"),
    ("decision_arguments", "invalid_arguments"),
    ("decision_schema", "invalid_arguments"),
    ("preserved_file", "workspace_policy_violation"),
    ("absent_file", "workspace_policy_violation"),
    ("no_extra_files", "workspace_policy_violation"),
    ("workspace_policy", "workspace_policy_violation"),
    ("expected_file", "state_mismatch"),
    ("checkpoint", "checkpoint_violation"),
)
ERROR_RULES = {
    "UNKNOWN_TOOL": "unknown_tool",
    "INVALID_ARGUMENTS": "invalid_arguments",
    "WORKSPACE_POLICY_VIOLATION": "workspace_policy_violation",
    "TIMEOUT": "timeout",
    "RUNTIME_ERROR": "runtime_error",
    "MISSING_EVIDENCE": "evidence_missing",
    "SCORING_ERROR": "scoring_error",
    "INVALID_SETUP": "invalid_setup",
    "CLEANUP_NOT_COMPLETE": "runtime_error",
}


def classify_failure(trial: dict | None) -> dict:
    result = {
        "domain": None,
        "primary": None,
        "secondary": [],
        "rule_version": RULE_VERSION,
        "evidence_refs": [],
        "diagnostics": [],
    }
    if trial is None:
        return {**result, "domain": "unknown", "primary": "evidence_missing"}
    assessment, observation = trial["assessment"], trial["observation"]
    verdict = assessment["verdict"]
    for i, event in enumerate(observation.get("events", [])):
        if event.get("type") == "tool" and event.get("error") and verdict == "PASS":
            result["diagnostics"].append(
                {
                    "primary": "recovered_error",
                    "evidence_refs": [f"/observation/events/{i}"],
                }
            )
    for i, metric in enumerate(assessment.get("metrics", [])):
        if metric.get("formal") is False and (
            metric.get("status") == "ERROR" or metric.get("errors")
        ):
            result["diagnostics"].append(
                {
                    "primary": "judge_error",
                    "evidence_refs": [f"/assessment/metrics/{i}"],
                }
            )
    if verdict == "PASS":
        return result
    candidates = []
    # INVALID 先使用采证/运行/评分错误来源，不能归因到 Agent 决策。
    for where, errors in (
        ("assessment", assessment.get("errors", [])),
        ("observation", observation.get("errors", [])),
    ):
        for i, error in enumerate(errors):
            if not isinstance(error, dict):
                continue
            code = str(error.get("code", "")).upper()
            if code == "JUDGE_ERROR":
                result["diagnostics"].append(
                    {
                        "primary": "judge_error",
                        "evidence_refs": [f"/{where}/errors/{i}"],
                    }
                )
                continue
            domain = {
                "harness": "infrastructure",
                "infrastructure": "infrastructure",
                "scoring": "scoring",
                "agent": "agent",
            }.get(error.get("kind"), "unknown")
            if verdict == "INVALID" and domain == "agent":
                domain = "unknown"
            if code in ERROR_RULES:
                candidates.append((domain, ERROR_RULES[code], f"/{where}/errors/{i}"))
    if verdict == "FAIL":
        decisive = []
        for field in ("checks", "metrics"):
            for i, check in enumerate(assessment.get(field, [])):
                if (
                    field == "metrics" and check.get("formal") is not True
                ) or check.get("passed", check.get("success")) is not False:
                    continue
                name = check.get("name", "")
                for prefix, label in CHECK_RULES:
                    if (
                        name == prefix or name.startswith((prefix + ":", prefix + "_"))
                    ):
                        decisive.append(("agent", label, f"/assessment/{field}/{i}"))
                        break
        candidates = decisive + candidates
    if candidates:
        domain, primary, ref = candidates[0]
        result.update(
            domain=domain,
            primary=primary,
            evidence_refs=[ref],
            secondary=[
                {"domain": d, "primary": p, "evidence_refs": [r]}
                for d, p, r in candidates[1:]
            ],
        )
    else:
        result.update(domain="unknown", primary="unknown")
    return result


def summarize_failures(population: dict) -> dict:
    values = [classify_failure(row["record"]) for row in population["trials"]]
    return {
        "rule_version": RULE_VERSION,
        "by_domain": dict(Counter(v["domain"] for v in values if v["domain"])),
        "by_type": dict(Counter(v["primary"] for v in values if v["primary"])),
        "diagnostics": dict(
            Counter(d["primary"] for v in values for d in v["diagnostics"])
        ),
    }
