"""选择预算不得抹掉义务；实测与候选覆盖严格分开。"""

import json

import pytest
from dataset_builder.full_generation.models import GenerationResult


def generation():
    slots = [
        dict(
            slot_id=s,
            target_id="tool.demo",
            layer="tools",
            dimension=s,
            source_refs=[],
            support_status="supported",
            case_kind="parameter",
        )
        for s in ("a", "b", "blocked")
    ]
    cases = [
        dict(
            slot_id=s,
            dataset_format="capability_contract_case",
            payload={
                "case_id": s,
                "input": {"operation": "invoke_tool"},
                "oracle": {"secret": "must never enter selection"},
            },
            execution_readiness="blocked" if s == "blocked" else "needs_runner",
            coverage_mode="direct",
        )
        for s in ("a", "b", "blocked")
    ]
    return GenerationResult(
        inventory=dict(
            bundle_sha256="a" * 64,
            bundle_path="bundle",
            delivery_root="delivery",
            targets=[],
            artifacts={},
            external_bindings={},
            gaps=[],
        ),
        slots=slots,
        cases=cases,
        blockers=[],
    )


def test_budget_keeps_full_denominator_and_never_exports_oracle():
    from dataset_builder.selection import select_cases

    result = select_cases(generation(), mode="quick", max_cases=1)
    assert result["obligation_count"] == 3
    assert len(result["selected_case_ids"]) == 1
    assert result["candidate_pair_count"] > result["selected_pair_count"]
    assert len(result["unselected_obligation_ids"]) == 2
    assert result["measured_pair_count"] == 0
    assert "must never enter selection" not in json.dumps(result)
    assert result["cases"][0]["uses_model"] == "unknown"
    assert result["cases"][0]["public_fault"] == "unknown"
    assert "blocked" not in result["selected_case_ids"]


def test_constraints_and_model_budget_restrict_candidates_not_obligations():
    from dataset_builder.selection import select_cases

    result = select_cases(generation(), mode="full", forbidden=[{"dimension": "a"}])
    assert result["selected_case_ids"] == ["b"]
    assert result["obligation_count"] == 3
    assert select_cases(generation(), max_model_cases=0)["selected_case_ids"] == []
    with pytest.raises(ValueError, match="factor"):
        select_cases(generation(), forbidden=[{"typo": "a"}])


def test_top_up_uses_only_observed_pairs_and_does_not_rerun_valid_cases():
    from dataset_builder.selection import select_cases

    first = select_cases(generation(), max_cases=1)
    case_id = first["selected_case_ids"][0]
    evidence = {
        "source_sha256": first["source_sha256"],
        "observations": [
            {
                "case_id": case_id,
                "valid_result": True,
                "observed_factors": {},
                "covered_obligation_ids": [],
            }
        ],
    }
    topup = select_cases(generation(), evidence=evidence, max_cases=2)
    assert topup["measured_pair_count"] == 0
    assert case_id not in topup["selected_case_ids"]
    assert len(topup["unfillable_pair_gaps"]) > 0
    assert topup["measured_obligation_ids"] == []
    evidence["source_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="source"):
        select_cases(generation(), evidence=evidence)


def test_cli_writes_exclusive_sidecar_and_preserves_input(tmp_path, capsys):
    from dataset_builder.cli import main

    source = tmp_path / "generation_result.json"
    source.write_text(generation().model_dump_json())
    before = source.read_bytes()
    output = tmp_path / "selection.json"
    args = [
        "select-cases",
        "--generation",
        str(source),
        "--output",
        str(output),
        "--mode",
        "quick",
        "--max-cases",
        "1",
    ]
    assert main(args) == 0
    assert json.loads(output.read_text())["obligation_count"] == 3
    assert source.read_bytes() == before
    assert main(args) == 1


def test_public_fault_uses_execution_input_without_oracle_inference():
    from dataset_builder.selection import select_cases

    plan = generation()
    plan.cases[0].payload["execution"] = {"fault_injection": {"kind": "timeout"}}
    result = select_cases(plan)
    assert result["cases"][0]["public_fault"] == {"kind": "timeout"}


def test_partial_observations_credit_only_explicit_pairs():
    from dataset_builder.selection import select_cases

    plan = generation()
    first = select_cases(plan)
    assert first["candidate_pair_count"] == 9
    evidence = {
        "source_sha256": first["source_sha256"],
        "observations": [
            {
                "case_id": "a",
                "valid_result": True,
                "observed_factors": {"target": "tool.demo", "layer": "tools"},
                "covered_obligation_ids": ["a"],
            }
        ],
    }
    result = select_cases(plan, evidence=evidence)
    assert result["measured_pair_count"] == 1
    assert result["selected_case_ids"] == ["b"]
    assert result["measured_obligation_ids"] == ["a"]
    assert len(result["planned_pair_gaps"]) == 3
    evidence["observations"][0]["observed_factors"]["target"] = "tool.other"
    with pytest.raises(ValueError, match="factors"):
        select_cases(plan, evidence=evidence)


def test_top_up_does_not_select_redundant_cases_after_observed_coverage_is_full():
    from dataset_builder.selection import select_cases

    plan = generation()
    plan.slots = plan.slots[:1]
    first_case = plan.cases[0]
    duplicate = first_case.model_copy(deep=True)
    duplicate.payload["case_id"] = "duplicate"
    plan.cases = [first_case, duplicate]
    first = select_cases(plan)
    evidence = {
        "source_sha256": first["source_sha256"],
        "observations": [
            {
                "case_id": "a",
                "valid_result": True,
                "observed_factors": first["cases"][0]["factors"],
                "covered_obligation_ids": ["a"],
            }
        ],
    }
    result = select_cases(plan, mode="full", evidence=evidence)
    assert result["measured_pair_count"] == 6
    assert result["selected_case_ids"] == []
