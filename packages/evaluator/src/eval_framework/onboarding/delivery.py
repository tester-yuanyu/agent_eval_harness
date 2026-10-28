"""Bounded, non-executable delivery snapshots and complete source validation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import unicodedata
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from ..capability_loader import load_capability_bundle
from .models import CandidateCase, CandidateManifest, SourceReference

MAX_FILES = 10_000
MAX_BYTES = 512 * 1024 * 1024
MAX_FILE_BYTES = 32 * 1024 * 1024
_COPY_CHUNK_BYTES = 64 * 1024


@dataclass(frozen=True)
class _DirectoryEntry:
    path: str
    is_dir: bool
    device: int
    inode: int
    mode: int
    size: int
    modified_ns: int


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative_path(value: str) -> Path:
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or re.match(r"^[A-Za-z]:", value)
    ):
        raise ValueError(f"unsafe delivery path: {value!r}")
    return Path(*path.parts)


def _bounded(sizes: list[int]) -> None:
    if len(sizes) > MAX_FILES or sum(sizes) > MAX_BYTES:
        raise ValueError("delivery exceeds file count or total size limit")
    if any(size > MAX_FILE_BYTES for size in sizes):
        raise ValueError("delivery exceeds per-file size limit")


def _portable_path(value: str) -> str:
    return "/".join(
        unicodedata.normalize("NFC", part.casefold()) for part in value.split("/")
    )


def _validate_inventory(entries: list[tuple[str, bool]], *, label: str) -> None:
    """Reject paths that change meaning across common filesystems."""

    paths: dict[str, tuple[str, bool]] = {}
    directories: dict[str, str] = {}
    for name, is_dir in entries:
        relative_path(name)
        normalized = _portable_path(name)
        previous = paths.get(normalized)
        if previous is not None:
            if previous[0] == name:
                raise ValueError(f"duplicate {label} path: {name}")
            raise ValueError(
                f"{label} paths collide after case/Unicode normalization: "
                f"{previous[0]!r} and {name!r}"
            )
        paths[normalized] = (name, is_dir)

        parts = name.split("/")
        directory_depth = len(parts) if is_dir else len(parts) - 1
        for index in range(1, directory_depth + 1):
            raw_parent = "/".join(parts[:index])
            normalized_parent = _portable_path(raw_parent)
            previous_parent = directories.get(normalized_parent)
            if previous_parent is not None and previous_parent != raw_parent:
                raise ValueError(
                    f"{label} paths collide after case/Unicode normalization: "
                    f"{previous_parent!r} and {raw_parent!r}"
                )
            directories[normalized_parent] = raw_parent

    files = {path for path, (_, is_dir) in paths.items() if not is_dir}
    for path, (name, _) in paths.items():
        parts = path.split("/")
        for index in range(1, len(parts)):
            if "/".join(parts[:index]) in files:
                raise ValueError(f"{label} file/directory path conflict: {name}")


def _same_entry(entry: _DirectoryEntry, current: os.stat_result) -> bool:
    return (
        entry.device,
        entry.inode,
        entry.mode,
        entry.size,
        entry.modified_ns,
    ) == (
        current.st_dev,
        current.st_ino,
        current.st_mode,
        current.st_size,
        current.st_mtime_ns,
    )


def _scan_directory(root_fd: int) -> list[_DirectoryEntry]:
    found: list[_DirectoryEntry] = []

    def visit(directory_fd: int, prefix: tuple[str, ...]) -> None:
        with os.scandir(directory_fd) as iterator:
            scanned = sorted(iterator, key=lambda item: item.name)
        for item in scanned:
            path = "/".join((*prefix, item.name))
            relative_path(path)
            current = item.stat(follow_symlinks=False)
            if stat.S_ISLNK(current.st_mode):
                raise ValueError(f"delivery symlink is not allowed: {path}")
            is_dir = stat.S_ISDIR(current.st_mode)
            if not is_dir and not stat.S_ISREG(current.st_mode):
                raise ValueError(f"delivery contains a non-regular file: {path}")
            entry = _DirectoryEntry(
                path=path,
                is_dir=is_dir,
                device=current.st_dev,
                inode=current.st_ino,
                mode=current.st_mode,
                size=current.st_size,
                modified_ns=current.st_mtime_ns,
            )
            found.append(entry)
            if is_dir:
                flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                try:
                    child_fd = os.open(item.name, flags, dir_fd=directory_fd)
                except OSError as exc:
                    raise ValueError(
                        f"delivery directory changed during snapshot: {path}"
                    ) from exc
                try:
                    if not _same_entry(entry, os.fstat(child_fd)):
                        raise ValueError(
                            f"delivery directory changed during snapshot: {path}"
                        )
                    visit(child_fd, (*prefix, item.name))
                finally:
                    os.close(child_fd)

    visit(root_fd, ())
    return found


def _open_directory(
    root_fd: int, path: str, expected: dict[str, _DirectoryEntry]
) -> int:
    directory_fd = os.dup(root_fd)
    traversed: list[str] = []
    try:
        for part in path.split("/") if path else ():
            traversed.append(part)
            logical = "/".join(traversed)
            next_fd = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=directory_fd,
            )
            os.close(directory_fd)
            directory_fd = next_fd
            if not _same_entry(expected[logical], os.fstat(directory_fd)):
                raise ValueError(
                    f"delivery directory changed during snapshot: {logical}"
                )
        return directory_fd
    except Exception:
        os.close(directory_fd)
        raise


def _copy_directory(source: Path, destination: Path) -> None:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        root_fd = os.open(source, flags)
    except OSError as exc:
        raise ValueError("delivery directory changed or became a symlink") from exc
    try:
        try:
            entries = _scan_directory(root_fd)
        except OSError as exc:
            raise ValueError("delivery inventory changed during snapshot") from exc
        _validate_inventory(
            [(entry.path, entry.is_dir) for entry in entries], label="delivery"
        )
        files = [entry for entry in entries if not entry.is_dir]
        _bounded([entry.size for entry in files])
        expected_directories = {entry.path: entry for entry in entries if entry.is_dir}

        destination.mkdir(parents=True)
        for entry in sorted(
            expected_directories.values(), key=lambda item: item.path.count("/")
        ):
            (destination / relative_path(entry.path)).mkdir()

        copied_total = 0
        for entry in files:
            logical = PurePosixPath(entry.path)
            parent = "" if str(logical.parent) == "." else str(logical.parent)
            try:
                parent_fd = _open_directory(root_fd, parent, expected_directories)
                try:
                    source_fd = os.open(
                        logical.name,
                        os.O_RDONLY | os.O_NOFOLLOW,
                        dir_fd=parent_fd,
                    )
                finally:
                    os.close(parent_fd)
            except (KeyError, OSError) as exc:
                raise ValueError(
                    f"delivery file changed or became a symlink: {entry.path}"
                ) from exc
            try:
                if not _same_entry(entry, os.fstat(source_fd)):
                    raise ValueError(
                        f"delivery file changed during snapshot: {entry.path}"
                    )
                copied = 0
                target = destination / relative_path(entry.path)
                with target.open("xb") as writer:
                    while chunk := os.read(source_fd, _COPY_CHUNK_BYTES):
                        copied += len(chunk)
                        copied_total += len(chunk)
                        if (
                            copied > entry.size
                            or copied > MAX_FILE_BYTES
                            or copied_total > MAX_BYTES
                        ):
                            raise ValueError("delivery changed or exceeds size limit")
                        writer.write(chunk)
                if copied != entry.size or not _same_entry(entry, os.fstat(source_fd)):
                    raise ValueError(
                        f"delivery file changed during snapshot: {entry.path}"
                    )
            finally:
                os.close(source_fd)
    finally:
        os.close(root_fd)


def _copy_zip(source: Path, destination: Path) -> None:
    with zipfile.ZipFile(source) as archive:
        entries = archive.infolist()
        inventory: list[tuple[str, bool]] = []
        for entry in entries:
            name = entry.filename.rstrip("/") if entry.is_dir() else entry.filename
            inventory.append((name, entry.is_dir()))
            mode = entry.external_attr >> 16
            if stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}:
                raise ValueError(f"ZIP symlink or special path is not allowed: {name}")
            if entry.flag_bits & 1:
                raise ValueError("encrypted ZIP delivery is unsupported")
        _validate_inventory(inventory, label="ZIP")
        _bounded([entry.file_size for entry in entries if not entry.is_dir()])

        destination.mkdir(parents=True)
        for name, is_dir in sorted(
            inventory, key=lambda item: (item[0].count("/"), not item[1])
        ):
            if is_dir:
                (destination / relative_path(name)).mkdir(parents=True, exist_ok=True)
        copied_total = 0
        for entry in entries:
            if entry.is_dir():
                continue
            target = destination / relative_path(entry.filename)
            target.parent.mkdir(parents=True, exist_ok=True)
            copied = 0
            with archive.open(entry) as reader, target.open("xb") as writer:
                while chunk := reader.read(_COPY_CHUNK_BYTES):
                    copied += len(chunk)
                    copied_total += len(chunk)
                    if (
                        copied > entry.file_size
                        or copied > MAX_FILE_BYTES
                        or copied_total > MAX_BYTES
                    ):
                        raise ValueError("ZIP changed or exceeds size limit")
                    writer.write(chunk)
            if copied != entry.file_size:
                raise ValueError(f"ZIP size mismatch: {entry.filename}")


def snapshot(source: Path, destination: Path) -> Path:
    """Validate the complete file inventory before copying any content."""
    if source.is_symlink():
        raise ValueError("delivery symlink is not allowed")
    source = source.resolve(strict=True)
    if destination.resolve().is_relative_to(source):
        raise ValueError("output path cannot be inside the source delivery")
    try:
        if source.is_dir():
            _copy_directory(source, destination)
        elif zipfile.is_zipfile(source):
            _copy_zip(source, destination)
        else:
            raise ValueError("candidate input must be a directory or ZIP delivery")
    except Exception:
        if destination.exists():
            shutil.rmtree(destination, ignore_errors=True)
        raise
    if (destination / "manifest.json").is_file():
        return destination
    children = list(destination.iterdir())
    if len(children) == 1 and children[0].is_dir():
        if (children[0] / "manifest.json").is_file():
            return children[0]
    raise ValueError("candidate delivery requires one unambiguous manifest.json root")


def pointer_value(document: Any, pointer: str) -> Any:
    if pointer == "":
        return document
    if not pointer.startswith("/") or re.search(r"~(?![01])", pointer):
        raise ValueError(f"invalid source pointer: {pointer}")
    try:
        for part in pointer[1:].split("/"):
            token = part.replace("~1", "/").replace("~0", "~")
            if isinstance(document, dict):
                document = document[token]
            elif isinstance(document, list) and re.fullmatch(r"0|[1-9][0-9]*", token):
                document = document[int(token)]
            else:
                raise KeyError(token)
    except (KeyError, IndexError) as exc:
        raise ValueError(f"unresolved source pointer: {pointer}") from exc
    return document


def resolve_reference(
    root: Path, manifest: CandidateManifest, ref: SourceReference
) -> Any:
    logical = "source_delivery/" + relative_path(ref.path).as_posix()
    if manifest.files_sha256.get(logical) != ref.sha256:
        raise ValueError(f"source reference hash is not bound by manifest: {ref.path}")
    content = (root / logical).read_text(encoding="utf-8")
    if ref.anchor is not None and ref.anchor not in content:
        raise ValueError(f"unresolved source anchor in {ref.path}")
    if ref.pointer is not None:
        return pointer_value(json.loads(content), ref.pointer)
    if ref.anchor is None:
        raise ValueError(f"source reference requires pointer or anchor: {ref.path}")
    return None


def capability_agent_path(root: Path, manifest: CandidateManifest) -> str:
    """Use the bound delivery declaration, or one unambiguous legacy bundle."""
    declaration = "source_delivery/manifest.json"
    if declaration in manifest.files_sha256:
        source = root / declaration
        if sha256(source) != manifest.files_sha256[declaration]:
            raise ValueError("source delivery manifest hash mismatch")
        metadata = json.loads(source.read_bytes())
        if not isinstance(metadata, dict):
            raise ValueError("source delivery manifest must contain an object")
        if "bundle_path" in metadata:
            bundle_path = metadata["bundle_path"]
            if not isinstance(bundle_path, str):
                raise ValueError("unsafe bundle path: expected a relative path")
            relative = relative_path(bundle_path).as_posix()
            logical = f"source_delivery/{relative}/agent.json"
            if logical not in manifest.files_sha256:
                raise ValueError("declared capability agent is not bound by manifest")
            return logical
    candidates = [
        path
        for path in manifest.files_sha256
        if path.startswith("source_delivery/") and path.endswith("/bundle/agent.json")
    ]
    if len(candidates) != 1:
        raise ValueError("missing or ambiguous manifest-bound capability bundle")
    return relative_path(candidates[0]).as_posix()


def read_delivery(root: Path) -> tuple[CandidateManifest, list[CandidateCase]]:
    manifest = CandidateManifest.model_validate_json(
        (root / "manifest.json").read_bytes()
    )
    actual_files = {
        p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()
    }
    if actual_files != set(manifest.files_sha256) | {"manifest.json"}:
        raise ValueError("manifest file inventory does not match delivery")
    for name, expected in manifest.files_sha256.items():
        file = root / relative_path(name)
        if re.fullmatch(r"[0-9a-f]{64}", expected) is None or sha256(file) != expected:
            raise ValueError(f"delivery file hash mismatch: {name}")
    dataset_paths = [item.path for item in manifest.datasets]
    if len(dataset_paths) != len(set(dataset_paths)):
        raise ValueError("duplicate dataset path")
    jsonls = {
        name
        for name in actual_files
        if name.startswith("datasets/") and name.endswith(".jsonl")
    }
    if jsonls != set(dataset_paths):
        raise ValueError("manifest dataset inventory does not match delivery")
    records: list[CandidateCase] = []
    seen: set[str] = set()
    for dataset in manifest.datasets:
        if manifest.files_sha256.get(dataset.path) != dataset.sha256:
            raise ValueError(f"dataset hash mismatch: {dataset.path}")
        rows = [
            CandidateCase.model_validate_json(line)
            for line in (root / relative_path(dataset.path)).read_text().splitlines()
            if line.strip()
        ]
        if len(rows) != dataset.case_count:
            raise ValueError(f"dataset case count mismatch: {dataset.path}")
        for row in rows:
            if (
                row.agent_id != manifest.agent_id
                or row.dataset_format != manifest.dataset_format
            ):
                raise ValueError(f"candidate identity mismatch: {row.case_id}")
            if any(
                getattr(row, key) != getattr(dataset, key)
                for key in ("kind", "layer", "target_id", "dataset_format")
            ):
                raise ValueError(f"dataset grouping mismatch: {row.case_id}")
            if row.case_id in seen:
                raise ValueError(f"duplicate candidate case ID: {row.case_id}")
            seen.add(row.case_id)
            for ref in row.source_refs:
                resolve_reference(root, manifest, ref)
            # Embedded schema/snapshot references are dependencies too.
            for key in ("schema_ref", "source_ref"):
                if key in row.input:
                    resolve_reference(
                        root, manifest, SourceReference.model_validate(row.input[key])
                    )
        records.extend(rows)
    if (
        len(records) != manifest.case_count
        or dict(Counter(r.kind for r in records)) != manifest.counts_by_kind
    ):
        raise ValueError("manifest case count mismatch")
    bundle = load_capability_bundle(
        (root / capability_agent_path(root, manifest)).parent,
        expected_sha256=manifest.bundle_sha256,
    )
    if bundle.provider_id != manifest.agent_id:
        raise ValueError("capability and delivery agent identity mismatch")
    return manifest, records
