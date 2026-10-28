from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from conftest import link_case, module_case
from pydantic import ValidationError

from eval_framework.assertions import ASSERTION_SCOPES
from eval_framework.dataset_loader import DatasetLoadError, load_dataset
from eval_framework.dataset_validator import validate_dataset
from eval_framework.provider import EvaluationPreflightError
from eval_framework.schemas import DatasetFilters, EvalCase, ExecutionSpec

SCENARIO_TYPES = {
    "normal",
    "valid_boundary",
    "invalid_parameter",
    "missing_parameter",
    "ambiguous_expression",
    "multi_condition",
    "expression_variant",
    "correction_conflict",
    "unsupported_batch",
}


def _write_manifest_dataset(tmp_path, cases, execution_profiles=...):
    path = tmp_path / "profile-cases.jsonl"
    path.write_text("\n".join(json.dumps(case) for case in cases) + "\n")
    manifest = {
        "dataset_version": "profile-fixture",
        "state": "FROZEN",
        "dataset_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    if execution_profiles is not ...:
        manifest["execution_profiles"] = execution_profiles
    path.with_suffix(".manifest.json").write_text(json.dumps(manifest))
    return path


def test_loads_manifest_execution_profiles(tmp_path):
    path = _write_manifest_dataset(
        tmp_path,
        [module_case()],
        {"legacy": {"allowed_tools": ["query_information"]}},
    )

    dataset = load_dataset(path)

    assert dataset.execution_profiles_source == "manifest"
    assert dataset.execution_profiles["legacy"].allowed_tools == ["query_information"]


def test_legacy_module_subset_synthesizes_empty_profiles(tmp_path):
    path = _write_manifest_dataset(tmp_path, [module_case(), link_case()])

    dataset = load_dataset(
        path,
        DatasetFilters(scopes=["module"]),
    )

    assert dataset.execution_profiles_source == "legacy_module"
    assert dataset.execution_profiles["legacy"].allowed_tools == []


def test_legacy_link_or_e2e_requires_execution_profiles(tmp_path):
    path = _write_manifest_dataset(tmp_path, [module_case(), link_case()])

    with pytest.raises(EvaluationPreflightError) as error:
        load_dataset(path, DatasetFilters(scopes=["link"]))

    assert error.value.code == "EXECUTION_PROFILE_REQUIRED"
    assert error.value.evidence_refs == [str(path.with_suffix(".manifest.json"))]


@pytest.mark.parametrize(
    "execution_profiles",
    [
        {},
        {"": {"allowed_tools": []}},
        {"legacy": {"allowed_tools": ["query_information", "query_information"]}},
        {"legacy": {"allowed_tools": "query_information"}},
    ],
)
def test_invalid_execution_profile_shape_has_stable_error_code(
    tmp_path, execution_profiles
):
    path = _write_manifest_dataset(
        tmp_path,
        [module_case()],
        execution_profiles,
    )

    with pytest.raises(EvaluationPreflightError) as error:
        load_dataset(path)

    assert error.value.code == "EXECUTION_PROFILE_INVALID"


def test_load_validate_hash_order_and_filters(dataset_path, cases, legacy_tool_catalog):
    dataset = load_dataset(dataset_path)
    assert [case.case_id for case in dataset.cases] == [
        case["case_id"] for case in cases
    ]
    assert dataset.sha256 == hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    assert validate_dataset(dataset, tools=legacy_tool_catalog).valid
    selected = load_dataset(
        dataset_path, DatasetFilters(scopes=["link"], labels=["offline"])
    )
    assert [case.case_id for case in selected.cases] == ["LINK-1"]


def test_loads_matching_generation_manifest_lifecycle(tmp_path):
    path = tmp_path / "draft.jsonl"
    path.write_text(json.dumps(module_case()) + "\n")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    (tmp_path / "generation_manifest.json").write_text(
        json.dumps(
            {
                "suite_id": "fixture-suite",
                "dataset_version": "1.2",
                "state": "VALIDATED",
                "draft_sha256": digest,
            }
        )
    )

    dataset = load_dataset(path)

    assert dataset.lifecycle_state == "VALIDATED"
    assert dataset.dataset_version == "1.2"
    assert dataset.suite_id == "fixture-suite"
    assert dataset.manifest_path == str(tmp_path / "generation_manifest.json")


def test_ignores_manifest_with_non_matching_dataset_hash(tmp_path):
    path = tmp_path / "draft.jsonl"
    path.write_text(json.dumps(module_case()) + "\n")
    (tmp_path / "generation_manifest.json").write_text(
        json.dumps(
            {
                "suite_id": "stale-suite",
                "dataset_version": "9.9",
                "state": "VALIDATED",
                "draft_sha256": "0" * 64,
            }
        )
    )

    dataset = load_dataset(path)

    assert dataset.lifecycle_state == "UNKNOWN"
    assert dataset.manifest_path is None


def test_invalid_json_reports_path_line_and_case(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text("\n{bad}\n")
    with pytest.raises(DatasetLoadError, match=r"bad.jsonl line=2 case_id=<unknown>"):
        load_dataset(path)


def test_protocol_error_and_extra_field_are_explicit(tmp_path):
    value = module_case()
    value["execution"]["secret_expected"] = "leak"
    path = tmp_path / "bad.jsonl"
    path.write_text(json.dumps(value))
    with pytest.raises(DatasetLoadError, match="execution/secret_expected"):
        load_dataset(path)
    with pytest.raises(ValidationError):
        ExecutionSpec.model_validate({**value["execution"], "user_input": 12})


@pytest.mark.parametrize(
    ("field", "value"),
    [("test_scope", "unknown"), ("case_id", "../escape")],
)
def test_invalid_enums_and_unsafe_case_ids_fail(field, value):
    case = module_case()
    case[field] = value
    with pytest.raises(ValidationError):
        EvalCase.model_validate(case)


def test_eval_case_accepts_exact_scenario_type_enum():
    for scenario_type in SCENARIO_TYPES:
        case = module_case(f"SCENARIO-{scenario_type}")
        case["scenario_type"] = scenario_type
        assert EvalCase.model_validate(case).scenario_type == scenario_type


@pytest.mark.parametrize("value", [None, "", "other", ["normal", "valid_boundary"]])
def test_eval_case_rejects_missing_empty_or_invalid_scenario_type(value):
    case = module_case()
    if value is None:
        case.pop("scenario_type")
    else:
        case["scenario_type"] = value
    with pytest.raises(ValidationError) as error:
        EvalCase.model_validate(case)
    assert error.value.errors(include_url=False)[0]["loc"] == ("scenario_type",)


def test_assertion_weight_and_duplicate_names_fail():
    case = module_case()
    case["oracle"]["evaluation"]["checks"][0]["weight"] = 0
    with pytest.raises(ValidationError):
        EvalCase.model_validate(case)
    case = module_case()
    case["oracle"]["evaluation"]["checks"].append(
        case["oracle"]["evaluation"]["checks"][0]
    )
    with pytest.raises(ValidationError, match="unique"):
        EvalCase.model_validate(case)


def test_duplicate_case_id_is_rejected(tmp_path):
    value = json.dumps(module_case())
    path = tmp_path / "duplicate.jsonl"
    path.write_text(f"{value}\n{value}\n")
    with pytest.raises(DatasetLoadError, match="duplicate case_id"):
        load_dataset(path)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda case: case["oracle"].update(expected_module_output=None),
            "module requires",
        ),
        (
            lambda case: case["execution"].update(allowed_tools=["bad_tool"]),
            "outside profile",
        ),
        (
            lambda case: case["oracle"]["evaluation"]["checks"].append(
                {"name": "tool_called", "weight": 1, "critical": False, "config": {}}
            ),
            "does not support module",
        ),
        (
            lambda case: case["execution"].update(
                fault_injection={"query_information": "commit_then_timeout"}
            ),
            "does not support fault mode",
        ),
    ],
)
def test_semantic_validation_rejects_invalid_cases(
    tmp_path, mutate, message, legacy_tool_catalog
):
    value = module_case()
    mutate(value)
    path = tmp_path / "invalid.jsonl"
    path.write_text(json.dumps(value))
    report = validate_dataset(load_dataset(path), tools=legacy_tool_catalog)
    assert not report.valid
    assert message in " ".join(issue.message for issue in report.issues)


def test_schema_is_generated_from_eval_case():
    committed = json.loads(
        (
            Path(__file__).resolve().parents[1] / "schemas/eval_case.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert committed == EvalCase.model_json_schema()
    assert "scenario_type" in committed["required"]
    assert set(committed["properties"]["scenario_type"]["enum"]) == SCENARIO_TYPES
    assert set(ASSERTION_SCOPES) >= {"intent_match", "final_state_match"}
