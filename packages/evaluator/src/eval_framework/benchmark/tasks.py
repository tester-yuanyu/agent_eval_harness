"""Frozen, local-only file-tool task contract and answer-free execution projection."""

from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter, defaultdict, deque
from pathlib import Path, PurePosixPath
from typing import Any

CONTRACT_VERSION = "file-tools-task-v1"
LAYERED_CONTRACT_VERSION = "file-tools-task-v2"
DECISION_CONTRACT_VERSION = "model-decisions-task-v1"
GRADER_VERSION = "file-tools-oracle-v1"
TOOLS = ("read_file", "write_file", "edit_file", "list_dir")
CATEGORIES = ("read_search", "create_edit", "multi_file", "multi_turn", "missing_error")


def _validate_layered(task: dict[str, Any]) -> None:
    """Validate explicit private checkpoints without guessing malformed selectors."""
    level = task.get("evaluation_level", "e2e")
    mode = task.get("execution_mode", "agent")
    if not isinstance(level, str) or level not in {"module", "chain", "e2e"}:
        raise ValueError("Unknown evaluation_level")
    if (level == "module" and mode not in ("module", "decision")) or (
        level != "module" and mode != "agent"
    ):
        raise ValueError(
            "module evaluation requires module execution; other levels use agent"
        )
    checkpoints = task.get("checkpoints", [])
    if not isinstance(checkpoints, list):
        raise ValueError("checkpoints must be a list")
    if level == "chain" and not checkpoints:
        raise ValueError("chain tasks require explicit checkpoints")
    ids: set[str] = set()
    for point in checkpoints:
        if not isinstance(point, dict):
            raise ValueError("checkpoint must be an object")
        identifier = point.get("id")
        if (
            not isinstance(identifier, str)
            or not identifier.strip()
            or identifier in ids
        ):
            raise ValueError("checkpoint ids must be nonempty and unique")
        ids.add(identifier)
        if not isinstance(point.get("required"), bool):
            raise ValueError("checkpoint required must be boolean")
        kind = point.get("kind")
        selectors = {
            "turn_files": {"turn", "expected_files"},
            "tool_args": {"tool", "arguments", "turn"},
            "tool_order": {"before", "after", "turn"},
        }
        if (
            not isinstance(kind, str)
            or kind not in selectors
            or set(point) - {"id", "kind", "required"} - selectors[kind]
        ):
            raise ValueError("Unknown checkpoint kind or fields")
        if "turn" in point:
            turn = point["turn"]
            if (
                isinstance(turn, bool)
                or not isinstance(turn, int)
                or not 1 <= turn <= 1 + len(task["followups"])
            ):
                raise ValueError(
                    "checkpoint turn must identify a declared 1-based turn"
                )
        if kind == "turn_files":
            values = point.get("expected_files")
            if "turn" not in point or not isinstance(values, dict) or not values:
                raise ValueError(
                    "turn_files checkpoint requires turn and nonempty expected_files"
                )
            for path, content in values.items():
                _safe_path(path)
                if not isinstance(content, str):
                    raise ValueError(
                        "checkpoint expected file contents must be strings"
                    )
        elif kind == "tool_args":
            if point.get("tool") not in task.get("allowed_tools", TOOLS):
                raise ValueError("checkpoint tool must be allowed")
            if not isinstance(point.get("arguments"), dict) or not point["arguments"]:
                raise ValueError(
                    "tool_args checkpoint requires a nonempty arguments subset"
                )
        elif any(
            point.get(key) not in task.get("allowed_tools", TOOLS)
            for key in ("before", "after")
        ):
            raise ValueError(
                "tool_order checkpoint requires allowed before/after tools"
            )
    calls = task.get("module_calls")
    if mode == "module":
        if task["followups"]:
            raise ValueError("module boundary tasks have one fixed request")
        if not isinstance(calls, list) or not calls or len(calls) > 40:
            raise ValueError("module tasks require 1 to 40 module_calls")
        for call in calls:
            if not isinstance(call, dict) or set(call) != {"name", "arguments"}:
                raise ValueError("module_calls require only name and arguments")
            if call["name"] not in task.get("allowed_tools", TOOLS) or not isinstance(
                call["arguments"], dict
            ):
                raise ValueError(
                    "module_calls require supported tools and argument objects"
                )
        results = task["oracle"].get("module_results")
        if not isinstance(results, list) or len(results) != len(calls):
            raise ValueError("module oracle must check every declared call")
        checked: set[int] = set()
        for result in results:
            if not isinstance(result, dict) or set(result) != {
                "call",
                "error",
                "output_contains",
            }:
                raise ValueError("module result requires call/error/output_contains")
            index = result["call"]
            if (
                isinstance(index, bool)
                or not isinstance(index, int)
                or not 1 <= index <= len(calls)
                or index in checked
            ):
                raise ValueError(
                    "module result call must be a unique valid 1-based index"
                )
            checked.add(index)
            if (
                not isinstance(result["error"], bool)
                or not isinstance(result["output_contains"], list)
                or not all(
                    isinstance(value, str) and value
                    for value in result["output_contains"]
                )
            ):
                raise ValueError(
                    "module result requires boolean error and string output checks"
                )
    elif calls is not None or "module_results" in task["oracle"]:
        raise ValueError("module_calls and module_results belong only to module tasks")
    decision = task["oracle"].get("decision")
    if mode == "decision":
        if task["followups"] or checkpoints:
            raise ValueError("decision tasks contain one isolated model request")
        if not isinstance(task.get("decision_context"), str):
            raise ValueError("decision_context must be public text")
        if not isinstance(decision, dict) or set(decision) != {
            "acceptable_tools",
            "arguments",
            "allow_no_tool",
            "max_calls",
        }:
            raise ValueError(
                "decision oracle requires tools, arguments and call policy"
            )
        acceptable = decision["acceptable_tools"]
        if (
            not isinstance(acceptable, list)
            or any(tool not in task.get("allowed_tools", TOOLS) for tool in acceptable)
            or len(acceptable) != len(set(acceptable))
            or not isinstance(decision["arguments"], dict)
            or not isinstance(decision["allow_no_tool"], bool)
            or type(decision["max_calls"]) is not int
            or decision["max_calls"] not in (0, 1)
        ):
            raise ValueError("Malformed decision oracle")
        if (not acceptable and not decision["allow_no_tool"]) or (
            decision["max_calls"] == 0 and (acceptable or not decision["allow_no_tool"])
        ):
            raise ValueError("Inconsistent decision abstention policy")
    elif decision is not None or "decision_context" in task:
        raise ValueError("decision fields belong only to decision execution")


