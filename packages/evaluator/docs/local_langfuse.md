# 本地 Langfuse 与自动评测交付

Langfuse 可以部署在自己的电脑上。本项目使用官方 Compose 和原生看板 API；Inspect 继续负责执行与正式评分，Evaluator 只把保存的结果交给 Langfuse 展示，不重算通过率。

## 一次性部署

安装并启动适合本机的 Docker Desktop。首次协议和系统授权由用户完成。项目 Python 环境需要已有的 PyYAML。以下命令从仓库根目录运行：

```bash
.venv/bin/python scripts/local_langfuse.py init --port 3300
.venv/bin/python scripts/local_langfuse.py up
.venv/bin/python scripts/local_langfuse.py lock
.venv/bin/python scripts/local_langfuse.py status
```

`init` 生成 `.env.langfuse.local.json` 与 `artifacts/local_langfuse/`。随机 API 密钥、管理员登录信息和服务配置只写入权限为 0600 的本地文件；目录为 0700，均被 Git 忽略。管理员信息在 `artifacts/local_langfuse/login.json`，不要把它贴进报告或提交仓库。重复 `init` 保留原凭据；更改已有端口会被拒绝，避免破坏持久化实例。

服务入口为 [本地 Langfuse](http://127.0.0.1:3300)。默认媒体端口为 9090。只有 Web 与媒体端口映射到 127.0.0.1，数据库不映射到宿主机。产品遥测和内置 AI Agent 关闭，不继承 Shell 中的云端 API 密钥。`scripts/langfuse/docker-compose.upstream.yml` 保存官方模板，部署清单记录其 SHA-256；首次拉取后 `lock` 把所有镜像固定到实际下载的 digest。

`stop` 停止本项目容器，`up` 再次启动；持久卷保留。Docker Desktop 需要保持运行。不要执行 `down --volumes` 或删除卷，否则会丢失本地 Langfuse 历史。备份时同时保留持久卷和受保护的部署配置。

## 每次运行自动交付

在仓库根目录完成上述初始化后，原来的 `run` 命令会在保存正式结果后自动同步本地 Langfuse，并在 CLI JSON 中返回 `delivery`。候选 ZIP 会等待全部分区处理完成、保存最终接入账本后统一生成看板。

```bash
.venv/bin/python -m eval_framework.cli run \
  --input /path/to/agent-dataset.zip --agent-root /path/to/agent \
  --output-dir artifacts/evaluation
```

配置查找顺序：显式 `--local-langfuse-config`、专用环境变量 `AGENT_EVALUATOR_LOCAL_LANGFUSE_CONFIG`、当前目录的 `.env.langfuse.local.json`。从别的工作目录调用时应显式指定配置路径。没有配置或 `enabled=false` 时不联网，原有输出保持兼容。只接受本机回环地址；不会读取历史 `.env.langfuse`、使用 Cloud 凭据或自动回退到 Cloud。

正式 `results.json`、Inspect 原生日志和 `report.md` 不被投递改写。交付阶段额外生成 `local_langfuse/<target>/REPORT.md` 和带来源 Hash 的 JSON 回执，链接到原报告、原生看板及实验。每个分区的统计卡读取唯一的保存值；静态检查、业务执行、未执行、临时结果和已有 Gate 分开说明。未执行项不计作 Agent 失败，也不制造 Trial 或质量分数。

默认看板采用四张指标卡、并排的质量结论与证据有效性横条图、断言明细表和执行范围图。存在行为分区时优先展示行为结果，静态检查独立放在下方；缺失指标不会补成零。严格通过率直接读取 Inspect 保存值，其分母为排除 `NOT_APPLICABLE` 的 Trial。执行范围和未执行数量分别复制已保存的案例元数据和接入账本，仅作为展示标签，不参与正式评分。重复同步复用同一看板与组件。浅色模式可通过左下角账户菜单的 Theme 切换。

## 补同步与故障处理

Langfuse 不可用时，正式评测结果和原退出码不变，投递为 `PENDING`。后续成功投递时会有限量补处理待同步记录；也可直接同步已有结果，不再调用 Agent：

```bash
.venv/bin/python -m eval_framework.cli sync-local \
  --source /absolute/path/to/intake.json \
  --local-langfuse-config .env.langfuse.local.json

# source 也接受保存的 run 目录或 invalid_run.json。
```

`ACCEPTED` 表示 API 接收，页面数据异步入库，仍须检查页面或回读。`RECONCILIATION_REQUIRED` 表示发送后是否接收无法确认，需要根据回执中的 ID 核对；不会盲目重发不可变 observation 或重复创建看板。修改正式来源后的待同步记录不会自动混入原交付。默认不传业务输入输出；首次导出选定的内容模式不能在重试时改变。

看板链接带本轮保存时间的固定范围，避免日后打开时被默认“最近一天”过滤掉。原生实验页中的 Baseline 只用于页面展示；正式 Gate 基线仍只接受 Evaluator 的显式输入。

历史 Cloud 回执 `langfuse_export.json` 保留，本地使用 `langfuse_export.<target>.json`。如以后需要显式 Cloud 导出，仍使用独立的 `export-langfuse` 命令，普通本地评测不会触发它。

部署依据：[官方 Compose](https://langfuse.com/self-hosting/deployment/docker-compose)、[官方初始化配置](https://langfuse.com/self-hosting/administration/headless-initialization)。
