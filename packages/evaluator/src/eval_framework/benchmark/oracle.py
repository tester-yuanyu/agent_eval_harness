"""Deterministic final-state oracle and an independent declarative reference runner.

The reference runner is a solvability check, never a measured Agent or a model input.
It transforms fixture contents and does not inspect the task's expected answers.
"""

from __future__ import annotations

import copy
import csv
import io
import json
import re
from typing import Any

from .tasks import GRADER_VERSION


def evaluate_oracle(
    task: dict[str, Any], observation: dict[str, Any]
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    violations: list[str] = []

    def check(name: str, passed: bool, reason: str, policy: bool = False) -> None:
        checks.append({"name": name, "passed": bool(passed), "reason": reason})
        if policy and not passed:
            violations.append(reason)

    check(
        "execution_completed",
        observation.get("status") == "completed",
        f"Execution status: {observation.get('status', 'missing')}",
    )
    check(
        "initial_state",
        observation.get("before_files") == task["fixtures"],
        "Initial workspace must exactly match the frozen fixtures",
    )
    files = observation.get("final_files")
    valid_files = isinstance(files, dict) and all(
        isinstance(k, str) and isinstance(v, str) for k, v in files.items()
    )
    check(
        "final_state_evidence",
        valid_files,
        "Final UTF-8 file-state evidence is required",
    )
    if not valid_files:
        return {
            "success": False,
            "checks": checks,
            "violations": violations,
            "grader_version": GRADER_VERSION,
        }
    oracle = task["oracle"]
    expected = oracle.get("expected_files", {})
    absent = set(oracle.get("absent_files", []))
    for path, content in expected.items():
        check(
            f"expected_file:{path}",
            files.get(path) == content,
            f"{path} must match its exact expected UTF-8 content",
        )
    for path in sorted(absent):
        check(f"absent_file:{path}", path not in files, f"{path} must not exist", True)
    unchanged = set(oracle.get("unchanged_files", []))
    if oracle.get("preserve_other_files", True):
        unchanged.update(set(task["fixtures"]) - set(expected) - absent)
    for path in sorted(unchanged):
        check(
            f"preserved_file:{path}",
            path in task["fixtures"] and files.get(path) == task["fixtures"][path],
            f"Unrequested change or deletion of {path}",
            True,
        )
    if oracle.get("forbid_extra_files", True):
        extras = sorted(set(files) - set(task["fixtures"]) - set(expected))
        check("no_extra_files", not extras, f"Unexpected files: {extras}", True)
    turns = observation.get("turns")
    turns_valid = isinstance(turns, list) and all(isinstance(t, dict) for t in turns)
    check(
        "all_turns_executed",
        turns_valid and len(turns) == 1 + len(task["followups"]),
        "Exactly the frozen prompt and follow-up turns must be executed",
    )
    output = str(turns[-1].get("output", "")) if turns_valid and turns else ""
    for token in oracle.get("response_contains", []):
        # Numeric and identifier prefixes must not count as a correct answer:
        # RESULT=2 is different from RESULT=20 or RESULT=2,3.
        token_pattern = (
            r"(?<![A-Za-z0-9_])" + re.escape(token) + r"(?![A-Za-z0-9_./,:=\-])"
        )
        check(
            f"response_contains:{token}",
            re.search(token_pattern, output) is not None,
            f"Final response must contain the requested literal token {token!r}",
        )
    return {
        "success": all(check["passed"] for check in checks),
        "checks": checks,
        "violations": violations,
        "grader_version": GRADER_VERSION,
    }


def _csv_read(content: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(content)))


def _csv_write(rows: list[dict[str, str]], fields: list[str]) -> str:
    handle = io.StringIO()
    writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return handle.getvalue()


def _query(files: dict[str, str], step: dict[str, Any]) -> str:
    kind = step["kind"]
    source = files.get(step.get("path", ""), "")
    lines = source.splitlines()
    if kind == "line_value":
        return next(
            line.split(step.get("sep", "="), 1)[1]
            for line in lines
            if line.startswith(step["key"] + step.get("sep", "="))
        )
    if kind == "json_value":
        value = json.loads(source)
        for key in step["keys"]:
            value = value[key]
        return str(value)
    if kind == "csv_sum":
        return str(sum(int(row[step["column"]]) for row in _csv_read(source)))
    if kind == "csv_max":
        return max(_csv_read(source), key=lambda r: int(r[step["column"]]))[
            step["return"]
        ]
    if kind == "csv_match":
        return next(
            row[step["return"]]
            for row in _csv_read(source)
            if row[step["column"]] == step["value"]
        )
    if kind == "csv_count":
        return str(
            sum(row[step["column"]] == step["value"] for row in _csv_read(source))
        )
    if kind == "line_count":
        return str(sum(bool(line.strip()) for line in lines))
    if kind == "word_count":
        return str(len(source.split()))
    if kind == "unique_count":
        return str(len(set(lines)))
    if kind == "line":
        return lines[step["index"]]
    if kind == "regex":
        return re.search(step["pattern"], source).group(1)
    if kind == "file_count":
        return str(sum(path.startswith(step["directory_prefix"]) for path in files))
    if kind == "find_path":
        return next(path for path in sorted(files) if step["needle"] in files[path])
    if kind == "intersection":
        return ",".join(sorted(set(lines) & set(files[step["other"]].splitlines())))
    if kind == "difference":
        return ",".join(sorted(set(lines) - set(files[step["other"]].splitlines())))
    if kind == "missing":
        return "MISSING:" + step["path"] if step["path"] not in files else "PRESENT"
    if kind == "invalid_json":
        try:
            json.loads(source)
        except json.JSONDecodeError:
            return "INVALID_JSON"
        return "VALID_JSON"
    if kind == "missing_key":
        return (
            "MISSING_KEY:" + step["key"]
            if step["key"] not in json.loads(source)
            else "PRESENT"
        )
    if kind == "missing_column":
        headers = next(csv.reader(io.StringIO(source)))
        return (
            "MISSING_COLUMN:" + step["column"]
            if step["column"] not in headers
            else "PRESENT"
        )
    if kind == "empty":
        return "EMPTY_FILE" if not source else "NOT_EMPTY"
    if kind == "conflict":
        values = [json.loads(files[path])[step["key"]] for path in step["paths"]]
        return "CONFLICT" if len(set(values)) > 1 else "CONSISTENT"
    if kind == "duplicate":
        values = [row[step["column"]] for row in _csv_read(source)]
        return "DUPLICATE_ID" if len(values) != len(set(values)) else "UNIQUE"
    raise ValueError(f"Unknown reference query: {kind}")