def _safe_path(value: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or "\x00" in value
        or PurePosixPath(value).is_absolute()
        or any(part in ("", ".", "..") for part in value.split("/"))
    ):
        raise ValueError(f"Unsafe relative path: {value!r}")


def validate_task(task: dict[str, Any]) -> None:
    """Reject malformed data and paths before any workspace is materialized."""
    for key in ("id", "family", "prompt"):
        if not isinstance(task.get(key), str) or not task[key].strip():
            raise ValueError(f"Task requires nonempty {key}")
    if task.get("category") not in CATEGORIES:
        raise ValueError("Unknown task category")
    if task.get("split") not in ("dev", "holdout"):
        raise ValueError("Task split must be dev or holdout")
    if not isinstance(task.get("followups"), list) or not all(
        isinstance(value, str) and value.strip() for value in task["followups"]
    ):
        raise ValueError("followups must be a list of nonempty strings")
    if not isinstance(task.get("fixtures"), dict):
        raise ValueError("fixtures must be a path-to-UTF8-text object")
    for path, content in task["fixtures"].items():
        _safe_path(path)
        if not isinstance(content, str):
            raise ValueError("Fixture contents must be strings")
        content.encode("utf-8")
    paths = set(task["fixtures"])
    for path in paths:
        if any(str(parent) in paths for parent in PurePosixPath(path).parents):
            raise ValueError("Fixture path is both a file and a directory")
    oracle = task.get("oracle")
    if not isinstance(oracle, dict):
        raise ValueError("oracle must be an object")
    if not isinstance(oracle.get("expected_files", {}), dict):
        raise ValueError("expected_files must be an object")
    for path, content in oracle.get("expected_files", {}).items():
        _safe_path(path)
        if not isinstance(content, str):
            raise ValueError("Expected file contents must be strings")
    for key in ("absent_files", "unchanged_files", "response_contains"):
        if not isinstance(oracle.get(key, []), list) or not all(
            isinstance(value, str) and value for value in oracle.get(key, [])
        ):
            raise ValueError(f"{key} must be a list of nonempty strings")
    for path in oracle.get("absent_files", []) + oracle.get("unchanged_files", []):
        _safe_path(path)
    if set(oracle.get("expected_files", {})) & set(oracle.get("absent_files", [])):
        raise ValueError("A file cannot be both expected and absent")
    for key in ("preserve_other_files", "forbid_extra_files"):
        if not isinstance(oracle.get(key, True), bool):
            raise ValueError(f"{key} must be boolean")
    for key in ("required_tools", "allowed_tools"):
        values = task.get(key, list(TOOLS) if key == "allowed_tools" else None)
        if (
            not isinstance(values, list)
            or (
                not values
                and not (
                    key == "required_tools" and task.get("execution_mode") == "decision"
                )
            )
            or any(value not in TOOLS for value in values)
        ):
            raise ValueError(f"{key} must contain supported file tools")
        if len(set(values)) != len(values):
            raise ValueError(f"Duplicate tool in {key}")
    if not set(task["required_tools"]).issubset(task.get("allowed_tools", TOOLS)):
        raise ValueError("Required tools must be allowed")
    steps = task.get("max_steps")
    if isinstance(steps, bool) or not isinstance(steps, int) or not 1 <= steps <= 40:
        raise ValueError("max_steps must be an integer between 1 and 40")
    if not isinstance(task.get("reference"), list) or not task["reference"]:
        raise ValueError("Task requires private declarative reference operations")
    _validate_layered(task)


