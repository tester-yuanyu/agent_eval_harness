"""Registered mini_agent adapter: Provider lifecycle inside Inspect Docker bridge."""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from inspect_ai.model import (
        ChatMessage,
        GenerateConfig,
        GenerateFilter,
        GenerateInput,
        Model,
    )
    from inspect_ai.tool import ToolChoice, ToolInfo

from .inspect_docker import bind_docker_environment, source_digest
from .inspect_runtime import aggregate_usage, inspect_model, model_evidence
from .package_sandbox import package_inputs, prepare_package_sandbox
from .request_budget import RequestBudget


def opencode_bridge_filter(
    config: dict, *, budget: RequestBudget | None = None
) -> GenerateFilter | None:
    """Attach truthful client identity and one session per trial conversation."""
    is_opencode = urlsplit(config.get("base_url") or "").hostname == "opencode.ai"
    if not is_opencode and budget is None:
        return None

    from inspect_ai.model import GenerateInput

    session_id = str(uuid.uuid4())

    async def apply_headers(
        model: Model,
        messages: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice | None,
        generation: GenerateConfig,
    ) -> GenerateInput:
        if budget is not None:
            budget.reserve()
        if not is_opencode:
            return GenerateInput(messages, tools, tool_choice, generation)
        headers = {
            **(generation.extra_headers or {}),
            "User-Agent": "agent-eval-suite/0.1.0",
            "x-opencode-session": session_id,
        }
        return GenerateInput(
            messages,
            tools,
            tool_choice,
            generation.model_copy(update={"extra_headers": headers}),
        )

    return apply_headers


def project_events(output: dict) -> list[dict]:
    raw = output.get("trace_events") or []
    result = []
    for index in sorted({e["turn_index"] for e in raw}):
        group = [e for e in raw if e["turn_index"] == index]
        parent = "turn-" + group[0]["run_id"]
        kinds = {event["event_type"] for event in group}
        complete = "run_finished" in kinds or (
            "run_started" not in kinds and "intent_decided" in kinds
        )
        turn_record = next(
            (
                t
                for t in output.get("turns", [])
                if t.get("run_id") == group[0]["run_id"]
            ),
            {},
        )
        user_input = next(
            (e["payload"]["user_input"] for e in group if "user_input" in e["payload"]),
            None,
        )
        result.append(
            dict(
                id=parent,
                type="turn",
                name=f"turn {index + 1}",
                turn=index + 1,
                start_time=group[0]["timestamp"],
                end_time=group[-1]["timestamp"] if complete else None,
                input={"user_input": user_input},
                output={
                    k: turn_record[k]
                    for k in ("status", "final_response")
                    if k in turn_record
                },
                incomplete=not complete,
            )
        )
        for event in group:
            result.append(
                dict(
                    id=event["event_id"],
                    type="event",
                    name=event["event_type"],
                    start_time=event["timestamp"],
                    end_time=event["timestamp"],
                    input=event["payload"],
                    output={},
                    parent_id=parent,
                    turn=index + 1,
                    source="agent_trace_sdk",
                    incomplete=False,
                )
            )
        for request in (e for e in group if e["event_type"] == "tool_requested"):
            call = request["payload"]
            terminal = next(
                (
                    e
                    for e in group
                    if e["payload"].get("call_id") == call["call_id"]
                    and e["event_type"]
                    in {"tool_succeeded", "tool_failed", "tool_timeout"}
                ),
                None,
            )
            result.append(
                dict(
                    id="tool-" + request["event_id"],
                    type="tool",
                    name=call["name"],
                    tool_call_id=call["call_id"],
                    start_time=request["timestamp"],
                    end_time=terminal["timestamp"] if terminal else None,
                    input=call["arguments"],
                    output=terminal["payload"] if terminal else None,
                    parent_id=parent,
                    turn=index + 1,
                    incomplete=terminal is None,
                    error=terminal["payload"].get("error") if terminal else None,
                )
            )
    # SQLite observations are independent reads, attached to their completed turns.
    for index, snapshot in enumerate(output.get("turn_snapshots", [])):
        turn = next(
            (e for e in result if e["type"] == "turn" and e["turn"] == index + 1), None
        )
        if turn:
            turn["output"]["state"] = snapshot
    return result


