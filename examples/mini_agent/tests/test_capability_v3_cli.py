from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run(module: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", module, *arguments],
        check=False,
        capture_output=True,
        text=True,
    )


def test_unversioned_cli_is_identical_to_v3_cli(tmp_path: Path) -> None:
    output = tmp_path / "unversioned"
    explicit_output = tmp_path / "explicit-v3"

    result = _run(
        "minimal_agent.capabilities.cli",
        "export",
        "--output",
        str(output),
    )
    explicit = _run(
        "minimal_agent.capabilities.v3.cli",
        "export",
        "--output",
        str(explicit_output),
    )
    unversioned_validation = _run(
        "minimal_agent.capabilities.cli",
        "validate",
        "--input",
        str(output),
    )
    explicit_validation = _run(
        "minimal_agent.capabilities.v3.cli",
        "validate",
        "--input",
        str(output),
    )

    assert result.returncode == 0, result.stderr
    assert explicit.returncode == 0, explicit.stderr
    assert json.loads(result.stdout)["snapshot_counts"] == {
        "agent": 1,
        "module": 7,
        "intent": 7,
        "tool": 0,
        "scope": 5,
        "chain": 3,
        "evidence": 5,
        "boundary": 7,
    }
    assert unversioned_validation.returncode == 0, unversioned_validation.stderr
    assert explicit_validation.returncode == 0, explicit_validation.stderr
    assert {
        path.relative_to(output): path.read_bytes()
        for path in output.rglob("*")
        if path.is_file()
    } == {
        path.relative_to(explicit_output): path.read_bytes()
        for path in explicit_output.rglob("*")
        if path.is_file()
    }


def test_cli_exports_validates_and_rejects_incompatible_root(tmp_path: Path) -> None:
    output = tmp_path / "capabilities"
    wrong_root = tmp_path / "wrong-version"
    wrong_root.mkdir()
    (wrong_root / "agent.json").write_text(
        json.dumps({"snapshot_format_version": "0.0"}),
        encoding="utf-8",
    )

    exported = _run(
        "minimal_agent.capabilities.cli",
        "export",
        "--output",
        str(output),
    )
    validated = _run(
        "minimal_agent.capabilities.cli",
        "validate",
        "--input",
        str(output),
    )
    wrong = _run(
        "minimal_agent.capabilities.cli",
        "validate",
        "--input",
        str(wrong_root),
    )

    assert exported.returncode == 0, exported.stderr
    assert json.loads(exported.stdout)["snapshot_counts"] == {
        "agent": 1,
        "module": 7,
        "intent": 7,
        "tool": 0,
        "scope": 5,
        "chain": 3,
        "evidence": 5,
        "boundary": 7,
    }
    assert validated.returncode == 0, validated.stderr
    assert json.loads(validated.stdout)["valid"] is True
    assert wrong.returncode == 1
    error = json.loads(wrong.stderr)
    assert error["status"] == "ERROR"
    assert "expected '3.0'" in error["message"]


def test_cli_export_accepts_explicit_portable_spec_root(tmp_path: Path) -> None:
    output = tmp_path / "capabilities"

    result = _run(
        "minimal_agent.capabilities.cli",
        "export",
        "--output",
        str(output),
        "--spec-root",
        str(PROJECT_ROOT / "capability_specs"),
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["snapshot_counts"]["agent"] == 1


def test_cli_resolves_selection_json(tmp_path: Path) -> None:
    output = tmp_path / "capabilities"
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
    assert (
        _run(
            "minimal_agent.capabilities.cli",
            "export",
            "--output",
            str(output),
        ).returncode
        == 0
    )

    result = _run(
        "minimal_agent.capabilities.cli",
        "resolve",
        "--input",
        str(output),
        "--selection",
        str(selection),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["support_status"] == "supported"
    assert payload["selection"]["intent_id"] == "intent.query_user"


def test_cli_diff_emits_machine_readable_result(tmp_path: Path) -> None:
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    for root in (old_root, new_root):
        assert (
            _run(
                "minimal_agent.capabilities.cli",
                "export",
                "--output",
                str(root),
            ).returncode
            == 0
        )

    result = _run(
        "minimal_agent.capabilities.cli",
        "diff",
        "--old",
        str(old_root),
        "--new",
        str(new_root),
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "added_ids": [],
        "affected_selection_roots": [],
        "changed_ids": [],
        "removed_ids": [],
    }
