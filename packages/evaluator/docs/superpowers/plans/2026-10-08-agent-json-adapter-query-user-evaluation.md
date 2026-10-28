# Agent JSON Adapter 与 QueryUser 评测精简实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` task-by-task in the current workspace. Do not use
> subagents unless the user explicitly requests delegation.

**Goal:** 在不改变 Evaluator Runner、断言和评分的前提下，让 mini_agent Provider
加载 `capabilities/agent.json`，完成 42 条冻结 QueryUser Case 的 native DeepSeek
评测，并保留 QueryUser 全链路工具注入能力。

**Architecture:** 现有 `MiniAgentAdapter` 已经是执行与结果协议桥：module 调用
`run_intent_only()`，full-chain 调用 `MinimalAgent.run()`，再读取 `IntentResult`、
`AgentResult`、`tool_calls`、`events` 和 `intent_trace_snapshot()`。本次不改这条链路，
只在它之前补充 `agent.json -> CapabilityRegistry` 转换，以及 per-Trial ToolRegistry
绑定。

**Spec:**
`docs/superpowers/specs/2026-10-08-agent-json-adapter-query-user-evaluation-design.md`

## 不变边界

- `src/eval_framework/runner.py` 不改；
- `src/eval_framework/assertions.py` 不改；
- 评分与报告协议不改；
- `src/eval_framework/mini_agent_adapter.py` 原则上不改，仅通过测试确认已有桥接；
- 42 条 JSONL、FROZEN Manifest、Coverage 和冻结 Bundle 内容不改；
- 不新增 CI，不默认运行 Judge；
- Evaluator 不导入 `minimal_agent.capabilities.v3`。

## 预计生产代码改动

1. 新增
   `src/eval_framework/providers/mini_agent/capability_adapter.py`；
2. 新增
   `src/eval_framework/providers/mini_agent/runtime_binding.py`；
3. 修改 `src/eval_framework/providers/mini_agent/provider.py`；
4. 小幅修改 `src/eval_framework/contracts/compiler.py`，使直接 Bundle 合同入口从
   `bundle_manifest.json` 切换到 `agent.json`；
5. `runtime_factory.py` 只有在现有 Registry factory 无法保证对象身份时才改；当前
   设计预计无需修改。

---

### Task 1：固定失败基线和协议桥测试

**Files:**

- Add existing frozen dataset and Bundle files under `datasets/mini_agent/`；
- Create: `tests/test_query_user_v2_evaluation.py`；
- Modify: `tests/test_provider_architecture.py`。

- [ ] 验证 Dataset SHA 为
  `e0c74a6bae2889c8d71709d17085bdba97322eb53a4615629b78fbffc3b1b2ac`、Bundle
  SHA 为
  `99baea74b9a4fbd6c493fb5a3159a8f019769804d94232f0d89aa072ea9af3d8`、Case 数为
  42、Manifest 状态为 FROZEN。
- [ ] 增加架构守卫，禁止 `minimal_agent.capabilities.v3` 导入。
- [ ] 用 spy 固定现有桥接：module 只调用 `run_intent_only()` 并读取
  `intent_trace_snapshot()`；full-chain 只消费 `AgentResult` 的 intent/tool_calls/events/
  final_response，不读取 oracle。
- [ ] 增加当前失败测试：正式数据集 `validate` 应成功且 ModelClient 创建次数为零。
- [ ] 运行定向测试，确认唯一目标失败是旧 loader 寻找 `bundle_manifest.json`。

```bash
.venv/bin/python -m pytest tests/test_query_user_v2_evaluation.py \
  tests/test_provider_architecture.py -q
```

### Task 2：实现无版本 `agent.json` Adapter 并接入 Provider

**Files:**

- Create: `src/eval_framework/providers/mini_agent/capability_adapter.py`；
- Modify: `src/eval_framework/providers/mini_agent/provider.py`；
- Test: `tests/test_mini_agent_agent_json_adapter.py`。

**Interface:**

```python
load_mini_agent_capability_bundle(
    root: Path,
    *,
    expected_sha256: str | None = None,
) -> CapabilityBundle
```

- [ ] 写失败测试：正式冻结 Bundle 可加载；module `intent_router`、intent
  `query_user` 和 Evidence 文档正确映射；没有 Tool 引用时不要求 `tools/` 空目录。
- [ ] 写安全测试：路径越界、引用缺失、Snapshot Hash/元数据不匹配、Bundle Hash
  不匹配和重复 ID 全部失败。
- [ ] Adapter 根据 `agent.json` 直接引用加载 Snapshot，用随 Bundle 冻结的 JSON
  Schema 校验，并转换为现有中立 `CapabilityBundle`/`CapabilityRegistry`。
