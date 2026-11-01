# File Tools v1 文件工具数据集说明

这是面向真实工具型 Agent 的合成文件任务集。每次执行从独立、固定的 UTF-8 文件工作区开始，Agent 通过 `read_file`、`write_file`、`edit_file`、`list_dir` 完成任务；评分读取独立采集的文件终态和公开回复。任务数据不依赖 nanobot 私有实现。

| 主类别 | 实例数 | 任务族 | 开发集（dev） | 留出集（holdout） |
| --- | ---: | ---: | ---: | ---: |
| 读取与搜索 `read_search` | 60 | 20 | 48 | 12 |
| 创建与编辑 `create_edit` | 100 | 20 | 80 | 20 |
| 多文件、多步骤 `multi_file` | 80 | 20 | 64 | 16 |
| 需求变更、多轮上下文 `multi_turn` | 40 | 10 | 32 | 8 |
| 缺失资源与异常输入 `missing_error` | 20 | 10 | 16 | 4 |
| **总计** | **300** | **80** | **240** | **60** |

300 是可执行实例数，80 是任务族数。每族包含 2–5 个不同参数和文件内容的实例；不能将这些参数变体表述为 300 种独立业务能力。建议同时报告类别、任务族、实例的结果，避免只展示总成功率。

`dev` 与 `holdout` 按完整任务族隔离，不把同一模板的参数变体随机分到两边。首次验收前不依据 holdout 结果调整提示词；一旦用于调参，必须如实说明它已不再是未使用的验收集。这个人工设计的切分没有证明对任意未知工具或领域的泛化能力。

## 语言与中文阅读入口

300 条 `prompt` 和 40 条后续指令（`followups`）均为中文自然语言，文件名、工具名、JSON 键和要求精确保留的文件内容继续使用原始字面量。300 条英文 `description` 是说明元数据，不进入 Agent 的执行输入。

可打开[中文逐条阅读页](../../../docs/dataset-reading.html)选择本数据集，查看具体任务、中文说明和原始文字；[逐条中文对照文件](reading.zh-CN.jsonl)记录来源任务 ID 与原始任务 SHA-256。对照只用于阅读，不替换模型输入、不修改评分依据，也不表示完成了新一轮评测。完整统计与处理规则见[评测集语言说明](../../../docs/dataset-language.md)。

## 文件和冻结规则

- `tasks.jsonl`：固定任务、输入文件、私有 oracle 和私有参考变换操作。
- `manifest.json`：数据集版本、任务字节 SHA-256、契约与 grader 版本、规模及来源说明。
- `build_dataset.py`：可重复生成器；默认校验既有文件完全一致，拒绝覆盖不同的冻结版本。修改任务需要发布新版本，不得为了让某次 Agent 通过而覆盖旧数据。

在仓库根目录运行：

```bash
.venvs/evaluator/bin/python data/benchmarks/file-tools-v1/build_dataset.py
.venvs/evaluator/bin/python -m pytest -q -c packages/evaluator/pyproject.toml \
  packages/evaluator/tests/benchmark/test_tasks.py \
  packages/evaluator/tests/benchmark/test_oracle.py
```

生成器可确定性复现 300 条实例及冻结 Hash。自动测试用独立参考变换器执行全部实例，并验证它们通过 oracle。参考执行器只读取 fixture 和受限的变换操作，不从 `oracle.expected_files` 复制答案。**参考执行通过仅证明预期答案可由给定初始环境计算得到，不是被测 Agent 的评测结果。**

## 执行与评分边界

`execution_task()` 只向 Agent 提供 `id`、`prompt`、`followups`、`fixtures`、`allowed_tools`、`max_steps`。`oracle`、`reference`、`required_tools`、分组与切分标签留在可信评测侧。

独立终态 oracle 检查：实际初始环境是否与 fixture 一致、任务是否执行完成、是否完整执行全部轮次、指定文件的精确内容、禁止创建的文件、不应变化的文件、意外创建的文件，以及请求的字面回复标记。`RESULT=2` 不会错误匹配 `RESULT=20`。JSON 格式和换行要求在任务中显式给出；格式不同可能导致文件终态失败，应在失败归因中与业务数值错误区分。

`required_tools` 表示参考工具覆盖，适用于工具选择的诊断评分。存在多个合法调用方案，例如文件替换可通过 `edit_file` 或 `write_file` 完成，因此该列表不应独立否决正确终态。`allowed_tools` 才是允许调用的工具边界。

## 来源与适用范围

本集由 AI 辅助编写，输入是公开可展示的虚构数据，没有真人个人信息或真实业务凭证。未经过用户人工逐条审核，`human_reviewed=false`。当前证据包括结构校验、Hash 校验、跨切分任务族隔离检查、参考执行与失败场景的自动测试。

本集覆盖文件工具、结构化数据转换、多步骤操作、多轮变更、异常输入的正确处理。它不包含 shell、浏览器、数据库、付款、消息发送或生产系统写入，也不代表 τ-bench、BFCL 或 SWE-bench 官方数据集。

多轮任务使用固定 follow-up，验证轮次数与最终文件状态；目前没有独立的中间轮状态 oracle，不能据此声称验证了每一轮承诺、动态用户模拟或复杂澄清策略。只有完整真实 Agent 执行日志、独立终态、正式评分与 Langfuse 记录齐备的运行，才应计入作品集结果。
