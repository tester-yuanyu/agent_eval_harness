"Compile source-backed cases without adopting unknown execution claims."

import hashlib
import json
from pathlib import Path

from ..full_generation.inventory import escape
from .inputs import bind_source
from .models import Candidate
from .schema_cases import schema_examples


def layer_for(payload):
    return {
        "tool": "tools",
        "module": "modules",
        "intent": "modules",
        "chain": "end_to_end",
    }.get(payload["snapshot_type"], "contracts")


def support(payload):
    statuses = [x["support_status"] for x in payload.get("capabilities", [])]
    if "unsupported" in statuses:
        return "unsupported"
    if not statuses or "unknown" in statuses:
        return "unknown"
    return "supported"


def build_cases(data):
    cases, blockers = [], []

    def ref(target, pointer=""):
        return bind_source(data, data["artifacts"][target]["path"], pointer=pointer)

    def blocker(code, target, reason, sources, action):
        bid = "nanobot:" + code + ":" + target
        if not any(b["blocker_id"] == bid for b in blockers):
            blockers.append(
                {
                    "blocker_id": bid,
                    "code": code,
                    "target_id": target,
                    "reason": reason,
                    "source_refs": sources,
                    "required_action": action,
                }
            )
        return bid

    def add(key, target, kind, category, title, inp, checks, refs, **kwargs):
        payload = data["artifacts"][target]["payload"]
        cid = "nanobot:" + target + ":" + hashlib.sha256(key.encode()).hexdigest()[:16]
        candidate = Candidate(
            case_id=cid,
            target_id=target,
            layer=kwargs.pop("layer", layer_for(payload)),
            kind=kind,
            category=category,
            title=title,
            input=inp,
            oracle={"checks": checks},
            source_refs=refs,
            support_status=support(payload),
            source_basis=kwargs.pop("source_basis", "snapshot"),
            execution_readiness=kwargs.pop("execution_readiness", "static_only"),
            **kwargs,
        )
        cases.append(candidate.model_dump(mode="json", exclude_none=True))

    metadata = {
        "snapshot_id",
        "snapshot_type",
        "snapshot_sha256",
        "snapshot_format_version",
        "contract_version",
        "source_hashes",
        "agent_id",
        "agent_version",
        "tool_version",
        "component_versions",
        "module_id",
        "tool_name",
        "capability_id",
        "chain_id",
        "scope_id",
        "boundary_id",
        "evidence_id",
        "capability_bundle_sha256",
    }
    for ident, item in sorted(data["artifacts"].items()):
        d = item["payload"]
        schemas = {}
        if "parameter_schema" in item:
            schemas[item["parameter_schema_pointer"]] = item["parameter_schema"]
        for field in (
            "input_schema",
            "output_schema",
            "parameters_schema",
            "payload_schema",
        ):
            if field in d:
                schemas["/" + field] = d[field]
        for pointer, schema in schemas.items():
            for i, example in enumerate(schema_examples(schema)):
                add(
                    pointer + ":example:" + str(i),
                    ident,
                    "schema_contract",
                    "schema_valid" if example["expected_valid"] else "schema_invalid",
                    f"{ident} {pointer}：" + "; ".join(example["dimensions"]),
                    {
                        "operation": "validate_schema",
                        "schema_ref": ref(ident, pointer),
                        "instance": example["instance"],
                        "dimensions": example["dimensions"],
                        "invoke_handler": False,
                    },
                    [
                        {
                            "subject": "schema_validation.valid",
                            "operator": "equals",
                            "expected": example["expected_valid"],
                        }
                    ],
                    [ref(ident, pointer)],
                )
        for field, value in sorted(d.items()):
            if field in metadata:
                continue
            pointer = "/" + escape(field)
            add(
                "declaration:" + pointer,
                ident,
                "contract_check",
                "declaration",
                f"{ident} 声明保持一致：{field}",
                {"operation": "inspect_snapshot", "source_ref": ref(ident, pointer)},
                [
                    {
                        "subject": "declared_value",
                        "operator": "equals",
                        "expected": value,
                    }
                ],
                [ref(ident, pointer)],
            )
        for i, claim in enumerate(d.get("capabilities", [])):
            if claim["support_status"] == "supported":
                continue
            refs = [ref(ident, f"/capabilities/{i}")]
            bid = blocker(
                "CAPABILITY_" + claim["support_status"].upper(),
                ident,
                claim.get("reason") or "Execution capability unresolved",
                refs,
                (
                    "Provide an explicit execution cont"
                    "ract and an isolated runner bindin"
                    "g."
                ),
            )
            add(
                "unresolved:" + str(i),
                ident,
                "blocked_obligation",
                "unknown_capability",
                f"{ident} 能力尚未明确：{claim['capability_key']}",
                {
                    "operation": "resolve_contract",
                    "capability_key": claim["capability_key"],
                },
                [],
                refs,
                execution_readiness="blocked",
                source_basis="missing_contract",
                blocker_ids=[bid],
            )
        if d["snapshot_type"] == "tool":
            for field in (
                "result_protocols",
                "idempotency_rules",
                "retry_policy",
                "permission_requirements",
                "side_effects",
                "batch_behavior",
            ):
                refs = [ref(ident, "/" + field)]
                bid = blocker(
                    "INCOMPLETE_" + field.upper(),
                    ident,
                    (
                        "Only registry metadata or unaudite"
                        "d/unknown semantics are supplied."
                    ),
                    refs,
                    (
                        "Supply tool-specific audited seman"
                        "tics and test fixture; do not infe"
                        "r absence of capability."
                    ),
                )
                add(
                    "missing:" + field,
                    ident,
                    "blocked_obligation",
                    "missing_semantics",
                    f"{ident} 待补充契约：{field}",
                    {"operation": "resolve_contract", "field": field},
                    [],
                    refs,
                    execution_readiness="blocked",
                    source_basis="missing_contract",
                    blocker_ids=[bid],
                )

    for filename in ("behavior_catalog.json", "module_catalog.json"):
        catalog = json.loads((Path(__file__).parent / filename).read_text())
        for row in catalog:
            target = row["target_id"]
            refs = [bind_source(data, **r) for r in row["sources"]]
            status = support(data["artifacts"][target]["payload"])
            bids = []
            if status != "supported":
                bids.append(
                    blocker(
                        "EXECUTION_UNKNOWN",
                        target,
                        (
                            "Implementation-derived hypothesis;"
                            " snapshot execution remains unknow"
                            "n."
                        ),
                        [ref(target, "/capabilities")],
                        (
                            "Confirm semantics and bind an isol"
                            "ated runner before execution."
                        ),
                    )
                )
            add(
                "behavior:" + row["key"],
                target,
                "behavior_candidate",
                row["category"],
                row["title"],
                row["input"],
                row["checks"],
                refs,
                preconditions=row["preconditions"],
                runner_requirements=row["requirements"],
                source_basis="implementation_derived",
                execution_readiness="blocked" if bids else "needs_runner",
                blocker_ids=bids,
            )

    # Missing chain definitions are obligations, not invented routes between tools.
    root_id = next(
        k
        for k, v in data["artifacts"].items()
        if v["payload"]["snapshot_type"] == "agent"
    )
    refs = [ref(root_id, "/chain_refs")]
    bid = blocker(
        "CRITICAL_CHAIN_NOT_DECLARED",
        root_id,
        (
            "Only the conversation end_to_end c"
            "hain is declared; no critical-link"
            " graph exists."
        ),
        refs,
        (
            "Declare critical chain nodes, edge"
            "s, allowed modules/tools, branches"
            " and evidence."
        ),
    )
    add(
        "critical_chain_missing",
        root_id,
        "blocked_obligation",
        "missing_chain",
        "关键链路未声明，不能将工具任意交叉组合",
        {"operation": "resolve_chain_contract"},
        [],
        refs,
        layer="critical_links",
        execution_readiness="blocked",
        source_basis="missing_contract",
        blocker_ids=[bid],
    )

    target = "chain.end_to_end"
    refs = [
        ref("boundary.conversation", "/prohibited_module_ids"),
        bind_source(
            data,
            "sources/nanobot/nanobot.py",
            anchor="response = await self._loop.process_direct(",
        ),
        bind_source(data, "sources/nanobot/agent/context.py", anchor="self.memory"),
    ]
    conflict = blocker(
        "CONVERSATION_BOUNDARY_IMPLEMENTATION_MISMATCH",
        target,
        (
            "Conversation prohibits internal mo"
            "dules used by the implementation; "
            "observation scope vs runtime bound"
            "ary is unresolved."
        ),
        refs,
        (
            "Re-export explicit observation sco"
            "pe and execution boundary; do not "
            "assert zero internal calls."
        ),
    )
    for i, branch in enumerate(data["artifacts"][target]["payload"]["branches"]):
        name = branch["branch_type"]
        branch_refs = [
            ref(target, f"/branches/{i}"),
            ref("evidence.final_response", "/applicable_result_paths"),
        ]
        bid = blocker(
            "UNRESOLVED_BRANCH_" + name.upper(),
            target,
            (
                "Business-task support is unknown; "
                "evidence only covers successful SD"
                "K return, not business gold answer"
                "s or all terminal branches."
            ),
            branch_refs,
            (
                "Provide branch-specific stimuli, t"
                "erminal oracle and replayable fixt"
                "ures."
            ),
        )
        checks = []
        if name == "normal":
            checks = [
                {
                    "subject": "serialized_RunResult",
                    "operator": "schema_valid",
                    "expected": data["artifacts"]["evidence.final_response"]["payload"][
                        "payload_schema"
                    ],
                }
            ]
        add(
            "chain:" + name,
            target,
            "behavior_candidate" if checks else "blocked_obligation",
            name,
            f"对话端到端 {name}："
            + ("SDK 返回结构候选，业务正确性待定义" if checks else "缺少分支专用契约"),
            {
                "operation": "invoke_sdk" if checks else "resolve_branch_contract",
                "entrypoint": "nanobot.nanobot.Nanobot.run",
                "arguments": {
                    "message": "你好，请简短介绍你的用途。",
                    "ephemeral": True,
                },
                "branch": name,
            },
            checks,
            branch_refs + refs,
            preconditions=[
                {
                    "fixture": "isolated_nanobot",
                    "network": "disabled",
                    "provider": "requires_explicit_replay_fixture",
                }
            ],
            execution_readiness="blocked",
            blocker_ids=[bid, conflict],
            runner_requirements=[
                "Resolve scope/boundary conflict",
                "Nanobot SDK adapter and response evidence serializer",
                "Branch-specific expected behavior",
            ],
        )

    for index, gap in enumerate(data["gaps"]):
        target = gap["fact_id"]
        blocker(
            f"SOURCE_GAP_{index:03}",
            target,
            gap["reason"],
            [
                bind_source(
                    data, "capability_contract_gaps.json", pointer=f"/gaps/{index}"
                )
            ],
            (
                "Preserve source unknown status unt"
                "il capability owner supplies evide"
                "nce."
            ),
        )
    return sorted(cases, key=lambda x: x["case_id"]), sorted(
        blockers, key=lambda x: x["blocker_id"]
    )
