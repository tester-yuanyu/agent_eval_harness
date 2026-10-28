"""Deterministic three-state resolution for composable v3 selections."""

from __future__ import annotations

from pydantic import Field

from capability_snapshot_kit.base import ProtocolModel
from capability_snapshot_kit.bundle import CapabilityBundleV3
from capability_snapshot_kit.models import (
    CapabilityClaimV3,
    CapabilityRequirementV3,
    ChainSnapshotV3,
    EvidenceSnapshotV3,
    IntentSnapshotV3,
    ScopeSnapshotV3,
    SnapshotV3,
    SupportStatusV3,
)
from capability_snapshot_kit.versions import SNAPSHOT_FORMAT_VERSION_V3


class CapabilitySelectionV3(ProtocolModel):
    scope_or_chain_id: str = Field(pattern=r"^(scope|chain)\.[a-z][a-z0-9_]*$")
    intent_id: str = Field(pattern=r"^intent\.[a-z][a-z0-9_]*$")
    tool_id: str | None = Field(default=None, pattern=r"^tool\.[a-z][a-z0-9_]*$")


class ResolvedRequirementV3(ProtocolModel):
    requirement_id: str
    capability_key: str
    provider_snapshot_ids: list[str]
    evidence_ids: list[str]
    support_status: SupportStatusV3
    diagnostics: list[str]


class ResolvedCapabilityGraphV3(ProtocolModel):
    selection: CapabilitySelectionV3
    support_status: SupportStatusV3
    snapshot_ids: list[str]
    requirements: list[ResolvedRequirementV3]
    diagnostics: list[str]


def _all_snapshots(bundle: CapabilityBundleV3) -> dict[str, SnapshotV3]:
    return {
        bundle.agent.snapshot_id: bundle.agent,
        **{snapshot.snapshot_id: snapshot for snapshot in bundle.child_snapshots},
    }


def _claims(snapshot: SnapshotV3) -> list[CapabilityClaimV3]:
    values = getattr(snapshot, "capabilities", None)
    return list(values) if isinstance(values, list) else []


def _diagnostic_path(
    source_id: str,
    requirement: CapabilityRequirementV3,
    provider_id: str | None,
) -> str:
    suffix = f" -> {provider_id}" if provider_id else ""
    return f"{source_id} -> {requirement.requirement_id}{suffix}"


def _resolve_provider(
    *,
    bundle: CapabilityBundleV3,
    source_id: str,
    requirement: CapabilityRequirementV3,
    intent: IntentSnapshotV3 | None,
    selection: CapabilitySelectionV3,
) -> tuple[SnapshotV3 | None, SupportStatusV3 | None, list[str]]:
    provider = requirement.provider
    if provider.role == "selected_intent":
        path = _diagnostic_path(source_id, requirement, selection.intent_id)
        if intent is None:
            return None, SupportStatusV3.UNKNOWN, [
                f"{path}: selected Intent provider is missing"
            ]
        return intent, None, []

    if provider.role == "selected_tool":
        required_name = intent.required_tool_name if intent is not None else None
        expected_id = f"tool.{required_name}" if required_name else None
        selected_id = selection.tool_id
        path = _diagnostic_path(source_id, requirement, selected_id or expected_id)
        if intent is None:
            return None, SupportStatusV3.UNKNOWN, [
                f"{path}: selected Intent is unavailable, so Tool binding is unknown"
            ]
        if expected_id is None:
            return None, SupportStatusV3.UNSUPPORTED, [
                f"{path}: selected Intent declares no required Tool"
            ]
        if selected_id is not None and selected_id != expected_id:
            return None, SupportStatusV3.UNSUPPORTED, [
                f"{path}: required-tool mismatch; Intent requires {expected_id}"
            ]
        if expected_id not in bundle.tools:
            return None, SupportStatusV3.UNSUPPORTED, [
                f"{path}: required Tool {expected_id} is not registered"
            ]
        if selected_id is None:
            return None, SupportStatusV3.UNKNOWN, [
                f"{path}: matching Tool exists but no Tool was selected"
            ]
        return bundle.tools[expected_id], None, []

    provider_id = provider.snapshot_id
    path = _diagnostic_path(source_id, requirement, provider_id)
    snapshots = _all_snapshots(bundle)
    if provider_id is None or provider_id not in snapshots:
        return None, SupportStatusV3.UNKNOWN, [
            f"{path}: exact snapshot provider is missing"
        ]
    return snapshots[provider_id], None, []


