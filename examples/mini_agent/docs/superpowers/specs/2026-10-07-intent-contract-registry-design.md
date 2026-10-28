# 通用意图契约注册表设计

## 1. 背景

`mini_agent` 当前由模型直接生成 `IntentResult`。公共协议只把
`parameters` 定义为 `dict[str, Any]`，因此只能验证意图结果的外壳，不能保证参数
名称、类型、格式、范围、组合关系或查询语义符合对应能力。

这导致以下已观察问题：

- `user_id` 被输出为字符串；
- 非正整数 ID 被判为可执行；
- 不合法的 email 和 phone 无法在意图层被稳定识别；
- OR 或批量查询可能被转换成工具实际执行的 AND 查询；
- 模型返回的 status、next_action 和 missing_parameters 可能与能力契约冲突；
- `run_intent_only()` 缺少足够的校验 Trace。

本设计不针对单一工具增加条件分支，而是新增一层可复用的意图能力契约。所有现有
意图均通过同一个注册表完成参数规范化、语义约束、Pydantic 校验和最终决策生成。

## 2. 目标

实现以下通用能力：

1. 为每个意图定义独立、版本化、可测试的参数协议；
2. 支持必填字段、可选字段、至少一个、恰好一个和互斥组合；
3. 支持类型、格式、枚举、数值范围和集合成员校验；
4. 支持安全且无歧义的参数规范化和语义转换；
5. 支持 OR、批量、多实体等无法由工具协议表达的语义限制；
6. 根据契约统一生成 READY、NEED_CLARIFICATION、NEED_CONFIRMATION 或
   REJECTED；
7. 保持 `run_intent_only()`、`run()` 和 `store.snapshot()` 的现有公共返回契约；
8. 记录可观察的校验 Trace，不记录或伪造模型内部思维过程；
9. 允许未来增加意图时复用公共组件，不修改 IntentRouter 的控制流程；
10. 不根据评测 case_id、固定输入或标准答案编写特殊逻辑。

## 3. 非目标

本次不实现：

- 新工具或新业务意图；
- RAG、Memory、多 Agent、Web 服务或前端；
- Judge、评分、评测报告或评测集修订；
- 通用自然语言语法解析器；
- 自动执行 OR 或批量请求；
- 从工具执行结果反推意图；
- 修改 `agent_dataset_builder` 或 `agent_evaluator`。

## 4. 设计原则

### 4.1 模型负责理解，代码负责约束

模型继续负责意图识别和自然语言参数提取。代码层负责验证模型候选是否符合已冻结
能力契约，并生成确定性的最终决策。

### 4.2 不静默改变业务语义

允许的规范化仅限无歧义转换，例如将纯数字 ID 字符串转换为整数、去除字符串首尾
空白。禁止把 OR 改为 AND、从多个值中任选一个、猜测缺失值或拆分成未授权的多次
调用。

### 4.3 意图契约与工具契约双层防线

意图契约决定请求是否具备进入下一阶段的条件。工具 Pydantic Schema 在实际调用前
继续执行严格验证。意图验证不能代替工具验证，工具验证也不能弥补错误的意图决策。

### 4.4 注册定义而非修改路由控制流

新增或调整意图时，应新增或修改 `IntentDefinition`。IntentRouter 不包含针对具体
intent、case_id 或固定用户输入的分支。

## 5. 组件设计

新增 `src/minimal_agent/intent_contracts.py`，包含以下公共组件。

### 5.1 IntentDefinition

```python
@dataclass(frozen=True)
class IntentDefinition:
    intent: IntentName
    contract_version: str
    parameters_model: type[BaseModel]
    normalizers: tuple[ParameterNormalizer, ...]
    semantic_constraints: tuple[SemanticConstraint, ...]
    completion_policy: CompletionPolicy
    execution_mode: Literal["read", "write", "unsupported"]
```

每个定义负责描述一个意图，不直接调用工具，也不读取 SQLite。

### 5.2 IntentRegistry

```python
class IntentRegistry:
    def register(self, definition: IntentDefinition) -> None: ...

    def get(self, intent: str) -> IntentDefinition: ...

    def validate(
        self,
        user_input: str,
        candidate: IntentResult,
        *,
        trace: TraceCollector | None = None,
    ) -> IntentResult: ...
```

要求：

- 重复注册明确失败；
- 未知或未注册意图明确失败；
- 所有默认支持意图在构造默认 Agent 时完成注册；
- 注册表不持有模型客户端、工具注册表或数据库。

### 5.3 ParameterNormalizer

```python
class ParameterNormalizer(Protocol):
    def normalize(
        self,
        user_input: str,
        parameters: dict[str, Any],
    ) -> NormalizationResult: ...
```

首批通用实现：

