# Builder P0：read_file 发布就绪验证

本切片提供一个版本化、固定案例集合的工具级发布流程：静态有效 → 原生 Harness 运行 → 独立断言 → 人工审核 → 显式冻结。首版只支持 `read_file`，不声称 MiniAgent、自然语言理解或端到端链路通过。不更改旧 `valid` 语义、EvalCase、v3 bundle 或历史冻结数据。

## 职责与执行边界

- `eval_contracts.readiness` 定义严格制作/证据/审核协议及确定性断言。
- Builder 准备原始字节副本，核对固定集合和证据，计算发布门槛。
- Evaluator 使用 `execute_native_task`、原生 ToolRouter、SandboxFilesEnvironment 和 Inspect 日志实际读取 fixture。
- reference 只接收 `reference_path`，最后输出从真实 tool message 获取。`expected_output` 仅用于 Builder 断言，不进入 Sample target、Agent 消息或执行器。
- `mockllm/model` 是本地确定性替身，用于产生原生 ModelEvent；不访问模型服务、不产生模型费用、不上传 Langfuse。此流程不是正式 Agent 评分，不替换 DeepEval。
- 根 CLI 用独立解释器调度。Builder 不依赖 Evaluator；无需安装 MiniAgent。

Inspect 的 local sandbox 是本地临时文件环境，并非只读或禁网的 OS 沙箱。首版执行固定受信任代码，用户数据不能指定 Python 入口或其他工具。

## 离线演示

在仓库根目录，使用现有独立环境（首次可运行 `python3 scripts/setup.py`）：

```bash
.venvs/core/bin/python -m agent_eval_suite.cli readiness run \
  --dataset examples/readiness/read_file.json \
  --workspace artifacts/readiness-read-file
```

`workspace` 必须不存在。输出包括原始 `dataset.json`、`evidence.json`、`logs/*.eval` 和 `report.json`。案例固定为普通文本、空文件两项，每项独立 fixture；同时核对其他文件不变。

全新安装只有 builder/evaluator 环境时，命令前缀可用 `.venvs/evaluator/bin/python`。根入口仍分别调度 `.venvs/builder/bin/python` 与 `.venvs/evaluator/bin/python`；也可用全局 `--builder-python`、`--evaluator-python` 显式指定。

```bash
.venvs/core/bin/python -m agent_eval_suite.cli readiness check \
  --dataset examples/readiness/read_file.json \
  --workspace artifacts/readiness-read-file
```

每次 check/freeze 都重新获取当前 Evaluator 源码及运行时身份，再调用 Builder；同时校验 Builder 与 Evaluator 实际安装的共享断言代码 Hash 一致。集合或字节变化、fixture/预期变化、运行器/共享断言实现变化、缺失/重复证据均不通过。版本 1 对相关整个 Python 包作保守 Hash，因此不相关实现变化也可能要求重跑。

`runtime_binding_rate` 的分母是固定案例总数，分子需要完整原生日志投影、实际 read_file 调用、匹配路径和初始状态且没有错误。`reference_verified_rate` 还要求执行完成、输出逐字匹配和所有 fixture 文件不变。两者不是 Agent 通过率；工具执行错误会保留在证据中。

成功示例仍为 `ready_for_review=true`、`release_ready=false`、`approval=PENDING`。Shell 返回 0 仅表示当前子命令成功；必须查看状态字段。

## 人工审核与显式冻结

审核者检查案例语义、reference 路径与日志后，创建审核 JSON。Hash 必须逐字取自当前 `report.json`，不得根据旧报告批准新证据：

```json
{
  "approved": true,
  "reviewer": "实际审核者",
  "dataset_sha256": "报告中的 dataset_sha256",
  "evidence_sha256": "报告中的 evidence_sha256",
  "reviewed_case_ids": ["read-file-text", "read-file-empty"]
}
```

```bash
.venvs/core/bin/python -m agent_eval_suite.cli readiness freeze \
  --dataset examples/readiness/read_file.json \
  --workspace artifacts/readiness-read-file \
  --review review.json \
  --output artifacts/readiness-read-file-release
```

冻结目录必须不存在。冻结前将输入字节复制到专属目录，对这些确切字节重新校验；失败清理本次新建目录，成功最后写入 `manifest.json` 作为完成标记。该新格式为 `readiness-read-file-v1`，不能冒充历史 EvalCase。此处不登记、上传或发布到托管服务。

证据和人工审核文件属于本地受信任制作流程：Hash 检测内容漂移，不提供签名认证。单独调用 Builder 的底层 `assess-readiness`/`freeze-readiness` 时，调用者负责提供实时、可信的 `--identity`；推荐使用会自动获取当前身份的根入口。

## 后续范围

本页记录初始 read_file 切片。后续已增加现有 full_generation 产物接入、MiniAgent query_user_info 两条 reference recipe，以及 P1 逐事实来源和差异审计，见[产物接入说明](builder-integration-2026-11-11.md)。其他工具/链路的执行适配及 P2 pairwise/配额仍未实施；局部通过不能替代全部历史覆盖项的验证。

## 验收记录

测试和全新克隆安装结果见本任务实施计划末尾执行记录。
