"""Compatibility alias for the shared phase2_schemas contract API."""

import sys

from eval_contracts import phase2_schemas as _shared

sys.modules[__name__] = _shared
