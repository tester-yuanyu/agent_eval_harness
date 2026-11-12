"""The current Harness must accept registered runtimes without nanobot imports."""

from __future__ import annotations

import copy
import json
import runpy
import sys
import time
from pathlib import Path

import pytest

from eval_framework.benchmark.runner import run_benchmark
from eval_framework.benchmark.tasks import execution_task, load_tasks
from eval_framework.errors import EvaluationPreflightError
from eval_framework.provider_registry import ProviderRegistry

ROOT = Path(__file__).resolve().parents[4]


class OfflineAdapter:
    provider_id = "offline-fixture"

    def __init__(self):
        self.received = []
        self.revision = 1

    def fingerprint_sources(self):
        return [Path(__file__)]

    def runtime_identity(self, mode=None):
        return {"agent": self.provider_id, "revision": self.revision}

    def needs_model(self, mode):
        return False

    def execution_kind(self, mode):
        return "offline_fixture"

    def inspect_model(self):
        raise AssertionError("offline adapter must not initialize a model")

    def sandbox_spec(self, output, *, needs_model):
        assert not needs_model
        return "local"

    async def execute(self, task, *, mode, config):
        self.received.append(copy.deepcopy(task))
        return {
            "status": "completed",
            "turns": [],
            "events": [],
            "usage": {},
            "errors": [],
            "before_files": dict(task["fixtures"]),
            "final_files": dict(task["fixtures"]),
            "runtime_identity": self.runtime_identity(mode),
            "evidence_complete": False,
        }


class AdapterFactory:
    def __init__(self, adapter):
        self.adapter = adapter

    def create_adapter(self, *, config):
        return self.adapter


def test_registered_adapter_runs_without_nanobot_and_never_receives_oracle(tmp_path):
    registry = ProviderRegistry()
    adapter = OfflineAdapter()
    registry.register(adapter.provider_id, AdapterFactory(adapter))
    task = load_tasks(ROOT / "data/benchmarks/file-tools-v2")[-1]
    run = run_benchmark(
        [task],
        dataset={"id": "adapter-contract-test"},
        config={"provider": adapter.provider_id},
        output=tmp_path,
        concurrency=1,
        provider_registry=registry,
    )
    assert adapter.received == [execution_task(task)]
    assert "oracle" not in adapter.received[0]
    assert run["identity"]["runtime"]["agent"] == adapter.provider_id
    assert run["identity"]["adapter"]["provider_id"] == adapter.provider_id
    assert run["summary"]["completed_trials"] == 1
    assert run["mode"] == "offline_fixture"
    assert run["trials"][0]["observation"]["execution_kind"] == "offline_fixture"
    assert run["trials"][0]["assessment"]["verdict"] != "PASS"
    assert (tmp_path / "inspect").is_dir()
    adapter.revision = 2
    with pytest.raises(ValueError, match="identity changed"):
        run_benchmark(
            [task],
            dataset={"id": "adapter-contract-test"},
            config={"provider": adapter.provider_id},
            output=tmp_path,
            concurrency=1,
            provider_registry=registry,
        )


def test_registry_rejects_unknown_or_incompatible_adapter():
    registry = ProviderRegistry()
    with pytest.raises(EvaluationPreflightError, match="unknown"):
        registry.create_adapter("missing", config={})
    registry.register("legacy-only", object())
    with pytest.raises(EvaluationPreflightError, match="benchmark"):
        registry.create_adapter("legacy-only", config={})
    registry.register("wrong", AdapterFactory(OfflineAdapter()))
    with pytest.raises(EvaluationPreflightError, match="created"):
        registry.create_adapter("wrong", config={})


WORKER = ROOT / "packages/evaluator/examples/offline_provider_worker.py"


def project_execution(task, mode):
    from eval_framework.schemas import ExecutionSpec

    assert "oracle" not in task
    return ExecutionSpec(
        user_input=task["prompt"],
        tool_profile="none",
        adapter_input={
            "input": {
                "operation": "inspect_snapshot",
                "declared_value": {"value": 42},
            },
            "preconditions": [],
        },
    ), "module"


def project_observation(output):
    return {
        "status": "completed",
        "observations": output.observations,
        "turns": [],
        "events": [],
        "usage": {},
        "errors": [],
        "evidence_complete": True,
    }


def provider_identity():
    return {"agent": "existing", "version": 1}


def provider_adapter(command=None):
    from eval_framework.agent_adapter import EvaluationProviderAdapter

    return EvaluationProviderAdapter(
        "existing",
        provider_version="external-binding-1.0",
        command=command or [sys.executable, str(WORKER)],
        project_execution=project_execution,
        project_observation=project_observation,
        identity=provider_identity,
        sources=[
            WORKER,
            ROOT / "packages/evaluator/src/eval_framework/providers/external",
        ],
    )


