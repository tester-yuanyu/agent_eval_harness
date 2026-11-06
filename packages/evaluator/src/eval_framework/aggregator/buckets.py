"""多标签桶独立分母；未审与未标注任务不被静默过滤。"""

from .populations import counts


def bucket_report(population: dict, records: list[dict]) -> dict:
    labels = {r["case_id"]: r for r in records if r["review_status"] == "reviewed"}
    output = {}
    for layer in sorted({r["layer"] for r in population["trials"]}):
        rows = [r for r in population["trials"] if r["layer"] == layer]
        cases = {r["case_id"] for r in rows}
        reviewed = cases & labels.keys()
        capabilities = sorted(
            {cap for case in reviewed for cap in labels[case]["capabilities"]}
        )
        difficulties = sorted({labels[case]["difficulty"] for case in reviewed})
        output[layer] = {
            "planned_tasks": len(cases),
            "reviewed_tasks": len(reviewed),
            "unlabeled_tasks": len(cases - reviewed),
            "unknown_difficulty_tasks": sum(
                labels[c]["difficulty"] == "unknown" for c in reviewed
            ),
            "multi_label_non_additive": True,
            "capabilities": {
                cap: counts(
                    [
                        r
                        for r in rows
                        if r["case_id"] in reviewed
                        and cap in labels[r["case_id"]]["capabilities"]
                    ]
                )
                for cap in capabilities
            },
            "difficulty": {
                d: counts(
                    [
                        r
                        for r in rows
                        if r["case_id"] in reviewed
                        and labels[r["case_id"]]["difficulty"] == d
                    ]
                )
                for d in difficulties
            },
        }
    return output
