"""Deterministic coverage: every declared contract item is accounted for."""

import hashlib

from .inventory import escape, source_ref
from .models import Blocker, CoverageSlot, FullInventory


def plan_coverage(inv: FullInventory) -> tuple[list[CoverageSlot], list[Blocker]]:
    slots, blockers = [], []

    def add(ident, layer, pointer, dimension, kind, status="supported"):
        ref = source_ref(inv, ident, pointer)
        key = f"{ident}|{pointer}|{dimension}"
        slot_id = ident + "." + hashlib.sha256(key.encode()).hexdigest()[:14]
        ids = []
        if status != "supported":
            bid = "UNSUPPORTED-" + slot_id
            ids.append(bid)
            blockers.append(
                Blocker(
                    blocker_id=bid,
                    affected_slot_ids=[slot_id],
                    reason=f"Source declares {status}; no positive oracle is inferred.",
                    source_refs=[ref],
                    required_action=(
                        "Provide a supported contract or an explicit negative behavior."
                    ),
                )
            )
        slots.append(
            CoverageSlot(
                slot_id=slot_id,
                target_id=ident,
                layer=layer,
                dimension=dimension,
                source_refs=[ref],
                support_status=status,
                case_kind=kind,
                blocker_ids=ids,
            )
        )

    def schema_slots(ident, layer, schema, prefix):
        # Every nested constraint has its own source pointer, including $defs.
        def walk(value, pointer):
            if isinstance(value, dict):
                for name, child in sorted(value.items()):
                    path = pointer + "/" + escape(name)
                    if name in {
                        "type",
                        "minimum",
                        "maximum",
                        "exclusiveMinimum",
                        "exclusiveMaximum",
                        "minLength",
                        "maxLength",
                        "minItems",
                        "maxItems",
                        "pattern",
                        "enum",
                        "required",
                        "additionalProperties",
                        "$ref",
                    }:
                        add(ident, layer, path, "constraint", "schema_constraint")
                    walk(child, path)
            elif isinstance(value, list):
                for i, child in enumerate(value):
                    if isinstance(child, (dict, list)):
                        walk(child, pointer + "/" + str(i))

        walk(schema, prefix)
        for name in sorted(schema.get("properties", {})):
            ptr = prefix + "/properties/" + escape(name)
            for dim in ("valid", "wrong_type", "omitted"):
                add(ident, layer, ptr, dim, "parameter")
            prop = schema["properties"][name]
            variants = prop.get("anyOf", [prop])
            if any(
                any(
                    k in v
                    for k in (
                        "minimum",
                        "exclusiveMinimum",
                        "maximum",
                        "minItems",
                        "minLength",
                        "pattern",
                    )
                )
                for v in variants
            ):
                for dim in ("boundary", "outside_boundary"):
                    add(ident, layer, ptr, dim, "parameter")

    for target in sorted(inv.targets, key=lambda x: x["snapshot_id"]):
        ident, typ = target["snapshot_id"], target["snapshot_type"]
        d = inv.artifacts[ident]["payload"]
        layer = (
            "tools"
            if typ == "tool"
            else "end_to_end"
            if ident == "chain.end_to_end"
            else "critical_links"
            if typ == "chain"
            else "modules"
        )
        for i, claim in enumerate(d.get("capabilities", [])):
            add(
                ident,
                layer,
                f"/capabilities/{i}",
                claim["capability_key"],
                "claim",
                claim.get("support_status", "unknown"),
            )
        if typ == "module":
            for field in ("input_schema", "output_schema"):
                add(ident, layer, "/" + field, field, "module_schema")
            for i, event in enumerate(d.get("trace_event_types", [])):
                add(ident, layer, f"/trace_event_types/{i}", event, "module_event")
        if typ == "intent":
            schema_slots(ident, layer, d["parameters_schema"], "/parameters_schema")
            for field in ("decision_rules", "parameter_semantics", "semantic_rules"):
                for key in sorted(d.get(field, {})):
                    add(ident, layer, "/" + field + "/" + escape(key), key, "semantic")
            for dim in ("complete", "missing", "invalid", "expression_variant"):
                add(ident, layer, "/decision_rules", dim, "intent_case")
        if typ == "tool":
            schema_slots(
                ident,
                layer,
                d["function_schema"]["parameters"],
                "/function_schema/parameters",
            )
            for code in sorted(d["result_protocols"]["declared_results"]):
                add(
                    ident,
                    layer,
                    "/result_protocols/declared_results/" + code,
                    code,
                    "tool_result",
                )
            for field in (
                "permission_requirements",
                "preconditions",
                "side_effects",
                "idempotency_rules",
                "retry_policy",
                "parameter_semantics",
                "combination_rules",
                "batch_behavior",
                "simulation_capabilities",
            ):
                if field in d:
                    value = d[field]
                    if isinstance(value, dict) and "support_status" in value:
                        status = value["support_status"]
                    else:
                        status = "supported"
                    add(ident, layer, "/" + field, field, "tool_rule", status)
            for key, value in sorted(d["result_protocols"].items()):
                if key != "declared_results":
                    add(
                        ident,
                        layer,
                        "/result_protocols/" + key,
                        key,
                        "tool_rule",
                        value.get("support_status", "supported"),
                    )
            for key in sorted(d.get("parameter_semantics", {}).get("rules", {})):
                add(
                    ident,
                    layer,
                    "/parameter_semantics/rules/" + escape(key),
                    key,
                    "tool_rule",
                )
        if typ == "chain":
            for field in ("nodes", "requirements", "branches"):
                for i, _value in enumerate(d.get(field, [])):
                    add(
                        ident, layer, f"/{field}/{i}", f"{field}:{i}", "chain_structure"
                    )
            for intent in sorted(
                x["snapshot_id"] for x in inv.targets if x["snapshot_type"] == "intent"
            ):
                for branch in ("normal", "error", "early_stop"):
                    add(ident, layer, "/branches", intent + ":" + branch, "chain_case")
        for field in ("boundary_refs", "evidence_refs"):
            for i in range(len(d.get(field, []))):
                add(ident, layer, f"/{field}/{i}", f"{field}:{i}", "dependency")
    for gap in inv.gaps:
        affected = [s for s in slots if s.target_id in gap["affected_snapshot_ids"]]
        blockers.append(
            Blocker(
                blocker_id=gap["gap_id"],
                affected_slot_ids=[s.slot_id for s in affected],
                reason=gap["reason"],
                source_refs=[s.source_refs[0] for s in affected[:1]],
                required_action=gap["required_action"],
            )
        )
        # Production absence doesn't block fixture tests, other gaps are checked
        # at case compilation according to the branch they actually affect.
    return sorted(slots, key=lambda s: s.slot_id), blockers
