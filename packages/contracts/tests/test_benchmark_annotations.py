import pytest


@pytest.mark.parametrize(
    "feature,value,want",
    [
        ("reference_tool_calls", 2, "easy"),
        ("reference_tool_calls", 3, "medium"),
        ("reference_tool_calls", 7, "hard"),
        ("dependency_depth", 1, "easy"),
        ("dependency_depth", 4, "hard"),
        ("interaction_turns", 1, "easy"),
        ("interaction_turns", 3, "hard"),
        ("recovery_branches", 0, "easy"),
        ("recovery_branches", 2, "hard"),
        ("dependency_depth", None, "unknown"),
    ],
)
def test_structural_difficulty_boundary(feature, value, want):
    from eval_contracts.benchmark_annotations import structural_difficulty

    features = {
        "reference_tool_calls": 2,
        "dependency_depth": 1,
        "interaction_turns": 1,
        "recovery_branches": 0,
    }
    features[feature] = value
    assert structural_difficulty(features) == want


def test_annotation_contract_rejects_unknown_capability_and_bool_feature():
    from eval_contracts.benchmark_annotations import AnnotationRecord

    base = {
        "case_id": "a",
        "dataset_sha256": "a" * 64,
        "capabilities": ["invented"],
        "difficulty": "unknown",
        "structural_features": {},
        "basis_refs": [],
        "review_status": "proposed",
    }
    with pytest.raises(ValueError):
        AnnotationRecord.model_validate(base)
    base.update(
        capabilities=["single_tool"], structural_features={"reference_tool_calls": True}
    )
    with pytest.raises(ValueError):
        AnnotationRecord.model_validate(base)
