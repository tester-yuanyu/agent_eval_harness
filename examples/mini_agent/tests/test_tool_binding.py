import json

import pytest

from minimal_agent.capabilities.cli import main as capability_main
from minimal_agent.cli import main as runtime_main
from minimal_agent.contracts.tools import ToolResult
from tests.support.model_client import DeterministicModelClient
from tests.support.tools import ECHO_CONTRACT, echo
from tests.test_runtime_agent import ready_intent, tool_call


def test_explicit_binding_rejects_missing_unknown_and_noncallable_handlers():
    from minimal_agent.runtime.tool_binding import bind_tools

    with pytest.raises(ValueError, match="missing"):
        bind_tools([ECHO_CONTRACT], {})
    with pytest.raises(ValueError, match="unknown"):
        bind_tools([ECHO_CONTRACT], {"echo": echo, "other": echo})
    with pytest.raises(ValueError, match="callable"):
        bind_tools([ECHO_CONTRACT], {"echo": None})
    with pytest.raises(ValueError, match="duplicate"):
        bind_tools([ECHO_CONTRACT, ECHO_CONTRACT], {"echo": echo})
    registry = bind_tools([ECHO_CONTRACT], {"echo": echo})
    assert registry.invoke("echo", {"text": "bound"}).data == {"text": "bound"}


def create_registry():
    from minimal_agent.runtime.tool_binding import bind_tools

    return bind_tools([ECHO_CONTRACT], {"echo": echo})


def invalid_factory():
    return {}


@pytest.mark.parametrize(
    "path",
    [
        "missing.module:factory",
        "tests.test_tool_binding:missing",
        "tests.test_tool_binding:ECHO_CONTRACT",
        "tests.test_tool_binding:invalid_factory",
        "tests.test_tool_binding",
    ],
)
def test_factory_errors_are_explicit(path):
    from minimal_agent.runtime.tool_binding import load_tool_registry

    with pytest.raises(ValueError):
        load_tool_registry(path)


def test_same_factory_drives_export_and_execution(tmp_path, capsys):
    factory = "tests.test_tool_binding:create_registry"
    assert (
        capability_main(
            [
                "export",
                "--output",
                str(tmp_path / "bundle"),
                "--tool-registry-factory",
                factory,
            ]
        )
        == 0
    )
    exported = json.loads(capsys.readouterr().out)
    assert exported["snapshot_counts"]["tool"] == 1
    client = DeterministicModelClient(
        [
            ready_intent(),
            tool_call(),
            {"type": "message", "content": "done"},
        ]
    )
    assert (
        runtime_main(
            ["run", "echo", "--tool-registry-factory", factory],
            openai_client_factory=lambda: client,
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert (
        result["tool_calls"][0]["output"]
        == ToolResult(
            success=True,
            code="OK",
            message="echoed",
            data={"text": "hello"},
        ).model_dump()
    )


def test_complete_export_fails_before_writing_if_bindings_are_missing(
    tmp_path,
    capsys,
):
    output = tmp_path / "missing"
    assert (
        capability_main(
            [
                "export",
                "--output",
                str(output),
                "--require-complete-tools",
            ]
        )
        == 1
    )
    error = json.loads(capsys.readouterr().err)
    assert "query_user_info" in error["message"]
    assert not output.exists()


def test_default_export_explicitly_warns_that_no_tools_are_registered(tmp_path, capsys):
    assert capability_main(["export", "--output", str(tmp_path / "empty")]) == 0
    captured = capsys.readouterr()
    assert "tool_count=0" in captured.err
    assert json.loads(captured.out)["snapshot_counts"]["tool"] == 0
