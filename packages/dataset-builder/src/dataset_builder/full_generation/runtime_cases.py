"""Runtime-compatible terminal cases and explicit fixture/runner obligations."""

from eval_framework.schemas import EvalCase

from .intent_cases import assertions, execution, intent_example
from .inventory import source_ref
from .models import Blocker, CompiledCase, ContractCase


def compile_runtime_cases(inv, slots):
    cases, blockers = [], []
    tools = sorted(
        v["payload"]["tool_name"]
        for v in inv.artifacts.values()
        if v["payload"]["snapshot_type"] == "tool"
    )
    for s in slots:
        if s.case_kind != "chain_case":
            continue
        ident, branch = s.dimension.split(":")
        d = inv.artifacts[ident]["payload"]
        dim = (
            "complete"
            if ident in {"intent.add_backpack_gift", "intent.unsupported"}
            else "missing"
        )
        text, expected = intent_example(
            inv, ident, dim if branch == "early_stop" else "complete"
        )
        refs = s.source_refs + [source_ref(inv, ident, "/decision_rules")]
        tool = d.get("required_tool_name")
        if branch == "early_stop":
            scope = "end_to_end" if s.layer == "end_to_end" else "link"
            oracle = {
                "expected_agent_status": expected["status"],
                "forbidden_tools": tools,
                "evaluation": assertions(["status_match", "tool_not_called"]),
            }
            if scope == "end_to_end":
                oracle["goal_state"] = {
                    "terminal_status": expected["status"],
                    "forbidden_tools": tools,
                }
                oracle["evaluation"] = {
                    "checks": [
                        {
                            "name": "turns_match",
                            "weight": 1,
                            "critical": True,
                            "config": {
                                "turns": [
                                    {"status": expected["status"], "tool_calls": []}
                                ]
                            },
                        }
                    ]
                }
            # Missing/confirmation/rejection are complete *single-run* outcomes,
            # not evidence of business task success or multi-turn recovery.
            payload = EvalCase.model_validate(
                {
                    "schema_version": "1.0",
                    "case_id": "R-" + s.slot_id,
                    "task_id": s.target_id + "." + ident,
                    "scenario_type": "missing_parameter"
                    if dim == "missing"
                    else "normal",
                    "test_scope": scope,
                    "target": s.target_id.removeprefix("chain."),
                    "execution": execution(text),
                    "oracle": oracle,
                    "labels": [
                        "slot:" + s.slot_id,
                        "intent:" + ident,
                        "early_stop",
                        "test_fixture",
                        "terminal_goal_only",
                        "needs_runtime_profile_binding",
                    ],
                }
            ).model_dump(mode="json")
            cases.append(
                CompiledCase(
                    slot_id=s.slot_id,
                    dataset_format="eval_case",
                    payload=payload,
                    execution_readiness="needs_runner",
                    coverage_mode="indirect",
                )
            )
            continue
        reason = None
        if ident == "intent.unsupported":
            reason = (
                "Unsupported requests have no successful to"
                "ol path; error injection route is unspecif"
                "ied."
            )
        elif ident == "intent.add_backpack_gift":
            reason = (
                "CONFIRMATION_RESUME_UNSUPPORTED: Agent stops before tool execution."
            )
        elif ident == "intent.prepare_resource" and branch == "normal":
            reason = (
                "PREPARE_RESOURCE_POLICY_MISMATCH: do not a"
                "ssert successful end-to-end behavior."
            )
        bid = "RUNTIME-" + s.slot_id
        readiness = "blocked" if reason else "needs_runner"
        if reason:
            blockers.append(
                Blocker(
                    blocker_id=bid,
                    affected_slot_ids=[s.slot_id],
                    reason=reason,
                    source_refs=refs,
                    required_action=(
                        "Resolve the explicit capability gap before runtime use."
                    ),
                )
            )
        required = [
            "Bind full fixture registry explicitly",
            "Map trace evidence to chain nodes",
            "Initialize deterministic fixture data and expose result assertions",
        ]
        pre = [
            {
                "kind": "isolated_fixture",
                "required": (
                    "Arrange matching records for the selected "
                    "arguments; never assume production IDs."
                ),
            }
        ]
        inp = {
            "user_input": text,
            "operation": "agent_run",
            "intent_id": ident,
            "tool_name": tool,
            "branch": branch,
        }
        if branch == "error":
            inp["controlled_fault"] = {
                "at": "tool_handler",
                "behavior": "raise_exception",
            }
            required.append(
                "Provide an explicit injection runner; nati"
                "ve evaluator rejects fault_injection."
            )
        oracle = {
            "checks": []
            if reason
            else [
                {
                    "op": "equals",
                    "actual": "agent_result.status",
                    "expected": "FAILED" if branch == "error" else "SUCCESS",
                },
                {"op": "subset", "actual": "tool_trace.names", "expected": [tool]},
            ],
            "boundary": s.target_id,
            "declared_branch": branch,
            "coverage_limit": (
                "Ordered node/evidence verification require"
                "s the declared runner binding."
            ),
        }
        case = ContractCase(
            case_id="R-" + s.slot_id,
            slot_id=s.slot_id,
            target_id=s.target_id,
            layer=s.layer,
            preconditions=pre,
            input=inp,
            oracle=oracle,
            source_refs=refs,
            runner_requirements=required,
        )
        cases.append(
            CompiledCase(
                slot_id=s.slot_id,
                dataset_format="capability_contract_case",
                payload=case.model_dump(mode="json"),
                execution_readiness=readiness,
                coverage_mode="contract",
                blocker_ids=[bid] if reason else [],
            )
        )
    return cases, blockers
