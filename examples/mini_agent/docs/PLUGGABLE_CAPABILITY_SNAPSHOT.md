# 通用 Agent 能力快照接入

本组件将 Agent 结构事实和 LLM 整理的语义候选编译成 **Capability Snapshot 3.0**。
它不依赖 mini_agent 的运行时，不限定工具型 Agent，也不替 Agent 执行评测。

## 三个独立接口

| 接口 | 输入 | 输出 | 信任含义 |
| --- | --- | --- | --- |
| Collector | 调用方指定的项目根目录，插件自有配置 | `FactDocument` | `configured`：可信插件对当前配置的声明 |
| Extractor | 约束、Schema、评测配置、显式选择的源文件 | `FactDocument` 候选 | `declared`：待核实的语义声明 |
| Compiler | 核验合并后的 Facts + Spec Pack | Snapshot 3.0 Bundle | 结构、引用和摘要一致；不等于运行通过 |

核心 API 位于 `capability_snapshot_kit.ingestion`；原有 `CapabilityAdapter` 的五组
Fact 方法不变，可通过 `AdapterCollector(adapter)` 接入。

新入口：`python -m capability_snapshot_kit`。原有 mini_agent 导出命令继续可用，但
只有新入口执行本页的来源核验及信任处理。不要将旧的直接编译 API 当成不可信 LLM 输入入口。

## 安装为独立组件

在本仓库构建只包含 Kit 的 wheel：

```bash
.venv/bin/python scripts/build_snapshot_kit.py --output exports/standalone_dist
```

在另一个 Agent 的虚拟环境中安装生成的 wheel：

```bash
python -m pip install /absolute/path/capability_snapshot_kit-0.1.0-py3-none-any.whl
capability-snapshot --help
```

独立包只依赖 Pydantic 和 PyYAML，不安装 minimal_agent、OpenAI SDK 或 Trace SDK。
构建脚本从唯一的 Kit 源码复制到临时构建项目，防止维护两份实现；可运行示例不进入 wheel。
无需在已经包含 Kit 的 minimal-agent 环境中重复安装独立 wheel。此版本为本地制品，未发布到 PyPI。

## 路径一：接入现有 Agent

Agent 自己实现一个插件工厂，返回具有 `collect(source_root: Path) -> FactDocument`
方法的对象。框架专属 import、凭据读取、注册表和模型配置都留在插件内。采集本身应只读，
不发起业务调用。插件作者负责确保报告的事实来自本次选择的实际配置。

```python
from capability_snapshot_kit.ingestion import AdapterCollector

def create():
    adapter = MyAgentCapabilityAdapter(my_agent)
    return AdapterCollector(adapter, sources=my_sources, origins=my_origins)
```

`sources` 是 source ID 到 `SourceReference(path, sha256, kind)` 的映射。
`origins` 是事实 ID（如 `module.dialogue`）到 source ID 列表的映射。使用
`source_reference(source_root, relative_path)` 计算摘要，不能手写猜测哈希。

```bash
python -m capability_snapshot_kit export \
  --collector your_package.capabilities:create \
  --source-root /absolute/path/to/your-agent \
  --spec-root /absolute/path/to/your-specs \
  --output /absolute/path/to/new-delivery
```

`module:factory` 由调用方显式选择，导入会执行本地 Python；不会从候选 JSON 或源文件内容
中寻找并执行插件。Collector 不需要继承 Kit 的类，只需满足接口并返回 FactDocument。

## 路径二：LLM 辅助接入

先显式选择文件生成请求包，不默认扫描整个仓库：

```bash
python -m capability_snapshot_kit prepare \
  --source-root /absolute/path/to/your-agent \
  --include agent.py --include contracts.py --include README.md \
  --profile conversation \
  --output /absolute/path/to/request.json
```

请求包含：完整抽取约束、FactDocument JSON Schema、所选评测 Spec、文件内容及 SHA256。
只选择允许提供给模型的文件；本组件不自动发送网络请求，也不自动发现模型密钥。
默认 `conversation` 配置不要求工具；复杂 Agent 可用 `--spec-root` 提供自己的配置。
生成候选后导出时必须选择相同的 Spec；带 `--request` 的导出会核对配置和来源白名单。

可以把 request.json 提供给你选择的模型，将结果保存为 candidate.json，也可以实现：

```python
from capability_snapshot_kit.ingestion import FactDocument

class Extractor:
    def extract(self, request):
        response = my_model.generate(request.model_dump(mode="json"))
        return FactDocument.model_validate_json(response)

def create():
    return Extractor()
```

