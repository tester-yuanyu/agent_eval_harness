# Langfuse 保存结果交付优化验收

本批只实现与离线验证保存结果的交付路径；未启动 Docker、未访问 Langfuse、未调用模型、未上传历史 365 条结果。原始 `results.json`、冻结任务与评分保持不变。现有 exporter 和证据验证仍是唯一实现，新增层负责目标、节流、写入检查点与同步状态。

## 显式目标与本地服务复用

提供两个不含凭据的示例：

- `configs/benchmark/langfuse-local-profile.example.json`：只允许 loopback 目标。
- `configs/benchmark/langfuse-cloud-profile.example.json`：远端 HTTPS 目标；必须明确修改 project ID，并配置示例指定的环境变量。

Profile 只保存 `public_key_env`、`secret_key_env` 的环境变量名称。不会从全局 `LANGFUSE_BASE_URL` 或其他 profile 自动选择替代目标。目标指纹沿用原 exporter 的 base URL + public key 算法，已有目标回执可继续使用；来源与目标改变时拒绝覆盖现有交付状态。未知字段、嵌入凭据、含认证信息的 URL、无效限流配置会在创建客户端前拒绝。

已有本地 Langfuse 可生成显式复用 profile；该命令只写 profile，不调用 Docker 或服务 API：

```sh
.venvs/evaluator/bin/python packages/evaluator/scripts/local_langfuse.py reuse \
  --base-url http://127.0.0.1:3000 --project-id agent-evaluator \
  --profile-output tmp/langfuse-local-profile.json
```

凭据仍由用户在本机配置到 `LOCAL_LANGFUSE_PUBLIC_KEY`、`LOCAL_LANGFUSE_SECRET_KEY`。不把已有部署私有配置复制到跟踪文件，不旋转或覆盖凭据，不隐式启动已有服务。

## 保存结果同步入口

默认评测流程仍只完成本地执行、评分与报告。明确要求交付时才调用：

```sh
.venvs/evaluator/bin/python -m eval_framework.benchmark.langfuse_delivery \
  --profile tmp/langfuse-local-profile.json \
  --run /absolute/path/to/saved-run \
  --dataset /absolute/path/to/tasks.jsonl \
  --verification-attempts 3 --index-wait 2
```

对应 API：`sync_run(run_dir, dataset_path, profile=load_profile(profile_path))`。本批验收没有执行以上真实同步命令。云端示例同样需要用户明确选择，不能作为本地服务不可用时的备用目标。

调用顺序复用 `export_run` → `export_metadata_evidence` → `verify_run`，不执行 Agent、不重新评分。每次验证前等待索引，最多按指定次数回读；不匹配记录 `PENDING_INDEX`，不会无限轮询。三个命令原有 API 和环境变量模式继续可用，新 profile/续传层是显式入口。

`langfuse_delivery.json` 单独记录 `local_status=COMPLETE` 和 `sync_status`：`PENDING`、`VERIFIED`、`PENDING_INDEX`、`NEEDS_RECONCILIATION` 或 `FAILED`。这里本地完成表示已存在保存结果，不代表 Agent PASS；远端失败不会重新触发 Agent 或降低本地评分。异常只写类型，不写可能带密钥的响应/异常全文。身份或 profile 配置错误仍直接报错。CLI 仅在 `VERIFIED` 时返回 0，其余状态返回 1。

阶段计时复用 `phase_timing.timed_phase`，追加到 `phase-timings.json`，阶段为 `langfuse_export`、`langfuse_metadata_export`、`langfuse_index_wait`、`langfuse_verify`。每轮验证单独保存 attempt、来源 Hash 与目标指纹，使用单调时钟记录本次真实耗时；不向历史结果补写未知阶段时间，不把重叠阶段累计值当墙钟。

## 续传与限流语义

- `langfuse_delivery_journal.json` 在每次 Dataset、Dataset Item、OTLP 或 Score 写入前持久化操作 Hash 和稳定 ID，不保存请求正文/凭据。操作 Hash 覆盖完整请求，来源由独立交付状态绑定。
- 已确认接收的操作可复用。未知接收状态先按数据集名称或稳定 observation/score/item ID 回读；全部找到才确认接受。找不到、部分找到或索引未完成均保留 `NEEDS_RECONCILIATION`，禁止盲目重放。可以稍后使用同一同步命令重新回读。
- 网络连接尚未建立和明确 HTTP 拒绝可以重新提交；HTTP 5xx、读写超时和部分接收不能假定未写入。SDK 隐式重试关闭；429 最多尝试三次，遵循数字或 HTTP-date `Retry-After`。
- Dataset、Tracing、Read 分别维护发送间隔；某个桶等待不会锁住另一个桶。示例间隔是保守本地配置，不宣称适用于任意云端套餐。
- 同一 run 的同步入口持有进程锁；已有 exporter 的 Dataset Item 线程由 journal 锁保护。不支持绕过 `sync_run` 同时用多个进程写同一 journal。
- 旧 exporter 已有但没有新 journal 的不确定 inflight 批次不能自动证明已接收，保持拒绝重发并要求显式核对，不伪造迁移状态。

对于最终一致索引，缺失 ID 不能证明请求被拒绝，因此本批选择安全停留待核对。未提供“强制重发”开关，完整内容是否一致继续由既有 `verify_run` 判断，ID 回读不会替代正式验证。

## 整批报告入口

`report_links.load_links` 继续返回原来的 `(case_id, trial) → trace URL` 映射。新增 `load_run_links` 返回 `dataset` 和 `experiments`，仅使用已经通过回读验证、来源 Hash 匹配、回执 Hash 匹配的材料；每个 experiment 的远端 item 数必须等于预期数及本地 trace 数。

数据集入口采用 `/datasets/<id>`，实验入口采用仓库现有已验证形式 `/experiments/results?baseline=<id>`，均对标识符进行 URL 编码。旧 `report-links-v1` 没有新增字段时可只读派生整批入口；存在新增字段时必须与派生结果完全一致。复制原始结果和完整回执到新报告目录不影响 Hash 校验，加载链接不改写历史文件。API 验证不等于新版本 UI 路由实测，本次没有在线打开界面。

## 离线验收与限制

新测试覆盖：profile 目标不回退、凭据引用与字段拒绝、独立桶与并发等待、429 `Retry-After`、未知 Dataset/Item/OTLP/Score 写入先回读、索引未完成禁止重放、空 partial-success 的正常接受、旧 inflight 接入、同步状态与有界验证、同 run 进程互斥、实验链接篡改拒绝、旧链接只读兼容、本地复用 CLI 不触发 Docker。

测试按 RED → GREEN 进行；19 项 delivery 测试以及 3 项本地部署测试通过，相关 exporter/evidence/metadata/report 回归一并执行。最终稳定源码的全包回归和全新克隆验收由协调者统一执行。本批提前尝试从根目录跑全包遇 `tests.support` 收集路径错误，已按 `packages/evaluator/AGENTS.md` 改为包目录命令；进行中的包回归日志位于 `tmp/eval-optimization-20261111/langfuse-evaluator-regression.log`。

本批没有真实服务性能测量，不承诺固定提速比例或在线交付完成；已 VERIFIED 的历史结果不重跑、不自动上传。
