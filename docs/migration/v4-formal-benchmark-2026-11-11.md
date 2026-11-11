# v4 正式 Harness 与 DeepSeek 评测

后续48条连接失败补测、G-Eval及云端交付记录见 [v4网络恢复交付](v4-recovery-2026-11-11.md)。下文末尾保留首次运行时的网络阻塞记录，不代表后续补测状态。

本轮只使用 `output/mini_agent_full_eval_20261111_v4/dataset`。历史115条数据集不属于本次范围，先前误启动的历史集已停止并独立保存，不合并分数。

## 执行与评分边界

365条行为定义全部重新经过 benchmark Harness / Inspect 调度，在每例独立Docker environment中运行，DeepEval拥有规则评分。28条意图模块、21条提前停止、27条正常/故障链路使用OpenCode配置的DeepSeek；233条Schema、35条工具行为、21条模块机制使用确定性驱动。六个工具均为隔离fixture，不能解释成生产后端验证。

Builder原始JSON和Oracle保持不变。Loader检查来源manifest、所有文件Hash、case载荷、参数Schema及能力文档；公开执行投影只含输入、执行计划、fixture与能力契约，不含case/Oracle。MiniAgent业务代码本轮未修改。

真实模型使用既有DeepSeekModelClient，经Inspect sandbox_agent_bridge访问OpenCode；密钥仅留在主机，worker使用本地代理令牌。意图结果和工具选择由真实模型产生。参考驱动中的固定候选和固定JSON回复不是正式模型断言，正式评分读取原用例Oracle及独立运行证据。

G-Eval复用现有DeepEval rubric与审计客户端，在保存证据上评价动作适当性、故障后处理和回复事实依据；事件按实际时间排序，同轮状态单独绑定。289条确定性案例标为NOT_APPLICABLE，不调用Judge。无后续动作或缺少完整证据时保留MISSING，不补造分数。沿用现有未校准语义：G-Eval是单独的质量评分，不覆盖规则FAIL，也不凭未设定的阈值生成综合通过率。

## 运行命令

使用Evaluator独立环境；下列run和judge会调用真实模型，export会上传已保存任务、执行证据与评分。本次用户已明确授权。输出必须是新目录，不自动重跑付费执行；judge按Hash绑定的journal续跑已保存评分。

```bash
.venvs/evaluator/bin/python scripts/mini_agent_v4_benchmark.py validate --output artifacts/mini-agent/v4-deepseek-formal-20261111-r2
.venvs/evaluator/bin/python scripts/mini_agent_v4_benchmark.py run --output artifacts/mini-agent/v4-deepseek-formal-20261111-r2 --concurrency 8
.venvs/evaluator/bin/python scripts/mini_agent_v4_benchmark.py judge --output artifacts/mini-agent/v4-deepseek-formal-20261111-r2
.venvs/evaluator/bin/python scripts/mini_agent_v4_benchmark.py report --output artifacts/mini-agent/v4-deepseek-formal-20261111-r2
.venvs/evaluator/bin/python scripts/mini_agent_v4_benchmark.py export --output artifacts/mini-agent/v4-deepseek-formal-20261111-r2
.venvs/evaluator/bin/python scripts/mini_agent_v4_benchmark.py verify --output artifacts/mini-agent/v4-deepseek-formal-20261111-r2
```

默认从`.env`读取OPENCODE_MODEL、OPENCODE_BASE_URL、OPENCODE_API_KEY和Langfuse配置。执行最多400次Agent请求、每例一次、不自动重试；Judge使用三项G-Eval维度，每例最多16次请求，不启动另外三个native agentic指标。模型和Judge用量分别保存，未知成本不填零。

## 产物

- `execution/`：365条Harness结果、原生Inspect日志及独立environment证据。
- `judged/`：独立评分结果、逐项G-Eval理由/请求记录、报告与Langfuse导出回执；保留source_results_sha256，不改执行结果。
- 854条原始定义中另有202条静态契约检查和287条blocked义务，仍保留在Builder交付内，不混入365条行为成功率，也不通过本次运行自动冻结或宣布整份交付可发布。

## 工程验收

详见同目录 `v4-formal-benchmark-plan-2026-11-11.md` 的执行记录及 `tmp/v4-formal/` 日志。

## 首次运行结果与当时未完成项

v4-r2共365条全部形成执行记录：289条确定性PASS；76条真实模型为13PASS、15FAIL、48INVALID（模型连接错误）。规则合计302PASS/15FAIL/48INVALID。实际成功模型响应为deepseek-v4.1-flash；记录到36条成功generation及48条失败generation，已知token小计28284，失败请求成本未知。

OpenCode只读接口与Langfuse云端TLS仍超时，G-Eval未运行、Langfuse未上传。代码接入、离线贯通和本地规则报告已完成，不能宣称本轮正式评测交付完整。保存pipeline_status.json与剩余judge/report/export/verify命令；继续评分不重跑Agent，48条INVALID需在网络恢复后另行有来源关联的补测，不能由Judge补造成功。

最终目录artifacts/mini-agent/v4-deepseek-formal-20261111-r2包含README、execution/report.html、failure_details.json和完整Inspect证据。1448份文件及压缩日志未发现实际OpenCode/Langfuse密钥泄漏。
