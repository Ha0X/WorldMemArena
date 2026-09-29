# 当前正式实验协议：Codex + GPT-6，GUI 子集

返回 [文档总览](README.md)。本页维护生效配置和复现步骤；进度统一见 [状态与 TODO](codex_gpt6_status_and_todo.md)，协议演进见 [实验过程](codex_gpt6_gui_experiment.md)。

日期：2026-09-29。目标是在 WorldMemArena 的 harness-based 范式下运行真实 Codex CLI + `gpt-6-astra`，取得可以与论文同名 QA 指标并列、但不夸大可比范围的结果。

本轮已完成：3 个 GUI 样本、161 QA，联合审计通过；宏平均 QA-C/H/O 为 70.81 / 13.01 / 16.18（%），F1 34.26%，BLEU-1 16.48%。最终结果与限制（本地产物：`exp_log/codex_persistent_isolated_v1/report/report.md`）。

## 固定配置

环境前提、安装路径限制及脚本分类见 [脚本导航](../scripts/README.md)。
源码审计要求与历史 manifest 哈希一致；本次 Git 整理不改写正式运行的 manifest 或原始证据。

- 仓库基线：`15ea25b723d9c4fb35e8062037aec6a5601e4442`；本地适配未提交，实际源码 SHA-256 存在每次运行的 `manifest.json`。
- Codex CLI：0.158.0；backbone 请求：`gpt-6-astra`；provider：icodeeasy Responses；reasoning effort：medium；personality：pragmatic。
- 数据 revision：`e2148757921fc7e2d66d8ed899823b763227c341`；本地 GUI 子集 `excel_01`、`file_mgmt_01`、`web_01`。每个 25 sessions / 5 checkpoints，QA 数为 54、54、53。
- Judge 请求：`gpt-5.4-mini`；provider 先前及本轮实际返回标识：`gpt-5.6-terra`。用户接受此差异，报告继续披露，不能据名称自行确认实际模型身份。
- 真实调用路径：repository CLI → pipeline → HarnessMemoryAdapter → Codex CLI。Judge 使用仓库 evaluator，5 个 worker。不重新执行 GUI 任务，输入的是已记录轨迹。

## 状态与输入协议

1. 每个样本启动新进程、新工作目录、新 CODEX_HOME、新临时数字 UID、新 Codex thread。
2. session 按仓库原顺序输入。首调用 `codex exec`，后续按确切 thread ID `codex exec resume ID`，不用 `--last`，不使用 ephemeral。
3. checkpoint 保持原 `_BATCH_QA_PROMPT`。问题和生成答案进入当前 thread 的后续历史；gold 不进入。
4. 原生 caption、图片路径与提示词内容保持原样。adapter 原本不通过 `--image` 主动附图，本轮也不附图。仅在某个 session 实际发给模型前，允许读取该 session 的精确附件文件；历史已见图片继续可读，未来图片不开放。
5. 不添加 B 的 JSON memory MCP，不规定如何写记忆，不人为补贴历史，不把 gold memory 点放入上下文。Codex 自行决定是否调用工具/写文件。

持续 thread 是修复仓库 Codex 历史交接缺失的本地适配。它符合论文公开描述的“sequential sessions + staged checkpoint QA”，但没有作者 trace 证明运行细节完全相同，因此不称为作者 runtime 的精确复现。N/B 旧探索不混入此结果。

## 运行隔离

容器内 bubblewrap 的挂载传播操作被拒绝，但 user/net/PID/IPC/UTS namespaces 与 Landlock 可用。本轮采用外层隔离约束整个 Codex 进程树：

- 每个样本使用新随机数字 UID，仅用于进程和新建临时文件，不创建系统账号或修改容器权限。
- Landlock 限制为样本目录可读写、系统 runtime 可读执行、已送达附件逐文件只读。仓库数据、gold、未来 session、旧实验目录、宿主 home/proc 不开放。
- Seccomp 补齐 ABI 1 的 truncate 等缺口，限制 namespace/ptrace/io_uring 和 Unix pathname socket。只保留 Codex 内部 signal 通知所需的已连接 Unix stream socketpair。
- 独立网络只有 loopback；可信 relay 将本地 Responses 请求转给隔离外的专用 Unix socket 代理。真实 API key 在外部代理内，Codex 环境只有 placeholder，不能访问宿主网络或任意外部站点。
- Codex 状态文件需要 chmod/fchmod 和 fd 形式的时间戳更新；这些操作由独有 UID 的文件所有权约束，同时保持外部输入只读。普通路径 truncate 仍拒绝。
- 内层 Codex sandbox 设置为 `danger-full-access` 以避免再次启动不可用的 bwrap；该模式只能由外层隔离启动器使用，不是在宿主直接无限制执行。

该隔离是保障本评测内容边界的运行配置，不是经过完整安全审计的恶意代码托管平台。ABI 1 对文件存在性/部分元数据不做完全隐藏，本轮也不研究资源耗尽攻击。遵照用户提醒，不继续扩展通用沙箱功能。