- `IntegerStringNormalizer`：指定字段的纯数字字符串转换为整数；
- `TrimStringNormalizer`：指定字符串字段去除首尾空白；
- `LowercaseStringNormalizer`：仅用于契约明确大小写不敏感的枚举或环境名；
- `AliasNormalizer`：把冻结的别名转换为规范枚举值。

每次转换必须记录字段、转换类型和转换前后值。不得记录模型隐藏推理。

### 5.4 SemanticConstraint

```python
class SemanticConstraint(Protocol):
    def evaluate(
        self,
        user_input: str,
        parameters: dict[str, Any],
    ) -> ConstraintResult: ...
```

首批通用实现：

- `DisallowAlternativeQuery`：识别明确的 OR 连接语义；
- `DisallowBatchQuery`：识别明确要求多个实体或分别查询的语义；
- `SingleEntityQuery`：将上述失败统一转换为单实体查询澄清；
- `MutuallyExclusiveFields`：多个选择模式不能同时存在；
- `ExactlyOneFieldGroup`：一组字段中必须且只能提供一个；
- `AtLeastOneFieldGroup`：一组字段中至少提供一个。

自然语言语义约束使用通用、可测试的词法规则和模型候选参数共同判断，不能匹配完整
固定句子。只有出现明确 OR、批量或多实体信号时才拦截；无法确定时不猜测。

### 5.5 CompletionPolicy

```python
class CompletionPolicy(Protocol):
    def decide(
        self,
        validation: ContractValidation,
    ) -> Decision: ...
```

内置策略：

- `ReadIntentPolicy`：参数完整合法时 READY，否则 NEED_CLARIFICATION；
- `WriteIntentPolicy`：参数完整合法时 NEED_CONFIRMATION，否则
  NEED_CLARIFICATION；
- `UnsupportedIntentPolicy`：固定 REJECTED。

status 与 next_action 的映射仍遵守公共 `IntentResult` 状态机。

## 6. 参数模型

每个意图拥有专用的 Pydantic v2 参数模型。参数模型使用 `extra="forbid"` 和
`strict=True`，并通过字段约束或 model validator 表达格式、范围与组合规则。

首轮为全部现有意图注册模型：

- `query_information`；
- `prepare_resource`；
- `query_user`；
- `query_gift`；
- `add_backpack_gift`；
- `query_custom_gift_record`；
- `query_pool`；
- `update_pool_weight`；
- `unsupported`。

意图参数模型表达“用户已提供的业务参数”，未提供的可选字段可以省略。工具 Function
Schema 继续要求全部属性 required，并通过 null 表达业务可选值。两层协议的序列化形式
不同，但字段类型、格式、范围和组合语义必须一致。

### 6.1 query_user

规则：

- `user_id`、`room_id` 为大于 0 的整数；
- `email` 为字符串，恰好包含一个 `@`，且两侧非空；
- `phone` 为 11 位十进制数字字符串；
- 四个字段至少一个；
- 多个不同字段表示同一用户查询的 AND；
- 明确 OR、批量或多实体查询不执行，返回单实体澄清；
- 非法字段值不保留在最终 parameters 中；
- 数字字符串 ID 可以规范化为整数。

OR 或批量请求的规范结果为：

```json
{
  "intent": "query_user",
  "status": "NEED_CLARIFICATION",
  "next_action": "ASK_USER",
  "parameters": {},
  "missing_parameters": ["single_user_query_condition"]
}
```

公开 reason 明确说明当前不支持 OR 或批量查询，并要求一次查询一个用户。

### 6.2 其他现有意图

其他意图按照当前 `PROJECT_SPEC.md`、工具参数 Schema 和已冻结写操作规则注册：

- 保持当前意图名称、参数名、默认语义和读写行为；
- query_gift、query_pool 和写操作的选择模式继续使用恰好一个规则；
- 写意图完整时继续请求确认；
- 不在本次增加新的业务字段或工具能力。

## 7. 验证和决策流程

```text
模型 IntentResult 候选
→ IntentResult 外壳校验
→ IntentRegistry 查找定义
→ 参数字段白名单检查
→ 依次执行 normalizers
→ 执行 semantic constraints
→ Pydantic 参数模型校验
→ 生成 ContractValidation
→ CompletionPolicy 生成规范决策
→ 构造并再次验证最终 IntentResult
```

注册表是最终决策权威：

- 模型候选中的 intent 和公开 reason 保留；
- parameters 使用规范化和过滤后的结果；
- status、next_action、missing_parameters 由契约重新生成；
- 模型候选与契约冲突时记录 Trace，不静默沿用模型决策。

## 8. 错误处理

### 8.1 明确失败

以下情况抛出明确异常：

- 模型输出不是合法 `IntentResult` 外壳；
- intent 没有注册定义；
- 注册表重复定义；
- normalizer 或 constraint 返回内部非法结果；
- 契约配置自身矛盾。

### 8.2 用户可修正问题

以下情况不抛出运行异常，而是返回 NEED_CLARIFICATION：

