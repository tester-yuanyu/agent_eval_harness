"""Immutable publication index outside the unchanged v3 bundle layout."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path


class SuiteError(ValueError):
    """An actionable configuration or integrity failure."""


def component(value: str, *, version: bool = False) -> str:
    pattern = r"[0-9][A-Za-z0-9._+-]*" if version else r"[A-Za-z0-9][A-Za-z0-9._-]*"
    if not re.fullmatch(pattern, value) or ".." in value:
        raise SuiteError(
            f"invalid {'immutable version' if version else 'name'}: {value!r}"
        )
    return value


def inside(root: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or "\\" in relative:
        raise SuiteError(f"path escapes registry: {relative!r}")
    candidate = root / path
    # A symlink could redirect a later operation even if its current target is inside.
    for part in (candidate, *candidate.parents):
        if part == root:
            break
        if part.is_symlink():
            raise SuiteError(f"symlink is not allowed in registry path: {part}")
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise SuiteError(f"path escapes registry: {relative!r}")
    return candidate


def tree_hash(root: Path) -> str:
    files = {}
    if root.is_symlink() or not root.is_dir():
        raise SuiteError(f"bundle must be a real directory: {root}")
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise SuiteError(f"symlink not allowed in bundle: {path}")
        if path.is_file():
            files[path.relative_to(root).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
        elif not path.is_dir():
            raise SuiteError(f"unsupported filesystem entry: {path}")
    return hashlib.sha256(
        json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def read_index(path: Path, field: str) -> dict:
    if not path.exists():
        return {"schema_version": 1, field: {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(data, dict)
        or data.get("schema_version") != 1
        or not isinstance(data.get(field), dict)
    ):
        raise SuiteError(f"invalid registry index: {path}")
    return data


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".index-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def locked(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(path.suffix + ".lock")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise SuiteError(
            f"registry is locked: {lock}; retry after its writer finishes"
        ) from exc
    try:
        os.close(fd)
        yield
    finally:
        lock.unlink()


class BundleRegistry:
    def __init__(self, root: Path, validate: Callable[[Path], dict]):
        self.root = root.resolve()
        self.validate = validate
        self.index = inside(self.root, "data/bundle-index.json")

    def _relative(self, agent: str, version: str) -> str:
        return f"data/bundles/{component(agent)}/{component(version, version=True)}"

    def publish(self, source: Path, agent: str, version: str) -> dict:
        relative = self._relative(agent, version)
        destination = inside(self.root, relative)
        tree_hash(source)  # Reject symlinks before copytree follows any links.
        with locked(self.index):
            index = read_index(self.index, "bundles")
            versions = index["bundles"].setdefault(agent, {})
            if version in versions or destination.exists():
                raise SuiteError(f"version already published: {agent}@{version}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            stage = Path(tempfile.mkdtemp(prefix=".publish-", dir=destination.parent))
            moved = False
            try:
                shutil.copytree(source, stage, dirs_exist_ok=True, symlinks=True)
                digest = tree_hash(stage)
                result = self.validate(stage)
                document = json.loads((stage / "agent.json").read_text())
                if document.get("agent_id") != agent:
                    raise SuiteError(
                        "publication agent does not match agent.json agent_id"
                    )
                record = {
                    "path": relative,
                    "agent_id": agent,
                    "version": version,
                    "agent_version": document.get("agent_version"),
                    "capability_bundle_sha256": result["capability_bundle_sha256"],
                    "agent_snapshot_sha256": result["agent_snapshot_sha256"],
                    "files_sha256": digest,
                }
                stage.rename(destination)
                moved = True
                versions[version] = record
                atomic_json(self.index, index)
            except BaseException:
                if moved:
                    shutil.rmtree(destination)
                raise
            finally:
                if stage.exists():
                    shutil.rmtree(stage)
        return record

    def resolve(self, agent: str, version: str) -> dict:
        expected = self._relative(agent, version)
        index = read_index(self.index, "bundles")
        try:
            record = index["bundles"][agent][version]
        except KeyError as exc:
            raise SuiteError(f"unknown fixed publication: {agent}@{version}") from exc
        if (
            not isinstance(record, dict)
            or record.get("path") != expected
            or record.get("agent_id") != agent
            or record.get("version") != version
        ):
            raise SuiteError("registry identity/path mismatch")
        path = inside(self.root, record["path"])
        if tree_hash(path) != record.get("files_sha256"):
            raise SuiteError("published bundle was tampered with: file Hash mismatch")
        actual = self.validate(path)
        for key in ("capability_bundle_sha256", "agent_snapshot_sha256"):
            if record.get(key) != actual.get(key):
                raise SuiteError(f"published bundle was tampered with: {key} mismatch")
        document = json.loads((path / "agent.json").read_text())
        if document.get("agent_id") != agent or document.get(
            "agent_version"
        ) != record.get("agent_version"):
            raise SuiteError("published Agent identity mismatch")
        return {**record, "resolved_path": str(path)}

    def list(self) -> dict:
        # Listing is discovery only. Formal use must call resolve for validation.
        return read_index(self.index, "bundles")
