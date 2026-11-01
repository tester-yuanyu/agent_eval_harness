"""Isolated τ worker: official simulation/reward with nanobot's real AgentLoop.

Proxy tools rendezvous with the official orchestrator. They never execute or
reimplement a domain tool: each official ToolMessage resumes nanobot's pending
call, preserving both the official trajectory and the Agent's actual loop.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
from concurrent.futures import CancelledError
from contextvars import ContextVar
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from queue import Queue
from threading import Thread
from typing import Any
from uuid import uuid4

try:
    from .tau_adapter import redact_secrets, verify_imported_tau
except ImportError:  # The isolated subprocess executes this file directly.
    from tau_adapter import redact_secrets, verify_imported_tau


def public_tau_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Copy public τ participant messages without provider-private state."""
    keys = {"role", "content", "tool_calls", "tool_call_id", "name"}
    return [
        {key: deepcopy(value) for key, value in message.items() if key in keys}
        for message in messages
    ]


class TauEvidence:
    """τ rendezvous evidence, independent of the file-tool Inspect bridge.

    The official orchestrator owns domain execution and reward. These records
    retain public agent/user interactions and pending tool handoffs only.
    """

    def __init__(self, path: Path, secret: str = "") -> None:
        self.path = path
        self.secret = secret
        self.events: list[dict[str, Any]] = []
        self.turn_id: str | None = None
        self.turn_index: int | None = None

    def write(self, event: dict[str, Any]) -> None:
        # Redact before JSON escaping so credentials containing quotes are
        # protected as well. In-memory native messages remain untouched.
        def clean(value: Any) -> Any:
            if isinstance(value, str):
                return (
                    value.replace(self.secret, "[REDACTED]") if self.secret else value
                )
            if isinstance(value, list):
                return [clean(item) for item in value]
            if isinstance(value, dict):
                return {clean(key): clean(item) for key, item in value.items()}
            return value

        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps(clean(event), ensure_ascii=False, default=str) + "\n"
            )
            stream.flush()

    def start(
        self, kind: str, name: str, input_value: Any, **extra: Any
    ) -> dict[str, Any]:
        event = {
            "id": uuid4().hex,
            "type": kind,
            "name": name,
            "start_time": datetime.now(UTC).isoformat(),
            "end_time": None,
            "input": deepcopy(input_value),
            "output": None,
            "usage": {},
            "parent_id": self.turn_id,
            "turn": self.turn_index,
            **extra,
        }
        self.events.append(event)
        self.write(event)
        return event

    def finish(self, event: dict[str, Any], output: Any, **extra: Any) -> None:
        event.update(
            end_time=datetime.now(UTC).isoformat(), output=deepcopy(output), **extra
        )
        self.write(event)


def load_tau_evidence(path: Path) -> list[dict[str, Any]]:
    """Merge append updates; a truncated final write retains the pending event."""
    events = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
                if isinstance(event, dict) and isinstance(event.get("id"), str):
                    events[event["id"]] = event
            except ValueError:
                continue
    return list(events.values())


def evidence_issues(events: list[dict], termination_reason: str) -> list[dict]:
    issues = []
    required = {
        "agent_turn": any(e.get("type") == "turn" for e in events),
        "agent_generation": any(
            e.get("type") == "generation" and e.get("participant") != "user_simulator"
            for e in events
        ),
        "user_simulator": any(e.get("participant") == "user_simulator" for e in events),
    }
    for component, present in required.items():
        if not present:
            issues.append({"code": "missing_evidence", "component": component})
    for event in events:
        if (
            not event.get("end_time")
            or event.get("error")
            or (
                event.get("type") in {"tool", "generation"}
                and event.get("output") is None
            )
        ):
            issues.append(
                {
                    "code": "incomplete_event",
                    "event_id": event["id"],
                    "error": event.get("error"),
                }
            )
    if termination_reason not in {"user_stop", "agent_stop"}:
        issues.append({"code": "official_termination", "reason": termination_reason})
    return issues