- 缺少必填参数；
- 类型、格式或范围不合法；
- 互斥字段冲突；
- OR、批量或多实体语义不受支持；
- 参数无法无歧义映射到已注册能力。

非法值从最终 parameters 中移除，合法且不会导致误执行的已提供值可以保留。OR、批量
和多实体请求固定清空 parameters，防止下游将其误解为 AND。

## 9. Trace

新增事件：

```text
intent_candidate_received
intent_definition_resolved
intent_parameter_normalized
intent_semantic_constraint_failed
intent_parameter_validation_failed
intent_contract_validated
intent_decided
```

事件只包含：

- intent；
- 契约版本；
- 参数规范化前后值；
- 公开校验错误类型和字段；
- 最终 status、next_action 和 missing_parameters。

事件不得包含隐藏推理、模型 chain-of-thought、评测 expected、case_id、评分规则或标准
答案。

`MinimalAgent.run()` 把这些事件写入现有运行 Trace。直接调用
`MinimalAgent.run_intent_only()` 时保存最近一次意图事件快照，并提供只读访问方法，
但保持其返回值仍为 `IntentResult`。模块级便利函数仍返回 `IntentResult`，不增加全局
可变 Trace 状态。

## 10. Prompt

Prompt 继续描述支持意图，但增加以下通用规则：

- 参数必须保留正确 JSON 类型；
- 不得把 ID 转成字符串；
- 不得猜测缺失值；
- 不得把 OR 转为 AND；
- 不支持的批量或多实体请求必须澄清；
- 必须遵守对应意图的格式、范围和组合规则；
- 模型结果仍会经过确定性契约校验。

Prompt 只用于提高候选质量，不能替代代码校验。

## 11. 兼容性

保持不变：

- `run_intent_only(user_input) -> IntentResult`；
- `run(user_input, ...) -> AgentResult`；
- `store.snapshot(run_id)`；
- 现有 intent 和工具名称；
- Function Calling 工具 Schema；
- ScriptedModelClient 和真实模型客户端协议；
- 写确认、幂等、SQLite 和故障注入语义。

允许新增：

- 默认 IntentRegistry 构造函数；
- 意图 Trace 只读快照接口；
- 通用参数模型、normalizer、constraint 和 completion policy。

## 12. 测试策略

所有实现遵循 RED、GREEN、REFACTOR。

### 12.1 注册表和公共组件

- 全部现有 intent 已注册；
- 未注册 intent、重复定义和错误配置明确失败；
- normalizer 顺序稳定；
- 通用必填、可选、至少一个、恰好一个和互斥规则可复用；
- 读、写和 unsupported 决策策略正确。

### 12.2 query_user 回归

- 报告中的五个输入形成确定性回归测试；
- 字符串 ID 规范化为整数；
- 0、负数和小数 ID 请求澄清；
- email 格式边界；
- phone 11 位数字边界；
- 明确 AND 保持 READY；
- OR、批量和多实体请求不转成 AND；
- 不支持回复清晰可观察。

### 12.3 其他意图兼容

- 现有 ScriptedModelClient 单元和集成测试继续通过；
- 所有读意图的必填和组合规则保持现状；
- 完整写意图仍进入 NEED_CONFIRMATION；
- 缺参写意图仍进入 NEED_CLARIFICATION；
- 工具严格 Schema 和完整 Agent 链路不回归。

### 12.4 Trace

- 规范化、失败和最终决策事件可观察；
- `run()` 与 `run_intent_only()` 使用同一意图 Trace 事件定义；
- Trace 不包含评测信息、API Key 或隐藏推理。

最终运行完整 Pytest 和 Ruff。

## 13. 迁移顺序

1. 增加失败测试，复现当前参数和 OR 问题；
2. 实现注册表、通用结果类型和公共策略；
3. 注册全部现有 intent；
4. 将 IntentRouter 接入注册表；
5. 增强 query_user 参数格式和语义约束；
6. 接入 Trace；
7. 同步 Prompt、PROJECT_SPEC 和 README；
8. 运行针对性测试、完整测试和 Ruff。

## 14. 风险和控制

### 14.1 过度规范化

风险：把本应澄清的值自动修复。控制：只允许无歧义、显式注册的 normalizer，并为
每种转换编写边界测试。

### 14.2 自然语言规则误判

风险：普通文本中的“或”被误判为 OR 查询。控制：语义约束同时要求连接词和多个已
提取查询条件或明确批量实体信号，不匹配完整固定句子。

### 14.3 两层 Schema 漂移

风险：意图参数模型和工具参数模型定义不一致。控制：为共享字段增加契约一致性测试，
并在文档中明确差异仅限“省略”与“required nullable”的序列化形式。

### 14.4 模型行为变化

风险：确定性校验改变现有 ScriptedModelClient 测试结果。控制：所有已冻结行为先写
兼容测试；只覆盖与正式契约冲突的模型候选决策。

