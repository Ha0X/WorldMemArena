# 历史故障诊断：原生 Codex 全量拒答

返回 [文档总览](README.md)。本页描述**修复前**的运行和证据，不是当前操作指南。历史交接与工具隔离后来已完成本地适配，并完成三个样本；当前方法见 [协议](codex_gpt6_isolated_protocol.md)，当前结果见 最终报告（本地产物：`exp_log/codex_persistent_isolated_v1/report/report.md`）。

2026-09-29。此前原生三个 GUI 样本的 9.32% QA-C 应标为**集成链路故障诊断**，不作为 Codex + GPT-6 的有效记忆能力对比结果。答案与评分真实保存，但“调用成功、记录一致”不等于“harness 运行能力验收通过”。

## 已确认的主因：历史状态没有交接给 QA

修复前的实际流程：

```text
S08 → fresh codex exec → 正确概括 B1 = Purchased → 进程结束
其他 session → 各自 fresh codex exec → 进程结束
checkpoint → 新 thread，仅收到问题 → 不包含 S08 → 回答 Not mentioned in memory.
```

- `harness_native.py::flush_ingest` 发送每个 session，但不把返回摘要加入后续上下文。
- `answer_batch` 仅拼接 QA prompt；`retrieve` 返回空 items 和 session ID 元数据。
- `_call_codex_exec_prompt` 每次新启动 exec；没有 resume/session-ID 交接，配置 `ephemeral: true`。
- `ephemeral: false` 单独改动也不能修复：只保存 transcript，不会自动在下一次 exec 中读取它。
- 共用 CODEX_HOME/cwd 或给出 1M context 上限，不会自动使不同 thread 共享历史。普通文件可跨调用保留，但没有建立文件记忆协议或确认其实际工作。
- 当时相关 adapter/pipeline/harness YAML 与上游基线 `15ea25b723d9c4fb35e8062037aec6a5601e4442` 一致。这说明该历史版本 Codex 分支的行为，不能由此断言论文作者运行时也这样配置；当前本地 adapter 已有显式可选修复。

原始日志证据：`exp_log/native_codex_gpt6/excel_01_run3/codex_calls/` 按时间排序，第 4 次为 S08，原始回答明确复述 “Purchased”；第 6 次为首个 checkpoint，原始回答就是 11 条拒答。
解析器未替换答案，judge 在这些回答生成后才运行，因此均不是这次全量拒答的来源。

## 受控诊断（不计入 benchmark 分数）

同一 Codex、gpt-6-astra、原生 QA prompt、运行环境和传输；只改变诊断输入是否包含此前实际观察的五个 session。未发送 gold answer、gold memory 或未来 session。

| 诊断输入 | 第一题 B1 文本 | 拒答数 |
|---|---|---:|
| 仅原生 checkpoint QA | Not mentioned in memory. | 11/11 |
| 已观察五个 session + 同份 QA | Purchased | 1/11 |

这是信息可见性诊断，不是把长上下文方案当作修复后的 harness 得分。剩余 10 个非拒答未经本轮 judge 重新评分，不能称为 10/11 Correct。

请求元数据确认：QA-only 没有历史 session 标记和 Purchased；补历史请求有五个 session 标记及 Purchased，两者都未使用 previous_response_id。
产物：`exp_log/native_codex_gpt6/context_diagnostic/{results.json,request_metadata.jsonl,*.prompt.txt,*.answer.txt}`。
脚本：`scripts/diagnose_native_context.py`。

## 第二个独立运行问题：shell 沙箱无法执行

保持同一原生配置，显式要求使用 shell 执行无副作用的 `pwd`。真实工具返回：

```text
bwrap: Failed to make / slave: Permission denied
```

在 `/tmp` 以及默认 cwd / 非 login shell 尝试中复现。证明当前 workspace-write 沙箱与容器运行权限存在兼容问题。即便要让模型自行落盘，也不能先假设 shell 可用。
该问题不能直接解释原始每一道拒答：原始运行尚无完整 request-body 工具跟踪。主因历史缺失有独立对照证据，shell 失败是另一个必须解决的运行验收问题。

可核验工具输入输出：`exp_log/native_codex_gpt6/context_diagnostic/tool_probe/verified/tool_exchange.jsonl`。
该诊断阶段没有关闭沙箱或提升权限绕过错误。后续采用外层隔离替代不可用的 bubblewrap，见文末解决状态。

## 纠正工具审计方法

这版 Codex 将工具说明编码到 developer 输入中，用 custom_tool_call 调用。请求顶层没有 tools 字段，不代表没有工具。
显式 pwd 探测能看到实际 custom_tool_call / custom_tool_call_output，但 CLI --json 输出只出现 agent_message 和 turn.completed，未独立报告 command_execution。
因此此前用“没有 item.completed 工具事件”推断“模型绝对没有工具调用”的方法不充分；现将原生报告的审计范围收窄为记录一致性，不能声称工具访问完整审计。
原始三个样本各有 30 次 HTTP 200 请求/30 次调用，未观察到额外模型工具反馈轮次；这只能补充证据，不能替代完整工具跟踪。

`codex features list` 显示 memories 默认 false、shell_tool/unified_exec 默认 true。之前探索 N 显式关闭 memories 与当前原生默认状态并非已证实的关键差异，不能用它解释分差。

## 版本核查补充（2026-09-29）

本地非浅克隆历史与上游当前 main 均指向 `15ea25b723d9c4fb35e8062037aec6a5601e4442`；当前已知 harness 实现历史只查到 `18b78cd`。README 无状态持久化额外步骤，本次公开 issue 检索未找到相关说明。未改动分支或联系作者。完整工作清单与排序见[状态和 TODO](codex_gpt6_status_and_todo.md)。

## 对早期结论的纠正

此前过早将 record-consistency audit 当作完整运行验收，且在已知独立 exec 后仍扩大样本，没有先验证记忆交接与 shell 可用性。这是执行与结论上的错误。旧记录和得分完整保留，但不再作为有效模型能力结论。

## 后续解决状态

| 问题 | 已采取的方法 | 当前证据 / 限制 |
|---|---|---|
| 不同调用间没有历史 | 用户同意每样本持续 thread，按确切 ID resume | 随机事实恢复、更新、QA 后保留及 reset 验收通过；作者 runtime 仍未确认 |
| bubblewrap 无法执行 | 在当前容器使用 Landlock、seccomp、独有 UID 与 namespaces 的外层隔离 | 真实工具验收 v4（本地产物：`exp_log/codex_persistent/isolated_tool_check_v4/result.json`） 通过，无需等待其他节点 |
| Gold / 未来附件边界 | 独立样本目录，附件按实际送达时点逐文件开放 | 本地隔离检查（本地产物：`exp_log/codex_persistent/environment_check/external_isolation.json`） 和时点回归测试通过 |
| 工具事件漏报 | 同时保存 CLI 事件与实际请求工具交换并去重 | 正式运行两份日志均未观察到主动工具调用，工具能力有独立验收 |
| “记录一致”被误当完整验收 | 在完整运行前补齐状态、工具与隔离验收 | 联合验证（本地产物：`exp_log/codex_persistent_isolated_v1/report/validation.json`） 覆盖 3 样本 / 161 QA / 90 次调用 |

早期 Excel 首 checkpoint 的 8 C / 2 H / 1 O 仍只作上下文验收；当前正式结果使用新的完整运行，不混入这 11 题。后续研究候选统一在 [状态与 TODO](codex_gpt6_status_and_todo.md)，本页不再维护待办清单。
