"""新分析绑定 manifest 原始字节；不重解释旧 dataset identity。"""

from pathlib import Path

from capability_snapshot_kit.hashing import sha256_json

from ..analysis_sources import read_json
from .io import file_sha256
from .loader import load_dataset


def build_dataset_binding(root: Path, *, contract_version: str | None = None) -> dict:
    path = Path(root).resolve()
    root = path if path.is_dir() else path.parent
    manifest, manifest_hash = read_json(root / "manifest.json")
    loaded = load_dataset(path)
    if contract_version is not None and loaded["contract_version"] != contract_version:
        raise ValueError("dataset contract differs from requested version")
    names = set(manifest.get("files", {}))
    names.add(path.name if path.is_file() else "tasks.jsonl")
    files = {}
    for name in sorted(names):
        candidate = (root / name).resolve()
        if (
            Path(name).is_absolute()
            or ".." in Path(name).parts
            or not candidate.is_relative_to(root)
        ):
            raise ValueError("dataset asset outside root")
        files[name] = file_sha256(candidate)
    if file_sha256(root / "manifest.json") != manifest_hash:
        raise ValueError("dataset manifest changed while loading")
    binding = {
        "binding_version": "dataset-binding-v1",
        "legacy_identity": loaded["legacy_identity"],
        "contract_version": loaded["contract_version"],
        "manifest_sha256": manifest_hash,
        "files": files,
    }
    return {"binding": binding, "dataset_sha256": sha256_json(binding)}
