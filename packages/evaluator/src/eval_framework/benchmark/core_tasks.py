"""Strict, immutable contracts for offline nanobot components (not Agent trials)."""

from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

CONTRACT_VERSION = "nanobot-core-task-v1"
DATASET_ID = "nanobot-core-v1"

# Required and optional argument types. All mappings are closed.
OP_ARGUMENTS = {
    "memory.append": (
        {"entry": "str"},
        {"session_key": "nullable_str", "max_chars": "positive"},
    ),
    "memory.read": ({"since_cursor": "nonnegative"}, {}),
    "memory.recent": (
        {"since_cursor": "nonnegative", "session_key": "nullable_str"},
        {"unified_session": "bool"},
    ),
    "memory.latest": ({}, {}),
    "memory.set_dream_cursor": ({"cursor": "nonnegative"}, {}),
    "memory.compact": ({}, {}),
    "memory.reload": ({}, {}),
    "memory.write": ({"content": "str"}, {}),
    "memory.read_long": ({}, {}),
    "session.add": (
        {"key": "text", "role": "role", "content": "str"},
        {"tool_call_id": "text", "tool_calls": "tool_calls"},
    ),
    "session.save": ({"key": "text"}, {}),
    "session.reload": ({"key": "text"}, {}),
    "session.history": (
        {"key": "text"},
        {"max_messages": "nonnegative", "include_runtime_context": "bool"},
    ),
    "session.clear": ({"key": "text"}, {}),
    "session.delete": ({"key": "text"}, {}),
    "context.system": (
        {},
        {
            "session_key": "nullable_str",
            "unified_session": "bool",
            "include_memory": "bool",
            "include_memory_recent_history": "bool",
        },
    ),
    "context.messages": (
        {"history": "messages", "current_message": "str"},
        {"current_role": "current_role"},
    ),
    "skills.list": ({}, {"filter_unavailable": "bool"}),
    "skills.load": ({"name": "text"}, {}),
    "skills.metadata": ({"name": "text"}, {}),
    "skills.invoked": ({"text": "str"}, {}),
    "skills.context": ({"text": "str"}, {}),
}


def _fail(message: str) -> None:
    raise ValueError(message)


def safe_relative_path(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and "\\" not in value
        and "\x00" not in value
        and not value.startswith("/")
        and all(part not in {"", ".", ".."} for part in value.split("/"))
        and PurePosixPath(value).as_posix() == value
    )


def _shape(value: Any, required: set[str], optional: set[str] = frozenset()) -> None:
    if (
        not isinstance(value, dict)
        or not required <= value.keys()
        or value.keys() - required - optional
    ):
        _fail(
            f"Invalid fields; required={sorted(required)}, optional={sorted(optional)}"
        )


def _typed(value: Any, kind: str) -> bool:
    if kind == "str":
        return isinstance(value, str)
    if kind == "text":
        return isinstance(value, str) and bool(value.strip()) and "\x00" not in value
    if kind == "nullable_str":
        return value is None or _typed(value, "text")
    if kind == "bool":
        return type(value) is bool
    if kind in {"positive", "nonnegative"}:
        return type(value) is int and value >= (1 if kind == "positive" else 0)
    if kind == "role":
        return value in ("user", "assistant", "tool", "system", "_command")
    if kind == "current_role":
        return value in ("user", "assistant")
    if kind == "tool_calls":
        if not isinstance(value, list):
            return False
        for call in value:
            _shape(call, {"id", "type", "function"})
            _shape(call["function"], {"name", "arguments"})
            if (
                call["type"] != "function"
                or not all(
                    _typed(v, "text") for v in (call["id"], call["function"]["name"])
                )
                or not isinstance(call["function"]["arguments"], str)
            ):
                return False
        return True
    if kind == "messages":
        if not isinstance(value, list) or len(value) > 100:
            return False
        for message in value:
            _shape(message, {"role", "content"})
            if not _typed(message["role"], "role") or not isinstance(
                message["content"], str
            ):
                return False
        return True
    return False


def validate_public_task(public: dict[str, Any]) -> None:
    _shape(public, {"settings", "operations"})
    settings = public["settings"]
    _shape(settings, set(), {"memory_max_history_entries", "disabled_skills"})
    if "memory_max_history_entries" in settings and not _typed(
        settings["memory_max_history_entries"], "positive"
    ):
        _fail("Invalid memory history limit")
    disabled = settings.get("disabled_skills", [])
    if not isinstance(disabled, list) or any(not _typed(v, "text") for v in disabled):
        _fail("Invalid disabled skills")
    operations = public["operations"]
    if not isinstance(operations, list) or not 1 <= len(operations) <= 40:
        _fail("Expected 1..40 operations")
    seen = set()
    for operation in operations:
        _shape(operation, {"id", "operation", "input"})
        identifier, name = operation["id"], operation["operation"]
        if not _typed(identifier, "text") or identifier in seen:
            _fail("Invalid or duplicate operation id")
        seen.add(identifier)
        if not isinstance(name, str) or name not in OP_ARGUMENTS:
            _fail("Unknown core operation")
        required, optional = OP_ARGUMENTS[name]
        args = operation["input"]
        _shape(args, set(required), set(optional))
        for key, value in args.items():
            if not _typed(value, (required | optional)[key]):
                _fail(f"Invalid operation argument {name}.{key}")


