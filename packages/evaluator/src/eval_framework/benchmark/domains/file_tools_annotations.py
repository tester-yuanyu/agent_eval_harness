"""保守的 file-tools 注释建议，不把参考脚本当模型能力证明。"""

from eval_contracts.benchmark_annotations import structural_difficulty


def suggest_file_tools_annotations(tasks: list[dict]) -> list[dict]:
    records = []
    for task in tasks:
        capabilities, basis = [], []
        tools = set(task.get("required_tools", []))
        if len(tools) == 1:
            capabilities.append("single_tool")
            basis.append("/required_tools")
        elif len(tools) > 1:
            capabilities.append("multi_tool_selection")
            basis.append("/required_tools")
        if any(
            c.get("kind") == "tool_order" and c.get("required") is True
            for c in task.get("checkpoints", [])
        ):
            capabilities.append("tool_sequence")
            basis.append("/checkpoints")
        if task.get("followups") and any(
            c.get("kind") == "turn_files" and c.get("required") is True
            for c in task.get("checkpoints", [])
        ):
            capabilities.append("multi_turn_state")
            basis.append("/followups")
        if task.get("oracle", {}).get("preserve_other_files") is True:
            capabilities.append("policy_compliance")
            basis.append("/oracle/preserve_other_files")
        features = {
            "reference_tool_calls": len(task["module_calls"])
            if "module_calls" in task
            else None,
            "dependency_depth": None,
            "interaction_turns": 1 + len(task.get("followups", [])),
            "recovery_branches": None,
        }
        records.append(
            {
                "case_id": task["id"],
                "capabilities": capabilities,
                "difficulty": structural_difficulty(features),
                "structural_features": features,
                "basis_refs": basis,
                "review_status": "proposed",
            }
        )
    return records
