# Codex + GPT-6 脚本导航

当前正式入口是 `run_native_codex_gpt6.py --persistent-session --isolated`。
完整参数与复现命令见 [运行协议](../docs/codex_gpt6_isolated_protocol.md)，结果见 [公开汇总](../docs/results/codex_gpt6_gui_subset/README.md)。

## 当前运行链路

```text
run_native_codex_gpt6.py
  → repository CLI / pipeline / HarnessMemoryAdapter
  → codex_native_logged.py
  → wma_isolation.py → real Codex CLI → controlled Responses proxy
  → repository QA evaluator
  → summarize_persistent_codex.py
```

| 文件 | 职责 |
|---|---|
| `run_native_codex_gpt6.py` | 单样本入口；模型配置、manifest、调用仓库 pipeline |
| `codex_native_logged.py` | CLI 参数与完成事件校验、调用日志、启动外层隔离 |
| `wma_isolation.py` | Landlock / seccomp / namespaces / 独立 UID 运行边界 |
| `wma_isolated_sample.py` | 独立样本状态与按 session 送达开放附件 |
| `wma_transport.py` | Responses 传输代理及实际工具交换审计 |
| `summarize_persistent_codex.py` | 联合审计和样本宏平均报告；依赖 `summarize_native_codex.py` 的统计函数 |

持续 thread 是可选适配，不改变其他 baseline 的默认行为。`harness_config.yaml` 的
`codex_persistent_session` 默认为 false；正式运行入口通过 `--persistent-session` 开启。
原生 session / QA 提示词保持不变。

## 检查与验收

在项目根目录、已配置的 `worldmemarena` 环境运行：

```bash
# 无模型请求，模拟 CLI 返回值。
conda run --no-capture-output -n worldmemarena python -m unittest discover -s tests -v

# 无模型请求；创建临时隔离进程，检查文件/网络边界和 Codex 启动。
conda run --no-capture-output -n worldmemarena python scripts/check_external_isolation.py
```

`check_isolated_codex.py` 是真实工具与上下文验收，会调用模型 API。
`check_codex_thread_handoff.py` 是真实 thread 交接验收，也会调用模型 API。
两者使用合成事实；查看脚本参数并指定新输出目录后再运行。

## 环境前提与当前限制

- Python 3.11+（使用标准库 `tomllib`）、项目依赖，以及 Codex CLI；已验收版本为 0.158.0。
- 本轮模型/provider 固定为 `gpt-6-astra` / icodeeasy；不是通用 provider 适配器。
- 原始 Codex 配置的 `model_provider` 需要为 `icodeeasy`。密钥通过本地环境或 `.env` 配置，不能提交到 Git。
- 隔离实现仅验收 Linux x86_64，需要 Landlock、libseccomp、`unshare`、`setpriv`、`ip`；运行身份须能为新临时目录分配独立 UID。换机器应先跑本地边界检查。
- 当前代码按 npm 全局安装路径定位 Codex：`/usr/local/bin/codex` 及 `wma_isolation.py` 中的 `CODEX_VENDOR`。不同安装布局需先适配并重新验收。
- 该 profile 是评测隔离配置，不是完整审计的通用恶意代码托管沙箱；失败时不要关闭外层隔离继续跑。
- Judge 的连接由仓库配置提供；本轮请求模型和返回标识存在差异，详见 [指标解释](../docs/codex_gpt6_paper_comparison.md)。

## 历史探索与诊断

以下脚本保留用于理解历史，不是当前正式实验入口；历史协议不能与当前分数混合。

| 文件 | 用途 |
|---|---|
| `run_codex_protocols.py`、`wma_memory_server.py` | N/B 等独立 runner 与自定义 JSON memory 探索 |
| `audit_codex_protocols.py`、`summarize_codex_protocols.py` | 历史探索审计与汇总 |
| `diagnose_native_context.py` | 原生入口历史断开诊断；会调用模型 API |
| `summarize_native_codex.py` | 未修复原生运行汇总，同时提供共用统计函数 |
| `check_landlock_isolation.py` | 早期单独 Landlock 探测；不能替代完整外层隔离验收 |
| `run_codex_gui_subtask.py` | 单问题直接调用探索，不是正式多 session 入口 |
| `run_gui_smoke.sh` | `BaseModel-icodeeasy` 冒烟运行，不是 Codex harness |

上游的 `run_worldmemarena.sh`、`run_worldmemarena_harness.sh` 保持原用途。

## 产物与版本

`exp_log/`、数据、图片、论文缓存和 Codex 状态不提交。公开汇总只包含白名单字段，
不含逐题 gold、会话内容、thread ID、主机路径或凭据。
历史正式运行按 manifest 中的源码 SHA-256 标识；Git 提交是后续整理版本。
审计器会拒绝运行源码漂移。若修改受审计源码，应使用保存的源码快照复核旧实验，
不能为了让检查通过而改写历史 manifest。
