"""Compatibility alias for the shared dataset_validator contract API."""

import sys

from eval_contracts import dataset_validator as _shared

sys.modules[__name__] = _shared
