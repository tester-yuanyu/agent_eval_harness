# Harness P0/P1 改造与验收

范围依据：[两批实施计划](harness-hardening-plan-2026-11-12.md)。基线为 `42331e3d539b660ed766c1db27f28741d94a50d4`。仅改 Evaluator 的执行、身份校验和可选展示边界；未修改 mini_agent 业务实现、冻结数据集和历史评分。

## 第一批：取消稳定性与证据保全

- 子进程取消测试先确认 worker 和后代已启动，再触发父取消；模拟 3 秒慢启动。独立启动上限默认 30 秒，可通过 `EVAL_TEST_STARTUP_TIMEOUT` 调整。仍验证 cleanup 标记与后代进程退出。
- 原生 Harness 在模型调用和工具路由边界通过 Inspect 公开日志 API 保存 checkpoint。每个 attempt 有独立目录、任务绑定、原生日志 Hash 和完整性回执。执行中断时保持部分证据状态，不据此判 PASS。
- mini_agent worker 的业务 SDK 直接写入 attempt 下的持久目录，不再只在正常退出时从临时目录复制。宿主在执行前保存请求绑定；成功、失败、取消都尝试取回该 attempt 的证据。
- 成功接收必须核对 stdout 与落盘 observation、case/attempt、Hash；业务轨迹还通过现有 SDK Reader 校验，与 observation 中的事件一致。损坏、缺失或错绑会降为不完整。
- 独立审查发现并修复双重失败：执行异常后的错误回执写入失败，不再覆盖原始执行异常或 `KeyboardInterrupt`。

新运行证据位于运行输出的 `evidence/<attempt>/`。原生路径含 `checkpoint.json` / `trace.inspect.json`；worker 路径含 `request.json` / `receipt.json` 和实际取回文件。宿主被强杀时可按请求记录中的 attempt 继续定位 worker 路径 `/sample/evidence/<attempt>`；本次没有添加自动恢复调度器。容器已销毁且文件未取回时，宿主请求记录不能重建丢失的业务证据。

持久化验收针对进程强杀，不宣称操作系统崩溃或存储设备断电下的完整性。取证是同次执行的审计材料，不是独立 Oracle。

## 第二批：身份校验复用与展示 API 隔离

`identity_checkpoint()` 只在一次同步身份校验内复用文件 bytes。执行前后分别创建新的上下文；不持久缓存路径、mtime 或整个身份结果，不跨 `await`。任务和线程的所有权检查阻止继承父任务快照。公共 Hash 算法、输入文件选择与历史产物保持原语义；本次源码变化会自然产生新的运行身份。

本机同一身份校验组合进行 5 次测量，复用开关两种模式的身份输出完全相同：

| Adapter | 文件读取次数（关 → 开） | 耗时中位数（关 → 开） |
| --- | ---: | ---: |
| raw_model | 382 → 96 | 43.48 → 29.82 ms |
| mini_agent_full | 1,433 → 459 | 343.01 → 252.54 ms |

这是身份计算微基准，不是 DeepSeek 或整轮评测速度测量。源码等长且 mtime 不变的修改、文件增删、异常清理及异步子任务均有离线覆盖。

`DashboardAPI` 集中 Langfuse unstable Dashboard/Widget 调用和定义验证，SDK 类型按需加载，沿用现有 client、节流器和重试参数。列表读取全部分页，重复项、缺页、集合变化和不兼容响应报错，避免遗漏已有组件后重复创建。写入前将本次看板回执置为 `UPDATING`，经过原有组件、布局回读才能转为 `VERIFIED`。模板、确定性 ID、统计口径和 Metrics 验证仍沿用已有实现。

## 验收记录

- 针对性测试：第一批原生 Harness / readiness / full benchmark / SDK 恢复共 72 项通过；后续身份、取消、证据边界组 31 项通过；Langfuse gateway / presentation / explorer / delivery / v4 共 48 项通过。审查双重失败用例先失败再修复，2 项通过。
- 源码和新增测试文件按 Evaluator 配置通过 Ruff。包级 Ruff 对比基线 65 项、当前 61 项，新增问题为 0；未批量整理无关历史文件。
- 全新克隆基线并覆盖本次源码后，`scripts/setup.py --only core` 安装和 `pip check` 成功；未安装 `minimal_agent` / `langfuse` 时核心和 gateway 导入成功。离线 demo 新建 5 个 smoke trial 并生成报告；optional/core 的 7 项测试通过。demo 仅验证安装和接口，不是重跑历史评测。
- 原有 `artifacts/mini-agent` 与 `output` 共 99,175 个文件逐一核对 SHA-256，变更 0、缺失 0。
- Evaluator 完整包回归：**1,675 passed / 9 skipped**，435.19 秒；跳过的是显式选择的 Docker / nanobot 可选集成和付费模型 smoke。完整回归后再次核对原有产物 Hash，仍全部一致。新克隆的 23 个变更 Python 文件与最终源码字节一致。

## 范围裁决与边界

- 实现阶段复用当前 checkout，不自动提交或推送；用户随后明确授权将本次 P0/P1 提交、推送并合并到远端默认分支 `codex/tool-benchmark-deepeval`。交付仅包含代码、测试与验收文档，已有运行输出不迁移。
- 看板分页集合变化时选择报错重试，不自动猜测或创建；并发人工编辑可能需要再执行交付。
- 未调用真实模型或 Langfuse 云端；审查也将真实服务兼容性留给后续明确授权的交付。此次验证覆盖 SDK 类型和离线响应，不代表云端现场验收。
- 未做 P2、依赖升级、兼容入口删除、配置系统重写或全局身份缓存。原先已有效的评测结果不重跑。
