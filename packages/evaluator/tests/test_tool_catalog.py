from __future__ import annotations

import pytest
from conftest import e2e_case, module_case

from eval_framework.capabilities import (
    CapabilityBundle,
    CapabilityDocument,
    CapabilityRegistry,
)
from eval_framework.dataset_validator import validate_dataset
from eval_framework.schemas import DatasetBundle, EvalCase, ExecutionProfile
from eval_framework.tool_catalog import ToolCatalog, ToolCatalogError


def _document(
    snapshot_id: str,
    snapshot_type: str,
    payload: dict,
) -> CapabilityDocument:
    return CapabilityDocument(
        snapshot_id=snapshot_id,
        snapshot_type=snapshot_type,
        snapshot_format_version="1.0",
        contract_version="fixture-v1",
        snapshot_sha256="a" * 64,
        payload=payload,
    )


def _registry() -> CapabilityRegistry:
    documents = (
        _document(
            "intent_router",
            "module",
            {"output_schema": {"type": "object"}},
        ).model_copy(update={"module_id": "intent_router"}),
        _document(
            "tool_catalog",
            "tool_catalog",
            {
                "profiles": {
                    "temporary_profile": ["temporary_read", "temporary_write"]
                },
                "tool_snapshot_ids": ["temporary_read", "temporary_write"],
            },
        ),
        _document(
            "temporary_read",
            "tool_capability",
            {
                "tool_name": "temporary_read",
                "tool_type": "read",
                "fault_modes": ["normal", "empty_result", "error", "timeout"],
            },
        ),
        _document(
            "temporary_write",
            "tool_capability",
            {
                "tool_name": "temporary_write",
                "tool_type": "write",
                "fault_modes": ["normal", "error", "timeout", "commit_then_timeout"],
            },
        ),
    )
    return CapabilityRegistry(
        CapabilityBundle(
            root="/fixture",
            provider_id="fixture",
            bundle_format_version="1.0",
            capability_bundle_sha256="b" * 64,
            documents=documents,
        )
    )


def _dataset(case: dict) -> DatasetBundle:
    profile = case["execution"]["tool_profile"]
    return DatasetBundle(
        path="/fixture/cases.jsonl",
        sha256="c" * 64,
        schema_versions=["1.0"],
        dataset_version="fixture",
        execution_profiles={
            profile: ExecutionProfile(
                allowed_tools=["temporary_read", "temporary_write"]
            )
        },
        execution_profiles_source="manifest",
        total_count=1,
        cases=[EvalCase.model_validate(case)],
    )


def test_temporary_profile_and_tools_require_no_evaluator_constants() -> None:
    registry = _registry()
    catalog = ToolCatalog.from_registry(
        registry,
        profiles={
            "temporary_profile": ExecutionProfile(
                allowed_tools=["temporary_read", "temporary_write"]
            )
        },
    )
    case = module_case()
    case["execution"].update(
        tool_profile="temporary_profile",
        allowed_tools=["temporary_read"],
    )

    report = validate_dataset(_dataset(case), registry, catalog)

    assert report.valid
    assert catalog.tools_for_profile("temporary_profile") == frozenset(
        {"temporary_read", "temporary_write"}
    )


def test_unknown_profile_is_a_validation_issue() -> None:
    registry = _registry()
    case = module_case()
    case["execution"]["tool_profile"] = "not_registered"

    report = validate_dataset(
        _dataset(case),
        registry,
        ToolCatalog.from_registry(
            registry,
            profiles={
                "temporary_profile": ExecutionProfile(
                    allowed_tools=["temporary_read", "temporary_write"]
                )
            },
        ),
    )

    assert not report.valid
    assert "unknown tool profile" in " ".join(issue.message for issue in report.issues)


def test_read_tool_rejects_commit_then_timeout() -> None:
    registry = _registry()
    case = module_case()
    case["execution"].update(
        tool_profile="temporary_profile",
        fault_injection={"temporary_read": "commit_then_timeout"},
    )

    report = validate_dataset(
        _dataset(case),
        registry,
        ToolCatalog.from_registry(
            registry,
            profiles={
                "temporary_profile": ExecutionProfile(
                    allowed_tools=["temporary_read", "temporary_write"]
                )
            },
        ),
    )

    assert not report.valid
    assert "does not support fault mode" in " ".join(
        issue.message for issue in report.issues
    )


def test_write_tool_rejects_empty_result() -> None:
    registry = _registry()
    case = module_case()
    case["execution"].update(
        tool_profile="temporary_profile",
        fault_injection={"temporary_write": "empty_result"},
    )

    report = validate_dataset(
        _dataset(case),
        registry,
        ToolCatalog.from_registry(
            registry,
            profiles={
                "temporary_profile": ExecutionProfile(
                    allowed_tools=["temporary_read", "temporary_write"]
                )
            },
        ),
    )

    assert not report.valid
    assert "does not support fault mode" in " ".join(
        issue.message for issue in report.issues
    )


def test_write_case_requires_responses_and_cleanup() -> None:
    registry = _registry()
    case = e2e_case()
    case["execution"].update(
        tool_profile="temporary_profile",
        allowed_tools=["temporary_write"],
        user_responses=[],
    )
    case["oracle"]["expected_tool_calls"][0]["name"] = "temporary_write"
    case["cleanup"] = None

    report = validate_dataset(
        _dataset(case),
        registry,
        ToolCatalog.from_registry(
            registry,
            profiles={
                "temporary_profile": ExecutionProfile(
                    allowed_tools=["temporary_read", "temporary_write"]
                )
            },
        ),
    )

    assert not report.valid
    assert "write case requires responses and cleanup" in " ".join(
        issue.message for issue in report.issues
    )


def test_manifest_profile_unknown_tool_is_rejected() -> None:
    with pytest.raises(ToolCatalogError, match="unknown tools"):
        ToolCatalog.from_registry(
            _registry(),
            profiles={
                "temporary_profile": ExecutionProfile(allowed_tools=["not_in_bundle"])
            },
        )


@pytest.mark.parametrize(
    "effects, operation", [([], "read"), ([{"type": "create"}], "write")]
)
def test_v3_catalog_derives_side_effects_without_claiming_fault_injection(
    effects, operation
):
    document = _document(
        "tool.fixture",
        "tool",
        {
            "tool_name": "fixture",
            "side_effects": effects,
        },
    ).model_copy(update={"snapshot_format_version": "3.0"})
    registry = CapabilityRegistry(
        _registry().bundle.model_copy(
            update={
                "bundle_format_version": "3.0",
                "documents": (document,),
            }
        )
    )
    before = document.model_dump()
    catalog = ToolCatalog.from_registry(
        registry,
        profiles={
            "fixture": ExecutionProfile(allowed_tools=["fixture"]),
        },
    )
    assert catalog.get_tool("fixture").operation == operation
    assert catalog.get_tool("fixture").fault_modes == frozenset()
    assert document.model_dump() == before


def test_v3_catalog_rejects_missing_side_effect_declaration():
    document = _document("tool.fixture", "tool", {"tool_name": "fixture"}).model_copy(
        update={"snapshot_format_version": "3.0"}
    )
    registry = CapabilityRegistry(
        _registry().bundle.model_copy(
            update={
                "bundle_format_version": "3.0",
                "documents": (document,),
            }
        )
    )
    with pytest.raises(ToolCatalogError):
        ToolCatalog.from_registry(registry, profiles={})
