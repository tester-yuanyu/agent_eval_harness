"""Compatibility alias for the shared errors contract API."""

import sys

from eval_contracts import errors as _shared

sys.modules[__name__] = _shared