def make_nanobot_agent(
    tools: list[Any], domain_policy: str, config: dict[str, Any], directory: Path
) -> Any:
    """Build a text-only τ participant without giving it the private Task."""
    from nanobot.agent.hook import AgentHook
    from nanobot.agent.loop import AgentLoop
    from nanobot.agent.tools.base import Tool, ToolResult
    from nanobot.agent.tools.registry import ToolRegistry
    from nanobot.bus.queue import MessageBus
    from nanobot.config.loader import set_config_path
    from nanobot.config.schema import ToolsConfig
    from nanobot.nanobot import Nanobot
    from nanobot.providers.base import GenerationSettings
    from nanobot.providers.openai_compat_provider import OpenAICompatProvider
    from nanobot.session.manager import JsonlSessionStore, SessionManager
    from tau2.agent.base_agent import HalfDuplexAgent
    from tau2.agent.llm_agent import AGENT_INSTRUCTION
    from tau2.data_model.message import (
        AssistantMessage,
        MultiToolMessage,
        ToolCall,
        ToolMessage,
        UserMessage,
    )

    if config.get("tokenizer_mode", "byte_fallback") == "byte_fallback":
        import nanobot.utils.helpers as helpers

        def byte_fallback() -> Any:
            raise RuntimeError("Explicit conservative UTF-8 byte token estimate")

        helpers._get_token_encoding = byte_fallback

    directory.mkdir(parents=True, exist_ok=True)
    workspace = directory / "private-workspace"
    workspace.mkdir()
    # These are public policy/instructions only. No task goals, evaluation
    # criteria, expected actions or private user scenario reach nanobot.
    (workspace / "AGENTS.md").write_text(
        AGENT_INSTRUCTION + "\n\n<policy>\n" + domain_policy + "\n</policy>\n"
    )
    set_config_path(directory / "isolated-config.json")
    journal = TauEvidence(
        directory / "nanobot-events.jsonl",
        os.environ.get(config.get("agent_api_key_env", "DEEPSEEK_API_KEY"), ""),
    )
    native_call_id: ContextVar[str | None] = ContextVar(
        "tau_native_call_id", default=None
    )

    class EvidenceHook(AgentHook):
        def __init__(self) -> None:
            super().__init__(reraise=True)

        async def before_execute_tool(
            self, context: Any, tool_call: Any, tool: Any, params: Any
        ) -> None:
            native_call_id.set(tool_call.id)

        async def after_iteration(self, context: Any) -> None:
            captured = {
                e.get("tool_call_id") for e in journal.events if e["type"] == "tool"
            }
            for call, detail in zip(
                context.tool_calls, context.tool_events, strict=False
            ):
                if call.id not in captured:
                    event = journal.start(
                        "tool",
                        call.name,
                        call.arguments,
                        tool_call_id=call.id,
                        execution_started=False,
                        execution_owner="nanobot_local_validation",
                    )
                    journal.finish(
                        event, detail.get("detail"), error=detail.get("detail")
                    )

    class Provider(OpenAICompatProvider):
        def _parse(self, response: Any) -> Any:
            self.response_model = getattr(response, "model", None)
            return super()._parse(response)

        async def chat(self, messages: list[dict], **kwargs: Any) -> Any:
            event = journal.start(
                "generation",
                config["agent_model"],
                {
                    "messages": public_tau_messages(messages),
                    "tools": deepcopy(kwargs.get("tools")),
                    "model": kwargs.get("model"),
                },
            )
            try:
                response = await super().chat(messages, **kwargs)
                extra = {}
                if response.finish_reason == "error":
                    extra["error"] = (
                        response.content or response.error_kind or "provider error"
                    )
                journal.finish(
                    event,
                    {
                        "content": response.content,
                        "tool_calls": [
                            {"id": c.id, "name": c.name, "arguments": c.arguments}
                            for c in response.tool_calls
                        ],
                        "finish_reason": response.finish_reason,
                    },
                    usage=dict(response.usage),
                    model=config["agent_model"],
                    response_model=getattr(self, "response_model", None),
                    **extra,
                )
                return response
            except BaseException as exc:
                journal.finish(event, None, error=type(exc).__name__)
                raise

    class DomainOnlyLoop(AgentLoop):
        def _register_default_tools(self, **_kwargs: Any) -> None:
            return None

    class NanobotTauAgent(HalfDuplexAgent[dict]):
        def __init__(self) -> None:
            super().__init__(tools=tools, domain_policy=domain_policy)
            self.events: Queue = Queue()
            self.pending: dict[str, asyncio.Future] = {}
            self.pending_events: dict[str, dict] = {}
            self.loop = asyncio.new_event_loop()
            self.thread = Thread(target=self.loop.run_forever, daemon=True)
            self.thread.start()
            self.session_key = "tau:" + uuid4().hex
            self.active = None
            self.stopped = False
            self.turn_index = 0
            asyncio.run_coroutine_threadsafe(self.initialize(), self.loop).result(30)

        async def initialize(self) -> None:
            owner = self

            class ProxyTool(Tool):
                def __init__(self, specification: dict) -> None:
                    self.specification = deepcopy(specification["function"])

                @property
                def name(self) -> str:
                    return self.specification["name"]

                @property
                def description(self) -> str:
                    return self.specification.get("description", "")

                @property
                def parameters(self) -> dict:
                    return self.specification["parameters"]

                async def execute(self, **kwargs: Any) -> Any:
                    event = journal.start(
                        "tool",
                        self.name,
                        kwargs,
                        tool_schema=self.parameters,
                        execution_started=True,
                        execution_owner="official_tau_environment",
                        tool_call_id=native_call_id.get(),
                    )
                    future = asyncio.get_running_loop().create_future()
                    owner.pending[event["id"]] = future
                    owner.pending_events[event["id"]] = event
                    owner.events.put(
                        (
                            "tool",
                            {
                                "id": event["id"],
                                "name": self.name,
                                "arguments": deepcopy(kwargs),
                            },
                        )
                    )
                    try:
                        result = await future
                        journal.finish(event, str(result), tool_error=result.is_error)
                        return result
                    except BaseException as exc:
                        if not event.get("end_time"):
                            journal.finish(event, None, error=type(exc).__name__)
                        raise
                    finally:
                        owner.pending.pop(event["id"], None)
                        owner.pending_events.pop(event["id"], None)

            registry = ToolRegistry()
            for tool in tools:
                registry.register(ProxyTool(tool.openai_schema))
            provider = Provider(
                api_key=os.environ.get(
                    config.get("agent_api_key_env", "DEEPSEEK_API_KEY"), ""
                ),
                api_base=config.get("agent_base_url"),
                default_model=config["agent_model"],
                api_type="chat_completions",
                extra_body=config.get("agent_extra_body"),
            )
            provider.generation = GenerationSettings(
                temperature=float(config.get("temperature", 0)),
                max_tokens=int(config.get("max_tokens", 2048)),
            )
            store = JsonlSessionStore(workspace, sessions_root=directory / "sessions")
            store.legacy_sessions_dir = directory / "legacy-sessions"
            sessions = SessionManager(
                workspace, store=store, sessions_root=directory / "sessions"
            )
            self.agent_loop = DomainOnlyLoop(
                bus=MessageBus(),
                provider=provider,
                workspace=workspace,
                model=config["agent_model"],
                max_iterations=config.get("max_agent_steps", 20),
                context_window_tokens=100_000,
                max_tool_result_chars=100_000,
                fail_on_tool_error=False,
                restrict_to_workspace=True,
                session_manager=sessions,
                tool_registry=registry,
                session_ttl_minutes=0,
                idle_compact_check_interval_seconds=0,
                disabled_skills=[
                    p.name
                    for p in (Path(config["nanobot_root"]) / "nanobot/skills").iterdir()
                    if p.is_dir()
                ],
                tools_config=ToolsConfig(restrict_to_workspace=True),
            )
            self.bot = Nanobot(self.agent_loop)

        def get_init_state(self, message_history: list | None = None) -> dict:
            session = self.agent_loop.sessions.get_or_create(self.session_key)
            for message in message_history or []:
                if isinstance(message, ToolMessage):
                    session.add_message(
                        "tool", message.content or "", tool_call_id=message.id
                    )
                else:
                    extra = {}
                    if message.tool_calls:
                        extra["tool_calls"] = [
                            {
                                "id": c.id,
                                "type": "function",
                                "function": {
                                    "name": c.name,
                                    "arguments": json.dumps(c.arguments),
                                },
                            }
                            for c in message.tool_calls
                        ]
                    session.add_message(message.role, message.content or "", **extra)
            self.agent_loop.sessions.save(session)
            return {"session_key": self.session_key}

        def generate_next_message(self, message: Any, state: dict) -> tuple[Any, dict]:
            if isinstance(message, UserMessage):
                if self.active is not None and not self.active.done():
                    raise RuntimeError(
                        "User turn arrived while nanobot awaits tool results"
                    )

                async def run_turn() -> None:
                    self.turn_index += 1
                    journal.turn_index = self.turn_index
                    turn = journal.start(
                        "turn", f"turn-{self.turn_index}", message.content
                    )
                    journal.turn_id = turn["id"]
                    try:
                        result = await self.bot.run(
                            message.content or "",
                            session_key=self.session_key,
                            channel="cli",
                            chat_id="tau",
                            ephemeral=False,
                            hooks=[EvidenceHook()],
                        )
                        if result.error:
                            raise RuntimeError(result.error)
                        journal.finish(turn, result.content, usage=dict(result.usage))
                        self.events.put(
                            ("response", (result.content, dict(result.usage)))
                        )
                    except BaseException as exc:
                        journal.finish(turn, None, error=type(exc).__name__)
                        self.events.put(("error", exc))
                    finally:
                        journal.turn_id = None

                self.active = asyncio.run_coroutine_threadsafe(run_turn(), self.loop)
            elif isinstance(message, (ToolMessage, MultiToolMessage)):
                replies = (
                    message.tool_messages
                    if isinstance(message, MultiToolMessage)
                    else [message]
                )
                for reply in replies:
                    future = self.pending.get(reply.id)
                    if future is None:
                        raise ValueError(f"No pending nanobot tool call {reply.id}")
                    result = (
                        ToolResult.error(reply.content or "")
                        if reply.error
                        else ToolResult(reply.content or "")
                    )
                    self.loop.call_soon_threadsafe(future.set_result, result)
            else:
                raise ValueError("Only official user/tool messages may reach nanobot")
            kind, value = self.events.get(
                timeout=float(config.get("timeout_seconds", 300))
            )
            if kind == "error":
                raise RuntimeError(
                    f"nanobot failed: {type(value).__name__}: {value}"
                ) from value
            if kind == "tool":
                return AssistantMessage(
                    role="assistant", tool_calls=[ToolCall(**value)]
                ), state
            content, usage = value
            # The queue write happens just before coroutine/session cleanup.
            # Finish it before an immediately following user turn is accepted.
            if self.active is not None:
                self.active.result(timeout=5)
            return AssistantMessage(
                role="assistant", content=content, usage=usage
            ), state

        def stop(self, message: Any = None, state: Any = None) -> None:
            if self.stopped:
                return
            self.stopped = True
            # Official limits can fire immediately after a tool has executed.
            # Preserve that response without waking the loop for another LLM call.
            replies = (
                message.tool_messages
                if isinstance(message, MultiToolMessage)
                else [message]
                if isinstance(message, ToolMessage)
                else []
            )
            for reply in replies:
                event = self.pending_events.get(reply.id)
                if event is not None and not event.get("end_time"):
                    journal.finish(
                        event,
                        reply.content or "",
                        tool_error=bool(reply.error),
                        termination_capture=True,
                    )
            if self.active is not None and not self.active.done():
                self.active.cancel()
            if self.loop.is_running():
                try:
                    asyncio.run_coroutine_threadsafe(
                        self.agent_loop.aclose(), self.loop
                    ).result(20)
                except (TimeoutError, CancelledError):
                    pass
                self.loop.call_soon_threadsafe(self.loop.stop)
                self.thread.join(timeout=5)

    return NanobotTauAgent()


