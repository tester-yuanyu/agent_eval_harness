from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from eval_framework.capabilities import CapabilityBundle, CapabilityRegistry
from eval_framework.providers.external import (
    ExternalAdapterError,
    ExternalProvider,
    ExternalProviderFactory,
    RuntimeBinding,
    binding_supports,
    snapshot_runtime_binding,
)
from eval_framework.schemas import (
    DatasetBundle,
    EvalCase,
    ExecutionProfile,
    ExecutionSpec,
    ValidationReport,
)


def execution(adapter_input: dict[str, object], *, timeout_seconds: float = 2.0):
    return ExecutionSpec.model_validate(
        {
            "user_input": "adapter fixture",
            "tool_profile": "none",
            "timeout_seconds": timeout_seconds,
            "adapter_input": adapter_input,
        }
    )


def provider(binding: RuntimeBinding) -> ExternalProvider:
    registry = CapabilityRegistry(
        CapabilityBundle(
            root=".",
            provider_id=binding.agent_id,
            bundle_format_version="3.0",
            capability_bundle_sha256="a" * 64,
            documents=(),
        )
    )
    return ExternalProvider(
        binding,
        registry,
        execution_profiles={"none": ExecutionProfile(allowed_tools=[])},
        runtime_files=snapshot_runtime_binding(binding),
    )


def dataset(adapter_input: dict[str, object]) -> DatasetBundle:
    item = EvalCase.model_validate(
        {
            "schema_version": "1.0",
            "case_id": "external-1",
            "task_id": "sdk",
            "scenario_type": "normal",
            "test_scope": "module",
            "target": "sdk",
            "execution": {
                "user_input": "adapter fixture",
                "tool_profile": "none",
                "adapter_input": adapter_input,
            },
            "oracle": {
                "evaluation": {
                    "checks": [
                        {
                            "name": "observations_match",
                            "weight": 1,
                            "critical": True,
                            "config": {
                                "checks": [
                                    {
                                        "path": "/declared_value",
                                        "operator": "equals",
                                        "expected": "fixture",
                                    }
                                ]
                            },
                        }
                    ]
                }
            },
        }
    )
    return DatasetBundle(
        path="cases.jsonl",
        sha256="a" * 64,
        schema_versions=["1.0"],
        dataset_version="1",
        provider_id="other_agent",
        capability_bundle_path="/frozen/capabilities",
        capability_bundle_sha256="a" * 64,
        execution_profiles={"none": ExecutionProfile(allowed_tools=[])},
        total_count=1,
        cases=[item],
    )
def run(value: ExternalProvider, spec: ExecutionSpec):
    runtime = value.create_runtime(spec, "session-1", "module")
    try:
        return value.run_module(runtime, spec)
    finally:
        value.cleanup(runtime)


