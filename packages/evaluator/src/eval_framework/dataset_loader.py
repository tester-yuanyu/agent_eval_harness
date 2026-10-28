"""Compatibility alias for the shared dataset_loader contract API."""

import sys

from eval_contracts import dataset_loader as _shared

sys.modules[__name__] = _shared
