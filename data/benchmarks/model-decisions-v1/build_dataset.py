"""Author isolated next-action cases; refuse to overwrite differing frozen bytes."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

TOOLS = ["read_file", "write_file", "edit_file", "list_dir"]


def all_tasks():
    tasks = []
    families = [
        "read_named",
        "read_range",
        "list_recursive",
        "write_exact",
        "edit_unique",
        "edit_occurrence",
        "abstain_ambiguous",
        "abstain_noop",
    ]
    for index, family in enumerate(families):
        for variant in range(1, 4):
            path = f"docs/item-{variant}.txt"
            content = f"alpha-{variant}\nstatus=draft\ngamma-{variant}\ndelta-{variant}\nepsilon-{variant}\n"
            fixtures = {path: content, "protected/keep.txt": "unchanged\n"}
            context = f"用户已确认相对路径 {path} 存在，并且是 UTF-8 文本文件。此轮只选择下一步操作，不执行文件操作。"
            expected, tool = {}, None
            category = "read_search"
            if family == "read_named":
                prompt = f"读取文件 {path} 的文本内容；不要改写或列出目录。"
                tool, expected = "read_file", {"path": path}
            elif family == "read_range":
                prompt = f"只读取 {path} 的第 {variant + 1} 至 {variant + 2} 行（从 1 开始编号），不要读取其他行。"
                tool, expected = (
                    "read_file",
                    {"path": path, "offset": variant + 1, "limit": 2},
                )
            elif family == "list_recursive":
                directory = f"catalog-{variant}"
                fixtures[f"{directory}/section/note.txt"] = "listed\n"
                context = f"用户已确认目录 {directory} 存在。"
                prompt = f"列出 {directory} 目录及其所有子目录中的文件名称，只需要目录清单，不读取文件内容。"
                tool, expected = "list_dir", {"path": directory, "recursive": True}
            elif family == "write_exact":
                destination = f"output-{variant}.txt"
                text = f"RELEASE={variant}\nREADY=true\n"
                context = f"用户确认 {destination} 不存在。要求使用整文件写入工具创建文件，不使用文本替换工具模拟创建。"
                prompt = f"创建 {destination}，完整内容严格为这个 JSON 字符串解码后的文本：{json.dumps(text)}。保留末尾换行。"
                tool, expected, category = (
                    "write_file",
                    {"path": destination, "content": text},
                    "create_edit",
                )
            elif family == "edit_unique":
                context += "\n用户提供的当前文件全文如下，无需再次读取：\n" + content
                prompt = f"在 {path} 中仅将 status=draft 替换为 status=release-{variant}，使用局部文本替换，不重写整个文件。"
                tool, expected, category = (
                    "edit_file",
                    {
                        "path": path,
                        "old_text": "status=draft",
                        "new_text": f"status=release-{variant}",
                    },
                    "create_edit",
                )
            elif family == "edit_occurrence":
                original = f"item-{variant}\nitem-{variant}\nitem-{variant}\n"
                fixtures[path] = original
                context += "\n用户提供的当前文件全文如下，无需再次读取：\n" + original
                prompt = f"使用局部文本替换，把 {path} 中第二次出现的 item-{variant} 改为 chosen-{variant}。必须使用 occurrence=2 精确选择，并使用 expected_replacements=1 防止多改；其余两处保持不变。"
                tool, expected, category = (
                    "edit_file",
                    {
                        "path": path,
                        "old_text": f"item-{variant}",
                        "new_text": f"chosen-{variant}",
                        "occurrence": 2,
                        "expected_replacements": 1,
                    },
                    "create_edit",
                )
            elif family == "abstain_ambiguous":
                context = "用户要求：缺少要修改的目标路径或具体新内容时，先询问，不得猜测目标，不得读取、列目录或修改文件。"
                prompt = [
                    "帮我把那个文件改一下。",
                    "把之前说的内容替换掉。",
                    "更新我刚才提到的文件。",
                ][variant - 1]
                category = "missing_error"
            else:
                context = "用户明确要求本轮不要访问文件系统。"
                prompt = f"只用普通文本回复 READY-{variant}，不要读取、列出、创建或修改任何文件。"
                category = "missing_error"
            decision = {
                "acceptable_tools": [tool] if tool else [],
                "arguments": expected,
                "allow_no_tool": tool is None,
                "max_calls": 1 if tool else 0,
            }
            tasks.append(
                {
                    "id": f"model-decisions-v1/{family}/{variant:03}",
                    "family": f"model_decision/{family}",
                    "category": category,
                    "evaluation_level": "module",
                    "execution_mode": "decision",
                    "split": "holdout" if index >= 6 else "dev",
                    "prompt": prompt,
                    "decision_context": context,
                    "followups": [],
                    "fixtures": fixtures,
                    "checkpoints": [],
                    "allowed_tools": TOOLS,
                    "required_tools": [tool] if tool else [],
                    "max_steps": 1,
                    "description": "One model next-action decision from public context and real tool schemas; no tool execution.",
                    "oracle": {
                        "expected_files": {},
                        "absent_files": [],
                        "unchanged_files": [],
                        "response_contains": [],
                        "preserve_other_files": True,
                        "forbid_extra_files": True,
                        "decision": decision,
                    },
                    "reference": [
                        {
                            "op": "isolated_model_decision",
                            "description": "No deterministic reference is an observed model decision.",
                        }
                    ],
                }
            )
    return sorted(tasks, key=lambda task: task["id"])


def build_dataset(destination=None):
    destination = Path(destination or Path(__file__).parent)
    tasks = all_tasks()
    payload = "".join(
        json.dumps(task, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
        for task in tasks
    ).encode()
    manifest = {
        "dataset_id": "model-decisions-v1",
        "version": "1.0.0",
        "contract_version": "model-decisions-task-v1",
        "grader_version": "file-tools-oracle-v1",
        "tasks_file": "tasks.jsonl",
        "tasks_sha256": hashlib.sha256(payload).hexdigest(),
        "case_count": len(tasks),
        "level_counts": dict(Counter(task["evaluation_level"] for task in tasks)),
        "category_counts": dict(Counter(task["category"] for task in tasks)),
        "split_counts": dict(Counter(task["split"] for task in tasks)),
        "family_count": 8,
        "split_strategy": "Family-disjoint: six operation families dev; two abstention families holdout.",
        "provenance": {
            "source": "AI-assisted authored isolated decision contexts",
            "human_reviewed": False,
            "runtime": "Real nanobot OpenAICompatProvider with real file-tool schemas; one provider.chat invocation.",
        },
        "limitations": [
            "24 instances are three parameter variants in eight families.",
            "Public context is user-supplied static input, not a prior observed tool execution.",
            "Explicit method constraints disambiguate write vs edit and occurrence vs line-hint alternatives.",
            "This measures local tool selection/arguments/abstention, not full planning, memory, or session management.",
            "Tool calls returned by the model are saved but never executed.",
            "Provider transport may internally retry; one decision is not a guarantee of one HTTP attempt.",
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
