"""Compatibility alias for the shared evidence_requirements contract API."""

import sys

from eval_contracts import evidence_requirements as _shared

sys.modules[__name__] = _shared