- [ ] `MiniAgentProvider.from_dataset()`、semantic validate 和当前能力加载统一调用该
  Adapter；旧 `bundle_manifest.json` 继续走兼容 loader。
- [ ] 当前能力从 `minimal_agent/capabilities/agent.json` 加载，不再调用
  `load_v2_directory()`。

```bash
.venv/bin/python -m pytest tests/test_mini_agent_agent_json_adapter.py \
  tests/test_query_user_v2_evaluation.py tests/test_provider_architecture.py -q
```

### Task 3：支持直接 Bundle 合同和 QueryUser runtime binding

**Files:**

- Modify: `src/eval_framework/contracts/compiler.py`；
- Create: `src/eval_framework/providers/mini_agent/runtime_binding.py`；
- Modify: `src/eval_framework/providers/mini_agent/provider.py`；
- Test: `tests/test_query_user_runtime_binding.py`；
- Modify: `tests/test_review_hardening.py`。

- [ ] Suite Compiler 同时兼容历史 `bundle_manifest.json` 和新版 `agent.json`；新版
  Provider 身份读取 `agent_id`，Bundle 身份读取 `capability_bundle_sha256`。
- [ ] 直接 Bundle 合同只接受 `agent.json` 入口；外部路径覆盖仍位于 runtime config，
  不修改 FROZEN Manifest，并继续校验 Bundle Hash。
- [ ] per-Trial Registry factory 根据 allowed tools 注册
  `query_user_evaluation_definition(evaluator_owned_handler)`。
- [ ] 默认 handler 返回确定性的合法 `EMPTY` ToolResult，不硬编码用户数据；构造
  Provider 时允许注入 fixture-aware handler factory。
- [ ] 使用稳定的 `minimal_agent.capabilities.export_capability_bundle()`，以当前
  IntentRegistry 和该 Registry 导出临时 runtime Bundle并校验。
- [ ] Registry factory 返回刚才用于导出的同一个对象；现有 `RuntimeFactory` 将它直接
  注入 `MinimalAgent`。测试用 `is` 验证对象身份，并验证不同 Trial 不共享对象。
- [ ] runtime Bundle 导出/校验发生在 ModelClient 创建之前；失败时不得产生模型调用。
- [ ] 0 Tool module profile 仍使用空 Registry；QueryUser full-chain profile 才注册
  `query_user_info`。

```bash
.venv/bin/python -m pytest tests/test_query_user_runtime_binding.py \
  tests/test_review_hardening.py tests/test_provider_architecture.py -q
```

### Task 4：离线验证、正式 validate 和 DeepSeek 运行

**Files:**

- Modify: `README.md`，只补充 `agent.json` Bundle 入口和评测命令；
- Create runtime artifacts under
  `artifacts/query_user_intent_v2_deepseek/`。

- [ ] 使用 `DeterministicModelClient` 按 42 条 oracle 输出执行离线回归，确认现有
  Runner、断言和评分得到 42/42 PASS。
- [ ] 运行全量离线测试、Ruff 和 `git diff --check`。
- [ ] 重新计算冻结输入 Hash，确认 Manifest、JSONL、Coverage 和 Bundle 内容未改。
- [ ] 执行正式 validate：

```bash
.venv/bin/python -m eval_framework.cli validate \
  --dataset datasets/mini_agent/module_query_user_intent_v2_0.jsonl \
  --provider mini_agent
```

- [ ] 只检查 DeepSeek 环境变量是否存在，不输出值；缺少 Key 时暂停，让用户在本机
  配置，不要求在聊天中粘贴。
- [ ] 执行 42 Case × 1 Trial、native DeepSeek、无 Judge：

```bash
.venv/bin/python -m eval_framework.cli run \
  --dataset datasets/mini_agent/module_query_user_intent_v2_0.jsonl \
  --provider mini_agent \
  --output-dir artifacts/query_user_intent_v2_deepseek
```

- [ ] 校验 results、run manifest 和报告中的 Dataset/Bundle Hash、Provider、模型、
  Case/Trial 数、PASS/FAIL/ERROR、分数及失败断言。
- [ ] 按任务边界提交代码、测试、文档和冻结数据；运行产物是否提交遵循仓库现有策略，
  不提交密钥。

## 最终验收

1. 42 条冻结 Case validate 成功并可执行；
2. Runner、Assertions、Scoring 不改；
3. 现有 MiniAgentAdapter 继续直接桥接公开结果协议；
4. `agent.json` 和 Bundle Hash 在模型调用前校验；
5. QueryUser full-chain 的 handler、runtime Bundle 和 MinimalAgent 使用同一个 Registry；
6. 无 `minimal_agent.capabilities.v3` 导入；
7. FROZEN Manifest 未原地修改；
8. 全量离线测试与 Ruff 通过；
9. 最终提供真实 DeepSeek 评测结果与产物路径。