def test_existing_external_provider_lifecycle_cleanup_on_success_and_failure():
    from eval_framework.agent_adapter import execute_provider_request

    provider = runpy.run_path(str(WORKER))["create_provider"]()
    cleaned = []
    provider.cleanup = lambda runtime: cleaned.append(runtime)
    execution, scope = project_execution({"prompt": "public"}, "module")
    request = {"execution": execution.model_dump(mode="json"), "scope": scope}
    result = execute_provider_request(provider, request)
    assert result["output"]["observations"] == {"declared_value": {"value": 42}}
    assert len(cleaned) == 1

    def fail(runtime, execution):
        raise ValueError("Provider failed")

    provider.run_module = fail
    with pytest.raises(ValueError, match="Provider failed"):
        execute_provider_request(provider, request)
    assert len(cleaned) == 2
    with pytest.raises(ValueError, match="only public"):
        execute_provider_request(provider, {**request, "oracle": {}})


def test_existing_provider_runs_in_inspect_and_missing_evidence_stays_missing(tmp_path):
    adapter = provider_adapter()
    registry = ProviderRegistry()
    registry.register(adapter.provider_id, AdapterFactory(adapter))
    result = run_benchmark(
        load_tasks(ROOT / "data/benchmarks/file-tools-v2")[-1:],
        dataset={"id": "existing-provider"},
        config={"provider": adapter.provider_id},
        output=tmp_path,
        provider_registry=registry,
    )
    observation = result["trials"][0]["observation"]
    assert observation["observations"] == {"declared_value": {"value": 42}}
    assert observation["evidence_complete"] is False
    assert result["mode"] == "offline_provider"
    assert result["trials"][0]["assessment"]["verdict"] != "PASS"


@pytest.mark.parametrize("cancel_parent", [False, True])
def test_provider_worker_timeout_stops_process_and_receives_budget(
    tmp_path, cancel_parent
):
    import anyio
    from inspect_ai import Task
    from inspect_ai import eval as inspect_eval
    from inspect_ai.dataset import Sample
    from inspect_ai.solver import solver

    worker = tmp_path / "slow_worker.py"
    receipt = tmp_path / "receipt.json"
    completed = tmp_path / "completed"
    worker.write_text(
        "import json, pathlib, sys, time\n"
        f"pathlib.Path({str(receipt)!r}).write_text(json.dumps(json.load(sys.stdin)))\n"
        "time.sleep(1.5)\n"
        f"pathlib.Path({str(completed)!r}).write_text('still running')\n"
    )
    adapter = provider_adapter([sys.executable, str(worker)])
    timeouts = []

    @solver
    def execute():
        async def solve(state, generate):
            with pytest.raises(TimeoutError):
                with anyio.fail_after(0.4 if cancel_parent else 5):
                    await adapter.execute(
                        {"prompt": "public"},
                        mode="module",
                        config={
                            "timeout_seconds": 10 if cancel_parent else 0.4,
                            "max_steps": 2,
                        },
                    )
            timeouts.append(True)
            state.completed = True
            return state

        return solve

    inspect_eval(
        Task(
            dataset=[Sample(input="public")],
            solver=execute(),
            sandbox="local",
            time_limit=10,
        ),
        model="mockllm/model",
        display="none",
        ctl_server=False,
        notification=False,
        log_dir=str(tmp_path / "inspect"),
    )
    assert timeouts == [True]
    execution = json.loads(receipt.read_text())["execution"]
    assert execution["timeout_seconds"] == (10 if cancel_parent else 0.4)
    assert execution["max_steps"] == 2
    time.sleep(1.6)
    assert not completed.exists()


@pytest.mark.parametrize("mode_only", [False, True])
def test_identity_drift_preserves_logs_without_completed_result(tmp_path, mode_only):
    from eval_framework.benchmark.runner import RuntimeIdentityChanged

    class DriftingAdapter(OfflineAdapter):
        def runtime_identity(self, mode=None):
            return {"revision": 0 if mode_only and mode is None else self.revision}

        async def execute(self, task, *, mode, config):
            observation = await super().execute(task, mode=mode, config=config)
            self.revision += 1
            return observation

    adapter = DriftingAdapter()
    registry = ProviderRegistry()
    registry.register(adapter.provider_id, AdapterFactory(adapter))
    task = load_tasks(ROOT / "data/benchmarks/file-tools-v2")[-1]
    with pytest.raises(RuntimeIdentityChanged):
        run_benchmark(
            [task],
            dataset={"id": "drift-test"},
            config={"provider": adapter.provider_id},
            output=tmp_path,
            concurrency=1,
            provider_registry=registry,
        )
    assert not (tmp_path / "results.json").exists()
    assert not (tmp_path / ".running").exists()
    assert list((tmp_path / "inspect").glob("*.eval"))


