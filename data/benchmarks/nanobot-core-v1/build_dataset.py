"""人工编写独立预期；构建时不导入/执行 nanobot，拒绝覆盖已冻结异字节。"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

CONTRACT = "nanobot-core-task-v1"


def eq(value, path=None):
    return [(path or ["output"], "equals", value)]


def check(path, kind, value):
    return [(path, kind, value)]


def step(operation, arguments=None, assertions=None):
    return (operation, arguments or {}, eq(None) if assertions is None else assertions)


def history(*entries):
    return "".join(
        json.dumps(
            {
                "cursor": i,
                "timestamp": "2026-01-01 00:00",
                "content": text,
                **({"session_key": key} if key is not None else {}),
            },
            sort_keys=True,
        )
        + "\n"
        for i, (text, key) in enumerate(entries, 1)
    )


def skill(name, text, extra=""):
    return (
        f"---\nname: {name}\ndescription: Controlled fixture for {name}\n"
        f"{extra}---\n{text}\n"
    )


def make_tasks():
    tasks = []

    def add(
        family,
        scenario,
        component,
        description,
        steps,
        *,
        fixtures=None,
        settings=None,
        split="dev",
        files=None,
    ):
        operations, assertions = [], []
        for index, (operation, arguments, checks) in enumerate(steps, 1):
            identifier = f"s{index}"
            operations.append(
                {"id": identifier, "operation": operation, "input": arguments}
            )
            assertions.extend(
                {"event": identifier, "path": path, "kind": kind, "value": value}
                for path, kind, value in checks
            )
        assertions.extend(files or [])
        tasks.append(
            {
                "id": f"core-{family}-{scenario}",
                "contract_version": CONTRACT,
                "family": family,
                "split": split,
                "component": component,
                "description": description,
                "fixtures": fixtures or {},
                "settings": settings or {},
                "operations": operations,
                "oracle": {"assertions": assertions},
            }
        )

    # Independent expected values are explicit, not captured from the target.
    family = "memory_history_integrity"
    add(
        family,
        "restart",
        "memory",
        "追加后重建 MemoryStore，严格游标边界只读取后续记录。",
        [
            step("memory.append", {"entry": "FIRST", "session_key": "a"}, eq(1)),
            step("memory.append", {"entry": "SECOND", "session_key": "a"}, eq(2)),
            step("memory.reload"),
            step(
                "memory.read",
                {"since_cursor": 1},
                check(["output"], "length", 1) + eq("SECOND", ["output", 0, "content"]),
            ),
        ],
        files=[
            {
                "scope": "final_files",
                "path": ["memory/history.jsonl"],
                "kind": "contains",
                "value": "SECOND",
            }
        ],
    )
    add(
        family,
        "empty",
        "memory",
        "空历史和空内容不伪造记录；空内容追加仍获得单调游标。",
        [
            step("memory.read", {"since_cursor": 0}, eq([])),
            step("memory.append", {"entry": ""}, eq(1)),
            step("memory.read", {"since_cursor": 1}, eq([])),
            step("memory.read", {"since_cursor": 0}, eq("", ["output", 0, "content"])),
        ],
    )
    add(
        family,
        "corrupt-recovery",
        "memory",
        "跳过损坏行/非法游标，从合法最大游标恢复追加。",
        [
            step(
                "memory.read",
                {"since_cursor": 0},
                check(["output"], "length", 1) + eq("VALID", ["output", 0, "content"]),
            ),
            step("memory.append", {"entry": "RECOVERED"}, eq(2)),
            step("memory.reload"),
            step(
                "memory.read",
                {"since_cursor": 1},
                check(["output"], "length", 1)
                + eq("RECOVERED", ["output", 0, "content"]),
            ),
        ],
        fixtures={
            "memory/history.jsonl": history(("VALID", None))
            + 'not-json\n{"cursor":true,"timestamp":"x","content":"BAD"}\n',
            "memory/.cursor": "broken",
        },
    )

    family = "memory_pending_retention"
    initial = {
        "memory/history.jsonl": history(("A", "a"), ("B", "a"), ("C", "a")),
        "memory/.cursor": "3",
    }
    add(
        family,
        "pending",
        "memory",
        "容量为一时仍保留全部尚未处理的历史。",
        [
            step("memory.compact"),
            step("memory.read", {"since_cursor": 0}, check(["output"], "length", 3)),
        ],
        fixtures=initial,
        settings={"memory_max_history_entries": 1},
    )
    add(
        family,
        "processed",
        "memory",
        "已处理记录超过容量时只保留最近记录。",
        [
            step("memory.set_dream_cursor", {"cursor": 3}),
            step("memory.compact"),
            step(
                "memory.read",
                {"since_cursor": 0},
                check(["output"], "length", 1) + eq("C", ["output", 0, "content"]),
            ),
        ],
        fixtures=initial,
        settings={"memory_max_history_entries": 1},
    )
    add(
        family,
        "advance",
        "memory",
        "处理进度推进后重新压缩，保留最后的待处理条目。",
        [
            step("memory.compact"),
            step("memory.set_dream_cursor", {"cursor": 2}),
            step("memory.compact"),
            step("memory.reload"),
            step(
                "memory.read",
                {"since_cursor": 0},
                check(["output"], "length", 1) + eq(3, ["output", 0, "cursor"]),
            ),
        ],
        fixtures=initial,
        settings={"memory_max_history_entries": 1},
    )

    family = "session_persistence_isolation"
    add(
        family,
        "roundtrip",
        "session",
        "真实磁盘保存后新 manager 读取，不以原缓存证明持久化。",
        [
            step(
                "session.add",
                {"key": "chat:a", "role": "user", "content": "PERSISTED_USER"},
            ),
            step("session.save", {"key": "chat:a"}),
            step(
                "session.reload",
                {"key": "chat:a"},
                eq({"key": "chat:a", "message_count": 1, "metadata": {}}),
            ),
            step(
                "session.history",
                {"key": "chat:a"},
                eq([{"role": "user", "content": "PERSISTED_USER"}]),
            ),
        ],
        files=[
            {
                "scope": "session_files",
                "path": [],
                "kind": "any_file_contains",
                "value": "PERSISTED_USER",
            }
        ],
    )
    add(
        family,
        "key-collision",
        "session",
        "冒号键与下划线键分别保存，重载后互不覆盖。",
        [
            step("session.add", {"key": "a:b", "role": "user", "content": "COLON"}),
            step("session.save", {"key": "a:b"}),
            step(
                "session.add", {"key": "a_b", "role": "user", "content": "UNDERSCORE"}
            ),
            step("session.save", {"key": "a_b"}),
            step("session.reload", {"key": "a:b"}, eq(1, ["output", "message_count"])),
            step(
                "session.history",
                {"key": "a:b"},
                eq([{"role": "user", "content": "COLON"}]),
            ),
            step(
                "session.history",
                {"key": "a_b"},
                eq([{"role": "user", "content": "UNDERSCORE"}]),
            ),
        ],
        files=[
            {
                "scope": "session_files",
                "path": [],
                "kind": "any_file_contains",
                "value": marker,
            }
            for marker in ("COLON", "UNDERSCORE")
        ],
    )
    add(
        family,
        "unsaved",
        "session",
        "未保存会话在重建 manager 后为空；明确保存的新消息可恢复。",
        [
            step("session.add", {"key": "temp", "role": "user", "content": "UNSAVED"}),
            step("session.reload", {"key": "temp"}, eq(0, ["output", "message_count"])),
            step(
                "session.add",
                {"key": "temp", "role": "user", "content": "RECOVERED_SESSION"},
            ),
            step("session.save", {"key": "temp"}),
            step("session.reload", {"key": "temp"}, eq(1, ["output", "message_count"])),
            step(
                "session.history",
                {"key": "temp"},
                eq([{"role": "user", "content": "RECOVERED_SESSION"}]),
            ),
        ],
        files=[
            {
                "scope": "session_files",
                "path": [],
                "kind": "any_file_contains",
                "value": "RECOVERED_SESSION",
            }
        ],
    )

    family = "session_legal_replay"
    add(
        family,
        "normal",
        "session",
        "正常用户与助手消息按顺序重放。",
        [
            step("session.add", {"key": "a", "role": "user", "content": "Q"}),
            step("session.add", {"key": "a", "role": "assistant", "content": "A"}),
            step(
                "session.history",
                {"key": "a"},
                eq(
                    [
                        {"role": "user", "content": "Q"},
                        {"role": "assistant", "content": "A"},
                    ]
                ),
            ),
        ],
    )
    add(
        family,
        "orphan",
        "session",
        "无匹配调用的 tool 结果不进入合法重放。",
        [
            step("session.add", {"key": "a", "role": "user", "content": "Q"}),
            step(
                "session.add",
                {
                    "key": "a",
                    "role": "tool",
                    "content": "ORPHAN_SECRET",
                    "tool_call_id": "missing",
                },
            ),
            step(
                "session.history", {"key": "a"}, eq([{"role": "user", "content": "Q"}])
            ),
        ],
    )
    add(
        family,
        "clear-recovery",
        "session",
        "清空后旧轮不可见，新轮可保存并重载。",
        [
            step("session.add", {"key": "a", "role": "user", "content": "OLD"}),
            step("session.clear", {"key": "a"}),
            step("session.history", {"key": "a"}, eq([])),
            step("session.add", {"key": "a", "role": "user", "content": "NEW"}),
            step("session.save", {"key": "a"}),
            step("session.reload", {"key": "a"}, eq(1, ["output", "message_count"])),
            step(
                "session.history",
                {"key": "a"},
                eq([{"role": "user", "content": "NEW"}]),
            ),
        ],
    )

    family = "context_memory_visibility"
    context_fixtures = {
        "memory/MEMORY.md": "LONG_SENTINEL",
        "memory/history.jsonl": history(
            ("SAME_SENTINEL", "chat:a"),
            ("OTHER_SENTINEL", "chat:b"),
            ("INTERNAL_SENTINEL", "cron:job"),
        ),
    }
    add(
        family,
        "session",
        "context",
        "默认按当前 session 展示近期历史，包含长记忆。",
        [
            step(
                "context.system",
                {"session_key": "chat:a"},
                check(["output"], "contains", "SAME_SENTINEL")
                + check(["output"], "contains", "LONG_SENTINEL")
                + check(["output"], "not_contains", "OTHER_SENTINEL")
                + check(["output"], "not_contains", "INTERNAL_SENTINEL"),
            )
        ],
        fixtures=context_fixtures,
    )
    add(
        family,
        "independent-toggles",
        "context",
        "关闭长记忆不会关闭近期历史；两个开关分别验证。",
        [
            step(
                "context.system",
                {"session_key": "chat:a", "include_memory": False},
                check(["output"], "not_contains", "LONG_SENTINEL")
                + check(["output"], "contains", "SAME_SENTINEL"),
            ),
            step(
                "context.system",
                {"session_key": "chat:a", "include_memory_recent_history": False},
                check(["output"], "contains", "LONG_SENTINEL")
                + check(["output"], "not_contains", "SAME_SENTINEL"),
            ),
        ],
        fixtures=context_fixtures,
    )
    add(
        family,
        "unified",
        "context",
        "统一会话可见普通跨会话历史，但不包含内部任务历史。",
        [
            step(
                "context.system",
                {"session_key": "chat:a", "unified_session": True},
                check(["output"], "contains", "OTHER_SENTINEL")
                + check(["output"], "not_contains", "INTERNAL_SENTINEL"),
            ),
            step(
                "context.system",
                {"session_key": "chat:a"},
                check(["output"], "not_contains", "OTHER_SENTINEL"),
            ),
        ],
        fixtures=context_fixtures,
    )

    family = "context_message_assembly"
    add(
        family,
        "empty",
        "context",
        "无历史时仍有 system 与当前 user，正文不丢失。",
        [
            step(
                "context.messages",
                {"history": [], "current_message": "HELLO"},
                check(["output"], "length", 2)
                + eq("system", ["output", 0, "role"])
                + eq({"role": "user", "content": "HELLO"}, ["output", 1]),
            )
        ],
    )
    add(
        family,
        "merge",
        "context",
        "相邻同角色 user 合并，下一次构造不携带上次消息。",
        [
            step(
                "context.messages",
                {
                    "history": [{"role": "user", "content": "FIRST"}],
                    "current_message": "SECOND",
                },
                check(["output"], "length", 2)
                + check(["output", 1, "content"], "contains", "FIRST")
                + check(["output", 1, "content"], "contains", "SECOND"),
            ),
            step(
                "context.messages",
                {"history": [], "current_message": "FRESH"},
                eq({"role": "user", "content": "FRESH"}, ["output", 1]),
            ),
        ],
    )
    add(
        family,
        "assistant",
        "context",
        "当前角色为 assistant 时保持角色且不注入用户显式技能上下文。",
        [
            step(
                "context.messages",
                {
                    "history": [{"role": "user", "content": "Q"}],
                    "current_message": "$alpha ANSWER",
                    "current_role": "assistant",
                },
                check(["output"], "length", 3)
                + eq({"role": "assistant", "content": "$alpha ANSWER"}, ["output", 2]),
            )
        ],
        fixtures={"skills/alpha/SKILL.md": skill("alpha", "SKILL_PRIVATE_SENTINEL")},
    )

    family = "skills_resolution"
    fixtures = {
        "skills/alpha/SKILL.md": skill("alpha", "WORKSPACE_BODY"),
        "builtin_skills/alpha/SKILL.md": skill("alpha", "BUILTIN_BODY"),
        "builtin_skills/beta/SKILL.md": skill("beta", "BETA_BODY"),
    }
    add(
        family,
        "priority",
        "skills",
        "同名 workspace skill 优先于 builtin。",
        [
            step(
                "skills.list",
                assertions=eq(
                    [
                        {"name": "alpha", "source": "workspace"},
                        {"name": "beta", "source": "builtin"},
                    ]
                ),
            ),
            step(
                "skills.load",
                {"name": "alpha"},
                check(["output"], "contains", "WORKSPACE_BODY")
                + check(["output"], "not_contains", "BUILTIN_BODY"),
            ),
        ],
        fixtures=fixtures,
    )
    add(
        family,
        "builtin",
        "skills",
        "显式隔离的 builtin 目录能提供技能，未知名称为空。",
        [
            step(
                "skills.load",
                {"name": "beta"},
                check(["output"], "contains", "BETA_BODY"),
            ),
            step("skills.load", {"name": "missing"}, eq(None)),
        ],
        fixtures={"builtin_skills/beta/SKILL.md": skill("beta", "BETA_BODY")},
    )
    add(
        family,
        "disabled",
        "skills",
        "禁用名称既不列出也不可被显式加载。",
        [
            step("skills.list", assertions=eq([{"name": "beta", "source": "builtin"}])),
            step("skills.load", {"name": "alpha"}, eq(None)),
            step("skills.invoked", {"text": "$alpha $beta"}, eq(["beta"])),
        ],
        fixtures=fixtures,
        settings={"disabled_skills": ["alpha"]},
    )

    family = "skills_invocation_availability"
    add(
        family,
        "deduplicate",
        "skills",
        "显式技能引用按首次顺序去重，忽略未知名称。",
        [
            step(
                "skills.invoked",
                {"text": "$alpha $missing $alpha $beta"},
                eq(["alpha", "beta"]),
            ),
            step(
                "skills.context",
                {"text": "$alpha"},
                eq("explicit_skills", ["output", "source"])
                + check(["output", "content"], "contains", "ALPHA_BODY"),
            ),
        ],
        fixtures={
            "skills/alpha/SKILL.md": skill("alpha", "ALPHA_BODY"),
            "skills/beta/SKILL.md": skill("beta", "BETA_BODY"),
        },
    )
    add(
        family,
        "unavailable",
        "skills",
        "缺失专属环境依赖时过滤可用列表及显式调用，仍可列出诊断信息。",
        [
            step("skills.list", assertions=eq([])),
            step(
                "skills.list",
                {"filter_unavailable": False},
                eq([{"name": "alpha", "source": "workspace"}]),
            ),
            step("skills.invoked", {"text": "$alpha"}, eq([])),
            step("skills.context", {"text": "$alpha"}, eq(None)),
        ],
        fixtures={
            "skills/alpha/SKILL.md": skill(
                "alpha",
                "UNAVAILABLE_BODY",
                "metadata:\n  nanobot:\n    requires:\n"
                "      env: [NANOBOT_CORE_REQUIRED_UNSET_7F3A]\n",
            )
        },
    )
    add(
        family,
        "always",
        "skills",
        "always 技能仍可识别，但不重复注入 explicit skill 上下文。",
        [
            step("skills.invoked", {"text": "$alpha"}, eq(["alpha"])),
            step("skills.context", {"text": "$alpha"}, eq(None)),
        ],
        fixtures={
            "skills/alpha/SKILL.md": skill("alpha", "ALWAYS_BODY", "always: true\n")
        },
    )

    # Reserved families: schema-validation only in this delivery, never executed.
    add(
        "memory_legacy_migration",
        "single",
        "memory",
        "reserved：旧 HISTORY.md 单条迁移保留正文。",
        [
            step(
                "memory.read",
                {"since_cursor": 0},
                check(["output"], "length", 1)
                + eq("LEGACY_BODY", ["output", 0, "content"]),
            )
        ],
        fixtures={"memory/HISTORY.md": "LEGACY_BODY\n"},
        split="holdout",
    )
    add(
        "memory_legacy_migration",
        "precedence",
        "memory",
        "reserved：已有 JSONL 时不从旧历史重复导入。",
        [
            step(
                "memory.read",
                {"since_cursor": 0},
                check(["output"], "length", 1)
                + eq("CURRENT", ["output", 0, "content"]),
            )
        ],
        fixtures={
            "memory/HISTORY.md": "OLD\n",
            "memory/history.jsonl": history(("CURRENT", None)),
        },
        split="holdout",
    )
    add(
        "session_delete_recreate",
        "delete",
        "session",
        "reserved：删除已保存会话后重新读取为空。",
        [
            step("session.add", {"key": "a", "role": "user", "content": "OLD"}),
            step("session.save", {"key": "a"}),
            step("session.delete", {"key": "a"}, eq(True)),
            step("session.reload", {"key": "a"}, eq(0, ["output", "message_count"])),
        ],
        split="holdout",
    )
    add(
        "session_delete_recreate",
        "missing",
        "session",
        "reserved：删除不存在会话返回 false，随后创建保存成功。",
        [
            step("session.delete", {"key": "absent"}, eq(False)),
            step("session.add", {"key": "absent", "role": "user", "content": "NEW"}),
            step("session.save", {"key": "absent"}),
            step(
                "session.reload", {"key": "absent"}, eq(1, ["output", "message_count"])
            ),
        ],
        split="holdout",
    )
    add(
        "context_bootstrap_visibility",
        "agents",
        "context",
        "reserved：工作区 AGENTS.md 正文进入系统上下文。",
        [
            step(
                "context.system",
                assertions=check(["output"], "contains", "BOOTSTRAP_AGENTS_SENTINEL"),
            )
        ],
        fixtures={"AGENTS.md": "BOOTSTRAP_AGENTS_SENTINEL"},
        split="holdout",
    )
    add(
        "context_bootstrap_visibility",
        "soul-user",
        "context",
        "reserved：SOUL.md 与 USER.md 各自进入系统上下文。",
        [
            step(
                "context.system",
                assertions=check(["output"], "contains", "BOOTSTRAP_SOUL_SENTINEL")
                + check(["output"], "contains", "BOOTSTRAP_USER_SENTINEL"),
            )
        ],
        fixtures={
            "SOUL.md": "BOOTSTRAP_SOUL_SENTINEL",
            "USER.md": "BOOTSTRAP_USER_SENTINEL",
        },
        split="holdout",
    )
    add(
        "skills_malformed_metadata",
        "yaml",
        "skills",
        "reserved：非法 YAML 元数据解析为空，正文读取不伪造元数据。",
        [
            step("skills.metadata", {"name": "alpha"}, eq(None)),
            step(
                "skills.load",
                {"name": "alpha"},
                check(["output"], "contains", "MALFORMED_BODY"),
            ),
        ],
        fixtures={"skills/alpha/SKILL.md": "---\nname: [broken\n---\nMALFORMED_BODY\n"},
        split="holdout",
    )
    add(
        "skills_malformed_metadata",
        "scalar",
        "skills",
        "reserved：非映射 frontmatter 不被认作有效 metadata。",
        [step("skills.metadata", {"name": "alpha"}, eq(None))],
        fixtures={"skills/alpha/SKILL.md": "---\nplain-scalar\n---\nBODY\n"},
        split="holdout",
    )
    return tasks


def build(directory=None):
    directory = Path(directory) if directory is not None else Path(__file__).parent
    tasks = make_tasks()
    raw = "".join(
        json.dumps(
            task,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
        for task in tasks
    ).encode()
    manifest = {
        "dataset_id": "nanobot-core-v1",
        "contract_version": CONTRACT,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "task_count": len(tasks),
        "family_count": len({t["family"] for t in tasks}),
        "split_counts": dict(Counter(t["split"] for t in tasks)),
        "human_reviewed": False,
        "holdout_status": "reserved_schema_validated_only",
        "oracle_provenance": (
            "explicit_source_contract_expectations_not_runtime_outputs"
        ),
    }
    assets = {
        "tasks.jsonl": raw,
        "manifest.json": (
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode(),
    }
    # Validate all destinations before any write; no partially updated frozen set.
    for name, content in assets.items():
        path = directory / name
        if path.exists() and path.read_bytes() != content:
            raise ValueError(f"Refusing to overwrite frozen bytes: {name}")
    directory.mkdir(parents=True, exist_ok=True)
    for name, content in assets.items():
        path = directory / name
        if not path.exists():
            path.write_bytes(content)
    return manifest


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False))
