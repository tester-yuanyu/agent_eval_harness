import json
import os
import subprocess
from pathlib import Path

import pytest
from eval_framework.benchmark.tau_adapter import (
    TAU_COMMIT,
    interpreter_path,
    redact_secrets,
    validate_config,
    verify_imported_tau,
    verify_source,
    worker_environment,
)


def test_tau_worker_excludes_ambient_credentials_and_optional_judge(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "selected-agent-key")
    monkeypatch.setenv("OPENAI_API_KEY", "ambient-openai-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ambient-anthropic-key")
    monkeypatch.setenv("PYTHONSTARTUP", "/unrelated/startup.py")
    config = {"source_root": "/source", "nanobot_root": "/nanobot"}
    env = worker_environment(config)
    assert env["DEEPSEEK_API_KEY"] == "selected-agent-key"
    assert "OPENAI_API_KEY" not in env
    assert "ANTHROPIC_API_KEY" not in env
    assert "PYTHONSTARTUP" not in env
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert env["GIT_CONFIG_GLOBAL"] == os.devnull
    enabled = {**config, "allow_official_judge": True}
    assert worker_environment(enabled)["OPENAI_API_KEY"] == "ambient-openai-key"
    assert redact_secrets("ambient-openai-key", enabled) == "[REDACTED]"


def test_empty_and_failed_tau_evidence_never_passes():
    from eval_framework.benchmark.tau_worker import evidence_issues

    assert evidence_issues([], "user_stop")
    events = [
        {"id": "turn", "type": "turn", "end_time": "done", "output": "answer"},
        {"id": "agent", "type": "generation", "end_time": "done", "output": {}},
        {
            "id": "user",
            "type": "generation",
            "participant": "user_simulator",
            "end_time": "done",
            "output": {},
        },
    ]
    assert evidence_issues(events, "user_stop") == []
    events[1].update(output=None, error="provider_failure")
    assert evidence_issues(events, "user_stop")
    assert any(
        p["code"] == "official_termination" for p in evidence_issues(events, "timeout")
    )


def test_wrong_imported_tau_source_is_rejected(tmp_path):
    expected = tmp_path / "pinned/src/tau2/__init__.py"
    expected.parent.mkdir(parents=True)
    expected.touch()
    wrong = tmp_path / "unrelated-tau2.py"
    wrong.touch()
    assert verify_imported_tau(str(expected), str(tmp_path / "pinned")) == str(expected)
    with pytest.raises(ValueError, match="outside the pinned source"):
        verify_imported_tau(str(wrong), str(tmp_path / "pinned"))


def test_venv_interpreter_symlink_is_not_resolved(tmp_path):
    target = tmp_path / "base-python"
    target.touch()
    venv_python = tmp_path / "venv/bin/python"
    venv_python.parent.mkdir(parents=True)
    venv_python.symlink_to(target)
    assert interpreter_path(str(venv_python)) == venv_python
    assert interpreter_path(str(venv_python)) != target


def test_secret_redaction_uses_worker_default_and_explicit_credentials(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-default-secret")
    monkeypatch.setenv("TAU_USER_KEY", "test-user-secret")
    value = {"errors": ["bad test-default-secret / test-user-secret"]}
    assert redact_secrets(value, {"user_api_key_env": "TAU_USER_KEY"}) == {
        "errors": ["bad [REDACTED] / [REDACTED]"]
    }


def test_run_wrapper_preserves_venv_and_redacts_artifacts(tmp_path, monkeypatch):
    from eval_framework.benchmark import tau_adapter

    base = tmp_path / "base-python"
    base.touch()
    selected = tmp_path / "venv/bin/python"
    selected.parent.mkdir(parents=True)
    selected.symlink_to(base)
    source = tmp_path / "source"
    source.mkdir()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "offline-secret-value")
    monkeypatch.setattr(tau_adapter, "verify_source", lambda _: {"commit": TAU_COMMIT})
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps({"error": "offline-secret-value"}),
            "provider error offline-secret-value",
        )

    monkeypatch.setattr(tau_adapter.subprocess, "run", fake_run)
    config = {
        "source_commit": TAU_COMMIT,
        "domain": "retail",
        "task_ids": ["0"],
        "source_root": str(source),
        "nanobot_root": str(source),
        "python": str(selected),
    }
    output = tmp_path / "artifacts"
    result = tau_adapter.run_tau(config, output, dry_run=True)
    assert commands[0][0] == str(selected)
    assert result["error"] == "[REDACTED]"
    assert "offline-secret-value" not in (output / "validation.json").read_text()
    assert "offline-secret-value" not in (output / "worker.log").read_text()


