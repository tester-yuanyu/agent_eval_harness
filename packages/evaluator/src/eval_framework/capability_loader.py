"""Compatibility alias for the shared capability_loader contract API."""

import sys

from eval_contracts import capability_loader as _shared

sys.modules[__name__] = _shared
