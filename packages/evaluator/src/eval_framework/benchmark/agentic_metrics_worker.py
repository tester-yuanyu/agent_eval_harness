"""旧 -m worker 入口；禁用上传的初始化仍在真实实现导入前执行。"""

import sys

from .scorers import agentic_metrics_worker as _implementation

if __name__ == "__main__":
    raise SystemExit(_implementation.main())

sys.modules[__name__] = _implementation
