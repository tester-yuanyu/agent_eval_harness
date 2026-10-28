from __future__ import annotations

import os
import stat
import zipfile
from pathlib import Path

import pytest

from eval_framework.onboarding import delivery


def _directory_delivery(root: Path) -> Path:
    root.mkdir()
    (root / "manifest.json").write_text("{}", encoding="utf-8")
    (root / "nested").mkdir()
    (root / "nested/data.txt").write_text("payload", encoding="utf-8")
    return root


def test_directory_snapshot_copies_regular_inventory(tmp_path: Path) -> None:
    source = _directory_delivery(tmp_path / "source")
    destination = tmp_path / "snapshot"

    root = delivery.snapshot(source, destination)

    assert root == destination
    assert (root / "manifest.json").read_text(encoding="utf-8") == "{}"
    assert (root / "nested/data.txt").read_text(encoding="utf-8") == "payload"


def test_directory_snapshot_rejects_special_file_before_copy(tmp_path: Path) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO creation is unavailable")
    source = _directory_delivery(tmp_path / "source")
    os.mkfifo(source / "pipe")
    destination = tmp_path / "snapshot"

    with pytest.raises(ValueError, match="non-regular"):
        delivery.snapshot(source, destination)

    assert not destination.exists()


def test_directory_snapshot_rejects_unsafe_name_before_copy(tmp_path: Path) -> None:
    source = _directory_delivery(tmp_path / "source")
    (source / "unsafe\\name").write_text("payload", encoding="utf-8")
    destination = tmp_path / "snapshot"

    with pytest.raises(ValueError, match="unsafe delivery path"):
        delivery.snapshot(source, destination)

    assert not destination.exists()


def test_directory_snapshot_does_not_follow_file_replaced_by_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _directory_delivery(tmp_path / "source")
    external = tmp_path / "external.txt"
    external.write_text("secret", encoding="utf-8")
    original_scan = delivery._scan_directory

    def scan_then_replace(root_fd: int):
        inventory = original_scan(root_fd)
        target = source / "nested/data.txt"
        target.unlink()
        target.symlink_to(external)
        return inventory

    monkeypatch.setattr(delivery, "_scan_directory", scan_then_replace)
    destination = tmp_path / "snapshot"

    with pytest.raises(ValueError, match="symlink|changed"):
        delivery.snapshot(source, destination)

    assert not destination.exists()


def test_directory_snapshot_applies_size_bound_before_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _directory_delivery(tmp_path / "source")
    monkeypatch.setattr(delivery, "MAX_FILE_BYTES", 3)
    destination = tmp_path / "snapshot"

    with pytest.raises(ValueError, match="size limit"):
        delivery.snapshot(source, destination)

    assert not destination.exists()


@pytest.mark.parametrize(
    "members",
    [
        [("node", "file"), ("node/child.txt", "child")],
        [("node/child.txt", "child"), ("node", "file")],
    ],
)
def test_zip_rejects_file_directory_prefix_conflict_before_extract(
    tmp_path: Path, members: list[tuple[str, str]]
) -> None:
    archive = tmp_path / "delivery.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("manifest.json", "{}")
        for name, value in members:
            handle.writestr(name, value)
    destination = tmp_path / "snapshot"

    with pytest.raises(ValueError, match="file/directory path conflict"):
        delivery.snapshot(archive, destination)

    assert not destination.exists()


@pytest.mark.parametrize(
    "first,second",
    [
        ("Folder/one.txt", "folder/two.txt"),
        (
            "caf\N{LATIN SMALL LETTER E WITH ACUTE}/one.txt",
            "cafe\N{COMBINING ACUTE ACCENT}/two.txt",
        ),
    ],
)
def test_zip_rejects_case_or_unicode_directory_collision(
    tmp_path: Path, first: str, second: str
) -> None:
    archive = tmp_path / "delivery.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("manifest.json", "{}")
        handle.writestr(first, "one")
        handle.writestr(second, "two")
    destination = tmp_path / "snapshot"

    with pytest.raises(ValueError, match="case/Unicode normalization"):
        delivery.snapshot(archive, destination)

    assert not destination.exists()


def test_zip_rejects_symlink_before_extract(tmp_path: Path) -> None:
    archive = tmp_path / "delivery.zip"
    link = zipfile.ZipInfo("link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("manifest.json", "{}")
        handle.writestr(link, "outside")
    destination = tmp_path / "snapshot"

    with pytest.raises(ValueError, match="symlink or special"):
        delivery.snapshot(archive, destination)

    assert not destination.exists()
