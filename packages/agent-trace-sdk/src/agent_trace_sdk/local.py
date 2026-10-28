"""Legacy import compatibility; no custom collector or storage implementation."""

from .native import InspectEvidenceSink as LocalEvidenceSink
from .reader import EvidenceReader

__all__ = ["LocalEvidenceSink", "EvidenceReader"]
