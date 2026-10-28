"""Automatic, source-preserving intake for supported Agent candidate formats."""

from .intake import prepare_input
from .models import PreparedInput

__all__ = ["PreparedInput", "prepare_input"]
