# mini_agent 评测实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement task-by-task.

**Goal:** 创建并执行105条 mini_agent 真实评测，交付可回溯报告和经验证的 Langfuse 展示。
**Architecture:** 复用现有 Provider/SDK/Inspect runner；可信领域注入；Docker bridge；DeepEval包装既有规则。
**Tech Stack:** Python 3.11、Inspect 0.3.280、DeepEval 4.2.9、Langfuse 5.0.2、Docker、deepseek-flash。
**Spec:** docs/superpowers/specs/2026-11-04-mini-agent-benchmark-design.md

## 约束与审阅重点
- 不改旧冻结数据或被测 Agent；明确测试 fixture 边界与确认能力缺口。
- Oracle 不进执行输入或模型消息；密钥不进容器、Git、日志。
- 身份/源 Hash固定；缺失证据不自动PASS；正式分母不含pilot。
- 普通测试不调用模型或托管服务；真实运行独立显式命令。

## 任务
- [ ] 编写领域/原生比较/执行投影回归并确认失败；实现领域注入及DeepEval评分（domain.py、mini_tasks.py、mini_scoring.py、runner.py、native_scoring.py）。
- [ ] 实现mini_adapter.py、mini_worker.py、包源码Docker构建及独立证据采集；注册已有MiniAgentProviderFactory，使用mock模型做桥接验收。
- [ ] 创建data/benchmarks/mini-agent-v1（生成器、任务、manifest、bundle、数据卡），锁定来源与人工预期，校验105条。
- [ ] 创建mini_cli.py和无密钥配置；复用报告与Langfuse导出；相关离线回归及独立审阅。
- [ ] 真实6条pilot；验证证据后执行105条，评分并生成报告，分析实际失败。
- [ ] 导出Langfuse、全量精确回读、浏览器抽查；全包回归、资产校验和全新克隆安装/demo验收；记录docs/migration与报告链接。

## 执行记录

- 领域投影/DeepEval/数据完整性测试：4 passed；Provider worker+SDK+参数/状态/回答/中断验收：8 passed（2026-11-04）。相关接入/导出离线测试25 passed；首次全包回归1144 passed、4 skipped，后续新增覆盖后再执行最终回归。
- Ruling：v1.0.0 已冻结后，离线检查发现新增工具预期遗漏nullable参数，以及查询答案未校验。保留v1.0.0，发布v1.0.1用于真实运行；历史93条Oracle不变。代价：同名任务需按manifest版本区分。
- Final review：mini_design_check 独立只读审阅。三项实质发现均纳入修复：中断时从持久SDK trace恢复事件并shield模型采证；查询fixture输出/EMPTY和回答一致性检查；报告识别新执行模式。另用有效工具参数执行回归定位新增Oracle缺陷。相关测试4 failed → 8 passed，记录artifacts/mini-agent/review-red.log和review-green.log。
- Ruling：查询回答一致性用确定性关键字段/措辞规则，避免额外LLM裁判费用；不能声称完整自然语言语义评价，报告说明严格措辞限制。