```bash
python -m capability_snapshot_kit extract \
  --request /absolute/path/to/request.json \
  --extractor your_package.extraction:create \
  --output /absolute/path/to/candidate.json

python -m capability_snapshot_kit export \
  --candidate /absolute/path/to/candidate.json \
  --request /absolute/path/to/request.json \
  --source-root /absolute/path/to/your-agent \
  --profile conversation \
  --output /absolute/path/to/new-delivery
```

Extractor 可接任意模型，也可返回本地生成结果。它的输出始终走 candidate 路径；不会因
插件是 Python 就获得 Collector 的信任。组件不内置厂商 API，真实模型调用需由接入方配置。

合并时可同时指定 `--collector` 和 `--candidate`。第一版对同 ID 的完整事实要求一致；
冲突会阻止导出，不做字段级自动覆盖。候选可以添加其他事实，但未被 Collector 确认的
能力状态全部归为 unknown，包括候选中的 supported 和 unsupported。
Agent 身份、版本、配置、入口和 Schema 不一致也会失败。

## 约束、验证与缺口

- 完整 LLM 约束随包提供：`resources/extraction.md`；输入 Schema 可用 `schema` 命令导出。
- 来源仅允许项目根目录内的普通文件；拒绝绝对路径、父目录跳转、符号链接越界和内容摘要变化。
- 单文件最多 1,000,000 字节，请求/来源总量最多 8,000,000 字节；输入须为 UTF-8 文本。
- 来源绑定在事实级别，可在职责、语义、reason 中记录具体符号；当前不自动证明某段源码支持某条声明。
- 缺少来源产生 `MISSING_SOURCE`。Collector 属于受信接入边界，其声明仍可进入配置快照，
  审核者应处理缺口；LLM 候选不会因此提升状态。
- LLM 不可新增 `registered=true` 的工具；依赖工具但无注册事实时保留 required_tool_name，
  报告 `REQUIRED_TOOL_NOT_REGISTERED`。真实工具须从 Collector 读取。
- `configured` 表示插件声明当前配置具备能力，**不是 observed，也不是评测 PASS**。
  即使来源是 trace，组件也不自动把单次记录提升为完整能力证明。
- 原始输入保存于 inputs.json；provenance.json 同时保留原声明与最终状态。
- 本版不自动发现所有能力、不调用未知 Agent、不提供生产后端、不新增评测用例或评分器。

## 交付与 Builder/Evaluator

```text
delivery/
  bundle/           # Builder 只读取这里，仍为 Snapshot 3.0
  facts.json        # 实际送入编译器的事实
  inputs.json       # Collector 和候选的原始结构化输入
  provenance.json   # configured/declared、文件来源、状态变化
  gaps.json         # 未核实、明确不支持、缺少来源/工具
  validation.json   # 结构、引用、Hash 校验；execution_verified=false
  manifest.json     # 根快照、子包、Spec 与所有交付文件的摘要
```

报告在 bundle 外，避免改变消费方协议。已存在的交付目录不会覆盖；manifest 最后写入，
是交付完整标志。数据和运行配置变化后生成新目录，再由 Builder/Evaluator 选择对应版本。
来源 SHA256 只能用于检测变化，不能替代语义审查或数字签名。

```bash
python -m capability_snapshot_kit validate --input /absolute/path/to/delivery/bundle
python -m capability_snapshot_kit resolve \
  --input /absolute/path/to/delivery/bundle --selection /absolute/path/to/selection.json
```

## 本仓库的两个接入示例

在仓库根目录运行，确保 examples 可以被 Python 导入：

```bash
.venv/bin/python -m capability_snapshot_kit export \
  --collector examples.customer_service.collector:create \
  --profile conversation --output exports/customer_service_v1

.venv/bin/python -m capability_snapshot_kit export \
  --collector examples.full_tool_fixture.collector:create \
  --spec-root capability_specs --output exports/mini_agent_portable_v1

.venv/bin/python -m examples.customer_service --input '退款政策是什么'
```

客服示例不依赖 minimal_agent，没有 Tool，提供示例政策回答、空输入追问和转人工建议；
不执行真实转接，不含跨轮记忆。它的业务 Intent 是 `intent.customer_support`，可选择
`scope.result` 或 `chain.end_to_end`，`tool_id` 为 null。这验证的是另一类 Agent 可以接入，
不表示通用客服模型已实现。

MiniAgent 示例仍为六个隔离内存工具，生成的 bundle 与原有 Adapter 导出一致。
独立 Kit 的 Collector 无需固定为这两个工厂，替换为目标项目的工厂即可。
