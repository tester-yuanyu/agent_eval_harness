"""只处理本地原始字节；合同验证和 manifest 身份由各领域维护。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_jsonl_bytes(raw: bytes) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()
    ]
