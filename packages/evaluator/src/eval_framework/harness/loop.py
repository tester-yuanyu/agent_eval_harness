"""历史原生 worker bridge 入口；保持旧导入及 patch 的同一模块对象。"""

import sys

from ..integrations.nanobot import inspect_bridge as _implementation

sys.modules[__name__] = _implementation
