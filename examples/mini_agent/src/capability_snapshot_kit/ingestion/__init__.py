"""Opt-in, source-backed inputs for the unchanged Snapshot 3.0 compiler."""

from .models import FactDocument, SourceReference
from .providers import AdapterCollector, FactCollector, FactExtractor

__all__ = [
    "AdapterCollector",
    "FactCollector",
    "FactDocument",
    "FactExtractor",
    "SourceReference",
]