def validate_core_task(task: dict[str, Any]) -> None:
    _shape(
        task,
        {
            "id",
            "contract_version",
            "family",
            "split",
            "component",
            "description",
            "fixtures",
            "settings",
            "operations",
            "oracle",
        },
    )
    if task["contract_version"] != CONTRACT_VERSION or task["split"] not in (
        "dev",
        "holdout",
    ):
        _fail("Unknown contract version or split")
    if task["component"] not in ("memory", "session", "context", "skills"):
        _fail("Unknown component")
    if any(not _typed(task[key], "text") for key in ("id", "family", "description")):
        _fail("Missing task identity or description")
    fixtures = task["fixtures"]
    if not isinstance(fixtures, dict) or any(
        not safe_relative_path(k) or not isinstance(v, str) for k, v in fixtures.items()
    ):
        _fail("Invalid fixture path/text")
    if any(a.startswith(b + "/") for a in fixtures for b in fixtures if a != b):
        _fail("Conflicting fixture paths")
    validate_public_task(
        {"settings": task["settings"], "operations": task["operations"]}
    )
    _shape(task["oracle"], {"assertions"})
    assertions = task["oracle"]["assertions"]
    if not isinstance(assertions, list) or not assertions:
        _fail("Missing private assertions")
    ids = {op["id"] for op in task["operations"]}
    checked = set()
    for assertion in assertions:
        if not isinstance(assertion, dict):
            _fail("Invalid assertion")
        if "event" in assertion:
            _shape(assertion, {"event", "path", "kind", "value"})
            if not isinstance(assertion["event"], str) or assertion["event"] not in ids:
                _fail("Unknown assertion event")
            checked.add(assertion["event"])
        else:
            _shape(assertion, {"scope", "path", "kind", "value"})
            if assertion["scope"] not in ("final_files", "session_files"):
                _fail("Unknown evidence scope")
        path = assertion["path"]
        if (
            not isinstance(path, list)
            or (not path and assertion["kind"] != "any_file_contains")
            or any(not (isinstance(v, str) or type(v) is int and v >= 0) for v in path)
        ):
            _fail("Invalid assertion path")
        if "event" in assertion and (not path or path[0] not in ("output", "error")):
            _fail("Only output/error may be asserted")
        if (
            "scope" in assertion
            and assertion["kind"] != "any_file_contains"
            and (len(path) != 1 or not safe_relative_path(path[0]))
        ):
            _fail("Invalid snapshot assertion path")
        if assertion["kind"] not in (
            "equals",
            "contains",
            "not_contains",
            "length",
            "subset",
            "any_file_contains",
        ):
            _fail("Unknown assertion kind")
        if assertion["kind"] == "any_file_contains" and (
            "scope" not in assertion
            or path != []
            or not _typed(assertion["value"], "text")
        ):
            _fail("Invalid snapshot content assertion")
        if assertion["kind"] == "length" and not _typed(
            assertion["value"], "nonnegative"
        ):
            _fail("Invalid length assertion")
    if checked != ids:
        _fail("Every operation must have a private assertion")
    try:
        json.dumps(task, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("Task must contain finite JSON") from exc


def core_execution_task(task: dict[str, Any]) -> dict[str, Any]:
    validate_core_task(task)
    return copy.deepcopy(
        {"settings": task["settings"], "operations": task["operations"]}
    )


def _read_dataset(path: Path) -> tuple[list[dict], dict, str]:
    from .datasets.io import read_jsonl_bytes

    path = Path(path)
    if path.is_dir():
        path = path / "tasks.jsonl"
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    manifest = json.loads(path.with_name("manifest.json").read_text())
    if manifest.get("sha256") != digest:
        _fail("Dataset SHA256 mismatch")
    if (
        manifest.get("dataset_id") != DATASET_ID
        or manifest.get("contract_version") != CONTRACT_VERSION
    ):
        _fail("Dataset identity/version mismatch")
    tasks = read_jsonl_bytes(raw)
    ids, families = set(), {}
    for task in tasks:
        validate_core_task(task)
        if task["id"] in ids:
            _fail("Duplicate task id")
        ids.add(task["id"])
        previous = families.setdefault(task["family"], task["split"])
        if previous != task["split"]:
            _fail("Family overlaps dev and holdout")
    if (
        not tasks
        or manifest.get("task_count") != len(tasks)
        or manifest.get("family_count") != len(families)
        or manifest.get("split_counts") != dict(Counter(t["split"] for t in tasks))
        or manifest.get("human_reviewed") is not False
    ):
        _fail("Manifest counts/review status mismatch")
    return tasks, manifest, digest


def load_core_tasks(path: Path) -> list[dict]:
    return _read_dataset(path)[0]


def core_dataset_identity(path: Path) -> dict:
    tasks, manifest, digest = _read_dataset(path)
    return {
        key: manifest[key]
        for key in (
            "dataset_id",
            "contract_version",
            "task_count",
            "family_count",
            "split_counts",
            "human_reviewed",
        )
    } | {"sha256": digest}
