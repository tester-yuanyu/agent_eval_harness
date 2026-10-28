"""Compatibility alias for the shared schema_base contract API."""

import sys

from eval_contracts import schema_base as _shared

sys.modules[__name__] = _shared