def _resolve_requirement(
    *,
    bundle: CapabilityBundleV3,
    source: ScopeSnapshotV3 | ChainSnapshotV3,
    requirement: CapabilityRequirementV3,
    intent: IntentSnapshotV3 | None,
    selection: CapabilitySelectionV3,
) -> ResolvedRequirementV3:
    provider, binding_status, diagnostics = _resolve_provider(
        bundle=bundle,
        source_id=source.snapshot_id,
        requirement=requirement,
        intent=intent,
        selection=selection,
    )
    provider_ids = [provider.snapshot_id] if provider is not None else []
    evidence_ids = list(requirement.evidence_ids)
    if binding_status is not None:
        return ResolvedRequirementV3(
            requirement_id=requirement.requirement_id,
            capability_key=requirement.capability_key,
            provider_snapshot_ids=provider_ids,
            evidence_ids=evidence_ids,
            support_status=binding_status,
            diagnostics=diagnostics,
        )

    assert provider is not None
    path = _diagnostic_path(source.snapshot_id, requirement, provider.snapshot_id)
    if provider.snapshot_format_version != SNAPSHOT_FORMAT_VERSION_V3:
        diagnostics.append(
            f"{path}: incompatible provider format {provider.snapshot_format_version!r}"
        )
        status = SupportStatusV3.UNKNOWN
    else:
        matching = [
            claim
            for claim in _claims(provider)
            if claim.capability_key == requirement.capability_key
        ]
        if not matching:
            diagnostics.append(
                f"{path}: provider has no claim for {requirement.capability_key}"
            )
            status = SupportStatusV3.UNKNOWN
        else:
            claim = matching[0]
            status = claim.support_status
            evidence_ids = sorted({*evidence_ids, *claim.evidence_ids})
            if status != SupportStatusV3.SUPPORTED:
                diagnostics.append(
                    f"{path}: provider claim is {status.value}: {claim.reason}"
                )

    if status == SupportStatusV3.SUPPORTED:
        evidence_snapshots: list[EvidenceSnapshotV3] = []
        missing: list[str] = []
        unavailable: list[str] = []
        for evidence_id in evidence_ids:
            evidence = bundle.evidence.get(evidence_id)
            if evidence is None:
                missing.append(evidence_id)
                continue
            evidence_snapshots.append(evidence)
            if (
                evidence.snapshot_format_version != SNAPSHOT_FORMAT_VERSION_V3
                or evidence.availability.support_status != SupportStatusV3.SUPPORTED
            ):
                unavailable.append(evidence_id)
        if missing:
            diagnostics.append(f"{path}: missing Evidence {sorted(missing)}")
            status = SupportStatusV3.UNKNOWN
        if unavailable:
            diagnostics.append(f"{path}: unavailable Evidence {sorted(unavailable)}")
            status = SupportStatusV3.UNKNOWN
        provider_ids.extend(item.snapshot_id for item in evidence_snapshots)

    return ResolvedRequirementV3(
        requirement_id=requirement.requirement_id,
        capability_key=requirement.capability_key,
        provider_snapshot_ids=sorted(set(provider_ids)),
        evidence_ids=evidence_ids,
        support_status=status,
        diagnostics=diagnostics,
    )


def resolve_capability_graph_v3(
    bundle: CapabilityBundleV3,
    selection: CapabilitySelectionV3,
) -> ResolvedCapabilityGraphV3:
    """Resolve a Scope/Chain plus selected Intent and Tool into three states."""

    source = bundle.scopes.get(selection.scope_or_chain_id) or bundle.chains.get(
        selection.scope_or_chain_id
    )
    intent = bundle.intents.get(selection.intent_id)
    if source is None:
        return ResolvedCapabilityGraphV3(
            selection=selection,
            support_status="unknown",
            snapshot_ids=sorted(
                snapshot_id
                for snapshot_id in (selection.intent_id, selection.tool_id)
                if snapshot_id in _all_snapshots(bundle)
            ),
            requirements=[],
            diagnostics=[
                f"{selection.scope_or_chain_id}: selected Scope/Chain snapshot "
                "is missing"
            ],
        )

    resolved = [
        _resolve_requirement(
            bundle=bundle,
            source=source,
            requirement=requirement,
            intent=intent,
            selection=selection,
        )
        for requirement in source.requirements
    ]
    mandatory = [
        item
        for item, requirement in zip(resolved, source.requirements, strict=True)
        if requirement.mandatory
    ]
    if any(item.support_status == SupportStatusV3.UNSUPPORTED for item in mandatory):
        status = SupportStatusV3.UNSUPPORTED
    elif any(item.support_status == SupportStatusV3.UNKNOWN for item in mandatory):
        status = SupportStatusV3.UNKNOWN
    else:
        status = SupportStatusV3.SUPPORTED

    available_ids = set(_all_snapshots(bundle))
    snapshot_ids = {
        source.snapshot_id,
        *(
            item
            for item in (selection.intent_id, selection.tool_id)
            if item in available_ids
        ),
        *(
            snapshot_id
            for requirement in resolved
            for snapshot_id in requirement.provider_snapshot_ids
        ),
    }
    diagnostics = [
        diagnostic for requirement in resolved for diagnostic in requirement.diagnostics
    ]
    return ResolvedCapabilityGraphV3(
        selection=selection,
        support_status=status,
        snapshot_ids=sorted(snapshot_ids),
        requirements=resolved,
        diagnostics=diagnostics,
    )
