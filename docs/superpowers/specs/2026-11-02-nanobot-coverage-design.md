# nanobot 能力覆盖与核心组件基准

用户已于 2026-11-02 授权按“固定版本与有效配置 → 覆盖矩阵 → 优先缺口 → 重复与审核”执行。原有文件任务不足以代表 nanobot 整体能力；本次交付可复查的覆盖边界，并补第一批可离线核验的核心组件。

## 方案与范围

采用独立 `nanobot-core-v1` 组件数据集和 Inspect 执行入口，复用 DeepEval 确定性评分。它与已有 File Tools / Model Decisions 并列，不能混算模型或 Agent 成功率。相较于把非文件操作塞进冻结文件任务合同，此方案保留旧合同和 Hash；相较于立即开放全部外部工具，它先补无需凭据即可验证的持久化、隔离和上下文机制。

第一批为 Session、Memory、Context、Skills 的明确模块边界。真实 nanobot 源码与独立解释器执行；不构造真实模型 Provider，不连接外网，不启动渠道，不发送消息，不修改被测源码。Shell/Web/MCP/渠道/定时/子代理等在矩阵中保留未覆盖或后续阶段，不能因源码存在或对象构造就标为已验收。

## 固定身份与覆盖语义

固定源码 commit、dirty、实际源码集合 Hash、逐文件 Hash、解释器及依赖指纹、有效评测 profile 和 Harness 代码身份。实际源码当前位于本机外部工作树，只读使用；公开产物不包含本机绝对路径、凭据或私有配置。原运行身份与本次组件 profile 分开。

矩阵逐项记录源码证据、有效启用状态、任务家族和场景、成功条件、证据要求、已有执行来源、缺口、优先级。`source_present`、`enabled_in_profile`、`dataset_defined`、`executed`、`passed`、`human_reviewed` 是不同状态；没有证据不得升级状态。覆盖清单是本版人工整理的边界，不宣称穷尽所有 nanobot 能力，也不输出“整体覆盖率”。

## 新任务合同与执行

使用新目录 `data/benchmarks/nanobot-core-v1`，构建器拒绝覆盖不同的已冻结字节。固定 32 条任务：24 条 dev（8 家族×3）与 8 条 holdout（4 个不同家族×2）；本版入口禁止执行 holdout。独立人工审核仍待完成，不宣称留出集经人工独立设计。每个任务包含公开 fixtures/operations 和私有 oracle，worker 只收到公开投影；不接收 id/family/split/oracle/参考答案。

worker 只允许显式操作集合，使用 nanobot 公共模块 API。每次调用记录唯一事件 ID、输入、结果或异常，供私有 Oracle 引用。每个 sample 有独立工作区、配置上下文和 sessions_root；进程内 Python audit hook 阻断网络、子进程与临时任务目录外写入。它是可信固定组件的实验护栏，不是恶意代码安全沙箱；Oracle 不进入执行 payload，但不宣称本地进程具备 OS 级不可读隔离。状态快照由执行器在 worker 外独立读取。Inspect 负责 Sample、Epochs、local sandbox、限时和原生日志；DeepEval 自定义 BaseMetric 负责逐项确定性判断，区分 INVALID、INCONCLUSIVE、FAIL、PASS。

开发集默认重复 3 次，共 72 次计划执行；缺失、无效与失败均保留在计划分母，另报有效分母。持久化测试是同进程新对象重载，不是跨进程重启；后者保留为缺口。确定性模块重复通过只说明已测条件可重复，不证明 LLM 稳定性。保留事件、任务/源码/契约/评分身份与失败理由；发布摘要不复制原始提示或绝对路径。

## 验收

先写失败测试验证严格合同、Oracle 不进入 worker、未知操作与路径拒绝、缺证据不通过、源码漂移拒绝、重复与非法 trial 拒绝、版本绑定和未执行留出状态。使用真实本地 nanobot 执行新增 dev 任务；如出现失败，保留原始失败结果，修复评测实现时写新运行，不能修改被测源码或为通过而改冻结 Oracle。

完成相关测试、分包回归、1,172 项旧资产 Hash 校验、全新克隆安装与离线 Demo。独立审查覆盖评分可信度与矩阵过度声明。人工标签/审核不由模型代填，真实模型评测与托管交付不在本次自动运行范围。
