"""Reproduce the public synthetic benchmark; refuse to overwrite frozen versions.

Run with the evaluator environment. Reference operations are private scorer inputs;
expected results below are calculated separately while constructing each fixture.
"""
# Prompt and fixture literals intentionally retain their exact published text.
# ruff: noqa: E501

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

TOOLS = ["read_file", "write_file", "edit_file", "list_dir"]
TASKS = []
SAFETY = "只在当前工作区内操作；未指定的文件保持不变，不要创建额外说明文件。"
JSON_STYLE = "JSON 使用两空格缩进、保留现有键顺序，文件末尾一个换行。"


def j(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def add(
    category,
    family,
    index,
    count,
    family_index,
    family_count,
    prompt,
    fixtures,
    expected=None,
    answer=None,
    reference=None,
    followups=None,
    tools=None,
    absent=None,
):
    task_id = f"file-tools-v1/{category}/{family}/{index:03d}"
    fixtures = {**fixtures, "protected/keep.txt": f"Do not modify: {task_id}\n"}
    TASKS.append(
        {
            "id": task_id,
            "family": f"{category}/{family}",
            "category": category,
            "split": "holdout" if family_index >= family_count * 4 // 5 else "dev",
            "prompt": prompt + "\n" + SAFETY,
            "followups": followups or [],
            "fixtures": fixtures,
            "oracle": {
                "expected_files": expected or {},
                "absent_files": absent or [],
                "response_contains": [answer] if answer else [],
                "preserve_other_files": True,
                "forbid_extra_files": True,
            },
            "required_tools": tools or ["read_file"],
            "allowed_tools": TOOLS,
            "max_steps": 16 if category in ("multi_file", "multi_turn") else 12,
            "reference": reference,
            "description": f"Synthetic {family}; independently variable fixture {index}/{count}.",
        }
    )


def read_tasks():
    families = [
        "env_lookup",
        "json_nested",
        "csv_total",
        "csv_argmax",
        "csv_lookup",
        "nonempty_count",
        "word_count",
        "unique_count",
        "first_line",
        "last_line",
        "regex_ticket",
        "recursive_inventory",
        "find_marker",
        "common_values",
        "missing_values",
        "active_count",
        "markdown_heading",
        "quoted_value",
        "json_array_index",
        "nth_line",
    ]
    for fi, family in enumerate(families):
        for n in range(1, 4):
            path, fixtures, tools = "input.txt", {}, ["read_file"]
            q = {"op": "answer", "prefix": "RESULT=", "path": path}
            if family == "env_lookup":
                fixtures[path] = f"HOST=service-{n}\nPORT={8100 + n}\nMODE=prod\n"
                prompt, answer = "读取 input.txt，报告 PORT 的值。", str(8100 + n)
                q.update(kind="line_value", key="PORT")
            elif family == "json_nested":
                fixtures[path] = j({"team": {"owner": f"owner-{n}", "size": n + 2}})
                prompt, answer = "读取 input.txt 中 JSON 的 team.owner。", f"owner-{n}"
                q.update(kind="json_value", keys=["team", "owner"])
            elif family == "csv_total":
                fixtures[path] = f"item,units\nA,{n + 2}\nB,{n * 3}\nC,{n + 7}\n"
                prompt, answer = "计算 input.txt CSV 的 units 列总和。", str(5 * n + 9)
                q.update(kind="csv_sum", column="units")
            elif family == "csv_argmax":
                fixtures[path] = f"name,score\na,{20 + n}\nb,{70 + n}\nc,{40 + n}\n"
                prompt, answer = "读取 input.txt，找出 score 最大的 name。", "b"
                q.update(kind="csv_max", column="score", **{"return": "name"})
            elif family == "csv_lookup":
                fixtures[path] = (
                    f"id,owner\nT-{n},Ada\nT-{n + 10},Lin\nT-{n + 20},Sam\n"
                )
                prompt, answer = f"读取 input.txt，找出 id=T-{n + 10} 的 owner。", "Lin"
                q.update(
                    kind="csv_match",
                    column="id",
                    value=f"T-{n + 10}",
                    **{"return": "owner"},
                )
            elif family == "nonempty_count":
                fixtures[path] = (
                    "\n".join([f"event-{i}" for i in range(n + 2)]) + "\n\n\n"
                )
                prompt, answer = "统计 input.txt 非空行数，忽略空行。", str(n + 2)
                q.update(kind="line_count")
            elif family == "word_count":
                fixtures[path] = " ".join(f"token{i}" for i in range(n + 4)) + "\n"
                prompt, answer = "按空白分隔统计 input.txt 的单词数。", str(n + 4)
                q.update(kind="word_count")
            elif family == "unique_count":
                fixtures[path] = (
                    "\n".join([f"tag-{i}" for i in range(n + 2)] + ["tag-0", "tag-1"])
                    + "\n"
                )
                prompt, answer = "统计 input.txt 去重后的整行数量。", str(n + 2)
                q.update(kind="unique_count")
            elif family in ("first_line", "last_line", "nth_line"):
                lines = [f"record-{n}-{i}" for i in range(1, n + 5)]
                fixtures[path] = "\n".join(lines) + "\n"
                idx = (
                    0
                    if family == "first_line"
                    else (-1 if family == "last_line" else n)
                )
                label = (
                    "第一行"
                    if idx == 0
                    else ("最后一行" if idx == -1 else f"第 {n + 1} 行")
                )
                prompt, answer = f"读取 input.txt 的{label}。", lines[idx]
                q.update(kind="line", index=idx)
            elif family == "regex_ticket":
                fixtures[path] = (
                    f"opened 2026-11-01\nprimary ticket: BUG-{300 + n}\nstatus: ready\n"
                )
                prompt, answer = (
                    "提取 input.txt 的 BUG-数字 格式工单号。",
                    f"BUG-{300 + n}",
                )
                q.update(kind="regex", pattern=r"(BUG-\d+)")
            elif family == "recursive_inventory":
                fixtures = {
                    f"logs/day-{i}/event.txt": f"event {i}\n" for i in range(n + 2)
                }
                prompt, answer = (
                    "递归列出 logs/ 下的文件，报告文件总数（只统计普通文件）。",
                    str(n + 2),
                )
                q = {
                    "op": "answer",
                    "kind": "file_count",
                    "path": "",
                    "directory_prefix": "logs/",
                    "prefix": "RESULT=",
                }
                tools = ["list_dir"]
            elif family == "find_marker":
                fixtures = {
                    f"notes/{name}.txt": f"ordinary-{n}\n"
                    for name in ("alpha", "beta", "gamma")
                }
                fixtures["notes/beta.txt"] = f"release TOKEN-{n}\n"
                prompt, answer = (
                    f"在 notes/ 中找到包含 TOKEN-{n} 的文件，报告相对路径。",
                    "notes/beta.txt",
                )
                q.update(kind="find_path", needle=f"TOKEN-{n}")
                tools = ["list_dir", "read_file"]
            elif family in ("common_values", "missing_values"):
                fixtures = {
                    path: f"a{n}\nb{n}\nc{n}\n",
                    "other.txt": f"b{n}\nc{n}\nd{n}\n",
                }
                common = family == "common_values"
                prompt = (
                    "比较 input.txt 和 other.txt，报告"
                    + ("两边共有" if common else "只在 input.txt 中出现")
                    + "的行，排序后用英文逗号连接。"
                )
                answer = f"b{n},c{n}" if common else f"a{n}"
                q.update(
                    kind="intersection" if common else "difference", other="other.txt"
                )
            elif family == "active_count":
                fixtures[path] = (
                    "id,status\n"
                    + "".join(f"{i},active\n" for i in range(n + 1))
                    + "99,closed\n"
                )
                prompt, answer = (
                    "统计 input.txt CSV 中 status=active 的记录数。",
                    str(n + 1),
                )
                q.update(kind="csv_count", column="status", value="active")
            elif family == "markdown_heading":
                fixtures[path] = f"# Release {n}\n\n## Scope\nfeature-{n}\n"
                prompt, answer = (
                    "读取 input.txt 的一级 Markdown 标题，去掉 # 和空格。",
                    f"Release {n}",
                )
                q.update(kind="regex", pattern=r"^# (.+)")
            elif family == "quoted_value":
                fixtures[path] = f'priority=low\nowner="user-{n}"\nstatus=ready\n'
                prompt, answer = "读取 input.txt 中 owner 的双引号内文本。", f"user-{n}"
                q.update(kind="regex", pattern=r'owner="([^"]+)"')
            else:
                fixtures[path] = j({"versions": [f"v{n}.0", f"v{n}.1", f"v{n}.2"]})
                prompt, answer = (
                    "读取 input.txt JSON 的 versions 数组第二个元素。",
                    f"v{n}.1",
                )
                q.update(kind="json_value", keys=["versions", 1])
            add(
                "read_search",
                family,
                n,
                3,
                fi,
                20,
                prompt + "最后一条回复包含 RESULT=<答案>，不写文件。",
                fixtures,
                answer="RESULT=" + answer,
                reference=[q],
                tools=tools,
            )


def create_tasks():
    families = [
        "replace_setting",
        "append_release",
        "prepend_header",
        "sort_records",
        "dedupe_tags",
        "filter_comments",
        "uppercase_codes",
        "lowercase_keys",
        "number_steps",
        "prefix_tasks",
        "json_set_status",
        "json_remove_legacy",
        "json_rename_key",
        "json_increment_quota",
        "csv_filter_active",
        "csv_sort_price",
        "csv_project_names",
        "csv_update_region",
        "template_render",
        "extract_section",
    ]
    for fi, family in enumerate(families):
        for n in range(1, 6):
            path, dest, fixtures = "source.txt", "result.txt", {}
            op = {"path": path, "dest": dest}
            if family == "replace_setting":
                fixtures[path] = f"mode=debug\nport={8200 + n}\n"
                prompt = "读取 source.txt，仅将 mode=debug 改成 mode=release，保存为 result.txt。"
                expected = f"mode=release\nport={8200 + n}\n"
                op.update(op="replace", old="mode=debug", new="mode=release")
            elif family == "append_release":
                fixtures[path] = f"# Version {n}\n"
                prompt = f"把 source.txt 复制为 result.txt，再追加一行 released={n}。"
                expected = fixtures[path] + f"released={n}\n"
                op.update(op="append", text=f"released={n}\n")
            elif family == "prepend_header":
                fixtures[path] = f"row-{n}\nrow-{n + 1}\n"
                prompt = (
                    "读取 source.txt，在最前面加入一行 GENERATED，写入 result.txt。"
                )
                expected = "GENERATED\n" + fixtures[path]
                op.update(op="prepend", text="GENERATED\n")
            elif family in (
                "sort_records",
                "dedupe_tags",
                "filter_comments",
                "uppercase_codes",
                "lowercase_keys",
                "number_steps",
                "prefix_tasks",
            ):
                if family == "sort_records":
                    lines, result, action = (
                        [f"c{n}", f"a{n}", f"b{n}"],
                        [f"a{n}", f"b{n}", f"c{n}"],
                        "sort",
                    )
                    instruction = "按字典序升序排序所有行"
                elif family == "dedupe_tags":
                    lines, result, action = (
                        [f"b{n}", f"a{n}", f"b{n}"],
                        [f"b{n}", f"a{n}"],
                        "dedupe",
                    )
                    instruction = "按第一次出现顺序删除重复行"
                elif family == "filter_comments":
                    lines, result, action = (
                        ["# comment", f"active={n}", "# end"],
                        [f"active={n}"],
                        "filter",
                    )
                    instruction = "删除以 # 开头的注释行"
                    op["prefix"] = "#"
                elif family == "uppercase_codes":
                    lines, result, action = (
                        [f"ab{n}", f"cd{n}"],
                        [f"AB{n}", f"CD{n}"],
                        "upper",
                    )
                    instruction = "把所有英文字母转为大写"
                elif family == "lowercase_keys":
                    lines, result, action = (
                        [f"HOST{n}", f"PORT{n}"],
                        [f"host{n}", f"port{n}"],
                        "lower",
                    )
                    instruction = "把所有英文字母转为小写"
                elif family == "number_steps":
                    lines, result, action = (
                        [f"start-{n}", f"finish-{n}"],
                        [f"1. start-{n}", f"2. finish-{n}"],
                        "number",
                    )
                    instruction = "给每行添加从 1 开始的编号，格式为 1. 原文本"
                else:
                    lines, result, action = (
                        [f"task-{n}", f"task-{n + 1}"],
                        [f"- [ ] task-{n}", f"- [ ] task-{n + 1}"],
                        "prefix",
                    )
                    instruction = "给每行添加前缀 '- [ ] '"
                    op["prefix"] = "- [ ] "
                fixtures[path], expected = (
                    "\n".join(lines) + "\n",
                    "\n".join(result) + "\n",
                )
                prompt = (
                    f"读取 source.txt，{instruction}，写入 result.txt，末尾一个换行。"
                )
                op.update(op="lines", action=action)
            elif family.startswith("json_"):
                value = {
                    "name": f"service-{n}",
                    "status": "draft",
                    "legacy": True,
                    "quota": 10 + n,
                }
                fixtures[path] = j(value)
                result = dict(value)
                if family == "json_set_status":
                    result["status"] = "ready"
                    instruction = "将 status 改为 ready"
                    op.update(action="set", key="status", value="ready")
                elif family == "json_remove_legacy":
                    del result["legacy"]
                    instruction = "删除 legacy 键"
                    op.update(action="remove", key="legacy")
                elif family == "json_rename_key":
                    result["service"] = result.pop("name")
                    instruction = "将 name 键改名为 service，将新键放到最后"
                    op.update(action="rename", key="name", new_key="service")
                else:
                    result["quota"] += n + 2
                    instruction = f"将 quota 加 {n + 2}"
                    op.update(action="increment", key="quota", amount=n + 2)
                expected = j(result)
                prompt = (
                    f"读取 source.txt JSON，{instruction}，保存为 result.txt。"
                    + JSON_STYLE
                )
                op["op"] = "json"
            elif family.startswith("csv_"):
                fixtures[path] = (
                    f"name,status,price,region\nB{n},inactive,{30 + n},west\nA{n},active,{10 + n},east\nC{n},active,{20 + n},west\n"
                )
                op["op"] = "csv"
                if family == "csv_filter_active":
                    expected = f"name,status,price,region\nA{n},active,{10 + n},east\nC{n},active,{20 + n},west\n"
                    instruction = "仅保留 status=active 的行，保持原顺序及全部列"
                    op.update(action="filter", column="status", value="active")
                elif family == "csv_sort_price":
                    expected = f"name,status,price,region\nA{n},active,{10 + n},east\nC{n},active,{20 + n},west\nB{n},inactive,{30 + n},west\n"
                    instruction = "按 price 数值升序排序，保留全部列"
                    op.update(action="sort", column="price")
                elif family == "csv_project_names":
                    expected = f"name,region\nB{n},west\nA{n},east\nC{n},west\n"
                    instruction = "仅保留 name,region 两列，保持行顺序"
                    op.update(action="project", columns=["name", "region"])
                else:
                    expected = f"name,status,price,region\nB{n},inactive,{30 + n},north\nA{n},active,{10 + n},east\nC{n},active,{20 + n},north\n"
                    instruction = "将 region 列的 west 替换为 north，其他单元格不变"
                    op.update(action="update", column="region", old="west", new="north")
                prompt = f"读取 source.txt CSV，{instruction}，保存为 result.txt，保留表头，使用 LF 换行。"
            elif family == "template_render":
                fixtures = {
                    path: "Hello {{name}}!\nTeam: {{team}}\n",
                    "values.json": j({"name": f"User{n}", "team": f"Team{n + 1}"}),
                }
                expected = f"Hello User{n}!\nTeam: Team{n + 1}\n"
                prompt = "用 values.json 的对应值替换 source.txt 的 {{name}}、{{team}} 占位符，写入 result.txt。"
                op.update(op="template", values="values.json")
            else:
                fixtures[path] = f"HEADER\nBEGIN\nitem-{n}\nitem-{n + 2}\nEND\nFOOTER\n"
                expected = f"item-{n}\nitem-{n + 2}\n"
                prompt = "提取 source.txt 的 BEGIN 与 END 标记之间的行（不含标记），写入 result.txt。"
                op.update(op="lines", action="section", start="BEGIN", end="END")
            add(
                "create_edit",
                family,
                n,
                5,
                fi,
                20,
                prompt,
                fixtures,
                expected={dest: expected},
                reference=[op],
                tools=["read_file", "write_file"],
            )


def multi_tasks():
    families = [
        "copy_config",
        "merge_fragments",
        "split_payload",
        "join_csv",
        "aggregate_csv",
        "update_crossref",
        "sync_versions",
        "redact_multi",
        "build_index",
        "json_merge",
        "json_extract",
        "distribute_template",
        "archive_report",
        "filter_then_count",
        "route_records",
        "reconcile_inventory",
        "group_csv",
        "manifest_from_json",
        "release_notes",
        "compare_snapshots",
    ]
    for fi, family in enumerate(families):
        for n in range(1, 5):
            fixtures, expected, ops = {}, {}, []
            if family == "copy_config":
                fixtures = {
                    "config/base.ini": f"port={8300 + n}\nmode=dev\n",
                    "config/secret.txt": f"keep-{n}\n",
                }
                expected = {
                    "deploy/app.ini": f"port={8300 + n}\nmode=prod\n",
                    "deploy/backup.ini": fixtures["config/base.ini"],
                }
                prompt = "将 config/base.ini 原样复制到 deploy/backup.ini，再复制到 deploy/app.ini 并仅把 mode=dev 改为 mode=prod。"
                ops = [
                    {
                        "op": "copy",
                        "path": "config/base.ini",
                        "dest": "deploy/backup.ini",
                    },
                    {
                        "op": "replace",
                        "path": "config/base.ini",
                        "dest": "deploy/app.ini",
                        "old": "mode=dev",
                        "new": "mode=prod",
                    },
                ]
            elif family == "merge_fragments":
                fixtures = {
                    "parts/01.txt": f"HEADER-{n}\n",
                    "parts/02.txt": f"BODY-{n}\n",
                    "parts/03.txt": f"END-{n}\n",
                }
                expected = {"release.txt": f"HEADER-{n}\nBODY-{n}\nEND-{n}\n"}
                prompt = "按文件名顺序拼接 parts/01.txt、02.txt、03.txt 的完整内容到 release.txt，不添加空行。"
                ops = [{"op": "join", "paths": list(fixtures), "dest": "release.txt"}]
            elif family == "split_payload":
                fixtures = {
                    "input.txt": f"A:item-{n}\nB:other-{n}\nA:item-{n + 1}\nB:other-{n + 1}\n"
                }
                expected = {
                    "a.txt": f"A:item-{n}\nA:item-{n + 1}\n",
                    "b.txt": f"B:other-{n}\nB:other-{n + 1}\n",
                }
                prompt = "读取 input.txt，将 A: 开头的整行写入 a.txt、B: 开头的整行写入 b.txt，各保持原顺序与前缀。"
                ops = [
                    {
                        "op": "lines",
                        "action": "keep",
                        "path": "input.txt",
                        "dest": f"{letter.lower()}.txt",
                        "prefix": letter + ":",
                    }
                    for letter in ("A", "B")
                ]
            elif family == "join_csv":
                fixtures = {
                    "first.csv": f"id,units\na,{n}\nb,{n + 1}\n",
                    "second.csv": f"id,units\nc,{n + 2}\n",
                }
                expected = {"combined.csv": f"id,units\na,{n}\nb,{n + 1}\nc,{n + 2}\n"}
                prompt = "将 first.csv 与 second.csv 的数据行按此顺序合并到 combined.csv，仅保留一个表头。"
                ops = [
                    {
                        "op": "csv",
                        "action": "concat",
                        "path": "first.csv",
                        "other": "second.csv",
                        "dest": "combined.csv",
                    }
                ]
            elif family == "aggregate_csv":
                fixtures = {
                    "a.csv": f"id,units\na,{n + 2}\nb,{n + 3}\n",
                    "b.csv": f"id,units\nc,{n + 4}\n",
                }
                expected = {
                    "all.csv": f"id,units\na,{n + 2}\nb,{n + 3}\nc,{n + 4}\n",
                    "total.txt": f"units={3 * n + 9}\n",
                }
                prompt = "将 a.csv、b.csv 合并为 all.csv（一个表头），再将 units 列总和写入 total.txt，格式 units=数值 加换行。"
                ops = [
                    {
                        "op": "csv",
                        "action": "concat",
                        "path": "a.csv",
                        "other": "b.csv",
                        "dest": "all.csv",
                    },
                    {
                        "op": "report",
                        "kind": "csv_sum",
                        "path": "all.csv",
                        "column": "units",
                        "dest": "total.txt",
                        "prefix": "units=",
                    },
                ]
            elif family in ("update_crossref", "sync_versions", "redact_multi"):
                if family == "update_crossref":
                    old, new = f"OLD-{n}", f"NEW-{n}"
                    fixtures = {
                        "index.txt": f"active={old}\n",
                        "record.txt": f"id={old}\nowner=team-{n}\n",
                    }
                elif family == "sync_versions":
                    old, new = f"{n}.0.0", f"{n}.1.0"
                    fixtures = {
                        "VERSION": old + "\n",
                        "package.txt": f"name=app\nversion={old}\n",
                        "docs.txt": f"Release {old}\n",
                    }
                else:
                    old, new = f"user{n}@example.test", "[REDACTED]"
                    fixtures = {
                        "contact.txt": f"email={old}\n",
                        "notes.txt": f"send to {old}\nkeep note-{n}\n",
                    }
                expected = {
                    p: content.replace(old, new) for p, content in fixtures.items()
                }
                prompt = f"读取并更新 {', '.join(fixtures)}，将所有字面量 {old} 替换为 {new}，其他内容不变。"
                ops = [
                    {"op": "replace", "path": p, "old": old, "new": new}
                    for p in fixtures
                ]
            elif family == "build_index":
                fixtures = {
                    "chapters/a.txt": f"Alpha-{n}\n",
                    "chapters/b.txt": f"Beta-{n}\n",
                }
                expected = {"index.txt": f"1. Alpha-{n}\n2. Beta-{n}\n"}
                prompt = "拼接 chapters/a.txt 和 chapters/b.txt 内容，再给每行添加从 1 开始的 '1. ' 编号，保存为 index.txt，不保留临时文件。"
                ops = [
                    {"op": "join", "paths": list(fixtures), "dest": "index.txt"},
                    {"op": "lines", "action": "number", "path": "index.txt"},
                ]
            elif family == "json_merge":
                fixtures = {
                    "base.json": j(
                        {"host": f"svc-{n}", "port": 8000 + n, "mode": "dev"}
                    ),
                    "override.json": j({"mode": "prod", "region": f"r{n}"}),
                }
                expected = {
                    "merged.json": j(
                        {
                            "host": f"svc-{n}",
                            "port": 8000 + n,
                            "mode": "prod",
                            "region": f"r{n}",
                        }
                    )
                }
                prompt = (
                    "合并 base.json 与 override.json 到 merged.json，重名键以后者为准，新键追加到末尾。"
                    + JSON_STYLE
                )
                ops = [
                    {
                        "op": "json",
                        "action": "merge",
                        "path": "base.json",
                        "other": "override.json",
                        "dest": "merged.json",
                    }
                ]
            elif family == "json_extract":
                fixtures = {
                    "bundle.json": j(
                        {
                            "app": {"name": f"svc-{n}", "replicas": n},
                            "db": {"port": 5400 + n},
                        }
                    )
                }
                expected = {
                    "app.json": j({"name": f"svc-{n}", "replicas": n}),
                    "db.json": j({"port": 5400 + n}),
                }
                prompt = (
                    "将 bundle.json 中 app 和 db 对应的对象分别保存为 app.json 和 db.json。"
                    + JSON_STYLE
                )
                ops = [
                    {
                        "op": "json",
                        "action": "extract",
                        "path": "bundle.json",
                        "key": key,
                        "dest": key + ".json",
                    }
                    for key in ("app", "db")
                ]
            elif family == "distribute_template":
                fixtures = {
                    "template.txt": "Hello {{name}}\n",
                    "east.json": j({"name": f"East-{n}"}),
                    "west.json": j({"name": f"West-{n}"}),
                }
                expected = {
                    "out/east.txt": f"Hello East-{n}\n",
                    "out/west.txt": f"Hello West-{n}\n",
                }
                prompt = "分别使用 east.json、west.json 填充 template.txt 的占位符，写入 out/east.txt 与 out/west.txt。"
                ops = [
                    {
                        "op": "template",
                        "path": "template.txt",
                        "values": f"{side}.json",
                        "dest": f"out/{side}.txt",
                    }
                    for side in ("east", "west")
                ]
            elif family == "archive_report":
                fixtures = {"report.txt": f"status=draft\nrevision={n}\n"}
                expected = {
                    "archive/report.txt": fixtures["report.txt"],
                    "report.txt": f"status=final\nrevision={n}\n",
                }
                prompt = "先把 report.txt 的当前内容备份到 archive/report.txt，再把原文件中的 status=draft 改成 status=final。"
                ops = [
                    {"op": "copy", "path": "report.txt", "dest": "archive/report.txt"},
                    {
                        "op": "replace",
                        "path": "report.txt",
                        "old": "status=draft",
                        "new": "status=final",
                    },
                ]
            elif family == "filter_then_count":
                fixtures = {
                    "events.txt": "# head\n"
                    + "".join(f"event-{i}\n" for i in range(n + 2))
                    + "# tail\n"
                }
                expected = {
                    "clean.txt": "".join(f"event-{i}\n" for i in range(n + 2)),
                    "count.txt": f"count={n + 2}\n",
                }
                prompt = "过滤 events.txt 中以 # 开头的行，保存为 clean.txt；统计保留的非空行数，写入 count.txt，格式 count=数量 加换行。"
                ops = [
                    {
                        "op": "lines",
                        "action": "filter",
                        "path": "events.txt",
                        "prefix": "#",
                        "dest": "clean.txt",
                    },
                    {
                        "op": "report",
                        "kind": "line_count",
                        "path": "clean.txt",
                        "prefix": "count=",
                        "dest": "count.txt",
                    },
                ]
            elif family == "route_records":
                fixtures = {"tickets.csv": f"id,team\nA{n},core\nB{n},web\nC{n},core\n"}
                expected = {
                    "core.csv": f"id,team\nA{n},core\nC{n},core\n",
                    "web.csv": f"id,team\nB{n},web\n",
                }
                prompt = "按 tickets.csv 的 team 值将数据分到 core.csv 与 web.csv，各保留表头和原行顺序。"
                ops = [
                    {
                        "op": "csv",
                        "action": "filter",
                        "path": "tickets.csv",
                        "column": "team",
                        "value": team,
                        "dest": team + ".csv",
                    }
                    for team in ("core", "web")
                ]
            elif family == "reconcile_inventory":
                fixtures = {
                    "expected.txt": f"A{n}\nB{n}\nC{n}\n",
                    "actual.txt": f"B{n}\nD{n}\n",
                }
                expected = {"missing.txt": f"A{n},C{n}\n", "unexpected.txt": f"D{n}\n"}
                prompt = "比较 expected.txt 与 actual.txt 的行集合；期望但缺少的项写到 missing.txt，实际多余的项写到 unexpected.txt。每份结果按字典序排序、逗号连接，末尾换行。"
                ops = [
                    {
                        "op": "report",
                        "kind": "difference",
                        "path": a,
                        "other": b,
                        "dest": dest,
                    }
                    for a, b, dest in (
                        ("expected.txt", "actual.txt", "missing.txt"),
                        ("actual.txt", "expected.txt", "unexpected.txt"),
                    )
                ]
            elif family == "group_csv":
                fixtures = {
                    "orders.csv": f"id,region,units\na,east,{n}\nb,west,{n + 2}\nc,east,{n + 1}\n"
                }
                expected = {
                    "east.csv": f"id,region,units\na,east,{n}\nc,east,{n + 1}\n",
                    "east_total.txt": f"total={2 * n + 1}\n",
                }
                prompt = "从 orders.csv 筛选 region=east 的行保存到 east.csv，再将该组 units 合计写入 east_total.txt，格式 total=数值 加换行。"
                ops = [
                    {
                        "op": "csv",
                        "action": "filter",
                        "path": "orders.csv",
                        "column": "region",
                        "value": "east",
                        "dest": "east.csv",
                    },
                    {
                        "op": "report",
                        "kind": "csv_sum",
                        "path": "east.csv",
                        "column": "units",
                        "prefix": "total=",
                        "dest": "east_total.txt",
                    },
                ]
            elif family == "manifest_from_json":
                fixtures = {
                    "meta.json": j({"name": f"app-{n}", "version": f"v{n}"}),
                    "manifest.template": "name={{name}}\nversion={{version}}\n",
                }
                expected = {
                    "dist/manifest.txt": f"name=app-{n}\nversion=v{n}\n",
                    "dist/meta.json": fixtures["meta.json"],
                }
                prompt = "用 meta.json 填充 manifest.template，写入 dist/manifest.txt；同时原样复制 meta.json 为 dist/meta.json。"
                ops = [
                    {
                        "op": "template",
                        "path": "manifest.template",
                        "values": "meta.json",
                        "dest": "dist/manifest.txt",
                    },
                    {"op": "copy", "path": "meta.json", "dest": "dist/meta.json"},
                ]
            elif family == "release_notes":
                fixtures = {
                    "title.txt": f"# Release {n}\n",
                    "changes.txt": f"fix-{n}\nfeature-{n}\n",
                }
                expected = {"release.md": f"# Release {n}\n- fix-{n}\n- feature-{n}\n"}
                prompt = "生成 release.md：第一行来自 title.txt，后面接 changes.txt 的各行并添加 '- ' 前缀，不插入空行或保留中间文件。"
                ops = [
                    {
                        "op": "lines",
                        "action": "prefix",
                        "path": "changes.txt",
                        "prefix": "- ",
                        "dest": "release.md",
                    },
                    {
                        "op": "join",
                        "paths": ["title.txt", "release.md"],
                        "dest": "release.md",
                    },
                ]
            else:
                fixtures = {"old.txt": f"a{n}\nb{n}\n", "new.txt": f"b{n}\nc{n}\n"}
                expected = {"added.txt": f"c{n}\n", "removed.txt": f"a{n}\n"}
                prompt = "比较 old.txt 与 new.txt 行集合，新增项写到 added.txt，删除项写到 removed.txt；结果排序后用逗号连接、末尾一个换行。"
                ops = [
                    {
                        "op": "report",
                        "kind": "difference",
                        "path": a,
                        "other": b,
                        "dest": dest,
                    }
                    for a, b, dest in (
                        ("new.txt", "old.txt", "added.txt"),
                        ("old.txt", "new.txt", "removed.txt"),
                    )
                ]
            tools = ["read_file", "write_file"]
            if family in ("update_crossref", "sync_versions", "redact_multi"):
                tools = ["read_file", "edit_file"]
            add(
                "multi_file",
                family,
                n,
                4,
                fi,
                20,
                prompt,
                fixtures,
                expected=expected,
                reference=ops,
                tools=tools,
            )


def multi_turn_tasks():
    families = [
        "change_mode",
        "revise_budget",
        "append_then_correct",
        "json_change_request",
        "filter_then_expand",
        "template_revision",
        "rename_reference",
        "revise_sort",
        "change_region",
        "revise_numbering",
    ]
    for fi, family in enumerate(families):
        for n in range(1, 5):
            fixtures, expected, ops = {}, {}, []
            if family == "change_mode":
                fixtures = {"base.ini": f"mode=dev\nport={8500 + n}\n"}
                prompt = "将 base.ini 复制到 work.ini，并把 mode 改为 staging。"
                followup = "需求变更：刚才生成的配置改用 prod 模式，端口不要改，其他文件保持不变。"
                expected = {"work.ini": f"mode=prod\nport={8500 + n}\n"}
                ops = [
                    {
                        "op": "replace",
                        "path": "base.ini",
                        "dest": "work.ini",
                        "old": "mode=dev",
                        "new": "mode=staging",
                    },
                    {
                        "op": "replace",
                        "path": "work.ini",
                        "old": "mode=staging",
                        "new": "mode=prod",
                    },
                ]
            elif family == "revise_budget":
                fixtures = {"base.json": j({"name": f"job-{n}", "budget": n * 10})}
                prompt = (
                    f"复制 base.json 为 plan.json，将 budget 增加 {n}。" + JSON_STYLE
                )
                followup = f"刚才预算追加得不够：在当前结果上再增加 {n + 3}，保留其他字段和格式。"
                expected = {"plan.json": j({"name": f"job-{n}", "budget": 12 * n + 3})}
                ops = [
                    {
                        "op": "json",
                        "action": "increment",
                        "path": "base.json",
                        "dest": "plan.json",
                        "key": "budget",
                        "amount": n,
                    },
                    {
                        "op": "json",
                        "action": "increment",
                        "path": "plan.json",
                        "key": "budget",
                        "amount": n + 3,
                    },
                ]
            elif family == "append_then_correct":
                fixtures = {"base.txt": f"item-{n}\n"}
                prompt = f"将 base.txt 复制为 list.txt，追加一行 item-{n + 1}。"
                followup = (
                    f"刚才追加的那一行编号写错了，请改为 item-{n + 5}，原有第一行保留。"
                )
                expected = {"list.txt": f"item-{n}\nitem-{n + 5}\n"}
                ops = [
                    {
                        "op": "append",
                        "path": "base.txt",
                        "dest": "list.txt",
                        "text": f"item-{n + 1}\n",
                    },
                    {
                        "op": "replace",
                        "path": "list.txt",
                        "old": f"item-{n + 1}",
                        "new": f"item-{n + 5}",
                    },
                ]
            elif family == "json_change_request":
                fixtures = {"base.json": j({"owner": f"team-{n}", "status": "draft"})}
                prompt = (
                    "复制 base.json 为 release.json，把 status 改为 review。"
                    + JSON_STYLE
                )
                followup = (
                    "审核通过，把刚才那份产物的 status 改为 approved，owner 不变。"
                )
                expected = {
                    "release.json": j({"owner": f"team-{n}", "status": "approved"})
                }
                ops = [
                    {
                        "op": "json",
                        "action": "set",
                        "path": "base.json",
                        "dest": "release.json",
                        "key": "status",
                        "value": "review",
                    },
                    {
                        "op": "json",
                        "action": "set",
                        "path": "release.json",
                        "key": "status",
                        "value": "approved",
                    },
                ]
            elif family == "filter_then_expand":
                fixtures = {
                    "tickets.csv": f"id,status\nA{n},open\nB{n},closed\nC{n},open\n"
                }
                prompt = "从 tickets.csv 筛选 status=open 的记录写到 selected.csv，保留表头与行顺序。"
                followup = "范围调整：刚才的输出现在应包含全部状态，按源文件的原始顺序，不要重复表头。"
                expected = {"selected.csv": fixtures["tickets.csv"]}
                ops = [
                    {
                        "op": "csv",
                        "action": "filter",
                        "path": "tickets.csv",
                        "dest": "selected.csv",
                        "column": "status",
                        "value": "open",
                    },
                    {"op": "copy", "path": "tickets.csv", "dest": "selected.csv"},
                ]
            elif family == "template_revision":
                fixtures = {
                    "template.txt": "Hello {{name}}\n",
                    "values.json": j({"name": f"User-{n}"}),
                }
                prompt = "用 values.json 填充 template.txt，结果写入 greeting.txt。"
                followup = "刚才输出中的 Hello 改为 Welcome，名字与原始文件保持不变。"
                expected = {"greeting.txt": f"Welcome User-{n}\n"}
                ops = [
                    {
                        "op": "template",
                        "path": "template.txt",
                        "values": "values.json",
                        "dest": "greeting.txt",
                    },
                    {
                        "op": "replace",
                        "path": "greeting.txt",
                        "old": "Hello",
                        "new": "Welcome",
                    },
                ]
            elif family == "rename_reference":
                fixtures = {"source.txt": f"owner=team-{n}\nstate=active\n"}
                prompt = "复制 source.txt 为 result.txt，把 owner= 的字段名改为 maintainer=，值不变。"
                followup = f"再把刚才改名字段的值改为 group-{n}；state 和源文件不变。"
                expected = {"result.txt": f"maintainer=group-{n}\nstate=active\n"}
                ops = [
                    {
                        "op": "replace",
                        "path": "source.txt",
                        "dest": "result.txt",
                        "old": "owner=",
                        "new": "maintainer=",
                    },
                    {
                        "op": "replace",
                        "path": "result.txt",
                        "old": f"team-{n}",
                        "new": f"group-{n}",
                    },
                ]
            elif family == "revise_sort":
                fixtures = {"source.txt": f"c{n}\na{n}\nb{n}\na{n}\n"}
                prompt = (
                    "把 source.txt 的行按字典序排序，结果写到 sorted.txt，保留重复行。"
                )
                followup = "刚才结果中的重复行也需要去掉，保持排序，源文件不变。"
                expected = {"sorted.txt": f"a{n}\nb{n}\nc{n}\n"}
                ops = [
                    {
                        "op": "lines",
                        "action": "sort",
                        "path": "source.txt",
                        "dest": "sorted.txt",
                    },
                    {"op": "lines", "action": "dedupe", "path": "sorted.txt"},
                ]
            elif family == "change_region":
                fixtures = {"source.csv": f"id,region\nA{n},east\nB{n},west\n"}
                prompt = "复制 source.csv 到 output.csv，将 region 的 east 改为 north。"
                followup = "刚才那份输出里 west 也改为 south，其他单元格和源文件不变。"
                expected = {"output.csv": f"id,region\nA{n},north\nB{n},south\n"}
                ops = [
                    {
                        "op": "csv",
                        "action": "update",
                        "path": "source.csv",
                        "dest": "output.csv",
                        "column": "region",
                        "old": "east",
                        "new": "north",
                    },
                    {
                        "op": "csv",
                        "action": "update",
                        "path": "output.csv",
                        "column": "region",
                        "old": "west",
                        "new": "south",
                    },
                ]
            else:
                fixtures = {"steps.txt": f"prepare-{n}\nfinish-{n}\n"}
                prompt = (
                    "给 steps.txt 的两行添加 1. 、2. 编号，结果写入 checklist.txt。"
                )
                followup = (
                    "刚才的清单改用 '- [ ] ' 复选框前缀替代数字编号，原始步骤文本不变。"
                )
                expected = {"checklist.txt": f"- [ ] prepare-{n}\n- [ ] finish-{n}\n"}
                ops = [
                    {
                        "op": "lines",
                        "action": "number",
                        "path": "steps.txt",
                        "dest": "checklist.txt",
                    },
                    {
                        "op": "lines",
                        "action": "prefix",
                        "path": "steps.txt",
                        "dest": "checklist.txt",
                        "prefix": "- [ ] ",
                    },
                ]
            add(
                "multi_turn",
                family,
                n,
                4,
                fi,
                10,
                prompt,
                fixtures,
                expected=expected,
                reference=ops,
                followups=[followup],
                tools=["read_file", "write_file"],
            )


def error_tasks():
    families = [
        "absent_input",
        "missing_nested",
        "missing_json_key",
        "invalid_json",
        "missing_csv_column",
        "empty_source",
        "conflicting_sources",
        "duplicate_identifier",
        "absent_template",
        "absent_second_source",
    ]
    for fi, family in enumerate(families):
        for n in range(1, 3):
            fixtures = {"readme.txt": f"workspace-{n}\n"}
            q = {"op": "answer"}
            absent = []
            if family in (
                "absent_input",
                "missing_nested",
                "absent_template",
                "absent_second_source",
            ):
                path = {
                    "absent_input": f"input-{n}.txt",
                    "missing_nested": f"missing/day-{n}/data.txt",
                    "absent_template": f"templates/release-{n}.txt",
                    "absent_second_source": f"part-{n + 1}.txt",
                }[family]
                if family == "absent_second_source":
                    fixtures[f"part-{n}.txt"] = "first part\n"
                    prompt = f"需要合并 part-{n}.txt 与 {path}，先检查两者。若任一缺失，不创建合并文件。"
                elif family == "absent_template":
                    fixtures["values.json"] = j({"name": f"User-{n}"})
                    prompt = f"需要用 values.json 填充 {path}，先确认模板存在。若缺失，不创建任何输出或模板。"
                else:
                    prompt = f"尝试读取 {path}；若不存在，不要创建该文件或编造内容。"
                answer = "MISSING:" + path
                prompt += f"若缺失，最终回复包含 {answer}。"
                q.update(kind="missing", path=path)
                absent = [path, "output.txt"]
            elif family == "missing_json_key":
                fixtures["config.json"] = j({"name": f"app-{n}", "port": 8000 + n})
                answer = "MISSING_KEY:token"
                prompt = f"读取 config.json 的 token 字段；若没有，回复包含 {answer}，不要增加字段。"
                q.update(kind="missing_key", path="config.json", key="token")
            elif family == "invalid_json":
                fixtures["config.json"] = f'{{"name": "app-{n}", "enabled": }}\n'
                answer = "INVALID_JSON"
                prompt = "检查 config.json 是否为有效 JSON。若无效，回复包含 INVALID_JSON；不要自动修复或写文件。"
                q.update(kind="invalid_json", path="config.json")
            elif family == "missing_csv_column":
                fixtures["orders.csv"] = f"id,price\nA{n},{20 + n}\n"
                answer = "MISSING_COLUMN:quantity"
                prompt = f"读取 orders.csv；计算 quantity 总和前先确认该列存在。若不存在，回复包含 {answer}，不要猜测总和或修改文件。"
                q.update(kind="missing_column", path="orders.csv", column="quantity")
            elif family == "empty_source":
                fixtures[f"empty-{n}.txt"] = ""
                answer = "EMPTY_FILE"
                prompt = f"读取 empty-{n}.txt；如果为空，回复包含 EMPTY_FILE，不要生成摘要或写文件。"
                q.update(kind="empty", path=f"empty-{n}.txt")
            elif family == "conflicting_sources":
                fixtures = {
                    "a.json": j({"revision": n}),
                    "b.json": j({"revision": n + 1}),
                }
                answer = "CONFLICT"
                prompt = "比较 a.json、b.json 的 revision；如不一致，回复包含 CONFLICT，不要合并或覆盖任何文件。"
                q.update(kind="conflict", paths=["a.json", "b.json"], key="revision")
            else:
                fixtures["items.csv"] = f"id,value\nA{n},first\nA{n},second\n"
                answer = "DUPLICATE_ID"
                prompt = "检查 items.csv 的 id 是否唯一。如果存在重复，回复包含 DUPLICATE_ID，不要静默去重或改写文件。"
                q.update(kind="duplicate", path="items.csv", column="id")
            add(
                "missing_error",
                family,
                n,
                2,
                fi,
                10,
                prompt,
                fixtures,
                answer=answer,
                reference=[q],
                absent=absent,
                tools=["read_file"],
            )


def main():
    read_tasks()
    create_tasks()
    multi_tasks()
    multi_turn_tasks()
    error_tasks()
    tasks = sorted(TASKS, key=lambda task: task["id"])
    data = (
        "\n".join(
            json.dumps(task, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            for task in tasks
        )
        + "\n"
    ).encode("utf-8")
    manifest = {
        "dataset_id": "file-tools-v1",
        "version": "1.0.0",
        "contract_version": "file-tools-task-v1",
        "grader_version": "file-tools-oracle-v1",
        "tasks_file": "tasks.jsonl",
        "tasks_sha256": hashlib.sha256(data).hexdigest(),
        "case_count": len(tasks),
        "category_counts": dict(sorted(Counter(t["category"] for t in tasks).items())),
        "split_counts": dict(sorted(Counter(t["split"] for t in tasks).items())),
        "family_count": len({t["family"] for t in tasks}),
        "split_strategy": "family-disjoint: last fifth of families in each category held out",
        "provenance": {
            "source": "AI-assisted authored synthetic file fixtures and task recipes",
            "human_reviewed": False,
            "reference_execution": "deterministic fixture transformations; not measured Agent results",
        },
        "limitations": [
            "Local UTF-8 file tools only; no shell, browser, DB, messaging, or production side effects.",
            "Variations within each family are parameterized fixtures, not independent task families.",
            "Final-state oracle checks exact formatting when explicitly requested; no private chain-of-thought is collected.",
            "Multi-turn tasks verify final state and turn count; do not establish arbitrary user-simulator ability.",
        ],
    }
    root = Path(__file__).resolve().parent
    outputs = {
        "tasks.jsonl": data,
        "manifest.json": (
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        ).encode(),
    }
    for name, payload in outputs.items():
        path = root / name
        if path.exists() and path.read_bytes() != payload:
            raise SystemExit(
                f"Refusing to overwrite frozen {path}; use a new dataset version"
            )
        if not path.exists():
            path.write_bytes(payload)
    print(json.dumps({"cases": len(tasks), "sha256": manifest["tasks_sha256"]}))


if __name__ == "__main__":
    main()
