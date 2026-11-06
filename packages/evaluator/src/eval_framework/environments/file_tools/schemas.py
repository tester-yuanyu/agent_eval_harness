"""文件领域工具声明；不依赖 Harness 或 Agent SDK。"""

from typing import Any

from ..base.protocol import ToolExecutionError

# name、description、字符串参数、参数是否全部可选。
TOOLS = (
    ("read_file", "Read a UTF-8 file", ("path",), False),
    ("write_file", "Write a UTF-8 file", ("path", "content"), False),
    (
        "edit_file",
        "Replace one matching occurrence",
        ("path", "old_text", "new_text"),
        False,
    ),
    ("list_dir", "List entries in a directory", ("path",), True),
)


def file_tool_schemas(allowed_tools: list[str]) -> list[dict[str, Any]]:
    if not set(allowed_tools) <= {tool[0] for tool in TOOLS}:
        raise ValueError("unknown file tool in task policy")
    return [
        {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {field: {"type": "string"} for field in fields},
                "required": [] if optional else list(fields),
            },
        }
        for name, description, fields, optional in TOOLS
        if name in allowed_tools
    ]


def validate_call(
    schemas: list[dict[str, Any]], name: str, arguments: dict[str, Any]
) -> None:
    schema = next((schema for schema in schemas if schema["name"] == name), None)
    if schema is None:
        raise ToolExecutionError("unsupported file operation")
    parameters = schema["parameters"]
    if (
        not isinstance(arguments, dict)
        or not set(parameters["required"]) <= arguments.keys()
        or not arguments.keys() <= parameters["properties"].keys()
        or any(not isinstance(value, str) for value in arguments.values())
    ):
        raise ToolExecutionError("invalid tool arguments")
