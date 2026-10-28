# 完整 fixture 能力评测集（待审核）

能力包 SHA-256：`215a9a3a445c8857f3bdd8dbecba935ce646bd8c784f16ecfc4a5da6042cce3c`
23 个目标，847 个覆盖项；行为案例 365 条，静态契约检查 202 条，阻塞义务 280 条。

**这些不是全部已可执行的测试。** EvalCase 子集通过真实 evaluator 静态校验；契约案例通过独立 Schema，仍需运行适配。所有实际执行状态为 NOT_RUN，所有人工批准为 PENDING。

| 层级 | 行为案例 | 契约检查 | 阻塞义务 |
|---|---:|---:|---:|
| modules | 167 | 103 | 106 |
| tools | 150 | 99 | 122 |
| critical_links | 32 | 0 | 33 |
| end_to_end | 16 | 0 | 19 |

## 文件入口

- `manifest.json`：分组文件路径、格式、数量与 Hash。
- `datasets/modules/`：模块与七种意图。
- `datasets/tools/`：六个工具。
- `datasets/critical_links/`：两条关键链路。
- `datasets/end_to_end/`：端到端。
- `coverage_matrix.json`：所有目标、覆盖项、来源与 blocker 的映射。
- `review.md`：行为案例的未勾选审核清单。
- `reports/validation.json`：静态校验结果。
- `blockers.json`：能力缺口及尚未映射的语义义务。

## 消费与限制

`eval_case` 文件才可传给 evaluator 的 load_dataset；与其同目录的 Manifest 提供 execution_profiles。
`capability_contract_case` 是独立定义协议，不能直接传给现有 evaluator。
工具 test_fixture 不是生产后端。各工具案例需要独立初始化；幂等序列内部共享一次 fixture。
原生工具目录尚不能直接理解 v3 工具快照的 operation/fault 字段；校验使用 source-derived ToolCatalog，不代表已注册 runtime handler。
单轮端到端早停仅验证 turns_match 的终态与零调用，不声称完成确认恢复或业务写入。
错误分支需要受控故障注入 adapter；当前 native runtime 不支持，故这些是待适配定义。
静态契约检查只核对快照声明，不计入行为覆盖率。blocked_obligation 无具体可执行 Oracle，不得作为已生成的有效行为测试运行。

## 本地复验

在 Builder 根目录执行：
```bash
PYTHONPATH=src ../agent_evaluator/.venv/bin/python -m dataset_builder.cli validate-full --workspace "/Users/yuanyu/Documents/ChatGPT/agent_dataset_builder/workspaces/full_tools_fixture_v1_full_eval_20261020"
```

复验只检查文件、协议、来源与覆盖，不调用 Agent 或付费模型。