class MiniAgentBenchmarkAdapter:
    provider_id = "mini_agent"

    def __init__(self, config: dict):
        self.config = dict(config)
        self.request_budget = RequestBudget(config.get("max_model_requests"))
        root = Path(config["repository_root"]).resolve(strict=True)
        self.packages = {
            name: root / path
            for name, path in {
                "contracts": "packages/contracts",
                "trace": "packages/agent-trace-sdk",
                "agent": "examples/mini_agent",
                "evaluator": "packages/evaluator",
            }.items()
        }
        self.bundle = Path(config["capability_bundle"]).resolve(strict=True)

    def fingerprint_sources(self):
        return [root / "src" for root in self.packages.values()]

    def runtime_identity(self, mode=None):
        return {
            "provider_id": self.provider_id,
            "version": "mini-inspect-v1",
            "mode": mode,
            "source_sha256": source_digest(package_inputs(self.packages, self.bundle)),
            "model": self.config.get("model"),
            "isolation": "docker",
            "fixture_implementation": "public-provider-test-fixtures-v1",
        }

    def needs_model(self, mode):
        if mode not in {"module", "agent"}:
            raise ValueError("unsupported mini_agent mode")
        return True

    def execution_kind(self, mode):
        return (
            "real_model_intent" if mode == "module" else "real_agent_test_environment"
        )

    def inspect_model(self):
        return inspect_model(self.config)

    def sandbox_spec(self, output: Path, *, needs_model: bool):
        self.output = output.parent
        return prepare_package_sandbox(
            self.packages,
            self.bundle,
            output,
            base_image=self.config.get("docker_base_image", "python:3.11-slim"),
        )

    async def execute(self, task: dict, *, mode: str, config: dict):
        import anyio
        from inspect_ai.agent import sandbox_agent_bridge
        from inspect_ai.log import transcript
        from inspect_ai.util import sandbox

        env = sandbox()
        start = len(transcript().events)
        result = dict(
            status="error",
            turns=[],
            events=[],
            usage={},
            errors=[],
            evidence_complete=False,
            runtime_identity=self.runtime_identity(mode),
            isolation="docker",
            execution_backend="inspect_ai",
            before_files={},
            final_files={},
        )
        prefix = [
            "env",
            "-i",
            "PATH=/usr/local/bin:/usr/bin:/bin",
            "DEEPEVAL_TELEMETRY_OPT_OUT=YES",
        ]
        setup = await env.exec(
            prefix
            + [
                "python",
                "-c",
                "import json,platform,importlib.metadata as m; "
                "print(json.dumps({'python':platform.python_version(),"
                "'packages':{d.metadata['Name']:d.version "
                "for d in m.distributions()}}))",
            ]
        )
        if not setup.success:
            raise RuntimeError("Provider sandbox setup failed: " + setup.stderr)
        runtime = json.loads(setup.stdout)
        result["runtime_environment"] = {
            **runtime,
            "docker_binding": bind_docker_environment(
                config["_inspect_docker_compose"], runtime
            ),
        }
        pending = None
        try:
            async with sandbox_agent_bridge(
                forward_generation_config=True,
                filter=opencode_bridge_filter(config, budget=self.request_budget),
            ) as bridge:
                finished = await env.exec(
                    prefix + ["python", "-m", "eval_framework.benchmark.mini_worker"],
                    input=json.dumps(
                        {
                            "task": task,
                            "bridge_url": f"http://localhost:{bridge.port}/v1",
                        }
                    ),
                    timeout=config.get("timeout_seconds", 120),
                )
                if not finished.success:
                    raise RuntimeError(
                        f"Provider worker exited {finished.returncode}: "
                        f"{finished.stderr[-2000:]}"
                    )
                result.update(json.loads(finished.stdout))
        except BaseException as exc:
            result["errors"].append(
                {"kind": "execution", "code": type(exc).__name__, "message": str(exc)}
            )
            if not isinstance(exc, Exception):
                pending = exc
        finally:
            # Preserve partial evidence on cancellation before re-raising to Inspect.
            with anyio.CancelScope(shield=True):
                with anyio.move_on_after(15):
                    try:
                        from agent_trace_sdk import EvidenceReader

                        content = await env.read_file("evidence/trace.inspect.json")
                        directory = self.output / "evidence" / uuid.uuid4().hex
                        directory.mkdir(parents=True, exist_ok=False)
                        target = directory / "trace.inspect.json"
                        target.write_text(content)
                        result["native_evidence"] = {
                            "path": str(target.relative_to(self.output)),
                            "sha256": hashlib.sha256(content.encode()).hexdigest(),
                        }
                        output = result.setdefault("adapter_output", {})
                        events, manifest = EvidenceReader().read(
                            directory, memory_manifest=output.get("evidence_manifest")
                        )
                        if output.get("trace_events") not in (None, events):
                            result["evidence_complete"] = False
                            result["errors"].append(
                                {"kind": "evidence", "code": "WORKER_DISK_MISMATCH"}
                            )
                        output.update(
                            trace_events=events,
                            evidence_manifest=manifest,
                            evidence_status=manifest["status"],
                        )
                        result["evidence_complete"] = bool(
                            result["evidence_complete"]
                            and manifest["status"] == "COMPLETE"
                        )
                    except Exception as exc:
                        result["evidence_complete"] = False
                        result["errors"].append(
                            {
                                "kind": "evidence",
                                "code": "PERSISTED_EVIDENCE_MISSING",
                                "message": str(exc),
                            }
                        )
                    output = result.get("adapter_output", {})
                    result["events"] = project_events(output)
                    generations = await model_evidence(
                        transcript().events[start:], result["events"]
                    )
                    result["events"].extend(generations)
                    result["usage"] = aggregate_usage(generations)
                    if output.get("module_output") is not None:
                        result["turns"] = [
                            {
                                "input": task["execution"]["user_input"],
                                "output": json.dumps(
                                    output["module_output"], ensure_ascii=False
                                ),
                            }
                        ]
                    else:
                        result["turns"] = [
                            {**turn, "output": turn.get("final_response", "")}
                            for turn in output.get("turns", [])
                        ]
                result["evidence_complete"] = bool(
                    result["evidence_complete"]
                    and any(e["type"] == "generation" for e in result["events"])
                    and not any(e.get("incomplete") for e in result["events"])
                )
        if pending:
            pending.benchmark_observation = result
            raise pending
        return result
