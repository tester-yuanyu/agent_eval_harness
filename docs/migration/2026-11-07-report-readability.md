# 本地评测报告可读性与用量补充验收

用户授权修改报告展示：问题摘要、失败原因的中文说明、证据支持的归因、成本估算和下一步建议。本次未修改 Agent、冻结数据集、Oracle 或已保存 verdict，未执行真实模型请求或托管上传。

## 实现范围

- 领域报告生成器新增问题摘要、读写操作统计、中文期望/实际说明和下一步建议。原始评分 JSON 与完整 Trace 保留。
- 诊断只读取保存事件。模型已提供但校验拒绝的字段，先按可观察事实说明；只有参考契约文件的 Hash 与运行身份一致时才进一步解释未声明字段。参考契约与运行实现保持区分，不能据此认定校验器本身错误。
- 确认轮只包含确认语句、通用指令且没有前轮参数时，说明请求上下文缺口；不把它写成模型遗忘，也不推断不可见的内部状态。
- 证据链接按 case/trial/event 隔离，点击后展开对应 Trace；重复 event ID 不跳到其他试次。
- 缓存用量从身份、完整记录和基础用量均匹配的 Inspect 日志补充到报告视图。历史 JSON 字节不变；缺失或不匹配不补零。
- `report-pricing.json` 为显式价格快照，绑定模型与端点，记录来源和核对日期。估算与原始 `cost_usd` 分开；Go 仅显示额度价值估算，不冒充现金扣款。缓存写入未提供时，价表必须明确该计价项不适用，才能估算。

## 本次产物

运行目录：`artifacts/mini-agent/opencode-go-deepseek-smoke-20261107T065009Z/`。

- `remaining/report.html`：5 条，3 PASS / 2 FAIL。写操作 0/2 通过，读操作 3/3 通过；两条写操作均出现参数契约不一致，E2E 额外出现确认轮请求缺少上下文。
- `chat-compatible/report.html`：1 条，1 PASS。
- 5 条报告用量核对：5,946 非缓存输入 + 1,024 缓存读取 + 668 输出 = 7,638 token。按显式峰谷价表估算额度价值为 USD 0.001295772–0.002591544；未恢复历史档位，不作为账单。
- 两份 HTML 内嵌评分、诊断、样本 Trace、价格快照与来源 Hash，可独立离线查看。原始结果和 Markdown 为可选链接。
- `report-refresh-verification.json` 保存 42 份原始结果、trial、证据与原生日志的 Hash；重新渲染后逐一核对未变化。HTML 凭据扫描通过。

## 验证结果与限制

- 最终报告相关测试：30 passed（包括新诊断、来源不匹配降级、缓存恢复、估算口径和跨试次证据定位）。
- Evaluator 完整回归：1,410 passed / 9 skipped / 1 failed，378.56 秒。失败名称为 `tests/benchmark/test_agent_adapters.py::test_provider_cleans_nested_processes_on_inspect_termination[True]`；失败在 `started.exists()`，即子进程未在 2 秒取消时限前启动。该用例单独复测：1 passed，8.42 秒。没有修改该用例或进程清理实现，不能将本次全量结果写成全绿。
- Evaluator 全包 Ruff 与 `git diff --check` 通过。
- 浏览器确认问题摘要、失败说明、缓存用量及估算区间可见；证据链接能定位并展开原始模型事件。
- 当前环境 `make demo` 离线验收：5 PASS，生成 Inspect 查看器，无付费模型调用。
- 全新克隆位于 `artifacts/mini-agent/report-clean-20261107/`，应用工作树改动，未复制 `.env`。`scripts/setup.py --only evaluator` 未完成：首次依赖下载出现代理握手超时，取消单次命令代理后仍无法取得 `setuptools>=68`。因此**全新环境安装及其演示未验收通过**；当前环境离线演示不能替代这一项。

验证日志均保存在上述运行目录下的 `report-*.log`。本次只更新可重新生成的 HTML/Markdown 与辅助价表，原始运行身份和正式判定保持不变。
