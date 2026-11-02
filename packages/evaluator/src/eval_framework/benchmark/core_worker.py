"""Single-use offline process executing allowlisted real nanobot component APIs.

No oracle, task identity, provider or credentials enter this boundary. The parent
runner independently snapshots files and binds the runtime source identity.
"""

from __future__ import annotations

import copy
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

if __package__:
    from .core_tasks import validate_public_task
else:  # Direct file entrypoint keeps the target interpreter independent.
    from core_tasks import validate_public_task


def install_safety_guards(workspace: Path, runtime_dir: Path) -> None:
    """Audit guards are process-local and intentionally cannot be removed."""
    roots = (workspace.resolve(), runtime_dir.resolve())
    private_home = Path.home() / ".nanobot"

    def contained(value: Any) -> bool:
        if isinstance(value, int):
            return True
        path = Path(os.fsdecode(value)).resolve()
        return any(path == root or path.is_relative_to(root) for root in roots)

    def audit(event: str, args: tuple) -> None:
        if event in {
            "socket.connect",
            "socket.connect_ex",
            "socket.sendto",
            "socket.getaddrinfo",
            "socket.gethostbyname",
            "socket.gethostbyaddr",
            "socket.bind",
        }:
            raise PermissionError("Core worker network access is disabled")
        if event in {
            "subprocess.Popen",
            "os.system",
            "os.posix_spawn",
            "os.fork",
            "os.forkpty",
            "pty.spawn",
        }:
            raise PermissionError("Core worker subprocess execution is disabled")
        if event == "open":
            path, mode, flags = args
            if not isinstance(path, int):
                resolved = Path(os.fsdecode(path)).resolve()
                if resolved == private_home or resolved.is_relative_to(private_home):
                    raise PermissionError("User nanobot state is inaccessible")
            writing = (
                isinstance(mode, str) and any(c in mode for c in "wax+")
            ) or flags & (
                os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
            )
            if writing and not contained(path):
                raise PermissionError("Write outside sample directories")
        if event in {
            "os.mkdir",
            "os.remove",
            "os.rmdir",
            "os.chmod",
            "os.utime",
            "os.truncate",
        } and not contained(args[0]):
            raise PermissionError("Mutation outside sample directories")
        if event in {"os.rename", "os.link", "os.symlink"} and (
            not contained(args[0]) or not contained(args[1])
        ):
            raise PermissionError("Link/rename outside sample directories")

    sys.addaudithook(audit)


class Components:
    def __init__(self, workspace: Path, runtime_dir: Path, settings: dict):
        from nanobot.config.loader import set_config_path

        self.workspace, self.runtime_dir, self.settings = (
            workspace,
            runtime_dir,
            settings,
        )
        config = runtime_dir / "config.json"
        config.write_text("{}\n", encoding="utf-8")
        set_config_path(config)
        self._memory = self._sessions = self._skills = self._context = None

    def memory(self):
        from nanobot.agent.memory import MemoryStore

        if self._memory is None:
            self._memory = MemoryStore(
                self.workspace,
                max_history_entries=self.settings.get(
                    "memory_max_history_entries", 1000
                ),
            )
        return self._memory

    def sessions(self):
        from nanobot.session.manager import SessionManager

        if self._sessions is None:
            self._sessions = SessionManager(
                self.workspace, sessions_root=self.runtime_dir / "sessions"
            )
        return self._sessions

    def skills(self):
        from nanobot.agent.skills import SkillsLoader

        if self._skills is None:
            self._skills = SkillsLoader(
                self.workspace,
                builtin_skills_dir=self.workspace / "builtin_skills",
                disabled_skills=set(self.settings.get("disabled_skills", [])),
            )
        return self._skills

    def context(self):
        from nanobot.agent.context import ContextBuilder

        if self._context is None:
            self._context = ContextBuilder(self.workspace, timezone="UTC")
            self._context.skills = self.skills()
        return self._context

    def execute(self, operation: str, arguments: dict) -> Any:
        args = copy.deepcopy(arguments)
        if operation.startswith("memory."):
            if operation == "memory.reload":
                self._memory = None
                self.memory()
                return None
            api = self.memory()
            methods = {
                "memory.append": "append_history",
                "memory.read": "read_unprocessed_history",
                "memory.recent": "read_recent_history_for_prompt",
                "memory.latest": "get_latest_cursor",
                "memory.set_dream_cursor": "set_last_dream_cursor",
                "memory.compact": "compact_history",
                "memory.write": "write_memory",
                "memory.read_long": "read_memory",
            }
            # Use the public content argument without rewriting its text.
            if operation == "memory.write":
                return api.write_memory(args["content"])
            if operation == "memory.set_dream_cursor":
                return api.set_last_dream_cursor(args["cursor"])
            return getattr(api, methods[operation])(**args)
        if operation.startswith("session."):
            key = args.pop("key")
            if operation == "session.reload":
                self._sessions = None
                session = self.sessions().get_or_create(key)
                return {
                    "key": session.key,
                    "message_count": len(session.messages),
                    "metadata": session.metadata,
                }
            manager = self.sessions()
            if operation == "session.delete":
                return manager.delete_session(key)
            session = manager.get_or_create(key)
            if operation == "session.add":
                return session.add_message(**args)
            if operation == "session.save":
                manager.save(session)
                return None
            if operation == "session.history":
                return session.get_history(**args)
            if operation == "session.clear":
                return session.clear()
        if operation.startswith("context."):
            api = self.context()
            if operation == "context.system":
                return api.build_system_prompt(**args)
            return api.build_messages(**args)
        if operation.startswith("skills."):
            api = self.skills()
            if operation == "skills.list":
                return sorted(
                    [
                        {"name": item["name"], "source": item["source"]}
                        for item in api.list_skills(**args)
                    ],
                    key=lambda item: item["name"],
                )
            if operation == "skills.load":
                return api.load_skill(**args)
            if operation == "skills.metadata":
                return api.get_skill_metadata(**args)
            if operation == "skills.invoked":
                return api.get_explicitly_invoked_skills(**args)
            block = api.build_explicit_skill_runtime_context(**args)
            return (
                None
                if block is None
                else {"source": block.source, "content": block.content}
            )
        raise ValueError("Unknown operation")


