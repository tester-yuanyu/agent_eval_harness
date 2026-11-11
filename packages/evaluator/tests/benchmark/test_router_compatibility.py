"""共享 Schema 校验保持同步错误接口和异步拒绝码。"""

import pytest
from eval_framework.environments.file_tools.schemas import TOOLS, file_tool_schemas
from eval_framework.harness.core.tool_router import ToolRouter as AsyncRouter
from eval_framework.harness.router import InvalidToolCall, ToolRouter
from inspect_ai.tool import ToolCall


@pytest.mark.parametrize(
    "name,args,code",
    [
        ("read_file", {"path": "a"}, None),
        ("write_file", {"path": "a", "content": "中文\r\n"}, None),
        ("list_dir", {}, None),
        ("write_file", {"path": "a"}, "missing_argument"),
        ("write_file", {"path": "a", "content": 1}, "argument_type"),
        ("list_dir", {"extra": "a"}, "invalid_argument"),
        ("unknown", {}, "tool_not_found"),
    ],
)
def test_sync_and_async_file_argument_decisions_match(name, args, code):
    sync = ToolRouter()
    async_router = AsyncRouter(file_tool_schemas([t[0] for t in TOOLS]))
    rejection = async_router.validate(ToolCall(id="a", function=name, arguments=args))
    assert (rejection.code if rejection else None) == code
    action = {"name": name, "arguments": args}
    if code:
        with pytest.raises(InvalidToolCall):
            sync.parse(action)
    else:
        assert sync.parse(action) == action


def test_sync_router_uses_environment_schema_without_coercing_or_mutating():
    class Environment:
        calls = []

        def tool_schemas(self):
            return [
                {
                    "name": "set_count",
                    "parameters": {
                        "type": "object",
                        "properties": {"count": {"type": "integer", "minimum": 1}},
                        "required": ["count"],
                        "additionalProperties": False,
                    },
                }
            ]

        def step(self, action):
            self.calls.append(action)
            return action["arguments"]["count"]

    environment = Environment()
    router = ToolRouter(environment)
    assert router.dispatch({"name": "set_count", "arguments": {"count": 2}}) == 2
    for arguments in ({"count": "2"}, {"count": 0}, {}, {"count": True}):
        with pytest.raises(InvalidToolCall):
            router.dispatch({"name": "set_count", "arguments": arguments})
    assert environment.calls == [{"name": "set_count", "arguments": {"count": 2}}]


def test_sync_allowed_tools_cannot_expand_environment_policy():
    class Environment:
        def tool_schemas(self):
            return file_tool_schemas(["read_file"])

    with pytest.raises(ValueError, match="unsupported allowed tools"):
        ToolRouter(Environment(), allowed_tools=["write_file"])


def test_sync_file_environment_exposes_independent_schema():
    from eval_framework.environments import FileToolsEnvironment

    environment = FileToolsEnvironment()
    schemas = environment.tool_schemas()
    schemas[0]["parameters"]["required"].clear()
    assert environment.tool_schemas()[0]["parameters"]["required"] == ["path"]
