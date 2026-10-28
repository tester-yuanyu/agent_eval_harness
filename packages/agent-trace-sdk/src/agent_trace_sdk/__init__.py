"""Business evidence adapters for Inspect; compatible Agent-facing imports."""

from .collector import TraceCollector
from .native import InspectEvidenceSink
from .protocol import EventRule, TraceContext, status_for
from .reader import EvidenceReader

# Import compatibility only: there is no legacy production writer.
LocalEvidenceSink = InspectEvidenceSink

__all__ = [
    "EventRule",
    "EvidenceReader",
    "LocalEvidenceSink",
    "InspectEvidenceSink",
    "TraceContext",
    "status_for",
    "TraceCollector",
]
