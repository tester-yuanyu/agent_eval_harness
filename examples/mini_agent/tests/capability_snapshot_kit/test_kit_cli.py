from __future__ import annotations

import json
from pathlib import Path

from capability_snapshot_kit.cli import main
from tests.support.capability_adapter import FakeCapabilityAdapter

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SPEC_ROOT = PROJECT_ROOT / "capability_specs"


def _main(*arguments: str) -> int:
    return main(
        list(arguments),
        adapter_factory=FakeCapabilityAdapter,
        default_spec_root=SPEC_ROOT,
    )


def test_cli_exports_validates_resolves_and_diffs_machine_json(
    tmp_path: Path,
    capsys,
) -> None:
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    selection = tmp_path / "selection.json"
    selection.write_text(
        json.dumps(
            {
                "scope_or_chain_id": "scope.understanding",
                "intent_id": "intent.query_user",
                "tool_id": None,
            }
        ),
        encoding="utf-8",
    )

    assert _main("export", "--output", str(old_root)) == 0
    exported = json.loads(capsys.readouterr().out)
    assert exported["snapshot_counts"]["agent"] == 1
    assert exported["output"] == str(old_root)

    assert _main("validate", "--input", str(old_root)) == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True

    assert (
        _main(
            "resolve",
            "--input",
            str(old_root),
            "--selection",
            str(selection),
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["support_status"] == "supported"

    assert (
        _main(
            "export",
            "--output",
            str(new_root),
            "--spec-root",
            str(SPEC_ROOT),
        )
        == 0
    )
    capsys.readouterr()
    assert _main("diff", "--old", str(old_root), "--new", str(new_root)) == 0
    assert json.loads(capsys.readouterr().out)["changed_ids"] == []


def test_cli_invalid_input_returns_machine_error(tmp_path: Path, capsys) -> None:
    missing = tmp_path / "missing"

    assert _main("validate", "--input", str(missing)) == 1

    error = json.loads(capsys.readouterr().err)
    assert error["status"] == "ERROR"
    assert error["error_type"]
