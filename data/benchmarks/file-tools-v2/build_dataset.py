"""Reproducible v2 authoring; refuses to replace differing frozen bytes.

Module expected results are authored contracts, never copied from test execution.
The fixture variants are not advertised as independent task families.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOLS = ["read_file", "write_file", "edit_file", "list_dir"]
POLICY = "\n只在当前工作区内操作；未指定的文件保持不变，不要创建额外说明文件。"


def oracle(expected=None, results=None):
    result = {
        "expected_files": expected or {},
        "absent_files": [],
        "unchanged_files": [],
        "response_contains": [],
        "preserve_other_files": True,
        "forbid_extra_files": True,
    }
    if results is not None:
        result["module_results"] = results
    return result


def point(identifier, kind, **fields):
    return {"id": identifier, "kind": kind, "required": True, **fields}


def module_cases():
    families = [
        "read_text",
        "read_slice",
        "read_missing",
        "write_create",
        "write_overwrite",
        "write_nested",
        "edit_exact",
        "edit_occurrence",
        "edit_replacement_guard",
        "reject_missing_parameter",
        "reject_parameter_type",
        "list_nested",
    ]
    tasks = []
    for family_index, family in enumerate(families):
        for value in range(1, 6):
            source = f"alpha-{value}\nbeta-{value}\ngamma-{value}\n"
            fixtures = {
                "input.txt": source,
                "protected/keep.txt": f"protected-{value}\n",
            }
            expected, calls, checks = {}, [], []

            def call(name, arguments, error=False, contains=()):
                calls.append({"name": name, "arguments": arguments})
                checks.append(
                    {
                        "call": len(calls),
                        "error": error,
                        "output_contains": list(contains),
                    }
                )

            if family == "read_text":
                call(
                    "read_file",
                    {"path": "input.txt"},
                    contains=[f"alpha-{value}", f"gamma-{value}"],
                )
            elif family == "read_slice":
                call(
                    "read_file",
                    {"path": "input.txt", "offset": 2, "limit": 1},
                    contains=[f"beta-{value}"],
                )
            elif family == "read_missing":
                call(
                    "read_file",
                    {"path": "missing.txt"},
                    error=True,
                    contains=["not found"],
                )
            elif family in {"write_create", "write_overwrite", "write_nested"}:
                path = {
                    "write_create": "output.txt",
                    "write_overwrite": "input.txt",
                    "write_nested": f"nested/level-{value}/output.txt",
                }[family]
                content = f"created-{value}\n中文内容-{value}\n"
                call(
                    "write_file",
                    {"path": path, "content": content},
                    contains=["Successfully"],
                )
                expected[path] = content
            elif family == "edit_exact":
                call("read_file", {"path": "input.txt"}, contains=[f"beta-{value}"])
                call(
                    "edit_file",
                    {
                        "path": "input.txt",
                        "old_text": f"beta-{value}",
                        "new_text": f"updated-{value}",
                    },
                    contains=["Successfully edited"],
                )
                expected["input.txt"] = source.replace(
                    f"beta-{value}", f"updated-{value}"
                )
            elif family == "edit_occurrence":
                fixtures["input.txt"] = f"item-{value}\nitem-{value}\n"
                call("read_file", {"path": "input.txt"}, contains=[f"item-{value}"])
                call(
                    "edit_file",
                    {
                        "path": "input.txt",
                        "old_text": f"item-{value}",
                        "new_text": f"changed-{value}",
                        "occurrence": 2,
                        "expected_replacements": 1,
                    },
                    contains=["Successfully edited"],
                )
                expected["input.txt"] = f"item-{value}\nchanged-{value}\n"
            elif family == "edit_replacement_guard":
                call("read_file", {"path": "input.txt"}, contains=[f"alpha-{value}"])
                call(
                    "edit_file",
                    {
                        "path": "input.txt",
                        "old_text": f"alpha-{value}",
                        "new_text": "must-not-write",
                        "expected_replacements": 2,
                    },
                    error=True,
                    contains=["expected 2 replacements"],
                )
            elif family == "reject_missing_parameter":
                call(
                    "write_file",
                    {"path": f"never-{value}.txt"},
                    error=True,
                    contains=["Invalid parameters", "content"],
                )
            elif family == "reject_parameter_type":
                call(
                    "read_file",
                    {"path": "input.txt", "offset": {"invalid": value}},
                    error=True,
                    contains=["Invalid parameters", "offset"],
                )
            elif family == "list_nested":
                fixtures[f"docs/section-{value}/note.txt"] = f"note-{value}\n"
                call(
                    "list_dir",
                    {"path": "docs", "recursive": True},
                    contains=[f"section-{value}/note.txt"],
                )
            category = (
                "missing_error"
                if family
                in {
                    "read_missing",
                    "reject_missing_parameter",
                    "reject_parameter_type",
                    "edit_replacement_guard",
                }
                else (
                    "read_search"
                    if family.startswith("read") or family.startswith("list")
                    else "create_edit"
                )
            )
            tasks.append(
                {
                    "id": f"file-tools-v2/module/{family}/{value:03}",
                    "family": f"module/{family}",
                    "category": category,
                    "evaluation_level": "module",
                    "execution_mode": "module",
                    "split": "holdout" if family_index >= 10 else "dev",
                    "prompt": f"Run the fixed nanobot ToolRegistry boundary inputs for {family}, fixture variant {value}.",
                    "description": "Real deterministic nanobot module boundary; no LLM decision is measured.",
                    "followups": [],
                    "fixtures": fixtures,
                    "module_calls": calls,
                    "checkpoints": [],
                    "oracle": oracle(expected, checks),
                    "allowed_tools": TOOLS,
                    "required_tools": list(dict.fromkeys(c["name"] for c in calls)),
                    "max_steps": 12,
                    "reference": [
                        {
                            "op": "module_boundary",
                            "description": "Validate by real isolated module execution; no reference Agent result.",
                        }
                    ],
                }
            )
    return tasks


def chain_cases():
    families = [
        "read_then_report",
        "two_source_join",
        "discover_and_copy",
        "draft_then_finalize",
        "replace_then_append",
        "copy_then_update",
        "json_stages",
        "csv_stages",
        "recover_missing",
        "resolve_conflict",
        "protect_source",
        "revision_constraints",
    ]
    tasks = []
    for family_index, family in enumerate(families):
        for value in range(1, 6):
            source = f"alpha-{value}\nbeta-{value}\n"
            fixtures = {
                "input.txt": source,
                "protected/keep.txt": f"protected-{value}\n",
            }
            final, followups, checkpoints, reference = {}, [], [], []
            category, required = "multi_file", ["read_file"]
            if family == "read_then_report":
                fixtures["input.txt"] = f"amount={value * 17}\n"
                final = {"report.txt": f"TOTAL={value * 17}\n"}
                prompt = "先用 read_file 读取 input.txt，再用 write_file 创建 report.txt，内容为 TOTAL=<amount值> 并以换行结尾。"
                checkpoints = [
                    point(
                        "read-source",
                        "tool_args",
                        tool="read_file",
                        arguments={"path": "input.txt"},
                    ),
                    point(
                        "read-before-write",
                        "tool_order",
                        before="read_file",
                        after="write_file",
                    ),
                ]
                reference = [
                    {
                        "op": "report",
                        "kind": "line_value",
                        "path": "input.txt",
                        "key": "amount",
                        "prefix": "TOTAL=",
                        "dest": "report.txt",
                    }
                ]
                required.append("write_file")
            elif family == "two_source_join":
                fixtures["second.txt"] = f"gamma-{value}\n"
                final = {"joined.txt": source + fixtures["second.txt"]}
                prompt = "分别读取 input.txt 和 second.txt，然后按此顺序原样连接到 joined.txt，不增加分隔符。"
                checkpoints = [
                    point(
                        "first-source",
                        "tool_args",
                        tool="read_file",
                        arguments={"path": "input.txt"},
                    ),
                    point(
                        "second-source",
                        "tool_args",
                        tool="read_file",
                        arguments={"path": "second.txt"},
                    ),
                ]
                reference = [
                    {
                        "op": "join",
                        "paths": ["input.txt", "second.txt"],
                        "dest": "joined.txt",
                    }
                ]
            elif family == "discover_and_copy":
                fixtures[f"docs/item-{value}.txt"] = f"catalog-{value}\n"
                final = {"chosen.txt": fixtures[f"docs/item-{value}.txt"]}
                prompt = "先用 list_dir 列出 docs 目录，再读取其中唯一的 txt 文件，将其原文复制到 chosen.txt。"
                checkpoints = [
                    point(
                        "discovery",
                        "tool_args",
                        tool="list_dir",
                        arguments={"path": "docs"},
                    ),
                    point(
                        "discover-before-read",
                        "tool_order",
                        before="list_dir",
                        after="read_file",
                    ),
                ]
                reference = [
                    {
                        "op": "copy",
                        "path": f"docs/item-{value}.txt",
                        "dest": "chosen.txt",
                    }
                ]
                required.append("list_dir")
            elif family == "draft_then_finalize":
                draft = f"DRAFT\n{source}"
                final = {"draft.txt": f"FINAL\n{source}"}
                prompt = "读取 input.txt，创建 draft.txt，第一行为 DRAFT，后面原样保留 input.txt。完成后等待我的下一条要求。"
                followups = [
                    "将 draft.txt 第一行 DRAFT 改为 FINAL，其余内容和换行完全保持不变。"
                ]
                checkpoints = [
                    point(
                        "draft-state",
                        "turn_files",
                        turn=1,
                        expected_files={"draft.txt": draft},
                    )
                ]
                reference = [
                    {
                        "op": "prepend",
                        "path": "input.txt",
                        "dest": "draft.txt",
                        "text": "DRAFT\n",
                    },
                    {
                        "op": "replace",
                        "path": "draft.txt",
                        "old": "DRAFT\n",
                        "new": "FINAL\n",
                    },
                ]
            elif family == "replace_then_append":
                first = source.replace("alpha", "renamed")
                final = {"input.txt": first + f"approved-{value}\n"}
                prompt = (
                    "读取 input.txt，将 alpha 替换为 renamed，其余内容与换行保持不变。"
                )
                followups = [
                    f"在 input.txt 最后追加 approved-{value} 一行，保留上轮修改，以换行结尾。"
                ]
                checkpoints = [
                    point(
                        "replacement-state",
                        "turn_files",
                        turn=1,
                        expected_files={"input.txt": first},
                    )
                ]
                reference = [
                    {
                        "op": "replace",
                        "path": "input.txt",
                        "old": "alpha",
                        "new": "renamed",
                    },
                    {
                        "op": "append",
                        "path": "input.txt",
                        "text": f"approved-{value}\n",
                    },
                ]
            elif family == "copy_then_update":
                final = {"copy.txt": source + "done\n"}
                prompt = "读取 input.txt，原样复制为 copy.txt，保留原文件。"
                followups = ["在 copy.txt 末尾追加 done 一行；input.txt 仍然保持原样。"]
                checkpoints = [
                    point(
                        "copy-state",
                        "turn_files",
                        turn=1,
                        expected_files={"copy.txt": source, "input.txt": source},
                    )
                ]
                reference = [
                    {"op": "copy", "path": "input.txt", "dest": "copy.txt"},
                    {"op": "append", "path": "copy.txt", "text": "done\n"},
                ]
            elif family == "json_stages":
                fixtures["input.txt"] = (
                    json.dumps({"count": value, "status": "new"}, indent=2) + "\n"
                )
                first = (
                    json.dumps({"count": value, "status": "review"}, indent=2) + "\n"
                )
                final = {
                    "input.txt": json.dumps(
                        {"count": value + 1, "status": "review"}, indent=2
                    )
                    + "\n"
                }
                prompt = "读取 input.txt 中 JSON，把 status 改为 review；保持 count 不变。JSON 使用两空格缩进，文件末尾一个换行。"
                followups = [
                    "把 count 加 1，保持 status=review；仍用两空格缩进，文件末尾一个换行。"
                ]
                checkpoints = [
                    point(
                        "review-state",
                        "turn_files",
                        turn=1,
                        expected_files={"input.txt": first},
                    )
                ]
                reference = [
                    {
                        "op": "json",
                        "path": "input.txt",
                        "action": "set",
                        "key": "status",
                        "value": "review",
                    },
                    {
                        "op": "json",
                        "path": "input.txt",
                        "action": "increment",
                        "key": "count",
                        "amount": 1,
                    },
                ]
            elif family == "csv_stages":
                fixtures["input.txt"] = f"item,amount\na,{value}\nb,{value * 2}\n"
                first = f"TOTAL={value * 3}\n"
                final = {"summary.txt": first + "STATUS=confirmed\n"}
                prompt = "读取 input.txt 的 CSV，求 amount 总和。写 summary.txt，内容严格为 TOTAL=<总和>，以换行结尾。"
                followups = [
                    "在 summary.txt 末尾追加 STATUS=confirmed 一行，保留之前总数，文件以换行结尾。"
                ]
                checkpoints = [
                    point(
                        "sum-state",
                        "turn_files",
                        turn=1,
                        expected_files={"summary.txt": first},
                    )
                ]
                reference = [
                    {
                        "op": "report",
                        "kind": "csv_sum",
                        "path": "input.txt",
                        "column": "amount",
                        "prefix": "TOTAL=",
                        "dest": "summary.txt",
                    },
                    {
                        "op": "append",
                        "path": "summary.txt",
                        "text": "STATUS=confirmed\n",
                    },
                ]
            elif family == "recover_missing":
                final = {"recovered.txt": source}
                prompt = "先尝试读取 primary.txt；若工具确认文件不存在，读取 input.txt 作为备用内容，原样写入 recovered.txt。不要创建 primary.txt。"
                checkpoints = [
                    point(
                        "attempt-primary",
                        "tool_args",
                        tool="read_file",
                        arguments={"path": "primary.txt"},
                    ),
                    point(
                        "use-fallback",
                        "tool_args",
                        tool="read_file",
                        arguments={"path": "input.txt"},
                    ),
                ]
                reference = [
                    {"op": "copy", "path": "input.txt", "dest": "recovered.txt"}
                ]
                category = "missing_error"
            elif family == "resolve_conflict":
                fixtures["resolved.txt"] = "WAITING\n"
                fixtures.update(
                    {
                        "left.txt": f"value={value}\n",
                        "right.txt": f"value={value + 1}\n",
                    }
                )
                final = {"resolved.txt": fixtures["right.txt"]}
                prompt = "读取 left.txt 和 right.txt。若值不一致，询问我采用哪一个，此轮不要写入任何文件，resolved.txt 保持 WAITING 状态。"
                followups = [
                    "采用 right.txt，原样复制到 resolved.txt，保留两个原文件。"
                ]
                checkpoints = [
                    point(
                        "read-left",
                        "tool_args",
                        tool="read_file",
                        arguments={"path": "left.txt"},
                        turn=1,
                    ),
                    point(
                        "read-right",
                        "tool_args",
                        tool="read_file",
                        arguments={"path": "right.txt"},
                        turn=1,
                    ),
                    point(
                        "conflict-no-change",
                        "turn_files",
                        turn=1,
                        expected_files=copy.deepcopy(fixtures),
                    ),
                ]
                reference = [
                    {"op": "copy", "path": "right.txt", "dest": "resolved.txt"}
                ]
            elif family == "protect_source":
                final = {"upper.txt": source.upper()}
                prompt = "读取 input.txt，把它的 ASCII 字母转为大写后保存为 upper.txt，保留行序和末尾换行；input.txt 不得修改。"
                checkpoints = [
                    point(
                        "source-read",
                        "tool_args",
                        tool="read_file",
                        arguments={"path": "input.txt"},
                    )
                ]
                reference = [
                    {
                        "op": "lines",
                        "path": "input.txt",
                        "dest": "upper.txt",
                        "action": "upper",
                    }
                ]
            elif family == "revision_constraints":
                first = "HEADER\n" + source
                final = {"output.txt": "HEADER\n" + source.replace("beta", "revised")}
                prompt = "读取 input.txt，创建 output.txt：首行为 HEADER，其后为 input.txt 原文。保留末尾换行。"
                followups = [
                    "只把 output.txt 中 beta 改为 revised，必须保留 HEADER、其余内容和换行，保持 input.txt 不变。"
                ]
                checkpoints = [
                    point(
                        "initial-constraints",
                        "turn_files",
                        turn=1,
                        expected_files={"output.txt": first},
                    )
                ]
                reference = [
                    {
                        "op": "prepend",
                        "path": "input.txt",
                        "dest": "output.txt",
                        "text": "HEADER\n",
                    },
                    {
                        "op": "replace",
                        "path": "output.txt",
                        "old": "beta",
                        "new": "revised",
                    },
                ]
            checkpoints.append(
                point(
                    "final-turn-state",
                    "turn_files",
                    turn=1 + len(followups),
                    expected_files=final,
                )
            )
            if followups:
                category = "multi_turn"
            tasks.append(
                {
                    "id": f"file-tools-v2/chain/{family}/{value:03}",
                    "family": f"chain/{family}",
                    "category": category,
                    "evaluation_level": "chain",
                    "execution_mode": "agent",
                    "split": "holdout" if family_index >= 10 else "dev",
                    "prompt": prompt + POLICY,
                    "followups": followups,
                    "fixtures": fixtures,
                    "description": "Fixed critical-chain checkpoints; equivalent edit/write paths allowed unless explicitly requested.",
                    "checkpoints": checkpoints,
                    "oracle": oracle(final),
                    "reference": reference,
                    "allowed_tools": TOOLS,
                    "required_tools": required,
                    "max_steps": 12,
                }
            )
    return tasks


def all_tasks():
    result = []
    source = ROOT / "data/benchmarks/file-tools-v1"
    payload = (source / "tasks.jsonl").read_bytes()
    identity = json.loads((source / "manifest.json").read_text())
    if hashlib.sha256(payload).hexdigest() != identity["tasks_sha256"]:
        raise ValueError("v1 source hash mismatch; refuse to derive an unpinned dataset")
    for line in payload.decode("utf-8").splitlines():
        task = json.loads(line)
        old_id = task["id"]
        task.update(
            id=old_id.replace("file-tools-v1/", "file-tools-v2/e2e/", 1),
            source_task_id=old_id,
            evaluation_level="e2e",
            execution_mode="agent",
            checkpoints=[],
        )
        if task["family"] == "read_search/markdown_heading":
            task["prompt"] = task["prompt"].replace(
                "去掉 # 和空格",
                "只去掉开头的 # 和其后的一个分隔空格，保留标题正文内部的空格",
            )
            task["errata"] = (
                "v1 ambiguous whitespace instruction clarified; expected answer unchanged."
            )
        result.append(task)
    return sorted(result + module_cases() + chain_cases(), key=lambda task: task["id"])


def build_dataset(destination=None):
    destination = Path(destination or Path(__file__).parent)
    tasks = all_tasks()
    payload = "".join(
        json.dumps(task, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
        for task in tasks
    ).encode()
    old_manifest = json.loads(
        (ROOT / "data/benchmarks/file-tools-v1/manifest.json").read_text()
    )
    manifest = {
        "dataset_id": "file-tools-v2",
        "version": "2.0.0",
        "contract_version": "file-tools-task-v2",
        "grader_version": "file-tools-oracle-v1",
        "tasks_file": "tasks.jsonl",
        "tasks_sha256": hashlib.sha256(payload).hexdigest(),
        "case_count": len(tasks),
        "level_counts": dict(Counter(task["evaluation_level"] for task in tasks)),
        "category_counts": dict(Counter(task["category"] for task in tasks)),
        "split_counts": dict(Counter(task["split"] for task in tasks)),
        "family_count": len({task["family"] for task in tasks}),
        "split_strategy": "Family-disjoint; inherited v1 splits; last two of twelve new families per layer held out.",
        "source_v1_sha256": old_manifest["tasks_sha256"],
        "provenance": {
            "source": "AI-assisted authored synthetic fixtures and private checkpoint contracts",
            "human_reviewed": False,
            "module_execution": "Real nanobot ToolRegistry and filesystem implementations, no model provider",
        },
        "limitations": [
            "300 E2E instances reuse 80 v1 families; three Markdown prompts clarified without oracle changes.",
            "60 module and 60 chain instances are five parameter variants in each of 12 families.",
            "Module population measures program boundaries, not LLM tool selection/planning/session management.",
            "Chains use fixed follow-ups; no dynamic user simulator. Filesystem only.",
            "Checkpoint presence is not completed execution; result evidence is produced separately.",
        ],
    }
    files = {
        "tasks.jsonl": payload,
        "manifest.json": (
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        ).encode(),
    }
    destination.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        target = destination / name
        if target.exists() and target.read_bytes() != content:
            raise ValueError(f"immutable dataset differs: {target}")
    for name, content in files.items():
        (destination / name).write_bytes(content)
    return manifest


if __name__ == "__main__":
    print(json.dumps(build_dataset(), ensure_ascii=False, indent=2))
