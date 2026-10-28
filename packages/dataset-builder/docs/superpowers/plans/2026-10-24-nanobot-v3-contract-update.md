# Nanobot v3 契约更新实施计划

> 用户已授权直接更新；执行计划、测试和最终独立审查，不再请求确认。

**Goal:** 依据新包补齐的执行契约更新候选、断言与阻塞清单，交付独立新版本并保留旧版。
**Architecture:** 扩展现有nanobot适配器以保留delivery/bundle布局，核验execution_contract.json与快照一致。新增明确契约候选；参数Schema支持本包not与Python-only注解。增量报告分别列出已解除、收窄、保留及新增阻塞。
**Spec:** 用户提供nanobot_snapshot_v3/EXECUTION_CONTRACT.md与execution_contract.json；只采用明确来源，不推测缺失预期。
**Tech Stack:** 现有Python/Pydantic/jsonschema，验证解释器为相邻agent_evaluator虚拟环境。

## 约束

- 不修改nanobot输入、旧nanobot候选集、mini_agent产物，不运行Agent、工具或外部服务。
- 静态契约supported不等于执行通过；未知业务、权限、副作用、幂等、批量、工具成功结构仍保留缺口。
- 区分返回、异常、取消；异常捕获envelope非原生输出且观察器unknown。
- 普通run边界不等同StreamEvent生命周期；不推断全局静止、回滚或completed即成功。
- 新目录workspaces/nanobot_full_eval_v3_20261024；DRAFT/NOT_RUN/PENDING，独立ZIP。
- 更新后的验证器继续复验旧交付；不以新版规则篡改历史产物。

## Tasks

- [x] 验证新包Hash、37快照、布局及新旧来源变化；补齐输入兼容测试。
- [x] 测试先行覆盖not互斥/保留channel、Python-only、required无properties、nullable数组和const。
- [x] 依据明确契约更新候选与阻塞原因、来源；新增共享错误与各终止分支候选，回归禁止猜测断言。
- [x] 支持--previous生成契约/候选/断言/阻塞差异报告，修正交付文档和动态统计。
- [x] 新旧回归、Ruff、独立审查、生成、复验和ZIP检查，验证两旧目录Hash未变。

## 完成证据

- 全项目测试：`PYTHONPATH=src ../agent_evaluator/.venv/bin/python -m pytest -p no:rerunfailures -q`，246 passed；日志 `/tmp/nanobot-v3-full-tests-final.log`。Ruff 检查本次涉及代码与测试通过。
- 独立审查逐条核对 31 条新增契约候选；修复来源标签降级、删除候选/阻塞关联绕过，以及同包删除旧分支阻塞被误报 superseded 三类问题。新增 mutation 回归，审查者最终复核关闭全部发现。
- 新交付 `workspaces/nanobot_full_eval_v3_20261024`：37 快照、31 主要目标、133 JSONL、2,724 记录（1,896 Schema、549 声明、120 行为、159 阻塞义务），222 个阻塞项。
- 行为候选 117 blocked、3 needs_runner；后者是原有 supported 的返回对象观测候选，未新增能力支持推断。全部 NOT_RUN / PENDING；EvalCase 兼容数 0。
- 差异：新增 349、移除 3、更新 2,375 条；更新中输入变化 75、断言变化 135，可重叠，2,186 条输入与断言语义均不变。阻塞保留 173、收窄 43、细化替代 3、新增 6、显式解除 0、无依据消失 0。
- generate-nanobot 暂存自验及 validate-nanobot 独立复验均 valid=true；包内差异基线无需旧目录原位置即可复算。
- ZIP 共 290 个文件、1,399,717 字节；CRC、文件清单及逐文件 SHA256 均与输出目录一致。ZIP SHA256：`5c6211b26256eb104e85d631596deaf7e016f4614bb3eab8da91af0b99ad8c76`。
- 与工作开始时 `/tmp/nanobot-v3-previous-lock.json` 比较：旧 nanobot 263 文件、mini_agent 253 文件均未变化。没有运行 Agent、真实工具或外部服务。
