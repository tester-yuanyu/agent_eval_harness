# nanobot 能力覆盖：已保存证据的公开摘要

本轮 24 个 dev 任务，计划每条 3 次；观察到 72/72 个 trial。PASS 69、FAIL 3、INVALID 0、INCONCLUSIVE 0，缺失 0。

这些是固定源码与配置下的真实组件调用，不是模型或完整 Agent 成绩。当前 trial 通过完整确定性重评分；历史结果仅核对原始来源/身份，不用当前评分版本重算。

| 组件 | 计划任务 | 观察/计划 trial | PASS | FAIL | INVALID | INCONCLUSIVE | 全部重复通过任务 |
|---|---:|---:|---:|---:|---:|---:|---:|
| context | 6 | 18/18 | 18 | 0 | 0 | 0 | 6 |
| memory | 6 | 18/18 | 18 | 0 | 0 | 0 | 6 |
| session | 6 | 18/18 | 15 | 3 | 0 | 0 | 5 |
| skills | 6 | 18/18 | 18 | 0 | 0 | 0 | 6 |

24/24 个任务重复记录齐全；24 个判定一致，23 个全部重复通过。一致失败不等于通过，这也不证明 LLM 稳定性。

当前 0 次模型调用；8 条 reserved holdout 仅做合同/Hash 校验、未执行；独立人工审核与人工标签均未完成。

`core-session_legal_replay-orphan` 保留原始失败和冻结 Oracle。其要求保留孤立 tool 之前的 user 消息，而当前实现采用合法后缀策略；这是需求/Oracle 待裁定项，不能直接称为产品缺陷。

被测源码为 dirty 工作树；commit 不能单独重建本次源码，须核对 snapshot 的逐文件与 working_tree Hash。
公开产物仅保留源码 Hash，不复制外部 nanobot 源码；本轮不构成完整产品验收。

## 历史来源单列

绑定 4 个历史运行，共 612 条历史 trial。这些记录保留原有版本和分母，不与本轮组件 trial 相加，不升级当前 File Tools profile 覆盖。

| 历史运行 | 观察/计划 trial | 原始结果 SHA256 |
|---|---:|---|
| modules60-scored-regrade-4bd78c93 | 60/60 | `425c9318ee06a276c08a1fe2792b2a73a727d22942a666a518a66b473fe1f39a` |
| decisions24x3-scored-regrade-016e7219 | 72/72 | `c318221f60571709e5843b7cbcc5b23e58d51eaa71dd2a7668fdaf2a26bb6507` |
| chains60x3-scored-regrade-f0242ffc | 180/180 | `769dcc543feb5ab2decc4043aa49a65e417ae570a0ed8ff9299548bf0f0201e3` |
| e2e300-scored-regrade-823fe3e8 | 300/300 | `6f95ca77865b0e0473cd3c82c33b08dd7a85d4e415dc1c3d920f72203e00dc3a` |

## 15 个能力域的当前覆盖边界

定义数以 case 为单位，包含已定义但未执行的 holdout；执行数以当前 profile 下证据完整的 trial 为单位，包含 FAIL，不等于通过数。源码存在或被其他组件间接调用，不自动增加任务数。
历史运行仅见上节；不得填入下表的当前执行数。本表是有限 catalog 的逐域清单，不计算 nanobot 整体覆盖率。

| 能力域 | File Tools 定义 case | File Tools 当前执行 trial | Core 定义 case | Core 当前执行 trial | 优先级 |
|---|---:|---:|---:|---:|---|
| 文件工具 | 444 | 0 | 0 | 0 | P0 |
| 会话持久化与隔离 | 0 | 0 | 8 | 18 | P0 |
| 长期记忆与历史存储 | 0 | 0 | 8 | 18 | P0 |
| 上下文组装与边界 | 0 | 0 | 8 | 18 | P0 |
| 技能发现与调用 | 0 | 0 | 8 | 18 | P0 |
| Shell与进程管理 | 0 | 0 | 0 | 0 | P1 |
| Web检索与抓取 | 0 | 0 | 0 | 0 | P1 |
| MCP协议与生命周期 | 0 | 0 | 0 | 0 | P1 |
| 渠道与消息投递 | 0 | 0 | 0 | 0 | P2 |
| 定时与Heartbeat/Dream | 0 | 0 | 0 | 0 | P2 |
| 子代理调度与结果回流 | 0 | 0 | 0 | 0 | P1 |
| 工具插件发现与注册 | 0 | 0 | 0 | 0 | P1 |
| 模型Provider与配置路由 | 0 | 0 | 0 | 0 | P1 |
| 工作区策略 | 0 | 0 | 0 | 0 | P0 |
| Gateway与API生命周期 | 0 | 0 | 0 | 0 | P2 |

### 尚无独立绑定任务的能力域

- **P0**：工作区策略。
- **P1**：Shell与进程管理、Web检索与抓取、MCP协议与生命周期、子代理调度与结果回流、工具插件发现与注册、模型Provider与配置路由。
- **P2**：渠道与消息投递、定时与Heartbeat/Dream、Gateway与API生命周期。

### 待裁定与未执行项

- **Oracle 人工裁定**：确认 `core-session_legal_replay-orphan` 应采用保留前缀还是合法后缀语义；保留原 FAIL，不直接称为产品缺陷。
- **核心 holdout**：定义 8 条，执行 0 个 trial；本轮仅校验合同与 Hash，未做执行验收或独立人工审核。

## 复核

- [summary.json](summary.json)：逐 trial 的 case/trial/verdict/validity/耗时、原始 row 与原始 trial 文件 Hash；含分母与重复一致性。
- [snapshot.json](snapshot.json)：源码逐文件 Hash、解释器/依赖与有效 profile 身份。
- [coverage.json](coverage.json)：源码存在、启用、场景定义、执行、通过及人工审核六种状态分开。
- 原始 results.json 字节 SHA256：`92ce64447f70dbe65b09d90cdbbbbc5f2c10f47ed819a60b9a40d1e88b8ff098`。
- 本轮 identity_hash：`223e95dad503e737d51b057ba736edb11ac7ea55ced5aac7714781165764e2dc`。

摘要未公开原始 observation、完整上下文、文件正文或本机绝对路径。在原工作区保留 raw results/trials 后，可按 summary 的原始 Hash 复核。生成命令见仓库 docs/benchmark/nanobot-coverage.md；使用相同输入再次生成得到相同字节，程序拒绝覆盖不同结果。
