# Environment 领域拆分设计

用户已在方案评估后授权实施。基线为 `04a1cc3`；Benchmark 的并行方案和工作树不属于本任务。

## 目标和取舍

采用渐进迁移：Environment 的异步 Protocol/异常从 Harness 移到中立 base，原位置重导出同一对象。公共文件操作收敛到 `_fs_utils.py`；保留 `local_files.py`、旧 sandbox 模块和同步 file_tools API。整体统一成 async 会破坏已有调用，因此同步旧类不改签名，需要时由异步 adapter 接入新 Harness。

新路径的领域实现归 `environments/file_tools/`。nanobot 原生进程桥归 `integrations/nanobot/environments/`，旧模块和包顶层通过延迟兼容导出保留；共享 Docker 身份绑定不迁入 nanobot。Environment 不依赖 Agent runtime 或 Harness 实现；Harness 负责生命周期与路由。

## 兼容边界

旧文件工具允许工作区内绝对路径、快照每文件上限 2,000,000 字节；sandbox 工具仅允许相对路径且保留原有无该大小上限的行为。公共实现通过显式策略保留差异、错误文本、排序、UTF-8 与 CRLF。旧同步 list_dir 返回列表，新路径返回文本。

worker 仍通过 Inspect `sandbox().exec` 执行，任务值只走 JSON。从唯一可信源码装配自包含 payload，不依赖沙箱安装 Evaluator；独立 nanobot 扁平 bundle 加入公共模块并计入原有 Hash 闭包。冻结资产和历史结果不改写。

工具阶段可恢复的参数/业务错误反馈 Agent；reset/snapshot 无法建立或取得可信状态、进程失败和协议损坏终止试验。取消与 Inspect 原生 limits 不包装。新增领域用 environment 注入证明契约通用，不扩展 Benchmark CLI 选择器或评分语义。

## 验收

公共 API 与旧 API 回归、路径/快照边界、隔离 worker 无第三方包执行、工具错误恢复/基础设施错误终止、无 Agent 导入、demo 领域注入、完整 Evaluator 回归、Ruff、冻结资产、全新安装与离线 demo。Docker 构建输入验证与真实 Docker 运行分别报告。