## 验收证据

- `exp_log/codex_persistent/environment_check/external_isolation.json`：20 项本地合成边界检查通过，包括当前图片读取、隔离外内容/网络限制、元数据修改限制、环境凭据清理、shell 与 Codex 启动。
- `exp_log/codex_persistent/isolated_tool_check_v4/result.json`：三次实际模型调用、同 thread；写文件、下一调用读回、只在上下文中出现的随机事实恢复、外部 canary 拒读通过，未出现 rollout 写入错误。
- `tests/test_codex_thread_handoff.py`：5 项测试，包括附件不能因预加载后续 session 而提前开放。
- v1–v3 工具目录仅为兼容性诊断，未使用 benchmark gold；v4 为最终验收。旧 Excel 首 checkpoint 只作历史上下文验收，不能替代本轮完整 Excel。

## 运行与产物

以下命令从项目根目录执行。重新评测会调用模型 API，必须使用不存在或为空的新输出目录；示例使用 `_rerun` 目录，避开本轮已完成产物。三个命令各自运行一个独立样本。

```bash
conda run --no-capture-output -n worldmemarena python -u scripts/run_native_codex_gpt6.py \
  --persistent-session --isolated --sample-index 1 \
  --output exp_log/codex_persistent_isolated_rerun/excel_01

conda run --no-capture-output -n worldmemarena python -u scripts/run_native_codex_gpt6.py \
  --persistent-session --isolated --sample-index 2 \
  --output exp_log/codex_persistent_isolated_rerun/file_mgmt_01

conda run --no-capture-output -n worldmemarena python -u scripts/run_native_codex_gpt6.py \
  --persistent-session --isolated --sample-index 3 \
  --output exp_log/codex_persistent_isolated_rerun/web_01
```

任何非空输出目录都会被拒绝，以免混合旧 thread；再次复现时还需换另一个目录名。有效运行不因分数低而重跑挑选。不要把这里的评测命令和 N/B 探索脚本混用。

完成后可以只审计和汇总，不重新调用模型。以下检查已有正式运行，并写入新的报告目录：

```bash
conda run --no-capture-output -n worldmemarena python scripts/summarize_persistent_codex.py \
  exp_log/codex_persistent_isolated_v1/excel_01 \
  exp_log/codex_persistent_isolated_v1/file_mgmt_01 \
  exp_log/codex_persistent_isolated_v1/web_01 \
  --output exp_log/codex_persistent_isolated_v1/report_recheck
```

审计覆盖全量 QA、原生提示词逐字一致、精确 resume/单 thread、样本间隔离、图片白名单、有效完成、QA 回复与评分记录一致、无 rollout 写入错误。审计器还检查运行源码哈希与原始状态；若代码已改变或原 `/tmp` 工作区已清理，需要先核对归档，不应直接忽略检查失败。

工具事件用 CLI 和传输两份证据，避免单看 CLI 漏报或两份相加重复计数。Codex resume 的 usage 是 thread 累计值，汇总取最终累计值并与 rollout 核对，不逐次相加。

### 文件与证据定位

| 文件 / 目录 | 作用 |
|---|---|
| [run_native_codex_gpt6.py](../scripts/run_native_codex_gpt6.py) | 调用仓库真实评测入口并记录 manifest |
| [harness_api.py](../eval_framework/baselines/_clients/harness_api.py)、[harness_native.py](../eval_framework/memory_adapters/harness_native.py) | 可选持续 thread 交接与附件送达钩子；原提示词不变 |
| [wma_isolation.py](../scripts/wma_isolation.py)、[wma_isolated_sample.py](../scripts/wma_isolated_sample.py) | 外层隔离、样本配置和图片开放范围 |
| [codex_native_logged.py](../scripts/codex_native_logged.py)、[wma_transport.py](../scripts/wma_transport.py) | CLI/传输日志与代理 |
| 正式产物根目录（本地产物：`exp_log/codex_persistent_isolated_v1/`） | 每样本原始调用、评分、附件记录及 state_snapshot |
| report/（本地产物：`exp_log/codex_persistent_isolated_v1/report/`） | 结果、验证、源码快照、环境版本和数据哈希 |

各次运行保存 manifest、CLI 参数/事件/stderr/status、请求工具审计、附件开放记录、pipeline、逐题预测/gold/评分及 aggregate metrics；真实 key 不写入这些日志。

各 manifest 中原配置可能保留 `ephemeral: true`，但启用 persistent-session 后实际命令不传 `--ephemeral`；以已审计的命令和 thread 交接记录为准。

## 与论文对照的边界

指标定义、宏平均方式、论文参考表以及 judge 案例统一见 [指标解释与论文对照](codex_gpt6_paper_comparison.md)。本地为三个 GUI 样本各一次运行，作者 runtime 未完全确认；结果主要体现持续上下文，不支持全 benchmark 排名、显著性或自主磁盘记忆效果的结论。
