"""同题重复执行的描述性一致性估计，保持完整计划总体。"""

from collections import defaultdict
from math import comb
from statistics import mean

from eval_contracts.benchmark_analysis import AnalysisPolicy


def reliability(
    population: dict, *, ks: tuple[int, ...], repeat_protocol: dict | None
) -> dict:
    AnalysisPolicy(ks=ks, repeat_protocol=repeat_protocol)
    output = {}
    for layer in sorted({r["layer"] for r in population["trials"]}):
        rows = [r for r in population["trials"] if r["layer"] == layer]
        by_case = defaultdict(list)
        for row in rows:
            by_case[row["case_id"]].append(row)
        n = population["trials_per_case"]
        incomplete = any(r["verdict"] in {"MISSING", "INVALID"} for r in rows)
        values = {}
        for k in ks:
            status = (
                "framework_demo_only"
                if population["framework_only"]
                else "insufficient_trials"
                if k > n
                else "unavailable_incomplete_population"
                if incomplete
                else "available"
            )
            micro = macro = None
            if status == "available":
                per_case = []
                families = defaultdict(list)
                for case_rows in by_case.values():
                    c = sum(r["verdict"] == "PASS" for r in case_rows)
                    estimate = comb(c, k) / comb(n, k) if c >= k else 0.0
                    per_case.append(estimate)
                    families[case_rows[0]["family"]].append(estimate)
                micro = mean(per_case) if per_case else None
                macro = mean(mean(v) for v in families.values()) if families else None
            values[str(k)] = {"status": status, "micro": micro, "family_macro": macro}
        output[layer] = {
            "planned_tasks": len(by_case),
            "trials_per_case": n,
            "families": len({r["family"] for r in rows}),
            "pass_hat_k": values,
            "all_trials_pass_rate": (
                sum(
                    all(r["verdict"] == "PASS" for r in group)
                    for group in by_case.values()
                )
                / len(by_case)
                if by_case and not population["framework_only"]
                else None
            ),
            "repeat_protocol_status": (
                "declared_independent"
                if repeat_protocol
                else "descriptive_not_verified_independent"
            ),
        }
    return {
        "by_layer": output,
        "definition": "comb(c,k)/comb(n,k); task micro and equal-family macro",
    }
