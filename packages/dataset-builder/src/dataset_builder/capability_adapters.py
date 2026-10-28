"""Deterministic adapters from trusted capability protocols to Capability IR."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from typing import Any

from .capability_bundle import BundleArtifact, ValidatedCapabilityBundle
from .capability_ir import (
    CapabilityClaimIR,
    CapabilityIR,
    CapabilitySelection,
    EvidenceIR,
    RequirementResolutionIR,
    SelectedIntentIR,
    SelectedNodeIR,
    SelectedToolIR,
    SourceArtifactBindingIR,
    SupportStatus,
)
from .capability_profiles import LoadedProtocolProfile, canonical_json_bytes


class AdapterConversionError(ValueError):
    """A structurally valid bundle cannot be converted under the profile."""


def resolve_support_status(statuses: Iterable[SupportStatus]) -> SupportStatus:
    values = tuple(statuses)
    if SupportStatus.UNSUPPORTED in values:
        return SupportStatus.UNSUPPORTED
    if SupportStatus.UNKNOWN in values:
        return SupportStatus.UNKNOWN
    return SupportStatus.SUPPORTED


def _support(value: object) -> SupportStatus:
    try:
        return SupportStatus(str(value))
    except ValueError:
        return SupportStatus.UNKNOWN


def _reference_ids(payload: Mapping[str, Any], field: str) -> tuple[str, ...]:
    value = payload.get(field, [])
    if not isinstance(value, list):
        return ()
    return tuple(
        sorted(
            item["snapshot_id"]
            for item in value
            if isinstance(item, dict) and isinstance(item.get("snapshot_id"), str)
        )
    )


def _claims(artifact: BundleArtifact) -> dict[str, Mapping[str, Any]]:
    raw = artifact.payload.get("capabilities", [])
    if not isinstance(raw, list):
        return {}
    return {
        str(item["capability_key"]): item
        for item in raw
        if isinstance(item, dict) and "capability_key" in item
    }


class CapabilityAdapter:
    """Translate the trusted Capability Snapshot format into Capability IR."""

    def convert(
        self,
        bundle: ValidatedCapabilityBundle,
        selection: CapabilitySelection,
        profile: LoadedProtocolProfile,
    ) -> CapabilityIR:
        if bundle.profile.sha256 != profile.sha256:
            raise AdapterConversionError("profile_binding_mismatch")
        selected_node = self._selected(
            bundle, selection.scope_or_chain_id, {"scope", "chain"}
        )
        intent = self._selected(bundle, selection.intent_id, {"intent"})
        tool = (
            self._selected(bundle, selection.tool_id, {"tool"})
            if selection.tool_id is not None
            else None
        )
        required_tool_name = intent.payload.get("required_tool_name")
        if tool is not None and tool.payload.get("tool_name") != required_tool_name:
            raise AdapterConversionError(
                "required_tool_name_mismatch:"
                f"expected={required_tool_name}:actual={tool.payload.get('tool_name')}"
            )

        start_ids = [selected_node.snapshot_id, intent.snapshot_id]
        if tool is not None:
            start_ids.append(tool.snapshot_id)
        selected_closure = bundle.reference_closure(start_ids)
        closure_by_id = {
            item.snapshot_id: item for item in (bundle.root, *selected_closure)
        }
        closure = tuple(
            closure_by_id[snapshot_id] for snapshot_id in sorted(closure_by_id)
        )
        requirement_results, used_claims = self._resolve_requirements(
            bundle=bundle,
            selected_node=selected_node,
            intent=intent,
            tool=tool,
            required_tool_name=(
                str(required_tool_name) if required_tool_name is not None else None
            ),
        )
        mandatory_statuses = [
            item.support_status for item in requirement_results if item.mandatory
        ]
        support_status = resolve_support_status(mandatory_statuses)
        evidence_ids = sorted(
            {
                evidence_id
                for item in requirement_results
                for evidence_id in item.evidence_ids
            }
        )
        evidence = tuple(
            self._evidence(bundle, evidence_id) for evidence_id in evidence_ids
        )
        boundary_ids = _reference_ids(selected_node.payload, "boundary_refs")

        raw: dict[str, Any] = {
            "schema_version": "1.0",
            "source_protocol_id": profile.profile.protocol_id,
            "source_protocol_version": profile.profile.protocol_version,
            "profile_id": profile.profile.profile_id,
            "profile_sha256": profile.sha256,
            "adapter_protocol": profile.profile.adapter.protocol,
            "adapter_version": profile.profile.adapter.version,
            "agent_snapshot_id": bundle.root.snapshot_id,
            "agent_snapshot_sha256": bundle.root.snapshot_sha256,
            "capability_bundle_sha256": bundle.capability_bundle_sha256,
            "selection": selection.model_dump(mode="json"),
            "selected_node": SelectedNodeIR(
                snapshot_id=selected_node.snapshot_id,
                snapshot_type=selected_node.snapshot_type,
                description=self._optional_string(
                    selected_node.payload.get("description")
                ),
                completion_condition=self._optional_string(
                    selected_node.payload.get("completion_condition")
                ),
                boundary_ids=boundary_ids,
            ).model_dump(mode="json"),
            "intent": SelectedIntentIR(
                snapshot_id=intent.snapshot_id,
                capability_id=str(intent.payload.get("capability_id", "")),
                contract_version=intent.contract_version,
                module_id=self._optional_string(intent.payload.get("module_id")),
                required_tool_name=self._optional_string(required_tool_name),
            ).model_dump(mode="json"),
            "tool": (
                SelectedToolIR(
                    snapshot_id=tool.snapshot_id,
                    tool_name=str(tool.payload.get("tool_name", "")),
                    registered=bool(tool.payload.get("registered", False)),
                    function_schema=dict(tool.payload.get("function_schema", {})),
                ).model_dump(mode="json")
                if tool is not None
                else None
            ),
            "support_status": support_status.value,
            "requirements": [
                item.model_dump(mode="json") for item in requirement_results
            ],
            "claims": [item.model_dump(mode="json") for item in used_claims],
            "evidence": [item.model_dump(mode="json") for item in evidence],
            "parameters_schema": dict(intent.payload.get("parameters_schema", {})),
            "decision_rules": dict(intent.payload.get("decision_rules", {})),
            "parameter_semantics": dict(
                intent.payload.get("parameter_semantics", {})
            ),
            "semantic_rules": dict(intent.payload.get("semantic_rules", {})),
            "source_artifacts": [
                SourceArtifactBindingIR(
                    snapshot_id=item.snapshot_id,
                    snapshot_type=item.snapshot_type,
                    snapshot_format_version=item.snapshot_format_version,
                    contract_version=item.contract_version,
                    relative_path=item.relative_path,
                    snapshot_sha256=item.snapshot_sha256,
                ).model_dump(mode="json")
                for item in closure
            ],
            "diagnostics": [],
            "unmapped_facts": [],
        }
        raw["canonical_sha256"] = hashlib.sha256(
            canonical_json_bytes(raw)
        ).hexdigest()
        return CapabilityIR.model_validate(raw)

    @staticmethod
    def _selected(
        bundle: ValidatedCapabilityBundle,
        snapshot_id: str,
        expected_types: set[str],
    ) -> BundleArtifact:
        artifact = bundle.artifacts_by_id.get(snapshot_id)
        if artifact is None:
            raise AdapterConversionError(f"selected_artifact_missing:{snapshot_id}")
        if artifact.snapshot_type not in expected_types:
            raise AdapterConversionError(
                f"selected_artifact_type_mismatch:{snapshot_id}:"
                f"{artifact.snapshot_type}"
            )
        return artifact

    def _resolve_requirements(
        self,
        *,
        bundle: ValidatedCapabilityBundle,
        selected_node: BundleArtifact,
        intent: BundleArtifact,
        tool: BundleArtifact | None,
        required_tool_name: str | None,
    ) -> tuple[tuple[RequirementResolutionIR, ...], tuple[CapabilityClaimIR, ...]]:
        results: list[RequirementResolutionIR] = []
        used_claims: list[CapabilityClaimIR] = []
        raw_requirements = selected_node.payload.get("requirements", [])
        if not isinstance(raw_requirements, list):
            raw_requirements = []
        for requirement in raw_requirements:
            if not isinstance(requirement, dict):
                continue
            provider = requirement.get("provider", {})
            provider = provider if isinstance(provider, dict) else {}
            role = str(provider.get("role", ""))
            provider_id = provider.get("snapshot_id")
            provider_id = provider_id if isinstance(provider_id, str) else None
            if role == "selected_intent":
                provider_artifact = intent
            elif role == "selected_tool":
                provider_artifact = tool
            else:
                provider_artifact = (
                    bundle.artifacts_by_id.get(provider_id)
                    if provider_id is not None
                    else None
                )
            key = str(requirement.get("capability_key", ""))
            required_evidence = tuple(
                sorted(
                    str(item)
                    for item in requirement.get("evidence_ids", [])
                    if isinstance(item, str)
                )
            )
            reason: str | None = None
            if role == "selected_tool" and provider_artifact is None:
                status = SupportStatus.UNSUPPORTED
                reason = (
                    "required tool is not selected or registered: "
                    f"{required_tool_name}"
                )
                claim_evidence: tuple[str, ...] = ()
                source_id = intent.snapshot_id
            elif provider_artifact is None:
                status = SupportStatus.UNKNOWN
                reason = "declared provider is unavailable"
                claim_evidence = ()
                source_id = provider_id or selected_node.snapshot_id
            else:
                claim = _claims(provider_artifact).get(key)
                source_id = provider_artifact.snapshot_id
                if claim is None:
                    status = SupportStatus.UNKNOWN
                    reason = "capability claim is absent"
                    claim_evidence = ()
                else:
                    status = _support(claim.get("support_status"))
                    reason = self._optional_string(claim.get("reason"))
                    claim_evidence = tuple(
                        sorted(
                            item
                            for item in claim.get("evidence_ids", [])
                            if isinstance(item, str)
                        )
                    )
                evidence_statuses = [
                    self._evidence(bundle, item).availability
                    for item in required_evidence
                ]
                status = resolve_support_status((status, *evidence_statuses))
            used_claims.append(
                CapabilityClaimIR(
                    capability_key=key,
                    support_status=status,
                    evidence_ids=claim_evidence,
                    reason=reason,
                    source_snapshot_id=source_id,
                )
            )
            results.append(
                RequirementResolutionIR(
                    requirement_id=str(requirement.get("requirement_id", "")),
                    capability_key=key,
                    mandatory=bool(requirement.get("mandatory", False)),
                    provider_role=role,
                    provider_snapshot_id=(
                        provider_artifact.snapshot_id
                        if provider_artifact is not None
                        else provider_id
                    ),
                    support_status=status,
                    evidence_ids=required_evidence,
                    reason=reason,
                )
            )
        return (
            tuple(sorted(results, key=lambda item: item.requirement_id)),
            tuple(
                sorted(
                    used_claims,
                    key=lambda item: (item.capability_key, item.source_snapshot_id),
                )
            ),
        )

    @staticmethod
    def _evidence(
        bundle: ValidatedCapabilityBundle, snapshot_id: str
    ) -> EvidenceIR:
        artifact = bundle.artifacts_by_id.get(snapshot_id)
        if artifact is None or artifact.snapshot_type != "evidence":
            return EvidenceIR(
                snapshot_id=snapshot_id,
                availability=SupportStatus.UNKNOWN,
            )
        availability = artifact.payload.get("availability", {})
        availability = availability if isinstance(availability, dict) else {}
        return EvidenceIR(
            snapshot_id=snapshot_id,
            availability=_support(availability.get("support_status")),
            observation_interface=CapabilityAdapter._optional_string(
                artifact.payload.get("observation_interface")
            ),
            payload_schema=dict(artifact.payload.get("payload_schema", {})),
            producer_module_ids=tuple(
                sorted(
                    item
                    for item in artifact.payload.get("producer_module_ids", [])
                    if isinstance(item, str)
                )
            ),
        )

    @staticmethod
    def _optional_string(value: object) -> str | None:
        return value if isinstance(value, str) else None
