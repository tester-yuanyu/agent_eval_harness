"""Archive the measured nanobot runtime source locally, without Git or credentials.

Use the evaluator Python so the immutable run's runtime identity implementation is
available. No Agent source is changed and no network or publication occurs.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Any

RUNTIME_SUFFIXES = {".py", ".md", ".json", ".toml", ".lock", ".yaml", ".yml", ".j2"}
SECRET_PATTERNS = (
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{24,}"),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
    re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----"),
    re.compile(
        r"(?i)(?:api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|password)"
        r"[\"']?\s*[:=]\s*[\"']([^\"'\n]{16,})[\"']"
    ),
)


def selected_runtime_files(root: Path) -> list[tuple[bytes, str, bytes]]:
    """Match runtime_identity's Git-visible paths, then reject unsafe selections."""
    names = subprocess.check_output(
        [
            "git",
            "-C",
            str(root),
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ]
    ).split(b"\0")
    selected = []
    for raw in sorted(set(names)):
        if not raw:
            continue
        name = os.fsdecode(raw)
        path = root / name
        if not path.is_file() or path.is_symlink():
            continue
        if not (name.startswith("nanobot/") or name in {"pyproject.toml", "uv.lock"}):
            continue
        if path.suffix not in RUNTIME_SUFFIXES:
            continue
        parts = Path(name).parts
        if Path(name).is_absolute() or ".." in parts:
            raise ValueError("Unsafe source path")
        if any(part == ".git" or part.startswith(".env") for part in parts):
            continue
        if any(
            (root.joinpath(*parts[:i])).is_symlink() for i in range(1, len(parts) + 1)
        ):
            continue
        selected.append((raw, name, path.read_bytes()))
    if not selected:
        raise ValueError("No eligible nanobot runtime files")
    return selected


def source_digest(files: list[tuple[bytes, str, bytes]]) -> str:
    digest = hashlib.sha256()
    for raw, _name, data in files:
        digest.update(raw + b"\0" + data + b"\0")
    return digest.hexdigest()


def potential_secret_files(files: list[tuple[bytes, str, bytes]]) -> list[str]:
    """Return names only; matched values never enter logs or manifests."""
    findings = []
    for _raw, name, data in files:
        content = data.decode("utf-8", errors="replace")
        for pattern in SECRET_PATTERNS:
            candidates = list(pattern.finditer(content))
            real = []
            for candidate in candidates:
                literal = (
                    candidate.group(1) if candidate.lastindex else candidate.group()
                )
                lowered = literal.lower()
                # Public examples and environment-variable references are not keys.
                if any(
                    marker in lowered
                    for marker in (
                        "your-",
                        "your_",
                        "example",
                        "placeholder",
                        "dummy",
                        "${",
                    )
                ):
                    continue
                real.append(candidate)
            if real:
                findings.append(name)
                break
    return sorted(findings)


def _archive_bytes(files: list[tuple[bytes, str, bytes]], manifest: dict) -> bytes:
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode="wb", filename="", mtime=0) as compressed:
        with tarfile.open(
            fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT
        ) as tar:
            members = [(name, data) for _raw, name, data in files]
            members.append(
                (
                    "SNAPSHOT_MANIFEST.json",
                    (
                        json.dumps(
                            manifest, ensure_ascii=False, sort_keys=True, indent=2
                        )
                        + "\n"
                    ).encode("utf-8"),
                )
            )
            for name, data in members:
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.mode = 0o644
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mtime = 0
                tar.addfile(info, io.BytesIO(data))
    return output.getvalue()


def _write_private(path: Path, content: bytes) -> None:
    """Publish a complete local file atomically and never overwrite an archive."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def package_snapshot(
    source: Path, output: Path, expected_hash: str, *, scan_only: bool = False
) -> dict[str, Any]:
    from eval_framework.benchmark.nanobot_runtime import runtime_identity

    source = source.expanduser().resolve(strict=True)
    identity_config = {"nanobot_root": str(source), "model": "source-snapshot-only"}
    before = runtime_identity(identity_config)
    files = selected_runtime_files(source)
    digest = source_digest(files)
    if digest != expected_hash or digest != before["working_tree_sha256"]:
        raise ValueError(
            "Selected source differs from measured runtime hash; no archive written"
        )
    findings = potential_secret_files(files)
    summary = {
        "source_commit": before["source_commit"],
        "source_dirty": before["source_dirty"],
        "working_tree_sha256": digest,
        "file_count": len(files),
        "potential_secret_files": findings,
        "scan_only": scan_only,
    }
    if findings or scan_only:
        return summary
    after = runtime_identity(identity_config)
    if any(
        before[key] != after[key]
        for key in ("source_commit", "working_tree_sha256", "source_dirty")
    ):
        raise ValueError("Source changed while reading; no archive written")
    manifest = {
        "format": "nanobot-runtime-source-snapshot-v1",
        "source_commit": before["source_commit"],
        "source_dirty": before["source_dirty"],
        "working_tree_sha256": digest,
        "hash_algorithm": "SHA256(sorted_git_path_bytes + NUL + file_bytes + NUL)",
        "selection": {
            "git_visible": "cached + untracked, excluding Git-ignored files",
            "roots": ["nanobot/", "pyproject.toml", "uv.lock"],
            "suffixes": sorted(RUNTIME_SUFFIXES),
            "excludes": ["symlinks", ".env* paths", ".git", "non-runtime assets"],
        },
        "files": [
            {
                "path": name,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
            for _raw, name, data in files
        ],
        "secret_scan": {
            "method": "local static token and literal pattern scan",
            "potential_secret_files": [],
            "limitation": (
                "Heuristic scan is not proof that all possible secrets are absent"
            ),
        },
        "restore": (
            "Runtime source snapshot only: restore into a fresh copy of the recorded "
            "commit, reconcile the selected file set to this manifest, and verify "
            "working_tree_sha256 before running. Git history and non-runtime build "
            "assets are not included."
        ),
        "remote_model_limit": "A fixed model alias does not freeze provider weights",
    }
    archive = _archive_bytes(files, manifest)
    archive_hash = hashlib.sha256(archive).hexdigest()
    receipt = {**manifest, "archive_file": output.name, "archive_sha256": archive_hash}
    manifest_path = output.with_suffix(output.suffix + ".manifest.json")
    if output.exists() or manifest_path.exists():
        raise FileExistsError(
            "Snapshot output already exists; choose a new output path"
        )
    _write_private(output, archive)
    _write_private(
        manifest_path,
        (json.dumps(receipt, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    return {
        **summary,
        "archive_file": str(output),
        "manifest_file": str(manifest_path),
        "archive_sha256": archive_hash,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-hash", required=True)
    parser.add_argument("--scan-only", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-f0-9]{64}", args.expected_hash):
        parser.error("expected hash must be the recorded 64-character SHA-256")
    result = package_snapshot(
        args.source, args.output, args.expected_hash, scan_only=args.scan_only
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if result["potential_secret_files"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