def write_worker(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "worker.py"
    path.write_text(body, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "payload",
    [
        {"version": "1.0", "agent_id": "a", "adapter": "static", "env": {}},
        {
            "version": "1.0",
            "agent_id": "a",
            "adapter": "static",
            "env_names": ["TOKEN=secret"],
        },
        {
            "version": "1.0",
            "agent_id": "a",
            "adapter": "stdio",
            "argv": [],
        },
    ],
)
def test_runtime_binding_rejects_extras_inline_env_and_empty_command(payload):
    with pytest.raises(ValidationError):
        RuntimeBinding.model_validate(payload)


def test_binding_supports_only_fixed_adapter_operations():
    static = RuntimeBinding(version="1.0", agent_id="fixture", adapter="static")
    assert binding_supports(
        static,
        {
            "input": {
                "operation": "validate_schema",
                "schema": {"type": "integer"},
                "instance": 3,
            },
            "preconditions": [],
        },
    ) == (True, None)
    assert binding_supports(
        static,
        {
            "input": {
                "operation": "validate_schema",
                "schema_ref": {"path": "bundle/tool.json"},
                "instance": 3,
            },
            "preconditions": [],
        },
    ) == (False, "static validate_schema requires an inline schema")

    nanobot = RuntimeBinding(
        version="1.0",
        agent_id="nanobot",
        adapter="nanobot_local",
        agent_root=Path("/opt/nanobot"),
        python=Path("/usr/bin/python3"),
    )
    supported = {
        "input": {
            "operation": "invoke_module",
            "entrypoint": "result_from_response",
            "arguments": {"response": None, "capture": {"fixture_ref": "capture"}},
        },
        "preconditions": [{"fixture": "capture"}],
    }
    assert binding_supports(nanobot, supported) == (True, None)
    ok, reason = binding_supports(
        nanobot,
        {
            "input": {"operation": "invoke_sdk", "entrypoint": "Nanobot.run"},
            "preconditions": [],
        },
    )
    assert ok is False
    assert reason == "nanobot_local does not support invoke_sdk/Nanobot.run"


def test_static_adapter_returns_observations_without_oracle_comparison():
    value = provider(
        RuntimeBinding(version="1.0", agent_id="fixture", adapter="static")
    )
    valid = run(
        value,
        execution(
            {
                "input": {
                    "operation": "validate_schema",
                    "schema": {"type": "integer"},
                    "instance": 3,
                },
                "preconditions": [],
            }
        ),
    )
    assert valid.observations == {"schema_validation": {"valid": True}}

    declared = run(
        value,
        execution(
            {
                "input": {
                    "operation": "inspect_snapshot",
                    "declared_value": {"enabled": True},
                },
                "preconditions": [],
            }
        ),
    )
    assert declared.observations == {"declared_value": {"enabled": True}}


def test_adapter_boundary_failures_are_not_classified_as_agent_quality():
    value = provider(
        RuntimeBinding(version="1.0", agent_id="fixture", adapter="static")
    )
    for code in (
        "SOURCE_HASH_MISMATCH",
        "PROTOCOL_RESPONSE_INVALID",
        "OPERATION_UNSUPPORTED",
    ):
        classified = value.classify_exception(ExternalAdapterError(code, "invalid"))
        assert classified.execution_status == "EVALUATOR_ERROR"
    assert value.classify_exception(
        ExternalAdapterError("ADAPTER_PROCESS_FAILED", "exit")
    ).execution_status == "AGENT_EXCEPTION"
    assert value.classify_exception(
        ExternalAdapterError("ADAPTER_TIMEOUT", "timeout")
    ).execution_status == "OUTER_TIMEOUT"


def test_factory_uses_binding_agent_id_and_reports_unsupported_cases(monkeypatch):
    registry = CapabilityRegistry(
        CapabilityBundle(
            root=".",
            provider_id="other_agent",
            bundle_format_version="3.0",
            capability_bundle_sha256="a" * 64,
            documents=(),
        )
    )
    monkeypatch.setattr(
        "eval_framework.providers.external.provider._load_registry",
        lambda *args, **kwargs: registry,
    )
    monkeypatch.setattr(
        "eval_framework.providers.external.provider.validate_core_dataset",
        lambda *args, **kwargs: ValidationReport(valid=True, issues=[]),
    )
    factory = ExternalProviderFactory()
    binding = {
        "version": "1.0",
        "agent_id": "other_agent",
        "adapter": "static",
    }
    supported = dataset(
        {
            "input": {
                "operation": "inspect_snapshot",
                "declared_value": "fixture",
            },
            "preconditions": [],
        }
    )
    assert factory.validate_dataset(supported, binding=binding).valid
    created = factory.create(supported, binding=binding)
    assert created.provider_id == "other_agent"
    assert not hasattr(factory, "provider_id")

    unsupported = dataset(
        {"input": {"operation": "future_operation"}, "preconditions": []}
    )
    report = factory.validate_dataset(unsupported, binding=binding)
    assert report.valid is False
    assert report.issues[0].case_id == "external-1"
    assert report.issues[0].message == "static does not support future_operation"


def test_factory_fingerprint_sources_are_bounded(tmp_path):
    factory = ExternalProviderFactory()
    default_sources = factory.fingerprint_sources()
    assert default_sources == [
        Path(
            sys.modules[ExternalProviderFactory.__module__].__file__
        ).resolve().parent
    ]

    sdk_types = tmp_path / "nanobot/sdk/types.py"
    sdk_types.parent.mkdir(parents=True)
    sdk_types.write_text("# fixture", encoding="utf-8")
    runtime_context = tmp_path / "nanobot/runtime_context.py"
    runtime_context.write_text("# fixture", encoding="utf-8")
    nanobot_sources = factory.fingerprint_sources(
        binding={
            "version": "1.0",
            "agent_id": "nanobot",
            "adapter": "nanobot_local",
            "agent_root": str(tmp_path),
            "python": sys.executable,
        }
    )
    assert sdk_types in nanobot_sources
    assert runtime_context in nanobot_sources
    assert tmp_path not in nanobot_sources

    worker = tmp_path / "worker.py"
    worker.write_text("# fixture", encoding="utf-8")
    stdio_sources = factory.fingerprint_sources(
        binding={
            "version": "1.0",
            "agent_id": "other_agent",
            "adapter": "stdio",
            "python": sys.executable,
            "argv": [str(worker), "--non-file-secret=hidden"],
        }
    )
    assert worker in stdio_sources
    assert all("hidden" not in str(item) for item in stdio_sources)


def test_runtime_snapshot_binds_argv_interpreter_and_code_file(tmp_path):
    worker = write_worker(
        tmp_path,
        "import json,sys\njson.load(sys.stdin)\n"
        "json.dump({'protocol_version':'1.0','observations':{}},sys.stdout)\n",
    )
    binding = RuntimeBinding(
        version="1.0",
        agent_id="other_agent",
        adapter="stdio",
        argv=[sys.executable, "-I", str(worker), "/tmp/non-code-output.json"],
    )
    identities = snapshot_runtime_binding(binding)
    paths = {item.path for item in identities}
    assert Path(sys.executable).resolve() in paths
    assert worker.resolve() in paths
    assert Path("/tmp/non-code-output.json") not in paths

    value = provider(binding)
    worker.write_text("raise SystemExit(0)\n", encoding="utf-8")
    with pytest.raises(ExternalAdapterError) as changed:
        run(
            value,
            execution({"input": {"operation": "custom"}, "preconditions": []}),
        )
    assert changed.value.code == "RUNTIME_FILE_MISMATCH"


def test_deleted_runtime_file_is_an_evaluator_error(tmp_path):
    worker = write_worker(
        tmp_path,
        "import json,sys\njson.load(sys.stdin)\n"
        "json.dump({'protocol_version':'1.0','observations':{}},sys.stdout)\n",
    )
    binding = RuntimeBinding(
        version="1.0",
        agent_id="other_agent",
        adapter="stdio",
        python=Path(sys.executable),
        argv=[str(worker)],
    )
    value = provider(binding)
    worker.unlink()

    with pytest.raises(ExternalAdapterError) as missing:
        run(
            value,
            execution({"input": {"operation": "custom"}, "preconditions": []}),
        )
    assert missing.value.code == "RUNTIME_FILE_INVALID"
    assert value.classify_exception(missing.value).execution_status == "EVALUATOR_ERROR"


def test_default_plugin_catalog_registers_external_provider():
    from eval_framework.composition import default_plugin_catalog
    from eval_framework.plugins.models import PluginReference

    registration = default_plugin_catalog().resolve(
        PluginReference(
            plugin_id="external_provider_v1",
            version="1.0.0",
            config={
                "binding": {
                    "version": "1.0",
                    "agent_id": "other_agent",
                    "adapter": "static",
                }
            },
        ),
        expected_kind="provider",
        contract_version="1.0",
        field_path="$.provider",
    )
    assert isinstance(registration.implementation, ExternalProviderFactory)


def test_stdio_sends_only_protocol_and_execution_and_hides_env_values(tmp_path):
    worker = write_worker(
        tmp_path,
        """import json, os, sys
request = json.load(sys.stdin)
json.dump({
    "protocol_version": "1.0",
    "observations": {
        "request_keys": sorted(request),
        "execution_keys": sorted(request["execution"]),
        "has_secret": (
            os.environ.get("EXTERNAL_PROVIDER_TEST_SECRET") == "sensitive-value"
        ),
    },
}, sys.stdout)
""",
    )
    os.environ["EXTERNAL_PROVIDER_TEST_SECRET"] = "sensitive-value"
    binding = RuntimeBinding(
        version="1.0",
        agent_id="fixture",
        adapter="stdio",
        python=Path(sys.executable),
        argv=[str(worker)],
        env_names=["EXTERNAL_PROVIDER_TEST_SECRET"],
    )
    value = provider(binding)
    spec = execution(
        {"input": {"operation": "custom"}, "preconditions": []}
    )
    output = run(value, spec)
    assert output.observations["request_keys"] == ["execution", "protocol_version"]
    assert "adapter_input" in output.observations["execution_keys"]
    assert output.observations["has_secret"] is True
    metadata = value.runtime_metadata(value.create_runtime(spec, "s", "module"))
    assert metadata["env_names"] == ["EXTERNAL_PROVIDER_TEST_SECRET"]
    assert "sensitive-value" not in json.dumps(metadata)


@pytest.mark.parametrize(
    "response",
    [
        {"protocol_version": "1.0", "observations": {}, "score": 1},
        {"protocol_version": "1.0", "observations": {}, "evidence": {}},
        {"protocol_version": "2.0", "observations": {}},
        {"protocol_version": "1.0", "observations": []},
    ],
)
def test_stdio_rejects_non_protocol_response(tmp_path, response):
    worker = write_worker(
        tmp_path,
        "import json, sys\njson.load(sys.stdin)\n"
        f"json.dump({response!r}, sys.stdout)\n",
    )
    value = provider(
        RuntimeBinding(
            version="1.0",
            agent_id="fixture",
            adapter="stdio",
            python=Path(sys.executable),
            argv=[str(worker)],
        )
    )
    with pytest.raises(ExternalAdapterError, match="response"):
        run(
            value,
            execution({"input": {"operation": "custom"}, "preconditions": []}),
        )


def test_stdio_enforces_output_bound_and_timeout(tmp_path):
    noisy = write_worker(
        tmp_path,
        "import sys\nsys.stdout.write('x' * 1024)\n",
    )
    value = provider(
        RuntimeBinding(
            version="1.0",
            agent_id="fixture",
            adapter="stdio",
            python=Path(sys.executable),
            argv=[str(noisy)],
            max_output_bytes=64,
        )
    )
    with pytest.raises(ExternalAdapterError) as bounded:
        run(
            value,
            execution({"input": {"operation": "custom"}, "preconditions": []}),
        )
    assert bounded.value.code == "OUTPUT_LIMIT_EXCEEDED"

    sleepy = write_worker(tmp_path, "import time\ntime.sleep(10)\n")
    value = provider(
        RuntimeBinding(
            version="1.0",
            agent_id="fixture",
            adapter="stdio",
            python=Path(sys.executable),
            argv=[str(sleepy)],
            timeout_seconds=0.05,
        )
    )
    with pytest.raises(ExternalAdapterError) as timed_out:
        run(
            value,
            execution({"input": {"operation": "custom"}, "preconditions": []}),
        )
    assert timed_out.value.code == "ADAPTER_TIMEOUT"


def test_stdio_timeout_kills_the_worker_process_group(tmp_path):
    sentinel = tmp_path / "child-survived"
    child_code = (
        "import pathlib,time;time.sleep(.3);"
        f"pathlib.Path({str(sentinel)!r}).write_text('alive')"
    )
    worker = write_worker(
        tmp_path,
        "import subprocess,sys,time\n"
        f"subprocess.Popen([sys.executable, '-c', {child_code!r}])\n"
        "time.sleep(10)\n",
    )
    value = provider(
        RuntimeBinding(
            version="1.0",
            agent_id="fixture",
            adapter="stdio",
            python=Path(sys.executable),
            argv=[str(worker)],
            timeout_seconds=0.1,
        )
    )
    with pytest.raises(ExternalAdapterError) as timed_out:
        run(
            value,
            execution({"input": {"operation": "custom"}, "preconditions": []}),
        )
    assert timed_out.value.code == "ADAPTER_TIMEOUT"
    time.sleep(0.35)
    assert not sentinel.exists()


def test_stdio_timeout_interrupts_a_worker_that_never_reads_stdin(tmp_path):
    worker = write_worker(tmp_path, "import time\ntime.sleep(.3)\n")
    value = provider(
        RuntimeBinding(
            version="1.0",
            agent_id="fixture",
            adapter="stdio",
            python=Path(sys.executable),
            argv=[str(worker)],
            timeout_seconds=0.05,
        )
    )
    spec = execution(
        {
            "input": {"operation": "custom", "payload": "x" * 2_000_000},
            "preconditions": [],
        }
    )
    started = time.monotonic()
    with pytest.raises(ExternalAdapterError) as timed_out:
        run(value, spec)
    assert timed_out.value.code == "ADAPTER_TIMEOUT"
    assert time.monotonic() - started < 0.25


def test_stdio_uses_isolated_cwd_and_does_not_echo_stderr_secrets(tmp_path):
    cwd_worker = write_worker(
        tmp_path,
        "import json,os,sys\njson.load(sys.stdin)\n"
        "json.dump({'protocol_version':'1.0','observations':"
        "{'cwd':os.getcwd()}},sys.stdout)\n",
    )
    value = provider(
        RuntimeBinding(
            version="1.0",
            agent_id="fixture",
            adapter="stdio",
            python=Path(sys.executable),
            argv=[str(cwd_worker)],
        )
    )
    output = run(
        value,
        execution({"input": {"operation": "custom"}, "preconditions": []}),
    )
    assert output.observations["cwd"] != str(Path.cwd())

    secret = "stderr-sensitive-value"
    os.environ["EXTERNAL_PROVIDER_STDERR_SECRET"] = secret
    failing_worker = write_worker(
        tmp_path,
        "import os,sys\n"
        "sys.stderr.write(os.environ['EXTERNAL_PROVIDER_STDERR_SECRET'])\n"
        "raise SystemExit(3)\n",
    )
    value = provider(
        RuntimeBinding(
            version="1.0",
            agent_id="fixture",
            adapter="stdio",
            python=Path(sys.executable),
            argv=[str(failing_worker)],
            env_names=["EXTERNAL_PROVIDER_STDERR_SECRET"],
        )
    )
    with pytest.raises(ExternalAdapterError) as failed:
        run(
            value,
            execution({"input": {"operation": "custom"}, "preconditions": []}),
        )
    assert failed.value.code == "ADAPTER_PROCESS_FAILED"
    assert secret not in str(failed.value)


def test_nanobot_source_hash_is_verified_before_worker_execution(tmp_path):
    source = tmp_path / "nanobot/sdk/types.py"
    source.parent.mkdir(parents=True)
    source.write_text("raise RuntimeError('must not execute')\n", encoding="utf-8")
    (tmp_path / "nanobot/runtime_context.py").write_text(
        "def public_history_messages(messages): return list(messages)\n",
        encoding="utf-8",
    )
    binding = RuntimeBinding(
        version="1.0",
        agent_id="nanobot",
        adapter="nanobot_local",
        agent_root=tmp_path,
        python=Path(sys.executable),
    )
    value = provider(binding)
    spec = execution(
        {
            "input": {
                "operation": "construct_and_serialize",
                "class_name": "RunResult",
                "arguments": {"content": "fixture"},
                "serializer": "dataclasses.asdict",
            },
            "preconditions": [],
            "source_files": [
                {"path": "nanobot/sdk/types.py", "sha256": "0" * 64}
            ],
        }
    )
    with pytest.raises(ExternalAdapterError) as mismatch:
        run(value, spec)
    assert mismatch.value.code == "SOURCE_HASH_MISMATCH"
    assert hashlib.sha256(source.read_bytes()).hexdigest() != "0" * 64


def test_nanobot_fixed_worker_supports_only_the_three_sdk_candidates(tmp_path):
    source = tmp_path / "nanobot/sdk/types.py"
    source.parent.mkdir(parents=True)
    (tmp_path / "nanobot/__init__.py").write_text(
        "raise RuntimeError('package init must not execute')\n", encoding="utf-8"
    )
    (tmp_path / "nanobot/sdk/__init__.py").write_text(
        "raise RuntimeError('sdk init must not execute')\n", encoding="utf-8"
    )
    runtime_context = tmp_path / "nanobot/runtime_context.py"
    runtime_context.write_text(
        "def public_history_messages(messages):\n    return list(messages)\n",
        encoding="utf-8",
    )
    source.write_text(
        """from dataclasses import dataclass, field
from nanobot.runtime_context import public_history_messages
@dataclass
class RunResult:
    content: str
    tools_used: list = field(default_factory=list)
    messages: list = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    stop_reason: str | None = None
    error: str | None = None
    metadata: dict = field(default_factory=dict)
def result_from_response(response, capture):
    return RunResult(
        content=(response.content if response else None) or "",
        tools_used=capture.tools_used,
        messages=capture.messages,
        usage=capture.usage,
        stop_reason=capture.stop_reason,
        error=capture.error,
        metadata=(response.metadata if response else None) or {},
    )
""",
        encoding="utf-8",
    )
    source_files = [
        {
            "path": "nanobot/sdk/types.py",
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        },
        {
            "path": "nanobot/runtime_context.py",
            "sha256": hashlib.sha256(runtime_context.read_bytes()).hexdigest(),
        },
    ]
    value = provider(
        RuntimeBinding(
            version="1.0",
            agent_id="nanobot",
            adapter="nanobot_local",
            agent_root=tmp_path,
            python=Path(sys.executable),
        )
    )

    serialized = run(
        value,
        execution(
            {
                "input": {
                    "operation": "construct_and_serialize",
                    "class_name": "RunResult",
                    "arguments": {"content": "fixture result"},
                    "serializer": "dataclasses.asdict",
                },
                "preconditions": [{"fixture": "sdk_value_object_only"}],
                "source_files": source_files,
            }
        ),
    )
    assert serialized.observations["result"] == {
        "content": "fixture result",
        "tools_used": [],
        "messages": [],
        "usage": {},
        "stop_reason": None,
        "error": None,
        "metadata": {},
    }

    for response, content, metadata in (
        (None, "", {}),
        (
            {"fixture_ref": "response"},
            "fixture result",
            {"request_id": "fixture-01"},
        ),
    ):
        preconditions = [
            {
                "fixture": "capture",
                "tools_used": ["fixture_tool"],
                "messages": [],
                "usage": {"input_tokens": 3},
                "stop_reason": "fixture_terminal",
                "error": None,
            }
        ]
        if response is not None:
            preconditions.append(
                {
                    "fixture": "response",
                    "content": "fixture result",
                    "metadata": metadata,
                }
            )
        merged = run(
            value,
            execution(
                {
                    "input": {
                        "operation": "invoke_module",
                        "entrypoint": "result_from_response",
                        "arguments": {
                            "response": response,
                            "capture": {"fixture_ref": "capture"},
                        },
                    },
                    "preconditions": preconditions,
                    "source_files": source_files,
                }
            ),
        )
        assert merged.observations["result"]["content"] == content
        assert merged.observations["result"]["metadata"] == metadata
    assert not list(tmp_path.rglob("__pycache__"))
