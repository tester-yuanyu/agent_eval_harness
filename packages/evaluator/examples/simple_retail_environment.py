"""离线领域扩展示例：注入库存环境，不修改 Harness 或调用真实模型。

运行：python examples/simple_retail_environment.py --output artifacts/retail-demo
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from eval_framework.environments import EnvironmentFailure, ToolExecutionError


class SimpleRetailEnvironment:
    """单 sample 的内存库存；业务错误允许 Agent 恢复。"""

    def __init__(self) -> None:
        self._inventory: dict[str, int] | None = None

    async def reset(self, initial_state: dict[str, Any]) -> None:
        stock = initial_state.get("inventory")
        if not isinstance(stock, dict) or any(
            not isinstance(item, str) or type(qty) is not int or qty < 0
            for item, qty in stock.items()
        ):
            raise EnvironmentFailure(
                "inventory must map item names to nonnegative integers"
            )
        self._inventory = deepcopy(stock)

    def tool_schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "reserve",
                "description": "Reserve available stock",
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "item": {"type": "string"},
                        "quantity": {"type": "integer", "minimum": 1},
                    },
                    "required": ["item", "quantity"],
                },
            }
        ]

    async def step(self, name: str, arguments: dict[str, Any]) -> str:
        if self._inventory is None:
            raise EnvironmentFailure("reset the environment before use")
        item, quantity = arguments.get("item"), arguments.get("quantity")
        if (
            name != "reserve"
            or not isinstance(item, str)
            or type(quantity) is not int
            or quantity < 1
        ):
            raise ToolExecutionError("invalid reservation")
        if quantity > self._inventory.get(item, 0):
            raise ToolExecutionError("insufficient stock")
        self._inventory[item] -= quantity
        return json.dumps({"reserved": quantity, "item": item})

    async def snapshot(self) -> dict[str, Any]:
        if self._inventory is None:
            raise EnvironmentFailure("reset the environment before use")
        return {"inventory": deepcopy(self._inventory)}

    async def teardown(self) -> None:
        self._inventory = None


def run_demo(output: Path) -> dict[str, Any]:
    """运行真实 Harness 和 Inspect transcript，模型输出固定且不联网。"""
    from eval_contracts.benchmark import TaskInput
    from inspect_ai import Task
    from inspect_ai import eval as inspect_eval
    from inspect_ai.dataset import Sample
    from inspect_ai.model import ChatMessageAssistant, ModelOutput, get_model
    from inspect_ai.solver import Generate, Solver, TaskState, solver
    from inspect_ai.tool import ToolCall

    from eval_framework.harness.adapters.inspect_solver import execute_native_task

    task = TaskInput(
        task_id="retail-demo",
        prompt="Reserve two apples",
        initial_state={"inventory": {"apple": 3}},
        tools=["reserve"],
    )
    outputs = []
    for identifier, quantity in (("too-many", 9), ("retry", 2)):
        response = ModelOutput.from_content("mockllm/model", "")
        response.choices[0].message = ChatMessageAssistant(
            content="",
            tool_calls=[
                ToolCall(
                    id=identifier,
                    function="reserve",
                    arguments={"item": "apple", "quantity": quantity},
                )
            ],
        )
        outputs.append(response)
    outputs.append(ModelOutput.from_content("mockllm/model", "Reserved two apples"))

    @solver
    def retail_solver() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            await execute_native_task(
                task, environment=SimpleRetailEnvironment(), task_state=state
            )
            return state

        return solve

    log = inspect_eval(
        Task(
            dataset=[Sample(id=task.task_id, input=task.prompt, target="")],
            solver=retail_solver(),
        ),
        model=get_model("mockllm/model", custom_outputs=outputs),
        log_dir=str(output),
        display="none",
        notification=False,
        ctl_server=False,
    )[0]
    if log.status != "success":
        raise RuntimeError(str(log.error))
    return log.samples[0].metadata["harness_observation"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/retail-demo"))
    args = parser.parse_args()
    row = run_demo(args.output)
    print(
        json.dumps(
            {"status": row["status"], "state": row["final_files"]}, ensure_ascii=False
        )
    )
