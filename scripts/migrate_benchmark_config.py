"""使用 Evaluator 环境，离线拆分旧 benchmark 配置；不执行模型或 Agent。"""

from eval_framework.orchestration.config import migration_main

if __name__ == "__main__":
    raise SystemExit(migration_main())
