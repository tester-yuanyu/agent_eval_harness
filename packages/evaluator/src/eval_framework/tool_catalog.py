"""Compatibility alias for the shared tool_catalog contract API."""

import sys

from eval_contracts import tool_catalog as _shared

sys.modules[__name__] = _shared