def test_tau_pin_and_explicit_task_subset_are_required():
    with pytest.raises(ValueError, match="commit"):
        validate_config({"source_commit": "main"})
    with pytest.raises(ValueError, match="task_ids"):
        validate_config(
            {"source_commit": TAU_COMMIT, "domain": "retail", "task_ids": []}
        )
    with pytest.raises(ValueError, match="retail"):
        validate_config(
            {"source_commit": TAU_COMMIT, "domain": "airline", "task_ids": ["0"]}
        )


def test_tau_pin_verification_rejects_mutated_tracked_content(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", str(source)], check=True, capture_output=True)
    (source / "policy.md").write_text("frozen")
    subprocess.run(["git", "-C", str(source), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "fixture",
        ],
        check=True,
        capture_output=True,
    )
    commit = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    assert verify_source(source, commit)["commit"] == commit
    (source / "policy.md").write_text("mutated")
    with pytest.raises(ValueError, match="modified"):
        verify_source(source, commit)


@pytest.mark.parametrize("cutoff", [False, True])
def test_real_nanobot_tau_tool_rendezvous_offline(tmp_path, cutoff):
    repo = Path(__file__).resolve().parents[4]
    python = repo / ".venvs/tau/bin/python"
    source = repo / ".sources/tau2-bench"
    nanobot = Path(os.environ.get("NANOBOT_TEST_ROOT", "/Users/yuanyu/Desktop/nanobot"))
    if not python.exists() or not source.exists() or not nanobot.exists():
        pytest.skip("optional pinned tau/nanobot environment unavailable")
    probe = subprocess.run(
        [str(python), "-c", "import tau2, nanobot"],
        env={**os.environ, "PYTHONPATH": str(nanobot), "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
    )
    if probe.returncode:
        pytest.skip("optional tau dependencies not installed")
    from eval_framework.benchmark import tau_adapter

    script = r'''
import json, sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from tau_worker import make_nanobot_agent
from tau2.environment.tool import as_tool
from tau2.data_model.message import UserMessage, ToolMessage, AssistantMessage
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.base import LLMResponse, ToolCallRequest
def lookup(value: str) -> str:
    """Return an actual deterministic fixture lookup."""
    return "record:"+value
count=0
async def chat(self,messages,**kwargs):
    global count
    count+=1
    assert {t["function"]["name"] for t in kwargs["tools"]} == {"lookup"}
    if count==1:
        assert any("PUBLIC_DOMAIN_POLICY" in str(m) for m in messages)
        assert not any("PRIVATE_EXPECTED_RESULT" in str(m) for m in messages)
        call=ToolCallRequest("original-id","lookup",{"value":"abc"})
        return LLMResponse(None,[call])
    assert any("record:abc" in str(m) for m in messages)
    if count==3:
        assert any("Lookup returned record:abc" in str(m) for m in messages)
        return LLMResponse("The previous lookup was record:abc")
    return LLMResponse("Lookup returned record:abc")
OpenAICompatProvider.chat=chat
cfg={"nanobot_root":sys.argv[2],"agent_model":"offline","agent_api_key_env":"TEST_TAU_KEY","tokenizer_mode":"byte_fallback","timeout_seconds":20}
tool=as_tool(lookup)
agent=make_nanobot_agent([tool],"PUBLIC_DOMAIN_POLICY",cfg,Path(sys.argv[3]))
greeting=AssistantMessage(role="assistant",content="How can I help?")
state=agent.get_init_state([greeting])
try:
    request=UserMessage(role="user",content="Look up abc")
    first,state=agent.generate_next_message(request,state)
    call=first.tool_calls[0]
    actual=tool(**call.arguments)
    if sys.argv[4] == "cutoff":
        agent.stop(ToolMessage(role="tool",id=call.id,content=actual),state)
        journal_path=Path(sys.argv[3])/"nanobot-events.jsonl"
        records=[json.loads(line) for line in journal_path.read_text().splitlines()]
        tool_events=[r for r in records if r.get("type")=="tool"]
        print(json.dumps({"tool_event":tool_events[-1],"model_calls":count}))
        raise SystemExit(0)
    second,state=agent.generate_next_message(ToolMessage(role="tool",id=call.id,content=actual),state)
    followup=UserMessage(role="user",content="What was the previous lookup?")
    third,state=agent.generate_next_message(followup,state)
    print(json.dumps({"first":first.model_dump(mode="json"),
        "second":second.model_dump(mode="json"),"third":third.content}))
finally:
    agent.stop()
'''
    result = subprocess.run(
        [
            str(python),
            "-c",
            script,
            str(Path(tau_adapter.__file__).parent),
            str(nanobot),
            str(tmp_path),
            "cutoff" if cutoff else "normal",
        ],
        env={
            **os.environ,
            "PYTHONPATH": str(nanobot),
            "PYTHONDONTWRITEBYTECODE": "1",
            "TAU2_DATA_DIR": str(source / "data"),
            "LITELLM_LOCAL_MODEL_COST_MAP": "True",
        },
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=50,
    )
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout.strip().splitlines()[-1])
    if cutoff:
        assert output["tool_event"]["output"] == "record:abc"
        assert output["tool_event"]["termination_capture"] is True
        assert output["model_calls"] == 1
        return
    assert output["first"]["tool_calls"][0]["name"] == "lookup"
    assert output["second"]["content"] == "Lookup returned record:abc"
    assert output["third"] == "The previous lookup was record:abc"


def test_official_reward_and_user_flow_with_offline_transports(tmp_path):
    """The real official DB evaluator must see nanobot's executed tool call."""
    repo = Path(__file__).resolve().parents[4]
    python = repo / ".venvs/tau/bin/python"
    source = repo / ".sources/tau2-bench"
    nanobot = Path(os.environ.get("NANOBOT_TEST_ROOT", "/Users/yuanyu/Desktop/nanobot"))
    if not python.exists() or not source.exists() or not nanobot.exists():
        pytest.skip("optional pinned tau/nanobot environment unavailable")
    env = {
        **os.environ,
        "PYTHONPATH": str(nanobot),
        "PYTHONDONTWRITEBYTECODE": "1",
        "TAU2_DATA_DIR": str(source / "data"),
        "LITELLM_LOCAL_MODEL_COST_MAP": "True",
        "TEST_TAU_KEY": "offline-no-network",
    }
    probe = subprocess.run(
        [str(python), "-c", "import tau2, nanobot"], env=env, capture_output=True
    )
    if probe.returncode:
        pytest.skip("optional tau dependencies not installed")
    from eval_framework.benchmark import tau_adapter

    script = r"""
import json,os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from tau_worker import execute
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.base import LLMResponse, ToolCallRequest
from tau2.data_model.message import AssistantMessage
import tau2.user.user_simulator as us
calls=0
async def chat(self,messages,**kwargs):
    global calls
    calls+=1
    if calls==1:
        args={"order_id":"#W2378156","item_ids":["1151293680","4983901480"],
            "new_item_ids":["7706410293","7747408585"],
            "payment_method_id":"credit_card_9513926"}
        return LLMResponse(None,[ToolCallRequest("exchange",
            "exchange_delivered_order_items",args)])
    return LLMResponse("Your exchange has been submitted.")
OpenAICompatProvider.chat=chat
ucalls=0
def user_generate(**kwargs):
    global ucalls
    ucalls+=1
    return AssistantMessage(role="assistant",content=(
        "Please submit the confirmed exchange for my order #W2378156."
        if ucalls==1 else "###STOP###"),usage={"prompt_tokens":3,"completion_tokens":2})
us.generate=user_generate
cfg={"nanobot_root":sys.argv[2],"agent_model":"offline","domain":"retail",
    "source_root":str(Path(os.environ["TAU2_DATA_DIR"]).parent),
    "task_ids":["0"],"user_model":"offline","timeout_seconds":20,
    "agent_api_key_env":"TEST_TAU_KEY","user_api_key_env":"TEST_TAU_KEY"}
print(json.dumps(execute({"config":cfg,"output":sys.argv[3]})))
"""
    result = subprocess.run(
        [
            str(python),
            "-c",
            script,
            str(Path(tau_adapter.__file__).parent),
            str(nanobot),
            str(tmp_path),
        ],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout.strip().splitlines()[-1])
    assert summary["status"] == "COMPLETED", summary
    assert summary["results"][0]["official_reward"] == 1
    assert summary["results"][0]["reward_info"]["db_check"]["db_match"] is True
    observed = json.loads(Path(summary["results"][0]["observation_path"]).read_text())
    assert (
        sum(e.get("participant") == "user_simulator" for e in observed["events"]) == 2
    )
    assert any(
        e["name"] == "exchange_delivered_order_items" for e in observed["events"]
    )
