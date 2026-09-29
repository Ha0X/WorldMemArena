# 当前状态与后续 TODO

更新：2026-09-29。返回 [文档总览](README.md)。本页只维护当前结论和后续工作；历史过程见 [实验记录](codex_gpt6_gui_experiment.md)。

## 当前结论

本轮计划已完成：真实 **Codex CLI 0.158.0 + gpt-6-astra**，通过仓库 CLI / pipeline / native harness adapter，评测三个 GUI 多 session 轨迹。共 75 sessions、15 checkpoints、161 QA，联合审计通过。

这里输入的是已记录的 GUI 轨迹，测的是 checkpoint 问答；没有重新执行桌面 GUI 任务。

| 样本 | QA 数 | Correct / Hallucination / Omission | QA-C ↑ | F1 ↑ | BLEU-1 ↑ |
|---|---:|---|---:|---:|---:|
| excel_01 | 54 | 39 / 10 / 5 | 72.22 | 33.79 | 15.45 |
| file_mgmt_01 | 54 | 37 / 7 / 10 | 68.52 | 35.72 | 18.08 |
| web_01 | 53 | 38 / 4 / 11 | 71.70 | 33.27 | 15.92 |
| 样本宏平均 | 161 合计 | 总计 114 / 21 / 26 | 70.81 | 34.26 | 16.48 |

分数单位为 %；QA-H / QA-O 宏平均为 13.01 / 16.18。完整报告（本地产物：`exp_log/codex_persistent_isolated_v1/report/report.md`） 是详细分数入口，[指标页](codex_gpt6_paper_comparison.md) 解释计算方式与论文可比性。

## 当前生效的方法

配置上仍是自主 Codex harness，而不是关闭工具的 long-context baseline。
仓库基线 adapter 明确声明持续会话、依赖 agent 自己的 context/memory、不由框架强制存储或检索；精确 resume 修复有此设计依据。
但本轮未观察到工具调用，不能据此归因外部记忆能力，也不能认定与直接 long-context 调用完全等价。
作者实际运行 trace 仍未取得。若研究外部 memory，应新设独立对照，不能悄悄替换原生协议。

- 每个样本一个持续 thread；首次 `exec`，随后精确 `resume ID`。不同样本使用独立进程、工作目录、CODEX_HOME、临时数字 UID 和 thread。
- 原生 session / QA prompt 保持不变。已见 session、问题及生成答案可以留在历史；gold 不进入被测模型。
- 保留 caption 和图片路径，不主动附图。图片按 session 实际送达时点逐文件开放，只能读取已见附件。
- 使用外层 Landlock、seccomp、namespaces 和独有 UID，替代当前容器不可用的 bubblewrap。真实 key 留在外部代理。
- Judge 请求 `gpt-5.4-mini`，provider 返回标识为 `gpt-5.6-terra`；差异已接受并记录。

具体配置、实现文件和命令只在 [实验协议](codex_gpt6_isolated_protocol.md) 维护。该持续 thread 策略是本地适配，作者确切 runtime 尚未确认。

## 已完成与验证

- [x] 固定模型和三样本数据；准备、校验 78 张图片。
- [x] 定位原生历史交接缺失，保留旧运行作为故障诊断。
- [x] 验证跨调用事实恢复、事实更新、QA 后保留及 reset 边界。
- [x] 完成外层隔离和真实 shell 写入/跨调用读回、上下文随机事实恢复。
- [x] 通过 5 项回归测试及 20 项本地隔离检查。
- [x] 完成三个样本：90 次模型调用、90 个成功模型请求、161 个成功 judge 请求。
- [x] 核对原生提示词、精确 thread ID、逐次图片范围、全部预测与评分记录；独立核对仓库 aggregate metrics。
- [x] 保存各样本 `state_snapshot/`、源码快照、环境版本及 87 个数据/图片文件哈希；生成论文同名指标对照。

证据：最终验证清单（本地产物：`exp_log/codex_persistent_isolated_v1/report/validation.json`）、本地隔离检查（本地产物：`exp_log/codex_persistent/environment_check/external_isolation.json`）、真实工具验收 v4（本地产物：`exp_log/codex_persistent/isolated_tool_check_v4/result.json`）。

## 解释结果时保留的限制

1. 正式样本未主动使用工具，CLI 与实际请求审计均支持这一观察。工具能力已单独验收，本轮分数主要体现持续上下文，不能当作自主磁盘记忆策略的效果。
2. 本地只有三个 GUI 样本各一次运行；论文 Table 3 覆盖更广范围，backbone、judge 身份及作者 runtime 也不完全相同。可以同指标参考，不能宣称严格同条件胜负或统计显著性。
3. 两例 judge 抽查（本地产物：`exp_log/codex_persistent_isolated_v1/excel_01/judge_spotcheck.md`） 显示所选 gold/evidence 可能不穷尽原始轨迹细节；原标签和分数保留，未人工改分。不能据两例认定全部 QA-H 都是误判。
4. 文件管理日志有 29 条 `OutputTextDelta without active item`；最终 completion 和全部 QA 有效，未见 rollout 写入失败。原 stderr 保留。
5. Token 使用最后一次 thread 累计值，并与 rollout 核对。三样本 input_tokens 合计 2,807,522，其中 cached_input_tokens 2,657,024；output_tokens 8,210。缓存是输入的子集，不再相加。

## 后续可选 TODO

以下属于新研究或更严格对照的候选，不是本轮尚未完成的运行步骤；尚未启动。

- [ ] 获得作者同子集预测或运行 trace，核对精确持久化机制和同子集分数。
- [ ] 单独设计完整轨迹证据复核，研究 judge 标签噪声；保留当前原始评分版本。
- [ ] 若研究磁盘记忆或 fresh context，固定图片输入、工具和 judge 后做单变量对照；不要将旧 N/B 解释成单变量实验。
- [ ] 若研究 B 的记忆覆写/压缩问题，在新实验开始前固定协议，不用已知 gold 反向修补本轮记忆。
- [ ] 扩大至相同评测集合并重复运行，再讨论全 benchmark 表现与方差。

Git 开发分支：`fix/codex-persistent-session`。用户已授权整理代码并发布到 `Ha0X/WorldMemArena`；提交后代码版本与正式实验原始版本分开记录，运行版本以各实验 manifest 与源码快照为准。
