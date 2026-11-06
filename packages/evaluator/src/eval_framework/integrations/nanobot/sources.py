"""宿主声明 worker 的标准库依赖闭包；Docker 与指纹共用此清单。"""

from pathlib import Path


def worker_source_paths() -> dict[str, Path]:
    root = Path(__file__).resolve().parents[2]
    paths = {
        name: root / "benchmark" / name
        for name in (
            "nanobot_runtime.py",
            "nanobot_worker.py",
            "module_worker.py",
            "decision_worker.py",
            "inspect_docker.py",
        )
    }
    paths["nanobot_sdk.py"] = Path(__file__).with_name("nanobot_sdk.py")
    paths["local_files.py"] = root / "environments/local_files.py"
    return paths


def integration_source_paths() -> dict[str, Path]:
    root = Path(__file__).resolve().parents[2]
    paths = [*worker_source_paths().values(), Path(__file__)]
    return {"eval_framework/" + p.relative_to(root).as_posix(): p for p in paths}
