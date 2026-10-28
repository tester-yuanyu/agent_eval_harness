"""Compatibility alias for the shared capabilities contract API."""

import sys

from eval_contracts import capabilities as _shared

sys.modules[__name__] = _shared
