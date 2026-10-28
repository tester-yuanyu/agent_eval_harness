"""Metadata-only generation plan; historical inputs/oracles never enter prompts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from dataset_builder.full_generation.inventory import pointer_value


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@dataclass
class FullPlan:
    root: Path
    specs: list[dict]
    documents: dict
    binding: dict

    def document(self, spec):
        return self.documents[spec["target_id"]]

    def declared(self, spec):
        return pointer_value(self.document(spec), spec["pointer"])

    def context(self, spec):
        ids = {spec["target_id"]}
        target = self.document(spec)
        if spec["case_kind"] == "chain_case":
            ids.add(spec["dimension"].split(":")[0])
        if spec["case_kind"] == "module_event":
            from dataset_builder.full_generation.contract_cases import EVENT_STIMULI

            binding = EVENT_STIMULI[self.declared(spec)]
            if binding.get("intent"):
                ids.add("intent." + binding["intent"])
            if binding.get("tool_name"):
                ids.add("tool." + binding["tool_name"])
        for ident in list(ids):
            doc = self.documents[ident]
            tool = doc.get("required_tool_name")
            if tool and "tool." + tool in self.documents:
                ids.add("tool." + tool)
        # Include declared evidence/boundary documents, but not every tool in a chain.
        for ref in target.get("boundary_refs", []) + target.get("evidence_refs", []):
            ident = ref.get("snapshot_id") if isinstance(ref, dict) else ref
            if ident in self.documents:
                ids.add(ident)
        docs = {key: self.documents[key] for key in sorted(ids)}
        return (
            "Author a test definition solely from these source snapshots. "
            "No actual Agent was executed. Tools are isolated fixtures, never production. "  # noqa: E501
            "Do not fill missing behavioral contracts.\nSOURCES:\n" + canonical(docs)
        )


def load_plan(root: Path) -> FullPlan:
    root = Path(root).resolve()
    manifest = json.loads((root / "manifest.json").read_text())
    for name, expected in manifest["files_sha256"].items():
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file() or sha(path) != expected:
            raise ValueError("historical source/hash mismatch: " + name)
    inv = json.loads((root / "inventory.json").read_text())
    documents = {k: v["payload"] for k, v in inv["artifacts"].items()}
    slots = json.loads((root / "coverage_plan.json").read_text())["slots"]
    matrix = {
        r["slot_id"]: r
        for r in json.loads((root / "coverage_matrix.json").read_text())["rows"]
    }
    blockers = {
        b["blocker_id"]: b
        for b in json.loads((root / "blockers.json").read_text())["blockers"]
    }
    specs = []
    for slot in slots:
        row = matrix[slot["slot_id"]]
        if len(row["cases"]) != 1:
            raise ValueError("exactly one baseline classification required")
        meta = row["cases"][0]
        ref = slot["source_refs"][0]
        if documents[slot["target_id"]]["snapshot_sha256"] != ref["snapshot_sha256"]:
            raise ValueError("source reference mismatch")
        pointer_value(documents[slot["target_id"]], ref["pointer"])
        gap_reason = ""
        original_blocked = meta["definition_kind"] == "blocked_obligation"
        if original_blocked:
            gap_reason = "; ".join(
                blockers[b]["reason"] for b in meta["blocker_ids"] if b in blockers
            )
            gap_reason = (
                gap_reason or "Concrete stimulus or executable predicate is not bound."
            )
        extra_gap = (
            slot["case_kind"] == "intent_case"
            and slot["dimension"] in {"missing", "invalid"}
            and slot["target_id"] != "intent.unsupported"
        )
        if extra_gap:
            gap_reason = "missing_parameters: the enum does not define an exact per-scenario mapping; no oracle may be guessed."  # noqa: E501
        specs.append(
            {
                **slot,
                "pointer": ref["pointer"],
                "parameter": ref["pointer"]
                .rsplit("/", 1)[-1]
                .replace("~1", "/")
                .replace("~0", "~")
                if slot["case_kind"] == "parameter"
                else None,
                "definition_kind": meta["definition_kind"],
                "baseline_format": meta["dataset_format"],
                "execution_readiness": meta["execution_readiness"],
                "input_only": original_blocked or extra_gap,
                "extra_oracle_gap": extra_gap,
                "gap_reason": gap_reason,
                "evidence_refs": [
                    r["snapshot_id"] + "#" + r["pointer"] for r in slot["source_refs"]
                ],
            }
        )
    if len({s["slot_id"] for s in specs}) != len(specs):
        raise ValueError("duplicate slot")
    return FullPlan(
        root,
        specs,
        documents,
        {
            "bundle_sha256": manifest["bundle_sha256"],
            "plan_sha256": sha(root / "coverage_plan.json"),
            "inventory_sha256": sha(root / "inventory.json"),
            "matrix_sha256": sha(root / "coverage_matrix.json"),
            "manifest_sha256": sha(root / "manifest.json"),
        },
    )
