from __future__ import annotations

from pathlib import Path

import pytest

import capability_snapshot_kit.exporting as exporting
from capability_snapshot_kit.exporting import export_capability_bundle_v3
from capability_snapshot_kit.spec_loader import load_capability_spec_pack_v3
from capability_snapshot_kit.validation import CapabilityBundleValidationErrorV3
from tests.support.capability_adapter import FakeCapabilityAdapter

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SPECS = load_capability_spec_pack_v3(PROJECT_ROOT / "capability_specs")


def _files(root: Path) -> dict[Path, bytes]:
    return {
        path.relative_to(root): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _export(root: Path) -> list[Path]:
    return export_capability_bundle_v3(root, SPECS, FakeCapabilityAdapter())


def test_two_exports_are_byte_identical(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"

    _export(first)
    _export(second)

    assert _files(first) == _files(second)


def test_empty_tool_export_keeps_tools_directory(tmp_path: Path) -> None:
    root = tmp_path / "bundle"

    paths = _export(root)

    assert [path.name for path in (root / "tools").iterdir()] == [".gitkeep"]
    assert root / "tools" / ".gitkeep" in paths


def test_validation_failure_preserves_existing_output_byte_for_byte(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "bundle"
    _export(root)
    before = _files(root)

    def fail_validation(_root: Path):
        raise CapabilityBundleValidationErrorV3(["forced validation failure"])

    monkeypatch.setattr(exporting, "validate_capability_bundle_v3", fail_validation)

    with pytest.raises(CapabilityBundleValidationErrorV3, match="forced"):
        _export(root)

    assert _files(root) == before


def test_replace_failure_restores_backup_byte_for_byte(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "bundle"
    _export(root)
    before = _files(root)
    real_replace = exporting.os.replace
    calls = 0

    def fail_second_replace(source: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("forced replace failure")
        real_replace(source, destination)

    monkeypatch.setattr(exporting.os, "replace", fail_second_replace)

    with pytest.raises(OSError, match="forced replace failure"):
        _export(root)

    assert _files(root) == before
