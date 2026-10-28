"""Compatibility alias for the shared schemas contract API."""

import sys

from eval_contracts import schemas as _shared

sys.modules[__name__] = _shared