def execute(payload: dict[str, Any]) -> dict[str, Any]:
    """Run unmodified official tasks, simulator, environment and reward evaluator."""
    from loguru import logger

    logger.remove()
    config, output = payload["config"], Path(payload["output"])
    sys.path.insert(0, config["nanobot_root"])
    sys.path.insert(0, str(Path(config["source_root"]) / "src"))
    import tau2

    actual_tau_module = verify_imported_tau(tau2.__file__, config["source_root"])
    from nanobot_runtime import runtime_identity, utc_now
    from tau2.data_model.tasks import RewardType
    from tau2.evaluator.evaluator import EvaluationType
    from tau2.evaluator.evaluator_nl_assertions import DEFAULT_LLM_NL_ASSERTIONS
    from tau2.orchestrator.orchestrator import Orchestrator
    from tau2.runner import build_environment, build_user, get_tasks, run_simulation

    tasks = get_tasks("retail", task_ids=config["task_ids"])
    needs_judge = [
        t.id
        for t in tasks
        if t.evaluation_criteria
        and RewardType.NL_ASSERTION in t.evaluation_criteria.reward_basis
        and t.evaluation_criteria.nl_assertions
    ]
    if needs_judge and not config.get("allow_official_judge", False):
        raise ValueError(
            "Selected official tasks require their NL assertion judge; explicitly "
            "enable allow_official_judge and its provider credentials"
        )
    environment = build_environment("retail")
    identity = runtime_identity(
        {
            "nanobot_root": config["nanobot_root"],
            "model": config["agent_model"],
            "base_url": config.get("agent_base_url"),
            "tokenizer_mode": config.get("tokenizer_mode", "byte_fallback"),
            "temperature": config.get("temperature", 0),
            "max_tokens": config.get("max_tokens", 2048),
            "max_steps": config.get("max_agent_steps", 20),
            "extra_body": config.get("agent_extra_body", {}),
        }
    )
    identity.update(
        adapter_version="tau-nanobot-rendezvous-v1",
        isolation="official_tau_domain_environment",
    )
    from importlib.metadata import distributions

    summary = {
        "status": "VALIDATED" if payload.get("dry_run") else "RUNNING",
        "suite": "tau-retail-v1.0.1-nanobot-pilot",
        "official_leaderboard_result": False,
        "tau_import_path": actual_tau_module,
        "domain": "retail",
        "task_ids": [t.id for t in tasks],
        "num_trials": config.get("num_trials", 1),
        "agent": "real_nanobot_AgentLoop_with_official_tau_tools",
        "agent_runtime_identity": identity,
        "runtime_packages": {
            dist.metadata["Name"]: dist.version for dist in distributions()
        },
        "user_simulator": "official_tau_user_simulator",
        "user_model": config["user_model"],
        "official_reward_evaluation": "EvaluationType.ALL",
        "official_judge_model_if_needed": DEFAULT_LLM_NL_ASSERTIONS,
        "tasks_requiring_judge": needs_judge,
        "policy_sha256": hashlib.sha256(environment.get_policy().encode()).hexdigest(),
        "tool_names": [tool.name for tool in environment.get_tools()],
        "task_sha256": {
            t.id: hashlib.sha256(t.model_dump_json().encode()).hexdigest()
            for t in tasks
        },
        "results": [],
        "limitations": [
            "Explicit English retail subset; not a full official leaderboard run",
            "Custom nanobot scaffolding and user model are experimental controls",
            "τ official reward is retained separately from file-tools DeepEval metrics",
        ],
    }
    if payload.get("dry_run"):
        return summary
    if not os.environ.get(config.get("agent_api_key_env", "DEEPSEEK_API_KEY")):
        raise ValueError("Agent provider credential environment variable is empty")
    if not os.environ.get(config.get("user_api_key_env", "DEEPSEEK_API_KEY")):
        raise ValueError("User simulator credential environment variable is empty")
    if needs_judge and not os.environ.get("OPENAI_API_KEY"):
        raise ValueError("Official NL judge requires its selected OpenAI credential")
    for task in tasks:
        for trial in range(1, config.get("num_trials", 1) + 1):
            directory = output / f"task-{task.id}-trial-{trial}"
            directory.mkdir()
            env = build_environment("retail")
            agent = make_nanobot_agent(
                env.get_tools(), env.get_policy(), config, directory
            )
            user = build_user(
                "user_simulator",
                env,
                task,
                llm=config["user_model"],
                llm_args={
                    "temperature": float(config.get("user_temperature", 0)),
                    "api_base": config.get("user_base_url"),
                    "api_key": os.environ.get(
                        config.get("user_api_key_env", "DEEPSEEK_API_KEY")
                    ),
                    "timeout": float(config.get("provider_timeout_seconds", 60)),
                },
            )
            user_journal = TauEvidence(
                directory / "user-simulator-events.jsonl",
                os.environ.get(config.get("user_api_key_env", "DEEPSEEK_API_KEY"), ""),
            )
            original_generate = user.generate_next_message

            def observed_user(
                message: Any,
                state: Any,
                *,
                recorded_journal: Any = user_journal,
                generate: Any = original_generate,
            ) -> tuple[Any, Any]:
                # Only public conversation IO is copied. Private user-simulator
                # instructions/state are not mislabeled as Agent input.
                event = recorded_journal.start(
                    "generation",
                    "official_user_simulator",
                    message.model_dump(mode="json") if message is not None else None,
                    participant="user_simulator",
                    model=config["user_model"],
                )
                try:
                    reply, new_state = generate(message, state)
                    recorded_journal.finish(
                        event,
                        reply.model_dump(mode="json"),
                        usage=reply.usage or {},
                    )
                    return reply, new_state
                except BaseException as exc:
                    recorded_journal.finish(event, None, error=type(exc).__name__)
                    raise

            user.generate_next_message = observed_user
            started_at = utc_now()
            try:
                simulation = run_simulation(
                    Orchestrator(
                        domain="retail",
                        agent=agent,
                        user=user,
                        environment=env,
                        task=task,
                        max_steps=config.get("max_steps", 60),
                        max_errors=config.get("max_errors", 10),
                        seed=config.get("seed", 42) + trial - 1,
                        timeout=float(config.get("timeout_seconds", 300)),
                    ),
                    evaluation_type=EvaluationType.ALL,
                )
                (directory / "official-result.json").write_text(
                    json.dumps(
                        redact_secrets(simulation.model_dump(mode="json"), config),
                        indent=2,
                    )
                )
                events = sorted(
                    load_tau_evidence(directory / "nanobot-events.jsonl")
                    + load_tau_evidence(directory / "user-simulator-events.jsonl"),
                    key=lambda event: event["start_time"],
                )
                turns = [event for event in events if event["type"] == "turn"]
                problems = evidence_issues(events, simulation.termination_reason.value)
                observation = {
                    "execution_kind": "real_agent_official_tau",
                    "status": "completed"
                    if simulation.termination_reason.value
                    in {"user_stop", "agent_stop"}
                    else simulation.termination_reason.value,
                    "evidence_complete": not problems,
                    "runtime_identity": identity,
                    "events": events,
                    "turns": [
                        {"input": e["input"], "output": e["output"]} for e in turns
                    ],
                    "errors": problems,
                    "official_messages": [
                        m.model_dump(mode="json") for m in simulation.messages
                    ],
                    "official_reward": simulation.reward_info.model_dump(mode="json"),
                    "final_database_hash": env.get_db_hash(),
                }
                (directory / "benchmark-observation.json").write_text(
                    json.dumps(
                        redact_secrets(observation, config),
                        indent=2,
                        ensure_ascii=False,
                    )
                )
                summary["results"].append(
                    {
                        "task_id": task.id,
                        "trial": trial,
                        "official_reward": simulation.reward_info.reward,
                        "reward_info": simulation.reward_info.model_dump(mode="json"),
                        "termination_reason": simulation.termination_reason.value,
                        "evidence_complete": not problems,
                        "messages": len(simulation.messages),
                        "verdict": "PASS"
                        if simulation.reward_info.reward == 1
                        else "FAIL",
                        "started_at": started_at,
                        "finished_at": utc_now(),
                        "observation_path": str(
                            directory / "benchmark-observation.json"
                        ),
                        "result_path": str(directory / "official-result.json"),
                    }
                )
            except Exception as exc:
                summary["results"].append(
                    {
                        "task_id": task.id,
                        "trial": trial,
                        "official_reward": None,
                        "verdict": "INVALID",
                        "started_at": started_at,
                        "finished_at": utc_now(),
                        "error": {
                            "type": type(exc).__name__,
                            "message": redact_secrets(str(exc), config),
                        },
                        "result_path": None,
                    }
                )
            finally:
                agent.stop()
                (output / "progress.json").write_text(
                    json.dumps(
                        redact_secrets(summary, config), indent=2, ensure_ascii=False
                    )
                )
    measured = [
        row["official_reward"]
        for row in summary["results"]
        if row.get("official_reward") is not None
    ]
    summary["valid_trials"] = len(measured)
    summary["planned_trials"] = len(tasks) * config.get("num_trials", 1)
    summary["status"] = (
        "COMPLETED"
        if len(measured) == summary["planned_trials"]
        else "PARTIAL"
        if measured
        else "FAILED"
    )
    summary["mean_official_reward"] = (
        sum(measured) / len(measured) if measured else None
    )
    return redact_secrets(summary, config)


if __name__ == "__main__":
    print(json.dumps(execute(json.load(sys.stdin)), ensure_ascii=False))
