"""历史导入门面；与迁移后的实现共享模块对象及 patch 边界。"""

import sys

from .scorers import agentic_metrics as _implementation

sys.modules[__name__] = _implementation
