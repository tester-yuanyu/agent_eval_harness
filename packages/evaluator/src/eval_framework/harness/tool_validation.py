"""运行方式中立的工具 Schema 校验；不执行工具、不记录事件。"""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from jsonschema.validators import validator_for


@dataclass(frozen=True)
class Rejection:
    code: str
    message: str


class ToolSchemaValidator:
    def __init__(self, schemas: list[dict[str, Any]]) -> None:
        self.schemas = {}
        self.validators = {}
        for original in schemas:
            schema = deepcopy(original)
            name, parameters = schema["name"], schema["parameters"]
            if name in self.schemas:
                raise ValueError(f"duplicate tool: {name}")
            validator = validator_for(parameters)
            validator.check_schema(parameters)
            self.schemas[name] = schema
            self.validators[name] = validator(parameters)

    def validate(
        self, name: str, arguments: Any, *, parse_error: str | None = None
    ) -> Rejection | None:
        if name not in self.schemas:
            return Rejection("tool_not_found", f"Unknown tool: {name}")
        if parse_error:
            return Rejection("invalid_argument", parse_error)
        error = next(self.validators[name].iter_errors(arguments), None)
        if error:
            code = {"required": "missing_argument", "type": "argument_type"}.get(
                error.validator, "invalid_argument"
            )
            return Rejection(code, error.message)
        return None
