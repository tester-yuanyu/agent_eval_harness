# Nanobot 独立评测候选集

Agent：nanobot 0.3.0；能力包：`b5dbc1184326a2d3edd641b046b6cba7029bd6f71ef7f561ac9367a787d6655f`。

35 个快照、31 个主要目标（8 模块、21 工具、1 意图、1 端到端链）；129 个 JSONL 文件。

参数/输出Schema契约用例 1599 条；行为候选 90 条；静态声明检查 529 条；阻塞义务 160 条。

**DRAFT / NOT_RUN / PENDING。现有 EvalCase 兼容条数为 0；这是独立候选协议，尚未运行 Agent。**

| 层级 | Schema用例 | 行为候选 | 声明检查 | 阻塞义务 |
|---|---:|---:|---:|---:|
| modules | 317 | 19 | 79 | 9 |
| tools | 1088 | 70 | 399 | 147 |
| critical_links | 0 | 0 | 0 | 1 |
| end_to_end | 0 | 1 | 8 | 2 |
| contracts | 194 | 0 | 43 | 1 |

## 入口

- [完整文件清单](manifest.json)
- [生成约束](GENERATION_CONSTRAINTS.md)
- [覆盖矩阵](coverage_matrix.json)
- [能力和适配缺口](blockers.json)
- [静态校验报告](reports/validation.json)
- [行为候选审核清单](review.md)
- [工具用例](datasets/tools/)
- [模块与意图用例](datasets/modules/)
- [关键链路缺口](datasets/critical_links/README.md)
- [端到端定义](datasets/end_to_end/)

## 阅读方式

先看 behavior_candidate 文件中的前置fixture、输入和oracle。schema_contract仅检查参数/输出Schema，不代表实际工具行为。contract_check只核对声明，blocked_obligation没有足够运行依据。unknown执行能力未被升级。端到端边界冲突和关键链路缺失已显式列出。

source_delivery/保留完整输入；inventory.json含适配后的参数Schema；capability_ir.json是当前对话选择的统一IR，不代表全部工具已归入该链。generator_sources/保留本次生成器与候选目录证据。

## 复验

在Builder根目录执行（将目录替换为本交付路径）：

```bash
PYTHONPATH=src ../agent_evaluator/.venv/bin/python -m dataset_builder.cli validate-nanobot --workspace workspaces/nanobot_full_eval_20261023
```

本目录与mini_agent评测集独立；复验不调用Agent、工具或外部服务。
