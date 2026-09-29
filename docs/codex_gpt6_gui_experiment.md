# 实验过程与决策记录

更新：2026-09-29。返回 [文档总览](README.md)。本页按实验阶段说明做过什么、为何改变方向、各批结果能说明什么。当前配置见 [协议](codex_gpt6_isolated_protocol.md)，当前分数见 最终报告（本地产物：`exp_log/codex_persistent_isolated_v1/report/report.md`），后续任务统一见 [状态与 TODO](codex_gpt6_status_and_todo.md)。

## 目标与数据

被测系统始终是 **真实 Codex CLI + gpt-6-astra**。论文 WorldMemArena 有 Lifelong Evolution 与 Agentic Execution 两个 regime，后者包括 GUI / Embodied；方法范式包括 long-context、手工设计的记忆系统和 harness-based agents。本次研究 harness-based 方法中的 GUI 轨迹 QA，不运行其他 backbone，也不重做实际 GUI 操作。

论文：[arXiv 2605.29341](https://arxiv.org/abs/2605.29341)；本地 PDF（本地产物：`WorldMemArena_paper.pdf`）。数据位于 `.cache/worldmemarena_gui`，revision 为 `e2148757921fc7e2d66d8ed899823b763227c341`。

| 样本 | sessions | checkpoints | QA | 图片 |
|---|---:|---:|---:|---:|
| excel_01 | 25 | 5 | 54 | 14 |
| file_mgmt_01 | 25 | 5 | 54 | 50 |
| web_01 | 25 | 5 | 53 | 14 |
| 合计 | 75 | 15 | 161 | 78 |

每个 session 有 gold memory points；每道 QA 有 gold answer 与 evidence IDs。Gold 供评分使用，与模型自己生成的记忆不同。

## 各批实验的身份

分数均为样本宏平均 QA-C；这些批次不合并计分。

| 阶段 | 实际方法 | QA 数 | QA-C | 当前定位 |
|---|---|---:|---:|---|
| 探索 N | 原生提示词 + 独立 runner，每次 fresh ephemeral，额外功能限制 | 161 | 18.62% | 历史探索，不是仓库默认 harness 复现 |
| 探索 B | fresh context + 自定义 JSON memory MCP，显式附加当前截图 | 161 | 50.92% | 自定义记忆协议，不是论文原生主结果 |
| 未修复的原生入口 | 仓库 CLI / adapter，每次新 thread，历史未交接 | 161 | 9.32% | 集成故障诊断，不是有效记忆能力结果 |
| 持续 thread 首 checkpoint | 本地状态修复，Excel 5 sessions / 11 QA | 11 | 72.73% | 仅上下文路径验收，不能替代完整工具验收 |
| 当前正式实验 | 仓库入口 + 每样本持续 thread + 外层隔离 | 161 | 70.81% | 完整且通过审计的当前 GUI 子集结果 |

## 阶段一：N/B 探索

N/B 使用独立运行器 `scripts/run_codex_protocols.py`，两者都不 resume，并非“resume 与 fresh context”的单变量比较。

| 项目 | N | B |
|---|---|---|
| session / QA 提示词 | 复用原生提示词 | 增加读写 memory 指示，QA 从 memory 回答 |
| 工具与状态 | 专用 workspace，提供 shell / 文件 / view_image 能力；额外禁用功能 | 仅 read_memory / write_memory；QA 只读 |
| 记忆存储 | 可自主写文件，没有强制交接协议 | 一个最大 256 KiB 的 JSON，由模型决定结构 |
| 图片 | caption 和路径，不主动附图 | caption + 当前 session 的显式截图输入 |
| Backbone / judge | gpt-6-astra / gpt-6-astra | gpt-6-astra / gpt-6-astra |

N 还限制了 host skills/plugins 等功能并固定推理设置，所以不能将 N 称为未经改动的仓库原生运行。N/B 同时改变记忆机制、提示词和显式视觉输入，分数差不能单独归因于 memory。`ephemeral` 不会自动删除 workspace 文件。

两组共 322 QA、180 次有效调用。B 的 75 个 session 都有成功写入，15 个 checkpoint 前后 memory bytes 不变；记录了 140 次 read_memory、78 次 write_memory。旧 CLI JSONL 对工具事件存在盲区，因此仅凭 N 未出现工具事件，不能证明完整工具访问边界。

观察到 B 的记忆维护问题，但未人为修补：

- Excel：S18 memory 约 17 KB；S20 读入旧记忆后写成约 3.3 KB，仅保留 S20，旧 image IDs 消失。
- 文件管理：S46 memory 为 99,252 bytes、23 个历史 session；S48 变为 5,130 bytes，仅保留 S48 明细及少量历史摘要。体积缩小本身不等于错误，但历史细节丢失可追踪。

证据在对应 `calls/S18`、`calls/S20`、`calls/S46`、`calls/S48`、`calls/S50` 的 `memory.after.json` 和 `result.json`。早期 A 为无文件工具的 partial 诊断（Excel 33 QA，其余各 11 QA）；B v2/v3 等连接/MCP 调试尝试亦排除。

历史 N/B 报告（本地产物：`exp_log/codex_gui_report/report.md`） 与 原始产物（本地产物：`exp_log/codex_protocols_v4/`） 保留，不重新解释为当前主结果。主运行记录过 4 次失败/重试；旧命令与细节在原文归档中保存。

## 阶段二：真实仓库入口与全量拒答

随后通过 `eval_framework.cli.main` → pipeline → `HarnessMemoryAdapter` → Codex 跑三个样本。该阶段保留原生 `/root/.codex`、`/tmp`、workspace-write 和 ephemeral 配置；只适配模型、连接和日志。

全部 161 个答案都是 `Not mentioned in memory.`。15 个 Correct 对应 gold 未记录信息的正确拒答，不能证明记忆保留。该批次重新标为故障诊断。

主因是 session 和 QA 落在不同 thread：S08 回复能复述 Purchased，checkpoint 却没有 S08 历史。共享 cwd/CODEX_HOME、大 context 或仅移除 ephemeral 都不会自动交接历史。独立对照仅补入已观察五个 session 后，拒答由 11/11 降到 1/11，并恢复 Purchased；10 个非拒答未在该诊断中重评分，不能称作 10/11 Correct。

另一个独立问题是 shell 实际返回 `bwrap: Failed to make / slave: Permission denied`。不能由“API 请求成功”推断 shell 或记忆链路可用。详细证据见 [故障诊断](codex_native_failure_diagnosis.md)。

连接调试还发现：`exec` 层级的传输覆盖位置影响生效；exit 0 可能没有有效 completion。因此包装器检查非零 input tokens 和完成事件，持久模式还检查确切 thread ID 与最终答案。早期 `excel_01` / `excel_01_run2` 保留为连接调试，未混入 `excel_01_run3` 故障报告。

这一阶段 judge 请求 gpt-5.4-mini，返回标识 gpt-5.6-terra；用户接受差异，后续继续记录。全量拒答在评分前已经生成，不能归因于 judge。

## 阶段三：持续 thread 决策与验收

用户同意采用每样本一个持续 thread 作为本地适配。首调用创建 thread，后续按确切 ID resume，reset 清空 ID；QA 和生成答案留在该样本历史，gold 不进入。

论文只明确顺序输入 session 与 staged checkpoint QA，未给足以确认 Codex 必须 resume 或必须 fresh 的 runtime 细节。当前选择符合公开范式，但不声称作者精确实现已确认。B 的 memory-only 协议没有混入本轮。

随机事实恢复/reset、旧值更新为新值、QA 后状态保留均通过。Excel 首 checkpoint 获得 8 C / 2 H / 1 O，证明上下文路径恢复；当时 shell 尚未通过验收，所以没有把这 11 题冒充完整运行结果。

## 阶段四：容器内隔离

最初将换节点视为必要条件，判断过早。继续探测发现：mount propagation 不可用，但 Landlock ABI 1、user/net/PID/IPC/UTS namespaces 可用。

单独 Landlock 探测能阻止隔离外内容读取，但不能阻止 ABI 1 的路径 truncate。使用合成临时文件实证后，增加 syscall 限制、独有临时 UID、独立网络及外部 API 凭据代理。Codex 状态保存所需的文件权限和 fd 时间戳更新也经过兼容性验证。

工具检查 v1–v3 只作兼容性诊断；**v4 是最终验收依据**：三次真实模型调用完成文件写入/跨调用读回、仅在上下文中出现的随机事实恢复、外部 canary 拒读，并且无 rollout 写入错误。外层隔离后才开始当前正式运行。实际机制与边界详见 [协议](codex_gpt6_isolated_protocol.md)。

## 阶段五：当前正式运行与审计

三个样本分别完整运行一次，保留全部 checkpoint，没有按分数挑选重跑。每个样本 30 次调用，共 161 QA；线程、原生提示词、图片开放时点、预测/评分对应关系及仓库聚合指标均通过审计。

正式样本未主动调用工具，故结果主要反映持续上下文；工具能力有独立验收。文件管理的 29 条流事件日志告警保留，最终 completion/答案有效，无 rollout 写入错误。Token 取 thread 最后累计值，不把每次累计快照相加。

Excel 两例 judge 抽查显示：double_click 与 Numbers tab 在已见轨迹/caption 中存在，但所选 gold/evidence 没覆盖，judge 据此判为 Hallucination。保留原始标签，另存 抽查证据（本地产物：`exp_log/codex_persistent_isolated_v1/excel_01/judge_spotcheck.md`），不据两例推翻全部标签。

## 产物定位

| 批次 | 位置 |
|---|---|
| 当前正式结果、源码快照、环境和数据哈希 | 最终报告目录（本地产物：`exp_log/codex_persistent_isolated_v1/report/`） |
| 当前逐样本日志、评分及 state_snapshot | 正式产物根目录（本地产物：`exp_log/codex_persistent_isolated_v1/`） |
| 持续 thread / 沙箱小型验收 | 验收目录（本地产物：`exp_log/codex_persistent/`） |
| 未修复原生运行、连接调试和上下文诊断 | 原生诊断目录（本地产物：`exp_log/native_codex_gpt6/`） |
| N/B 探索 | N/B 产物（本地产物：`exp_log/codex_protocols_v4/`）、汇总报告（本地产物：`exp_log/codex_gui_report/`） |
| 整理前的逐阶段日志、旧命令与 TODO | [完整原文归档](archive/2026-09-29-before-cleanup/README.md) |
