"""Explicit source acquisition; evaluation never calls this module's sync method."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from .registry import SuiteError, atomic_json, component, inside, locked, read_index


def git_bytes(path: Path, *args: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null", *args],
            cwd=path,
            capture_output=True,
            timeout=60,
            check=False,
            env={
                **os.environ,
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_NO_REPLACE_OBJECTS": "1",
            },
        )
    except subprocess.TimeoutExpired as exc:
        raise SuiteError(
            "Git operation timed out; no publication was registered"
        ) from exc
    if result.returncode:
        raise SuiteError(
            result.stderr.decode("utf-8", errors="replace").strip()
            or "Git operation failed"
        )
    return result.stdout


def git(path: Path, *args: str) -> str:
    return git_bytes(path, *args).decode("utf-8", errors="surrogateescape").strip()


def commit_id(value: str) -> str:
    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value):
        raise SuiteError("source resolution requires a full pinned commit Hash")
    return value


def verify_tracked_files(root: Path, commit: str) -> None:
    """Compare actual bytes/modes with the commit tree, never the Git index cache."""
    entries = git_bytes(root, "ls-tree", "-rz", "--full-tree", commit)
    for entry in entries.split(b"\0"):
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        mode, object_type, object_hash = metadata.split()
        relative = Path(os.fsdecode(raw_path))
        if relative.is_absolute() or ".." in relative.parts:
            raise SuiteError("tracked source path escapes checkout")
        path = root / relative
        failure = f"tracked source was modified: {relative}"
        # Parent symlinks could otherwise redirect an unchanged file outside the checkout.
        for parent in path.parents:
            if parent == root:
                break
            if parent.is_symlink() or not parent.is_dir():
                raise SuiteError(failure)
        try:
            if mode == b"160000":
                # Gitlinks are recorded in the tree, but sync never fetches their code.
                # A populated submodule would add executable bytes we have not verified.
                if path.is_symlink() or (
                    path.exists() and (not path.is_dir() or any(path.iterdir()))
                ):
                    raise SuiteError(
                        "populated submodules require independent pinned source verification"
                    )
                continue
            actual = path.lstat()
            if mode == b"120000":
                if not stat.S_ISLNK(actual.st_mode):
                    raise SuiteError(failure)
                content = os.fsencode(os.readlink(path))
            elif mode in (b"100644", b"100755"):
                executable = bool(actual.st_mode & stat.S_IXUSR)
                if not stat.S_ISREG(actual.st_mode) or executable != (
                    mode == b"100755"
                ):
                    raise SuiteError(failure)
                content = path.read_bytes()
            else:
                raise SuiteError(f"unsupported tracked source mode: {mode!r}")
        except OSError as exc:
            raise SuiteError(failure) from exc
        if object_type != b"blob":
            raise SuiteError("unsupported tracked source object type")
        algorithm = "sha256" if len(object_hash) == 64 else "sha1"
        actual_hash = hashlib.new(
            algorithm, b"blob " + str(len(content)).encode() + b"\0" + content
        ).hexdigest()
        if actual_hash != object_hash.decode("ascii"):
            raise SuiteError(failure)


class SourceRegistry:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.index = inside(self.root, "data/source-index.json")

    def sync(self, name: str, repository: str, ref: str) -> dict:
        component(name)
        if (
            not repository
            or repository.startswith("-")
            or not ref
            or ref.startswith("-")
        ):
            raise SuiteError("repository/ref must be explicit non-option values")
        if (
            urlsplit(repository).scheme in ("http", "https")
            and urlsplit(repository).username
        ):
            raise SuiteError(
                "use Git credential configuration, not credentials embedded in a repository URL"
            )
        # Local source paths are made portable across the temporary clone cwd.
        if Path(repository).exists():
            repository = str(Path(repository).resolve())
        base = inside(self.root, f".sources/{name}")
        base.mkdir(parents=True, exist_ok=True)
        with locked(self.index):
            index = read_index(self.index, "sources")
            stage = Path(tempfile.mkdtemp(prefix=".sync-", dir=base))
            destination = None
            moved = False
            try:
                git(stage, "init", "-q")
                git(stage, "remote", "add", "origin", repository)
                git(stage, "fetch", "--no-tags", "--depth", "1", "origin", ref)
                commit = commit_id(
                    git(stage, "rev-parse", "--verify", "FETCH_HEAD^{commit}")
                )
                git(stage, "checkout", "--detach", commit)
                tree = git(stage, "rev-parse", "HEAD^{tree}")
                verify_tracked_files(stage, commit)
                versions = index["sources"].setdefault(name, {})
                if commit in versions:
                    existing = self.resolve(name, commit)
                    if existing["repository"] != repository:
                        raise SuiteError(
                            "source name/commit is already bound to another repository"
                        )
                    return existing
                relative = f".sources/{name}/{commit}"
                destination = inside(self.root, relative)
                if destination.exists():
                    raise SuiteError(
                        f"unregistered source destination already exists: {destination}"
                    )
                record = {
                    "name": name,
                    "repository": repository,
                    "requested_ref": ref,
                    "commit": commit,
                    "tree": tree,
                    "path": relative,
                }
                stage.rename(destination)
                moved = True
                versions[commit] = record
                atomic_json(self.index, index)
            except BaseException:
                if moved and destination is not None:
                    shutil.rmtree(destination)
                raise
            finally:
                if stage.exists():
                    shutil.rmtree(stage)
        return {**record, "resolved_path": str(destination)}

    def resolve(self, name: str, commit: str) -> dict:
        component(name)
        commit_id(commit)
        index = read_index(self.index, "sources")
        try:
            record = index["sources"][name][commit]
        except KeyError as exc:
            raise SuiteError(
                f"unknown pinned source: {name}@{commit}; explicitly sync it first"
            ) from exc
        expected = f".sources/{name}/{commit}"
        if (
            record.get("name") != name
            or record.get("commit") != commit
            or record.get("path") != expected
        ):
            raise SuiteError("source registry identity/path mismatch")
        path = inside(self.root, expected)
        if (
            git(path, "rev-parse", "HEAD") != commit
            or git(path, "rev-parse", "HEAD^{tree}") != record["tree"]
        ):
            raise SuiteError("source checkout no longer matches pinned commit/tree")
        if git(path, "remote", "get-url", "origin") != record["repository"]:
            raise SuiteError("source repository provenance mismatch")
        verify_tracked_files(path, commit)
        if git(path, "status", "--porcelain", "--untracked-files=all"):
            raise SuiteError(
                "source checkout was modified; it cannot claim the pinned identity"
            )
        return {**record, "resolved_path": str(path)}
