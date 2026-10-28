"""Deterministic prompt assembly from an allow-listed source pack."""

from __future__ import annotations

import json

from .suite_definition import SuiteDefinition


def build_prompt(suite: SuiteDefinition, source_pack: str) -> str:
    schema = suite.batch_type.model_json_schema()
    return (
        "你负责生成评测集语义候选，而不是完整的 EvalCase 对象。"
        "只返回一个严格符合所给 Schema 的 JSON object。"
        "不得提供思维过程、评分理由、case_id、断言权重、tool_profile、"
        "cleanup 数据或执行层标识符。\n\n"
        f"SUITE：{suite.suite_id}\nPROMPT_VERSION：{suite.prompt_version}\n\n"
        f"候选协议 STRICT SCHEMA：\n"
        f"{json.dumps(schema, ensure_ascii=False)}\n\n"
        f"SOURCE PACK：\n{source_pack}"
    )
