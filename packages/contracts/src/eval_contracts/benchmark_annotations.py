"""版本化能力注释；私有依据与公开分桶标签分离。"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, StrictInt, StrictStr, field_validator

from .schema_base import StrictModel

Capability = Literal[
    "single_tool",
    "multi_tool_selection",
    "tool_sequence",
    "parallel_calls",
    "irrelevance_rejection",
    "schema_robustness",
    "multi_turn_state",
    "error_recovery",
    "policy_compliance",
]
CAPABILITIES = (
    "single_tool",
    "multi_tool_selection",
    "tool_sequence",
    "parallel_calls",
    "irrelevance_rejection",
    "schema_robustness",
    "multi_turn_state",
    "error_recovery",
    "policy_compliance",
)


class StructuralFeatures(StrictModel):
    reference_tool_calls: StrictInt | None = Field(default=None, ge=0)
    dependency_depth: StrictInt | None = Field(default=None, ge=0)
    interaction_turns: StrictInt | None = Field(default=None, ge=0)
    recovery_branches: StrictInt | None = Field(default=None, ge=0)


class AnnotationRecord(StrictModel):
    dataset_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    case_id: StrictStr = Field(min_length=1)
    capabilities: list[Capability]
    difficulty: Literal["easy", "medium", "hard", "unknown"]
    structural_features: StructuralFeatures
    basis_refs: list[StrictStr]
    review_status: Literal["proposed", "reviewed"]

    @field_validator("capabilities")
    @classmethod
    def unique_capabilities(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("duplicate capability")
        return value


def structural_difficulty(features: dict) -> str:
    model = StructuralFeatures.model_validate(features)
    calls, depth, turns, branches = (
        model.reference_tool_calls,
        model.dependency_depth,
        model.interaction_turns,
        model.recovery_branches,
    )
    if None in (calls, depth, turns, branches):
        return "unknown"
    if calls >= 7 or depth >= 4 or turns >= 3 or branches >= 2:
        return "hard"
    if calls <= 2 and depth <= 1 and turns <= 1 and branches == 0:
        return "easy"
    return "medium"
