"""nanobot 历史入口；SDK 实现与通用文件操作分别归 integration/Environment。

独立 worker 不安装 Evaluator：直接运行时加载标准库模块，Docker 使用同一
来源清单复制这些模块。包内调用保留旧签名和公开名称。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

if __package__:
    from ..environments.local_files import safe_path as safe_path
    from ..environments.local_files import snapshot_files as snapshot_files
    from ..integrations.nanobot.nanobot_sdk import (
        EXECUTION_KEYS as EXECUTION_KEYS,
    )
    from ..integrations.nanobot.nanobot_sdk import (
        FILE_TOOLS as FILE_TOOLS,
    )
    from ..integrations.nanobot.nanobot_sdk import (
        TOKENIZER_SHA256 as TOKENIZER_SHA256,
    )
    from ..integrations.nanobot.nanobot_sdk import (
        TOKENIZER_URL as TOKENIZER_URL,
    )
    from ..integrations.nanobot.nanobot_sdk import (
        execution_projection as execution_projection,
    )
    from ..integrations.nanobot.nanobot_sdk import (
        prepare_tokenizer as prepare_tokenizer,
    )
    from ..integrations.nanobot.nanobot_sdk import (
        runtime_identity as runtime_identity,
    )
    from ..integrations.nanobot.nanobot_sdk import (
        utc_now as utc_now,
    )
else:
    # 源码树下的独立解释器与扁平 Docker bundle 使用同一组标准库模块。
    framework = Path(__file__).resolve().parent.parent
    for directory in (framework / "environments", framework / "integrations/nanobot"):
        if directory.is_dir():
            sys.path.insert(0, str(directory))
    from local_files import safe_path as safe_path
    from local_files import snapshot_files as snapshot_files
    from nanobot_sdk import (
        EXECUTION_KEYS as EXECUTION_KEYS,
    )
    from nanobot_sdk import (
        FILE_TOOLS as FILE_TOOLS,
    )
    from nanobot_sdk import (
        TOKENIZER_SHA256 as TOKENIZER_SHA256,
    )
    from nanobot_sdk import (
        TOKENIZER_URL as TOKENIZER_URL,
    )
    from nanobot_sdk import (
        execution_projection as execution_projection,
    )
    from nanobot_sdk import (
        prepare_tokenizer as prepare_tokenizer,
    )
    from nanobot_sdk import (
        runtime_identity as runtime_identity,
    )
    from nanobot_sdk import (
        utc_now as utc_now,
    )


async def execute_task(
    task: dict[str, Any], *, config: dict[str, Any], workspace: Path | None = None
) -> dict[str, Any]:
    """Execute through Inspect; standalone callers retain their workspace API."""
    from .inspect_runtime import execute_boundary

    return await execute_boundary(
        execution_projection(task),
        config=config,
        workspace=workspace,
        mode="agent",
        identity=runtime_identity(config),
    )
