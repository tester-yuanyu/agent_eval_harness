# Builder 选例与能力采集审计验收

本批对应优化计划 P2-1/P2-2。只增加独立 sidecar，不改冻结数据、历史结果、generation plan、FactDocument schema 或 v3 bundle；不运行 Agent、模型 API 或托管服务。保留当前工作树的前序改动，不暂存、不提交。

## Builder 选例

新增 `dataset_builder.selection.select_cases(GenerationResult, ...)` 与 `write_selection(source, output, ...)`，CLI 为 `dataset-builder select-cases`。直接复用已有 `GenerationResult.slots/cases`，不重新生成数据，不改生成器及原产物。

- `quick` 默认最多 20 例；`full` 默认包含所有未阻塞且满足约束的现有候选；两者都可设置 `--max-cases`、`--max-model-cases`。预算按例数计，不伪造 token 或费用估计；模型使用未知者保守占用模型预算。
- sidecar 保留全部 `obligations` 及固定的 `obligation_count`，包括阻塞、预算排除和约束排除的义务。每例包含执行类别、模型使用状态、义务、readiness、blocker、coverage mode、公开故障输入；不输出 Oracle。没有来源支持的类别/模型/故障值为 `unknown`。公开故障仅取 `input.controlled_fault` 或 `execution.fault_injection`，不从预期答案倒推。
- 2-way 的因素为 `target/layer/dimension/execution_category`。分母是现有未阻塞且满足约束候选中真实存在的 pair 并集，不是任意参数笛卡尔积，不表示全局能力覆盖，也不创造新的组合测试。
- 约束 JSON 是禁配合取项数组，例如 `[{"layer":"tools","execution_category":"tool_behavior"}]`；不接受未知因素名。候选池先过滤约束，再以新增 pair、义务数和 case ID 确定性排序选择。
- `candidate_pairs`、`selected_pair_count` 是计划覆盖。实测单独记 `measured_pairs/measured_pair_gaps`；没有观测证据时严格为 0。`planned_pair_gaps` 表示本次计划补齐后仍剩的缺口，`unfillable_pair_gaps` 表示保留已有有效结果后，剩余候选无法补齐的缺口。

仓库根目录示例（输出需使用新路径）：

```bash
.venvs/builder/bin/python -m dataset_builder.cli select-cases \
  --generation output/mini_agent_full_eval_20261111_v4/dataset/generation_result.json \
  --mode quick --max-cases 20 --max-model-cases 5 \
  --output tmp/selection-quick.json

.venvs/builder/bin/python -m dataset_builder.cli select-cases \
  --generation output/mini_agent_full_eval_20261111_v4/dataset/generation_result.json \
  --mode full --constraints tmp/constraints.json \
  --evidence tmp/observations.json --output tmp/selection-top-up.json
```

`observations.json` 协议：

```json
{
  "source_sha256": "复制同一 generation plan 的 selection.source_sha256",
  "observations": [
    {
      "case_id": "现有 case ID",
      "valid_result": true,
      "observed_factors": {"target": "tool.demo", "layer": "tools"},
      "covered_obligation_ids": ["该例显式覆盖的 slot ID"]
    }
  ]
}
```

证据必须绑定相同 generation plan 的规范化 Hash；CLI 另存原始文件 SHA-256。只承认观测中明确提供的 pair 与本例义务；拒绝未知 case、重复观测、与候选不符的因素、越界义务。全部 pair 与义务已获观测覆盖时，top-up 停止选择冗余候选。`valid_result=true` 表示结果可用，**有效 FAIL 也必须保留**，因此该例不再进入 top-up；它本身不产生任何覆盖信用。成功/失败不能代替覆盖观测。证据是调用者提供的观测摘要，当前 sidecar 不验证运行签名、trace 内容或评分，不能用来覆盖正式评分结论。未提供证据的命令仅列计划，不会自动重跑已有结果。

## 能力采集范围与逐事实失效

新增 `capability_snapshot_kit.ingestion.collection_audit.audit_collection(document, source_root, scope=...)` 及 `CollectionScope`；新增 `capability-snapshot audit-collection`。现有 `audit`、严格导出来源校验和 bundle 格式保持兼容。

```bash
.venvs/core/bin/python -m capability_snapshot_kit.ingestion.cli audit-collection \
  --document output/mini_agent_full_eval_20261111_v4/capability_delivery/collected_facts.json \
  --source-root examples/mini_agent \
  --scope tmp/collection-scope.json --output tmp/collection-audit.json
```

可选范围文件：

```json
{
  "requested_sources": ["agent.py", "intent.py", "private.py"],
  "expected_fact_ids": ["agent.demo", "intent.query", "tool.absent"],
  "omissions": {"private.py": "excluded_by_owner"}
}
```

只读取文档明确绑定的来源，不扫描仓库。范围核算列出遗漏来源、遗漏原因、缺失事实和范围外已采集来源；未说明原因时输出 `unknown`。没有范围声明时 `collection_completeness=unknown`；声明内全部核算可为 `accounted_within_declared_scope`，但 `global_completeness` 始终为 `unknown`、`execution_verified=false`。路径继承现有相对路径和根目录约束。

逐事实沿 `origins` 依赖查来源：字节变化或丢失使对应事实 `invalidated`；无法读取或没有来源绑定为 `unknown`；全部来源匹配为 `unchanged`。因此某个文件变化不会失效无依赖的其他事实。此状态只表示当前来源 Hash 与声明匹配，不证明事实语义或模型能力。CLI 会记录输入文档 Hash；输出仅以排他方式新建。

## 验证与边界

TDD：选例最初 4 项测试因 API/CLI 缺失失败，快照审计最初 4 项因 API/CLI 缺失失败；分别实现后通过。随后公开 `execution.fault_injection` 的回归测试先复现 `unknown` 错误，再补齐读取。另验证部分观测仅计明确 pair、不重跑有效结果、拒绝错误因素。另以先失败后修复测试确保已观测完整覆盖时 top-up 不选择冗余候选。最终新增测试 11 项通过。

验证记录：

- 新增选择与审计测试：11 passed。
- 修改文件 Ruff：通过。
- Contracts 全包：41 passed。
- Builder 首次从仓库根目录运行：351 passed、5 skipped、31 setup errors；错误集中在 `test_synthesis_constraints.py` 的包相对 fixture 路径。没有修改测试或冻结数据，改在 Builder 包目录运行完整回归：384 passed、5 skipped（缺可选 DeepEval）。新增冗余 top-up 回归后最终完整验证：**385 passed、5 skipped，118.08 秒**。完整日志位于 `tmp/eval-optimization-20261111/builder-snapshot/builder-selection-final-regression.log`；首次路径错误详情保存在同目录 `builder-selection-regression.log`。
- 实际 v4 CLI 验收输出：`tmp/eval-optimization-20261111/builder-snapshot/`。quick 保留 854 义务，选 20 例、108/429 个候选 pair；full 保留 854 义务，选 567 例、429/429 pair。两者实测覆盖均为 0，未执行任何案例。
- 既有 v4 文档审计：23 个来源、26 个事实均匹配；未提供完整采集范围，故完整性为 unknown。执行前后 v4 全部 422 个文件 SHA-256 一致。

预算与 2-way 仅针对已生成的合法候选，不能补出未定义场景；`needs_runner` 仍表示需要适配，不因被选中变成可运行或通过。模型是否实际调用需真实绑定/轨迹佐证；本批不作推断。没有新增依赖，没有改动原 v4 结果，也没有自动上传。最终全新克隆安装验收由协调者在各批整合后执行。
