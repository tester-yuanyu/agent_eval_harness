"""Local JSON loading, compatibility projection and explicit offline migration."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from .specs import (
    BenchmarkSpec,
    EnvironmentSpec,
    ExecutionSpec,
    HarnessSpec,
    ModelSpec,
    RunRequest,
    validate_local_path,
    validate_public_config,
)

SPEC_TYPES = {
    "model": ModelSpec,
    "harness": HarnessSpec,
    "environment": EnvironmentSpec,
    "benchmark": BenchmarkSpec,
    "execution": ExecutionSpec,
}
PATH_FIELDS = {
    "environment": {
        "nanobot_root", "python", "tokenizer_cache_dir", "repository_root",
        "capability_bundle",
    },
    "benchmark": {"dataset"},
}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON configuration key")
        value[key] = item
    return value


def _local_path(value: str, base: Path) -> Path:
    path = Path(validate_local_path(value)).expanduser()
    # Do not resolve symlinks: a venv interpreter must retain its venv path.
    return Path(os.path.abspath(path if path.is_absolute() else base / path))


def read_config_json(path: Path) -> dict[str, Any]:
    """Read a JSON object without executing code or accepting duplicate keys."""
    path = _local_path(str(path), Path.cwd())
    value = json.loads(path.read_text(), object_pairs_hook=_unique_object)
    if not isinstance(value, dict):
        raise ValueError("configuration must be a JSON object")
    validate_public_config(value)
    return value


def is_run_request(value: dict[str, Any]) -> bool:
    return "schema_version" in value or bool(
        {"harness", "environment", "benchmark", "execution"} & value.keys()
    ) or isinstance(value.get("model"), dict)


def legacy_run_request(value: dict[str, Any]) -> RunRequest:
    """Keep legacy omission and cwd-relative path semantics exactly as supplied."""
    validate_public_config(value)
    sections: dict[str, Any] = {"schema_version": "1.0"}
    known: set[str] = set()
    for name, cls in SPEC_TYPES.items():
        fields = set(cls.model_fields) if name in {
            "model", "harness", "environment"
        } else set()
        known.update(fields)
        sections[name] = {key: item for key, item in value.items() if key in fields}
    unknown = set(value) - known
    if unknown:
        raise ValueError(
            "unknown legacy configuration fields: " + ", ".join(sorted(unknown))
        )
    return RunRequest.model_validate(sections)


def load_run_request(path: Path) -> RunRequest:
    path = _local_path(str(path), Path.cwd())
    value = read_config_json(path)
    if not is_run_request(value):
        return legacy_run_request(value)
    resolved = dict(value)
    for section in SPEC_TYPES:
        if section not in resolved:
            continue  # The schema reports required missing sections.
        item = resolved[section]
        base = path.parent
        if isinstance(item, str):
            reference = _local_path(item, base)
            item = read_config_json(reference)
            base = reference.parent
        if isinstance(item, dict):
            item = dict(item)
            for field in PATH_FIELDS.get(section, set()):
                if field in item and item[field] is not None:
                    item[field] = str(_local_path(item[field], base))
        resolved[section] = item
    return RunRequest.model_validate(resolved)


def migrate_legacy_config(source: Path, output: Path) -> Path:
    """Write all five specs plus run.json; never change or overwrite the source."""
    value = read_config_json(source)
    if is_run_request(value):
        raise ValueError("migration expects a legacy flat benchmark configuration")
    request = legacy_run_request(value)
    sections = request.model_dump(exclude_unset=True)
    for section, fields in PATH_FIELDS.items():
        for field in fields:
            item = sections[section].get(field)
            if item is not None:
                sections[section][field] = str(_local_path(item, Path.cwd()))
    RunRequest.model_validate(sections)
    output = _local_path(str(output), Path.cwd())
    if output.exists():
        raise ValueError("migration output already exists")
    output.mkdir(parents=True, exist_ok=False)
    manifest: dict[str, Any] = {"schema_version": "1.0"}
    for section in SPEC_TYPES:
        filename = f"{section}.json"
        with (output / filename).open("x") as handle:
            json.dump(sections[section], handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        manifest[section] = filename
    destination = output / "run.json"
    with destination.open("x") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return destination


def migration_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="离线拆分旧 benchmark 配置为五份 Spec")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        destination = migrate_legacy_config(args.input, args.output)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(migration_main())
