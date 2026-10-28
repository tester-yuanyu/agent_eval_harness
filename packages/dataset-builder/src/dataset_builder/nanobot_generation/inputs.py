"Read-only Nanobot handoff adaptation with the trusted v3 validation kernel."

import hashlib
import json
from pathlib import Path

from ..capability_adapters import CapabilityAdapter
from ..capability_bundle import load_validated_bundle
from ..capability_ir import CapabilitySelection
from ..capability_profiles import load_trusted_profile
from ..full_generation.inventory import pointer_value
from ..resources import resource_root

ROOT = resource_root()


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def safe_path(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(root):
        raise ValueError(f"unsafe path: {relative}")
    return path


def load_input(root: Path, expected_hash: str) -> dict:
    root = root.resolve()
    manifest = json.loads((root / "manifest.json").read_text())
    files = manifest["files_sha256"]
    for name, expected in files.items():
        path = safe_path(root, name)
        if not path.is_file() or sha256(path) != expected:
            raise ValueError(f"source hash mismatch: {name}")
    if manifest["capability_bundle_sha256"] != expected_hash:
        raise ValueError("bundle hash mismatch")
    for name in ("capability_contract_gaps.json", "validation_report.json"):
        if name not in files:
            raise ValueError(f"unbound input: {name}")
    profile = load_trusted_profile(
        "capability-snapshot", "3.0", ROOT / "protocol_profiles/trust_store.json"
    )
    bundle_path = safe_path(root, manifest["bundle_path"])
    bundle = load_validated_bundle(bundle_path, profile)
    if bundle.capability_bundle_sha256 != expected_hash:
        raise ValueError("validated bundle hash mismatch")
    agent = bundle.root.payload
    if agent["agent_id"] != "nanobot":
        raise ValueError("nanobot adapter cannot generate another agent")
    artifacts = {}
    for artifact in bundle.artifacts:
        path = artifact.path.relative_to(root).as_posix()
        if path not in files:
            raise ValueError(f"unbound snapshot: {path}")
        payload = dict(artifact.payload)
        item = {"path": path, "payload": payload}
        if artifact.snapshot_type == "tool":
            function = payload["function_schema"]
            pointer = "/function_schema"
            if function.get("type") == "function":
                function = function["function"]
                pointer += "/function"
            if function.get("name") != payload["tool_name"]:
                raise ValueError("function name mismatch")
            item["parameter_schema"] = function["parameters"]
            item["parameter_schema_pointer"] = pointer + "/parameters"
        artifacts[artifact.snapshot_id] = item
    gaps = json.loads((root / "capability_contract_gaps.json").read_text())
    if (
        "capability_bundle_sha256" in gaps
        and gaps["capability_bundle_sha256"] != expected_hash
    ):
        raise ValueError("gaps bundle hash mismatch")
    ir = CapabilityAdapter().convert(
        bundle,
        CapabilitySelection(
            scope_or_chain_id="chain.end_to_end", intent_id="intent.assistant"
        ),
        profile,
    )
    result = {
        "adapter_version": "nanobot-handoff-1.0",
        "agent_id": agent["agent_id"],
        "agent_version": agent["agent_version"],
        "bundle_sha256": expected_hash,
        "source_root": str(root),
        "files_sha256": {**files, "manifest.json": sha256(root / "manifest.json")},
        "artifacts": artifacts,
        "primary_targets": sorted(
            k
            for k, v in artifacts.items()
            if v["payload"]["snapshot_type"] in {"tool", "module", "intent", "chain"}
        ),
        "gaps": gaps["gaps"],
        "capability_ir": ir.model_dump(mode="json"),
        "adaptation_notes": [
            (
                "Function envelope is projected to "
                "parameter_schema; source files rem"
                "ain unchanged."
            ),
            (
                "Gap report is bound by the deliver"
                "y manifest hash; missing embedded "
                "hash is not fabricated."
            ),
            (
                "Unknown claims, unstructured resul"
                "ts and unknown retry/idempotency r"
                "emain unknown."
            ),
        ],
    }

    if "execution_contract.json" in files:
        contract = json.loads((root / "execution_contract.json").read_text())
        if (contract.get("contract_version"), contract.get("evidence_kind")) != (
            "nanobot-collector-v2",
            "source_contract_not_execution_trace",
        ):
            raise ValueError("unsupported execution contract revision")
        if contract["input_schema"] != agent["input_schema"]:
            raise ValueError("execution input contract differs from snapshot")
        for item in artifacts.values():
            d = item["payload"]
            if d["snapshot_type"] == "tool":
                if d["result_protocols"] != contract["tool_dispatch"]:
                    raise ValueError("tool dispatch contract differs from snapshot")
                if d["retry_policy"] != contract["tool_dispatch"]["retry"]:
                    raise ValueError("tool retry contract differs from snapshot")
        result["execution_contract"] = contract
        result["adapter_version"] = "nanobot-handoff-2.0"
    return result


def bind_source(data, path, pointer=None, anchor=None):
    if path not in data["files_sha256"]:
        raise ValueError(f"unbound source: {path}")
    file = safe_path(data["source_root"], path)
    if sha256(file) != data["files_sha256"][path]:
        raise ValueError(f"source hash mismatch: {path}")
    ref = {"path": path, "sha256": data["files_sha256"][path]}
    if pointer is not None:
        pointer_value(json.loads(file.read_text()), pointer)
        ref["pointer"] = pointer
    if anchor is not None:
        if not anchor or anchor not in file.read_text():
            raise ValueError(f"missing source anchor: {path}: {anchor!r}")
        ref["anchor"] = anchor
    return ref
