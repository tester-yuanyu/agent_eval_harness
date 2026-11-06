# Benchmark 职责边界整理

用户已批准本任务上一轮评审中的渐进式重构，并授权与 Harness 任务协调文件所有权。

## 目标与方案

保留 Inspect 执行/日志、DeepEval 正式评分、现有 CLI/Python 入口和冻结数据。将公共编排、比较、数据读取、file-tools 领域规则、独立 reference 与 nanobot 集成分开。选择逐层迁移实现并保留旧入口；不采用直接删除 worker、统一替换 AgentLoop、取消运行中身份检查的方案，因为它们改变评测语义或隔离边界。

## 实施边界

- runner 的长参数列表改为运行上下文与 Inspect 依赖对象；比较实现归 aggregator，旧导入可用。
- file-tools 的验证/选择/公开投影归领域模块；JSONL 读取、字节摘要等基础能力共享，各合同保留自己的严格校验、manifest 字段和历史 hash 语义。不修改冻结 JSON，也不把执行代码配置化。
- reference 实现归可信 scorer 层；oracle.py 保留兼容入口。
- 通用本地文件操作归 Environment；nanobot tokenizer/源码身份归可选 integration。独立 worker 仍可在未安装 Evaluator 的解释器下运行。
- source identity 保留旧标签算法和完整覆盖；新增实现纳入来源，不把旧结果改写成新身份；继续逐样本检查运行前后漂移。
- Domain 保持公开投影、评分与身份职责；runtime/sandbox 保持 adapter 所有。不同合同不合并成一个宽松校验器。

## 并行协作

本任务 worktree 为 workspaces/benchmark-cleanup。Harness 任务拥有 harness/**、composition.py、orchestration/specs.py、benchmark/adapters.py 及其 P1 测试。本任务拥有 benchmark 的上述模块、新 aggregator 比较模块、environments/local_files.py 与文件操作引用。交叉入口保持签名，迁移前检查双方状态。独立提交，整合后回归。

## 验收

用既有测试验证 Oracle 隔离、断点恢复、漂移拒绝、可比性、历史评分、module/decision 语义。新增测试针对跨模块边界、独立 worker 导入和源文件覆盖。检查全部冻结资产；执行 Evaluator 回归、相关 contracts/root 检查、ruff；全新克隆独立安装并离线演示。不得调用真实模型或上传服务。

## 不在本次强行实施的变更

不为目录整齐而改变 tau/mini/core 的运行协议、依赖 pin 或独立评分语义；不删除兼容模块或 worker。后续弃用须有逐路径等价证据。性能优化须以实测和不可变运行快照为前提，本次不取消漂移检查。
