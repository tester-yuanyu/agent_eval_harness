"""离线演示：Inspect 自研循环、真实本地文件工具和 DeepEval 正式评分。

仅使用 Inspect mockllm；不接受真实模型配置，不上传任何托管服务。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from inspect_ai.model import ChatMessageAssistant, ModelOutput, get_model
from inspect_ai.tool import ToolCall

from eval_framework.benchmark.runner import run_benchmark
from eval_framework.harness.adapters.runtime import RawModelRuntimeAdapter
from eval_framework.provider_registry import ProviderRegistry


def answer(messages, tools, tool_choice, config):
    result = ModelOutput.from_content("mockllm/model", "Created result.txt")
    if messages[-1].role == "user":
        result.choices[0].message = ChatMessageAssistant(
            content="",
            tool_calls=[
                ToolCall(
                    id="create",
                    function="write_file",
                    arguments={"path": "result.txt", "content": "hello"},
                )
            ],
        )
    return result


class DemoAdapter(RawModelRuntimeAdapter):
    def inspect_model(self):
        return get_model("mockllm/model", custom_outputs=answer)

    def runtime_identity(self, mode=None):
        return {
            **super().runtime_identity(mode),
            "demo": "scripted-mock-not-agent-score",
        }


class DemoFactory:
    def create_adapter(self, *, config):
        return DemoAdapter(config)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    registry = ProviderRegistry()
    registry.register("raw_model", DemoFactory())
    task = {
        "id": "native-offline-demo",
        "category": "create_edit",
        "family": "demo",
        "split": "dev",
        "prompt": "Create result.txt containing hello",
        "followups": [],
        "fixtures": {},
        "max_steps": 3,
        "allowed_tools": ["write_file"],
        "required_tools": ["write_file"],
        "oracle": {"expected_files": {"result.txt": "hello"}},
        "reference": [
            {
                "tool": "write_file",
                "arguments": {"path": "result.txt", "content": "hello"},
            }
        ],
    }
    run = run_benchmark(
        [task],
        dataset={"id": "synthetic-native-offline-demo-v1"},
        config={"provider": "raw_model", "model": "mockllm/model", "sandbox": "local"},
        output=args.output,
        concurrency=1,
        provider_registry=registry,
    )
    row = run["trials"][0]
    print(
        json.dumps(
            {
                "verdict": row["assessment"]["verdict"],
                "stop_reason": row["observation"]["stop_reason"],
                "output": str(args.output),
                "meaning": "框架离线验收，不代表 nanobot 或真实模型成绩",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if row["assessment"]["verdict"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
