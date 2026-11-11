"""Agent 无关的不可变交付发布：manifest 为最后的完成标记。"""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def publish_delivery(staging: Path, output: Path) -> None:
    if not (staging / "manifest.json").is_file():
        raise ValueError("staged delivery must contain manifest.json")
    # Exclusive reservation is outside the cleanup block: an existing artifact
    # or another writer's directory must never be removed on failure.
    output.mkdir(parents=True, exist_ok=False)
    try:
        for path in sorted(
            staging.iterdir(),
            key=lambda item: (item.name == "manifest.json", item.name),
        ):
            os.replace(path, output / path.name)
    except BaseException:
        shutil.rmtree(output)
        raise
