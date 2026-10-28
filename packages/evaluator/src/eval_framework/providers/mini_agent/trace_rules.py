"""mini_agent-specific trace observations."""

from collections.abc import Sequence

from ...phase2_schemas import NormalizedTraceEvent, TraceIssue
from ...schemas import CaseResult


class MiniAgentConfirmationTraceRule:
    def analyze(
        self,
        timeline: Sequence[NormalizedTraceEvent],
        case: CaseResult,
    ) -> Sequence[TraceIssue]:
        del case
        types = [event.event_type for event in timeline]
        if "confirmation_accepted" in types and "confirmation_requested" not in types:
            event = next(
                item for item in timeline if item.event_type == "confirmation_accepted"
            )
            return [
                TraceIssue(
                    code="SUGGESTED_MINI_AGENT_CONFIRMATION_SEQUENCE",
                    message="Inspect mini_agent confirmation sequencing.",
                    evidence_refs=[event.evidence_ref],
                )
            ]
        return []
