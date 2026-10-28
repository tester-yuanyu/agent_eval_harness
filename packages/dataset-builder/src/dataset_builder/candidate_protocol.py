"""Dynamic candidate protocols built from strict suite configuration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, create_model

from .suite_config import CandidateProtocolConfig, SuiteConfig


class StrictCandidateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class CandidateProtocol:
    candidate_type: type[BaseModel]
    batch_type: type[BaseModel]


def _literal(values: list[str]):
    return Literal.__getitem__(tuple(values))


def _model_prefix(suite_id: str) -> str:
    return "".join(part.capitalize() for part in suite_id.split("_"))


def build_candidate_protocol(
    config: SuiteConfig,
    candidate: CandidateProtocolConfig,
) -> CandidateProtocol:
    prefix = _model_prefix(config.metadata.suite_id)
    fields = {
        "slot_id": (str, Field(min_length=1)),
        "user_input": (str, Field(min_length=1)),
        "expected_intent": (_literal(candidate.allowed_intents), ...),
        "expected_status": (_literal(candidate.allowed_statuses), ...),
        "expected_next_action": (
            _literal(candidate.allowed_next_actions),
            ...,
        ),
        "expected_parameters_json": (str, ...),
        "missing_parameters": (list[str], ...),
        "scenario_type": (_literal(candidate.allowed_scenario_types), ...),
        "difficulty": (_literal(candidate.allowed_difficulties), ...),
        "coverage_tags": (list[str], ...),
    }
    if candidate.rule_refs_required:
        fields["rule_refs"] = (list[str], Field(min_length=1))
    candidate_type = create_model(
        f"{prefix}Candidate",
        __base__=StrictCandidateModel,
        **fields,
    )
    batch_type = create_model(
        f"Generated{prefix}Batch",
        __base__=StrictCandidateModel,
        candidates=(list[candidate_type], ...),
    )
    return CandidateProtocol(candidate_type=candidate_type, batch_type=batch_type)
