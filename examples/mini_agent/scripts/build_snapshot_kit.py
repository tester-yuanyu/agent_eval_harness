"""Build the standalone distribution from the single canonical Kit source tree.

Only build requirements may be downloaded by pip; no publication is performed.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

METADATA = """[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "capability-snapshot-kit"
version = "0.1.0"
description = "用于评测的 Agent 能力快照，支持可插拔接入并保留源码依据"
readme = "README.md"
requires-python = ">=3.11"
dependencies = ["pydantic>=2.6,<3", "PyYAML>=6.0,<7"]

[project.scripts]
capability-snapshot = "capability_snapshot_kit.ingestion.cli:main"

[tool.setuptools.packages.find]
where = ["src"]
include = ["capability_snapshot_kit*"]
namespaces = false

[tool.setuptools.package-data]
capability_snapshot_kit = ["resources/**/*.md"]
"""


def stage_project(repository: Path, destination: Path) -> None:
    # The public namespace now belongs to the shared contracts distribution.
    source = repository.parents[1] / "packages/contracts/src/capability_snapshot_kit"
    shutil.copytree(
        source,
        destination / "src/capability_snapshot_kit",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    (destination / "pyproject.toml").write_text(METADATA, encoding="utf-8")
    (destination / "README.md").write_text(
        "# Capability Snapshot Kit\n\n"
        "独立的 Snapshot 3.0 编译器，支持可插拔的事实接入。\n\n"
        "运行 `capability-snapshot --help` 或 "
        "`python -m capability_snapshot_kit --help`.\n"
        "包含提取说明和不使用工具的对话配置。\n"
        "安装时不引入 Agent 运行时或模型 Provider。"
        "插件由使用者显式选择，必须是可信的本地 Python 工厂。\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="snapshot-kit-build-") as temp:
        project = Path(temp)
        stage_project(Path(__file__).resolve().parents[1], project)
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                "--no-deps",
                "--wheel-dir",
                str(output),
                str(project),
            ],
            check=True,
        )


if __name__ == "__main__":
    main()