def run(payload: dict) -> dict:
    result = {
        "status": "error",
        "execution_kind": "real_core_module",
        "events": [],
        "errors": [],
        "usage": {},
    }
    try:
        if not isinstance(payload, dict) or set(payload) != {
            "task",
            "workspace",
            "runtime_dir",
        }:
            raise ValueError("Invalid worker envelope")
        validate_public_task(payload["task"])
        workspace, runtime_dir = (
            Path(payload["workspace"]),
            Path(payload["runtime_dir"]),
        )
        if not workspace.is_absolute() or not runtime_dir.is_absolute():
            raise ValueError("Sample directories must be absolute")
        # Resolve links before installing the guard, then fail rather than allowing
        # a fixture symlink to reach outside either independently measured scope.
        for path in (workspace, runtime_dir):
            if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
                raise ValueError("Sample directories cannot have symlink parents")
            if path.exists() and any(p.is_symlink() for p in path.rglob("*")):
                raise ValueError("Symlink fixtures are forbidden")
        workspace, runtime_dir = workspace.resolve(), runtime_dir.resolve()
        if (
            workspace == runtime_dir
            or workspace.is_relative_to(runtime_dir)
            or runtime_dir.is_relative_to(workspace)
        ):
            raise ValueError("Runtime and workspace must be disjoint")
        workspace.mkdir(parents=True, exist_ok=True)
        runtime_dir.mkdir(parents=True, exist_ok=True)
        install_safety_guards(workspace, runtime_dir)
        components = Components(workspace, runtime_dir, payload["task"]["settings"])
        for step in payload["task"]["operations"]:
            event = {
                "id": step["id"],
                "type": "module",
                "operation": step["operation"],
                "input": copy.deepcopy(step["input"]),
                "output": None,
                "error": None,
                "start_time": time.time(),
                "end_time": None,
                "incomplete": True,
            }
            result["events"].append(event)
            try:
                event["output"] = components.execute(step["operation"], step["input"])
                json.dumps(event["output"], allow_nan=False)
            except Exception as exc:
                event["output"] = None
                event["error"] = {"type": type(exc).__name__, "message": str(exc)}
            event["end_time"] = time.time()
            event["incomplete"] = False
        result["status"] = "completed"
    except Exception as exc:
        result["errors"].append({"type": type(exc).__name__, "message": str(exc)})
    return result


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "execution_kind": "real_core_module",
                    "events": [],
                    "errors": [{"type": type(exc).__name__, "message": str(exc)}],
                    "usage": {},
                }
            )
        )
        return
    print(json.dumps(run(payload), ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