def _apply(files: dict[str, str], step: dict[str, Any]) -> str | None:
    op = step["op"]
    path = step.get("path")
    dest = step.get("dest", path)
    if op == "answer":
        return step.get("prefix", "") + _query(files, step)
    if op == "replace":
        source = files[path]
        if step["old"] not in source:
            raise ValueError("Reference replacement text is absent")
        files[dest] = source.replace(step["old"], step["new"])
    elif op == "append":
        files[dest] = files[path] + step["text"]
    elif op == "prepend":
        files[dest] = step["text"] + files[path]
    elif op == "copy":
        files[dest] = files[path]
    elif op == "join":
        files[dest] = step.get("separator", "").join(files[p] for p in step["paths"])
    elif op == "lines":
        lines = files[path].splitlines()
        action = step["action"]
        if action == "sort":
            lines = sorted(lines)
        elif action == "dedupe":
            lines = list(dict.fromkeys(lines))
        elif action == "filter":
            lines = [line for line in lines if not line.startswith(step["prefix"])]
        elif action == "keep":
            lines = [line for line in lines if line.startswith(step["prefix"])]
        elif action == "upper":
            lines = [line.upper() for line in lines]
        elif action == "lower":
            lines = [line.lower() for line in lines]
        elif action == "number":
            lines = [f"{i}. {line}" for i, line in enumerate(lines, 1)]
        elif action == "prefix":
            lines = [step["prefix"] + line for line in lines]
        elif action == "section":
            lines = lines[lines.index(step["start"]) + 1 : lines.index(step["end"])]
        else:
            raise ValueError(f"Unknown reference line transformation: {action}")
        files[dest] = "\n".join(lines) + "\n"
    elif op == "json":
        value = json.loads(files[path])
        action = step["action"]
        if action == "set":
            value[step["key"]] = step["value"]
        elif action == "remove":
            del value[step["key"]]
        elif action == "rename":
            value[step["new_key"]] = value.pop(step["key"])
        elif action == "increment":
            value[step["key"]] += step["amount"]
        elif action == "extract":
            value = value[step["key"]]
        elif action == "merge":
            value.update(json.loads(files[step["other"]]))
        else:
            raise ValueError(f"Unknown reference JSON transformation: {action}")
        files[dest] = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    elif op == "csv":
        source = files[path]
        fields = next(csv.reader(io.StringIO(source)))
        rows = _csv_read(source)
        action = step["action"]
        if action == "filter":
            rows = [row for row in rows if row[step["column"]] == step["value"]]
        elif action == "sort":
            rows.sort(key=lambda row: int(row[step["column"]]))
        elif action == "project":
            fields = step["columns"]
            rows = [{key: row[key] for key in fields} for row in rows]
        elif action == "update":
            for row in rows:
                if row[step["column"]] == step["old"]:
                    row[step["column"]] = step["new"]
        elif action == "concat":
            rows.extend(_csv_read(files[step["other"]]))
        else:
            raise ValueError(f"Unknown reference CSV transformation: {action}")
        files[dest] = _csv_write(rows, fields)
    elif op == "template":
        source = files[path]
        values = json.loads(files[step["values"]])
        for key, value in values.items():
            source = source.replace("{{" + key + "}}", str(value))
        files[dest] = source
    elif op == "report":
        files[dest] = step.get("prefix", "") + _query(files, step) + "\n"
    else:
        raise ValueError(f"Unknown reference operation: {op}")
    return None


def reference_observation(task: dict[str, Any]) -> dict[str, Any]:
    """Run trusted transformation recipes without reading ``task['oracle']``."""
    before = copy.deepcopy(task["fixtures"])
    files = copy.deepcopy(before)
    answers = []
    for step in task["reference"]:
        answer = _apply(files, step)
        if answer is not None:
            answers.append(answer)
    inputs = [task["prompt"], *task["followups"]]
    turns = [
        {"input": value, "output": "Reference transformation completed."}
        for value in inputs
    ]
    turns[-1]["output"] = "\n".join(answers) or "Reference transformation completed."
    return {
        "status": "completed",
        "before_files": before,
        "final_files": files,
        "turns": turns,
        "events": [],
        "usage": {},
        "errors": [],
        "execution_kind": "deterministic_reference_not_agent",
    }
