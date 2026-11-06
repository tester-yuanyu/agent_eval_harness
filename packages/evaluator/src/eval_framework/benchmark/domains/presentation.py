"""从领域公开投影构造 Inspect 输入；暂留包内，避免提前冻结共享协议。"""

from __future__ import annotations

import hashlib
import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class SampleSpec:
    input: str
    files: dict[str, str]


class DomainPresentation(Protocol):
    task_name: str

    def prepare_sample(self, public_task: dict) -> SampleSpec: ...

    def identity(self) -> dict: ...

    def fingerprint_sources(self) -> list[Path]: ...


def presentation_identity(presentation: DomainPresentation) -> dict:
    implementation = inspect.getsourcefile(type(presentation))
    if implementation is None:
        raise ValueError("presentation requires inspectable implementation")
    paths = list(
        dict.fromkeys([Path(implementation), *presentation.fingerprint_sources()])
    )
    return {
        "task_name": presentation.task_name,
        "configuration": presentation.identity(),
        "sources": {
            f"{i}:{path.name}": hashlib.sha256(path.read_bytes()).hexdigest()
            for i, path in enumerate(paths)
        },
    }


@dataclass(frozen=True)
class FileToolsPresentation:
    task_name: str = "file_tool_benchmark"

    def prepare_sample(self, public_task: dict) -> SampleSpec:
        from ..inspect_runtime import sample_files

        return SampleSpec(public_task["prompt"], sample_files(public_task["fixtures"]))

    def identity(self) -> dict:
        return {"kind": "file-tools-v1"}

    def fingerprint_sources(self) -> list[Path]:
        return [Path(__file__), Path(__file__).parents[1] / "inspect_runtime.py"]


@dataclass(frozen=True)
class ProviderPresentation:
    task_name: str = "provider_benchmark"

    def prepare_sample(self, public_task: dict) -> SampleSpec:
        return SampleSpec(public_task["execution"]["user_input"], {})

    def identity(self) -> dict:
        return {"kind": "provider-v1"}

    def fingerprint_sources(self) -> list[Path]:
        return [Path(__file__)]
