"""只向已有严格合同 loader 分发，不转换冻结任务结构。"""

from pathlib import Path

from ..analysis_sources import read_json


def load_dataset(path: Path) -> dict:
    root = Path(path) if Path(path).is_dir() else Path(path).parent
    manifest, _ = read_json(root / "manifest.json")
    contract = manifest.get("task_contract", manifest.get("contract_version"))
    if contract == "provider-tasks-v1":
        from ..provider_tasks import load_provider_tasks, provider_dataset_identity

        tasks, identity = load_provider_tasks(root), provider_dataset_identity(root)
    elif contract == "nanobot-core-task-v1":
        from ..core_tasks import core_dataset_identity, load_core_tasks

        tasks, identity = load_core_tasks(root), core_dataset_identity(root)
    elif contract in {
        "file-tools-task-v1",
        "file-tools-task-v2",
        "model-decisions-task-v1",
    }:
        from ..tasks import dataset_identity, load_tasks

        tasks, identity = load_tasks(path), dataset_identity(path)
    else:
        raise ValueError("unsupported dataset contract")
    return {"tasks": tasks, "legacy_identity": identity, "contract_version": contract}