def _paths(path: Path) -> tuple[Path, Path]:
    path = Path(path)
    return (
        (path / "tasks.jsonl", path / "manifest.json")
        if path.is_dir()
        else (path, path.with_name("manifest.json"))
    )


def dataset_identity(path: Path) -> dict[str, Any]:
    """Read and verify immutable bytes and pinned contract/grader versions."""
    tasks_path, manifest_path = _paths(path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual = hashlib.sha256(tasks_path.read_bytes()).hexdigest()
    if actual != manifest.get("tasks_sha256"):
        raise ValueError("Dataset SHA-256 mismatch; frozen task bytes changed")
    if manifest.get("contract_version") not in {
        CONTRACT_VERSION,
        LAYERED_CONTRACT_VERSION,
        DECISION_CONTRACT_VERSION,
    }:
        raise ValueError("Unsupported task contract version")
    if manifest.get("grader_version") != GRADER_VERSION:
        raise ValueError("Unsupported oracle grader version")
    return manifest


def load_tasks(dataset_path: Path, verify: bool = True) -> list[dict[str, Any]]:
    tasks_path, _ = _paths(dataset_path)
    identity = dataset_identity(dataset_path) if verify else None
    tasks = [
        json.loads(line)
        for line in tasks_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not tasks:
        raise ValueError("Dataset contains no tasks")
    ids: set[str] = set()
    family_splits: dict[str, str] = {}
    for task in tasks:
        validate_task(task)
        if task["id"] in ids:
            raise ValueError(f"Duplicate task id: {task['id']}")
        ids.add(task["id"])
        previous = family_splits.setdefault(task["family"], task["split"])
        if previous != task["split"]:
            raise ValueError(f"Family leaks across splits: {task['family']}")
    if identity:
        if identity.get("contract_version") in {
            LAYERED_CONTRACT_VERSION,
            DECISION_CONTRACT_VERSION,
        }:
            if any(
                not {"evaluation_level", "execution_mode", "checkpoints"} <= task.keys()
                for task in tasks
            ):
                raise ValueError(
                    "Layered tasks require explicit level, mode and checkpoints"
                )
            if identity.get("level_counts") != dict(
                Counter(t["evaluation_level"] for t in tasks)
            ):
                raise ValueError("Manifest level counts mismatch")
            if identity.get("family_count") != len(family_splits):
                raise ValueError("Manifest family count mismatch")
        if identity.get("case_count") != len(tasks):
            raise ValueError("Manifest case count mismatch")
        if identity.get("category_counts") != dict(
            Counter(t["category"] for t in tasks)
        ):
            raise ValueError("Manifest category counts mismatch")
        if identity.get("split_counts") != dict(Counter(t["split"] for t in tasks)):
            raise ValueError("Manifest split counts mismatch")
    return tasks


def select_tasks(
    tasks: list[dict[str, Any]], limit: int | None = None, split: str | None = None
) -> list[dict[str, Any]]:
    """Stable round-robin sampling across categories, then across task families."""
    if split not in (None, "dev", "holdout"):
        raise ValueError("Unknown split")
    if limit is not None and (isinstance(limit, bool) or limit < 1):
        raise ValueError("limit must be positive")
    grouped: dict[str, dict[str, deque]] = defaultdict(lambda: defaultdict(deque))
    for task in sorted(tasks, key=lambda item: item["id"]):
        if split is None or task["split"] == split:
            grouped[task["category"]][task["family"]].append(task)
    category_queues: dict[str, deque] = {}
    for category, families in grouped.items():
        queue: deque = deque()
        while any(families.values()):
            for family in sorted(families):
                if families[family]:
                    queue.append(families[family].popleft())
        category_queues[category] = queue
    result: list[dict[str, Any]] = []
    while any(category_queues.values()):
        for category in CATEGORIES:
            queue = category_queues.get(category)
            if queue:
                result.append(queue.popleft())
                if limit is not None and len(result) >= limit:
                    return result
    return result


def execution_task(task: dict[str, Any]) -> dict[str, Any]:
    """The only permitted input to an untrusted Agent runtime; no oracle metadata."""
    validate_task(task)
    return copy.deepcopy(
        {
            "id": task["id"],
            "prompt": task["prompt"],
            "followups": task["followups"],
            "fixtures": task["fixtures"],
            "allowed_tools": task.get("allowed_tools", list(TOOLS)),
            "max_steps": task["max_steps"],
            **(
                {"module_calls": task["module_calls"]}
                if task.get("execution_mode") == "module"
                else {}
            ),
            **(
                {"decision_context": task["decision_context"]}
                if task.get("execution_mode") == "decision"
                else {}
            ),
        }
    )
