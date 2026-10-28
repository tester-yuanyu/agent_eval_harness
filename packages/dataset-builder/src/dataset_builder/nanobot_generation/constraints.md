# Nanobot 评测生成约束

## 来源与格式

输入为用户交付的 Capability Snapshot v3；保留全部原文件与 Hash。工具的 OpenAI function envelope 仅投影为统一参数 Schema。缺口报告由外层清单绑定，不补写不存在的原始字段。源码是证据子集，不能视为完整可运行项目。

## 分层与覆盖

模块与意图、工具、关键链路、端到端、辅助契约分别输出。所有35个快照均有记录。参数覆盖类型、必填/省略、nullable、枚举各值、上下界及越界、额外属性和嵌套数组/对象；缺少Schema限制时不会自行增加限制。参数用例只检查JSON Schema，不声明SDK或工具运行时接受/拒绝。

行为候选来自绑定源码中的明确分支，使用隔离fixture/服务替身。候选保留正常、语义异常、边界和明确序列。没有对所有参数做笛卡尔积，也没有将全部工具强行组合到对话链。关键链路缺少声明，单列缺口；端到端只提出成功返回结构候选，错误/早停仍缺分支Oracle。

## 预期与支持状态

schema_contract验证Schema判定；contract_check仅核对声明；behavior_candidate是带预期和fixture的源码推导假设；blocked_obligation是缺少具体可执行断言的义务。四类分别计数。unknown不转换为supported；未声明batch不等于不支持；未审计权限、副作用、重试和幂等不补充假设。参数中的默认值不会由Schema校验器自动填入。

## 边界和运行依赖

conversation的prohibited_module_ids与源码内部依赖存在冲突，须澄清观察范围和实际执行边界。独立模块/工具候选不受该对话链的观察选区限制，也不冒充该链中的有效执行路径。缺少完整nanobot依赖、隔离环境、runner、断言映射及外部服务夹具；所有Agent业务均NOT_RUN。

## 交付与审核

本交付采用nanobot_candidate 1.0独立协议，不能直接传给现有EvalCase loader。严格Schema见schemas/。静态校验通过不代表业务通过。DRAFT、PENDING，审核清单全部未勾选；不运行真实工具、发送消息、启动定时任务或连接模型；不自动冻结。每条记录有独立nanobot命名空间、来源摘要与Pointer/源码锚点。mini_agent目录不修改。