def test_adapter_cannot_silently_downgrade_requested_sandbox(tmp_path):
    adapter = OfflineAdapter()
    registry = ProviderRegistry()
    registry.register(adapter.provider_id, AdapterFactory(adapter))
    with pytest.raises(ValueError, match="sandbox"):
        run_benchmark(
            load_tasks(ROOT / "data/benchmarks/file-tools-v2")[-1:],
            dataset={"id": "sandbox-contract"},
            config={"provider": adapter.provider_id, "sandbox": "docker"},
            output=tmp_path,
            provider_registry=registry,
        )
    assert not adapter.received


def test_mode_identity_is_frozen_for_resume(tmp_path):
    class ModeAdapter(OfflineAdapter):
        def runtime_identity(self, mode=None):
            return {"revision": 0 if mode is None else self.revision}

    adapter = ModeAdapter()
    registry = ProviderRegistry()
    registry.register(adapter.provider_id, AdapterFactory(adapter))
    arguments = dict(
        tasks=load_tasks(ROOT / "data/benchmarks/file-tools-v2")[-1:],
        dataset={"id": "mode-identity"},
        config={"provider": adapter.provider_id},
        output=tmp_path,
        provider_registry=registry,
    )
    run_benchmark(**arguments)
    adapter.revision += 1
    with pytest.raises(ValueError, match="identity changed"):
        run_benchmark(**arguments)


@pytest.mark.parametrize("cancel_parent", [False, True])
def test_provider_cleans_nested_processes_on_inspect_termination(
    tmp_path, cancel_parent
):
    import os

    import anyio
    import psutil
    from inspect_ai import Task
    from inspect_ai import eval as inspect_eval
    from inspect_ai.dataset import Sample
    from inspect_ai.solver import solver

    startup_budget = int(os.environ.get("EVAL_TEST_STARTUP_TIMEOUT", "30"))
    assert startup_budget >= 5
    started = tmp_path / "started"
    cleaned = tmp_path / "cleaned"
    child = tmp_path / "stdio_child.py"
    descendant = "import time; time.sleep(120)"
    child.write_text(
        "import subprocess,sys,time,pathlib,json,os\n"
        f"descendant = subprocess.Popen([sys.executable, '-c', {descendant!r}])\n"
        f"pathlib.Path({str(started)!r}).write_text("
        "json.dumps([os.getpid(), descendant.pid]))\n"
        "time.sleep(120)\n"
    )
    worker = tmp_path / "provider_worker.py"
    worker.write_text(
        "import json,sys,runpy,pathlib,time\n"
        "time.sleep(3)  # Deliberately slow startup before Provider imports.\n"
        "from eval_framework.agent_adapter import execute_provider_request\n"
        "from eval_framework.providers.external import RuntimeBinding\n"
        "from eval_framework.providers.external.binding import "
        "snapshot_runtime_binding\n"
        f"provider = runpy.run_path({str(WORKER)!r})['create_provider']()\n"
        "provider.binding = RuntimeBinding(version='1.0', agent_id='existing', "
        f"adapter='stdio', argv=[sys.executable, {str(child)!r}])\n"
        "provider._runtime_files = tuple(snapshot_runtime_binding(provider.binding))\n"
        "provider.cleanup = lambda runtime: "
        f"pathlib.Path({str(cleaned)!r}).write_text('cleaned')\n"
        "print(json.dumps(execute_provider_request(provider, json.load(sys.stdin))))\n"
    )
    adapter = provider_adapter([sys.executable, str(worker)])
    timeouts = []

    @solver
    def execute():
        async def solve(state, generate):
            async def wait_for_started(scope):
                with anyio.fail_after(startup_budget):
                    while not started.exists():
                        await anyio.sleep(0.05)
                if cancel_parent:
                    # Start the cancellation clock only after nested processes exist.
                    scope.deadline = anyio.current_time() + 0.1

            async with anyio.create_task_group() as group:
                with pytest.raises(TimeoutError):
                    with anyio.fail_after(startup_budget + 10) as scope:
                        group.start_soon(wait_for_started, scope)
                        await adapter.execute(
                            {"prompt": "public"},
                            mode="module",
                            config={
                                "timeout_seconds": startup_budget
                                + (5 if cancel_parent else 2)
                            },
                        )
            timeouts.append(True)
            state.completed = True
            return state

        return solve

    inspect_eval(
        Task(
            dataset=[Sample(input="public")],
            solver=execute(),
            sandbox="local",
            time_limit=startup_budget + 20,
        ),
        model="mockllm/model",
        display="none",
        ctl_server=False,
        notification=False,
        log_dir=str(tmp_path / "inspect"),
    )
    assert timeouts == [True]
    assert started.exists(), "test must reach the nested process"
    assert cleaned.exists(), "Provider cleanup was skipped"
    pids = json.loads(started.read_text())

    def still_running(pid):
        try:
            return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            return False

    deadline = time.monotonic() + 5
    while any(still_running(pid) for pid in pids) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not any(still_running(pid) for pid in pids), "nested process survived"
