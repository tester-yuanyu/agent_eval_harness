"""Independent semantic checks over saved outputs of fixed nanobot module calls.

This reads frozen fixture data and public call arguments. It never invokes a
nanobot implementation or treats substring presence as complete read evidence.
The pinned corpus contains small UTF-8 inputs and complete directory listings;
unsupported truncation or mutation-before-read requires a new explicit contract.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

MODULE_ORACLE_VERSION = "module-output-semantics-v1"
_NUMBERED = re.compile(r"([1-9][0-9]*)\| (.*)")
_MORE = re.compile(
    r"\(Showing lines ([0-9]+)-([0-9]+) of ([0-9]+)\. "
    r"Use offset=([0-9]+) to continue\.\)"
)
_END = re.compile(r"\(End of file [—-] ([0-9]+) lines total\)")


def _check(name: str, passed: bool, reason: str) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "reason": reason}


def _read_semantics(
    fixtures: dict[str, str],
    arguments: dict[str, Any],
    output: Any,
) -> tuple[bool, str]:
    path = arguments.get("path")
    if not isinstance(path, str) or path not in fixtures:
        return False, "Successful read must have a frozen fixture source"
    offset, limit = arguments.get("offset", 1), arguments.get("limit", 2000)
    if type(offset) is not int or type(limit) is not int or offset < 1 or limit < 1:
        return False, "Successful read requires valid positive offset and limit"
    if not isinstance(output, str) or "\n\n" not in output:
        return False, "Read output lacks numbered rows and explicit range metadata"
    body, footer = output.rstrip("\n").rsplit("\n\n", 1)
    rows = []
    for line in body.split("\n"):
        match = _NUMBERED.fullmatch(line)
        if match is None:
            return False, "Read output contains malformed or unnumbered content"
        rows.append((int(match.group(1)), match.group(2)))
    source_lines = fixtures[path].splitlines()
    end = min(len(source_lines), offset + limit - 1)
    expected = [(number, source_lines[number - 1]) for number in range(offset, end + 1)]
    if not expected or rows != expected:
        return (
            False,
            "Numbered read rows must exactly match the requested fixture range; "
            "extra, missing or changed lines fail",
        )
    more, finished = _MORE.fullmatch(footer), _END.fullmatch(footer)
    if end < len(source_lines):
        correct = bool(more) and tuple(map(int, more.groups())) == (
            offset,
            end,
            len(source_lines),
            end + 1,
        )
    else:
        correct = bool(finished) and int(finished.group(1)) == len(source_lines)
    return (
        correct,
        "Read range metadata must identify the selected indices "
        "and fixture line count",
    )


def _list_semantics(
    fixtures: dict[str, str],
    arguments: dict[str, Any],
    output: Any,
) -> tuple[bool, str]:
    path = arguments.get("path")
    if not isinstance(path, str) or not isinstance(output, str):
        return False, "Directory listing requires a relative path and text evidence"
    prefix = "" if path in ("", ".") else path.rstrip("/") + "/"
    expected: set[str] = set()
    recursive = arguments.get("recursive", False)
    if not isinstance(recursive, bool):
        return False, "Directory listing recursive flag must be boolean"
    for fixture in fixtures:
        if not fixture.startswith(prefix):
            continue
        relative = fixture[len(prefix) :]
        parts = relative.split("/")
        if recursive:
            expected.add(relative)
            expected.update(
                "/".join(parts[:index]) + "/" for index in range(1, len(parts))
            )
        else:
            expected.add(parts[0] + ("/" if len(parts) > 1 else ""))
    limit = arguments.get("max_entries", 200)
    if type(limit) is not int or limit < 1 or not expected or len(expected) > limit:
        return (
            False,
            "Pinned module listing oracle requires a complete nonempty "
            "fixture directory listing",
        )
    actual = []
    for entry in output.splitlines():
        if entry.startswith("📁 "):
            entry = entry[2:] + "/"
        elif entry.startswith("📄 "):
            entry = entry[2:]
        actual.append(entry)
    return (
        Counter(actual) == Counter(expected),
        "Listing must contain exactly the fixture files and directories, "
        "without missing, duplicate or fabricated entries",
    )


def evaluate_module_calls(
    task: dict[str, Any],
    observation: dict[str, Any],
) -> list[dict[str, Any]]:
    """Check actual call binding and bounded read/list semantics; no live execution."""
    if task.get("execution_mode") != "module":
        return []
    calls = task.get("module_calls", [])
    events_value = observation.get("events", [])
    events = (
        [
            event
            for event in events_value
            if isinstance(event, dict) and event.get("type") == "tool"
        ]
        if isinstance(events_value, list)
        else []
    )
    checks = [
        _check(
            "module_call_count",
            len(events) == len(calls) and bool(calls),
            "Every public module call must have exactly one recorded tool event",
        )
    ]
    expectations = {
        entry["call"]: entry
        for entry in task.get("oracle", {}).get("module_results", [])
    }
    fixtures = task.get("fixtures", {})
    mutated: set[str] = set()
    for index, call in enumerate(calls, 1):
        event = events[index - 1] if index <= len(events) else None
        bound = (
            event is not None
            and event.get("name") == call["name"]
            and event.get("input") == call["arguments"]
        )
        checks.append(
            _check(
                f"module_invocation:{index}",
                bound,
                "Recorded tool name and input must match the fixed public module call",
            )
        )
        arguments, name = call["arguments"], call["name"]
        expected_success = expectations.get(index, {}).get("error") is False
        if expected_success and name in ("read_file", "list_dir"):
            if not bound or event.get("is_error", event.get("tool_error")) is not False:
                passed, reason = (
                    False,
                    "Semantic read/list checks require bound successful tool evidence",
                )
            elif name == "read_file" and arguments.get("path") in mutated:
                passed, reason = (
                    False,
                    "Read after mutation requires an explicit "
                    "intermediate source contract",
                )
            elif name == "read_file":
                passed, reason = _read_semantics(
                    fixtures, arguments, event.get("output")
                )
            else:
                passed, reason = _list_semantics(
                    fixtures, arguments, event.get("output")
                )
            checks.append(_check(f"module_output_semantics:{index}", passed, reason))
        if name in ("write_file", "edit_file") and isinstance(
            arguments.get("path"), str
        ):
            mutated.add(arguments["path"])
    return checks
