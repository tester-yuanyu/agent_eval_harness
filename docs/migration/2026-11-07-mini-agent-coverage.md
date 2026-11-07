# mini_agent 场景覆盖与全链路验收

用户于 2026-11-07 批准场景盘点、版本化用例、代表集真实评测、Trace/评分/HTML、Langfuse 及解耦方案。真实请求与托管交付均在此授权范围内；没有执行 LLM Judge，没有修改 Agent 业务代码。

## 数据和真实运行

范围为 query_user、query_gift、add_backpack_gift。1.1.0 派生自冻结 1.0.1，保留已有 105 条 Oracle，新增礼物工具查询、工具故障、工具限制、注入文本及重复确认等 10 条，共 115 条。覆盖矩阵 27 个交叉标签，代表集 30 条。rate_limit 已构造但未抽取；不能把全部已构造用例计作真实验证。

独立审查发现重复确认用例在第一次成功后可能提前终止，导致未测试第三轮也能通过。1.1.1 保留旧文件，新增显式 adapter_input.continue_after_terminal 布尔控制及从持久化 run_finished 计数的 completed_turns=3 断言；未改变共享 ExecutionSpec 或默认会话结束行为。

本次运行根目录：`artifacts/mini-agent/coverage-20261107/`。

| 运行 | 数据版本 | 结果 | 模型调用 | 证据 |
|---|---|---|---:|---|
| run / run-8863b27fef8f43e2 | 1.1.0 | 30 条：19 PASS、11 FAIL | 47 | 30/30 完整 |
| continuation / continuation-b72e6bbc9a984ce8 | 1.1.1 | 1 INVALID | 3 | 外层 120 秒时限取消，保留部分证据 |
| continuation-retry / continuation-retry-06570fc7757b4498 | 1.1.1 | 1 FAIL | 3 | 外层时限提高到 240 秒，3 轮完成，证据完整 |

总计 53 次模型调用，低于授权的 60 次。主集 16 module / 7 chain / 7 e2e；178 项正式规则指标。模型为 OpenCode 路由的 deepseek-v4.1-flash，未切换模型规避失败。补跑只执行受影响用例，不混合不同运行身份计算同一个成功率。首个超时补跑保留为 INVALID，不改成 Agent FAIL。

主集用量：29,436 非缓存输入 + 4,224 缓存读取 + 3,007 输出 = 36,667 token。主集报告沿用显式价表显示额度价值 USD 0.00623227–0.01246454，不作为实际账单。超时请求的未知用量不补零。

## 结果与限制

- 意图读操作、查询工具、受控超时和执行异常可以完成评分、Trace 和报告。
- 写操作存在参数名与契约不一致，确认请求未携带前轮参数；保留为 Agent/接入路径问题，没有修改 Oracle 使其通过。
- MINI-FAULT-003：工具返回 success=false/BUSINESS_FAILURE，模型回复正确说明失败，但 Agent 的工具记录及最终状态仍为 SUCCESS，评分识别出状态不一致。
- MINI-DENY-001：没有发生工具调用，但最终为 InvalidModelOutputError，未满足可理解的限制说明。不能将其表述为发生了越权写入。
- 主集和最终补跑均没有 confirmation_accepted 或实际礼物写入。重复确认补跑的三轮断言通过，但首次发放没有成功，不能声称已验证成功发放后的重复确认行为。
- RBAC/租户隔离、生产服务、动态用户模拟、开放式语义质量、其他意图和未声明的恢复策略不在已验证范围。

## Langfuse

项目：`cmvgd40xe02ecad0en362z7wd`。根目录 `.env` 保存本地凭据，Git 忽略且未进入产物。

| 运行 | 原始观察记录 | 远端评分（含 verdict） | 无损元数据证据 | 回读 |
|---|---:|---:|---:|---|
| 主集 | 408 | 208 | 30 | VERIFIED，30/30 |
| 超时补跑 | 29 | 1 | 1 | VERIFIED，1/1 |
| 最终补跑 | 35 | 7 | 1 | VERIFIED，1/1 |

无损证据为展示辅助 span，不是新增模型、工具、评分或 Trial。API 回读核对身份、输入输出、父子关系、时间、模型、token、评分关联及实验条目数。主集首先因 API 省略空对象 before_files={} 核验失败；补充证据协议 v3 保留原始 JSON 字节和 Hash，并绑定来源与父节点，只在证明完整且其他叶子一致时接受省略形式。保留 v1/v2 生成规则；原先零观察记录的 v2 收据归档为 `.v2.empty.json`。上传后的首轮读取尚未看到新 span，延后再次回读通过，没有重复上传原始结果。

浏览器实际打开主集 MINI-QUSER-001 的 Langfuse 页面，确认树状 Trace、turn、模型 generation、intent 事件、820 token 和 6 项指标可见。主集详细 HTML 也经浏览器确认摘要、30 条结果、评分、成本口径与 Trace 入口可见。

## 解耦与本地验收

- 具体工具契约、环境、状态与事件映射留在 mini 可选适配层；通用 runner 未添加 mini 名称分支。
- public_execution 只交付 execution/scope/environment；worker 不接受 Oracle。32 份原生 Inspect sample 的 target 均为空；模型输入未发现测试 Oracle 标记；原始结果、原生日志、独立 Trace 和 HTML 中未发现配置密钥。
- `delivery-verification.json` 保存所有运行原始文件 Hash；native_evidence 引用与实际字节核对通过。HTML 及 Langfuse 重放不修改原始结果。
- 全新克隆位于 `clean-checkout/`，复制当前工作树文件而不复制 `.env`；显式 PyPI 索引完成 `scripts/setup.py --only core`，pip check 通过。既没有 minimal_agent，也没有 Langfuse SDK；核心导入与 5 条离线 demo 通过，独立外部适配器检查 10 passed。
- 全新环境额外取消测试首轮 11 passed / 1 failed，失败为 `test_provider_cleans_nested_processes_on_inspect_termination[False]` 未在 2 秒内启动子进程，单独复测仍失败；没有修改此测试。它不证明子进程清理成功，作为环境/启动时限限制保留。
- 首轮 Evaluator 全包回归：1422 passed / 9 skipped / 1 failed，失败为 `test_worker_timeout_kills_child_and_keeps_independent_state[False]` 在 0.3 秒内未到达写入，单独复测通过。
- 续接修复后的全包回归：1427 passed / 9 skipped，316.68 秒。随后元数据 v3 修复的最终针对性回归：46 passed（含元数据、mini 覆盖和续接测试）；Ruff 与 git diff --check 通过。未把此前失败日志删除或写成全绿。

## 交付

- `index.html`：交付总览，区分实际到达与已执行。
- `run/report.html`：30 条详细报告，逐项评分与完整 Trace。
- `run/coverage.html`：覆盖矩阵及明确排除项。
- `continuation-retry/report.html`：三轮补跑证据与判定。
- `continuation/report.html`：保留的超时诊断。
- `langfuse-links.json`：32 条已核验 Trace 链接。
- `mini-agent-evaluation-reports.zip`：报告、原始结果、Inspect 日志、独立 Trace、Langfuse 收据和验收记录，不包含 Docker 构建目录、环境或凭据。

框架全链路已在上述代表范围内验证；Agent 的成功发放链路尚未通过。本轮未提交、合并或推送仓库修改。
