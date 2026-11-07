# mini_agent 场景覆盖与全链路验收

用户于 2026-11-07 批准聊天中的方案并要求执行。本文件记录执行边界和进度入口。

目标：构造版本化场景集，执行约 24～30 条代表用例，保存 Inspect Trace、DeepEval 正式评分、独立状态证据、HTML，并向 Langfuse 导出及回读核验。

约束：仅当前仓库；历史数据和结果不变；Agent 不因评测要求改变业务行为；Oracle 不进入执行端；Langfuse 和 mini_agent 均可选；测试离线；真实调用最多 60 次（无自动重试）；不启用 LLM Judge。角色权限、动态用户模拟、开放式语义质量不冒充已经支持。

- [x] 1. 扩展可选 mini 适配层的受控只读测试环境：礼物查询、业务错误、超时、执行异常；离线验证真实工具路径、证据和错误评分。
- [x] 2. 基于 1.0.1 派生新冻结版本，保留旧 Oracle；新增场景与覆盖清单，标明未支持项；选不超过 30 条代表集。
- [x] 3. 给真实请求增加共享调用上限，补齐缓存 token 投影；运行离线回归和核心替换性验证。
- [x] 4. 真实执行代表集，核验评分、Trace、状态快照，生成覆盖报告与详细 HTML。
- [x] 5. Langfuse 导出／回读，核对分层事件与分数；无凭据时保留可重放产物并准确记录阻塞。
- [x] 6. 审查改动、包回归及干净环境验收，写入 docs/migration/ 的证据记录。

实现文件：`providers/mini_agent/benchmark_environment.py`、`benchmark/mini_worker.py`、新增 `benchmark/mini_coverage.py`、`benchmark/mini_adapter.py`、`harness/tracer.py`、`benchmark/langfuse_export.py` 及对应测试。新增数据目录 `data/benchmarks/mini-agent-v1.1.0/`。通用执行器不添加 mini 分支。

验收区分：数据已构造、真实运行到达、评分结果、框架链路完整性；Agent FAIL 不等于框架故障。数据库为隔离测试账本，异常为确定性注入，不声称验证真实生产服务或网络故障。
