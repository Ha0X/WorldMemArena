# Codex + GPT-6 GUI 子集公开汇总

本目录提交的是已完成实验的聚合结果，原始日志与数据保留在本地，不随代码发布。
详细数值见 [summary.json](summary.json)，解释见 [指标与论文对照](../../codex_gpt6_paper_comparison.md)。

## 范围与配置

- 真实 Codex CLI 0.158.0，请求模型 `gpt-6-astra`，icodeeasy Responses provider。
- 仓库基线 `15ea25b723d9c4fb35e8062037aec6a5601e4442`；采用可选持续 thread 修复及外层隔离。
- 数据 revision `e2148757921fc7e2d66d8ed899823b763227c341`。
- 三个 GUI 样本各完整运行一次；75 sessions、15 checkpoints、161 QA、78 张截图、90 次模型调用。
- Judge 请求 `gpt-5.4-mini`，返回标识为 `gpt-5.6-terra`；不据此宣称与论文 judge 相同。
- 沿用仓库提示词及 QA evaluator；图片输入保持 caption + 文件路径，不自动附图。

## 结果

分数为百分数，宏平均是三个样本指标的算术平均。

| 样本 | QA | C / H / O 数量 | QA-C | QA-H | QA-O | F1 | BLEU-1 |
|---|---:|---|---:|---:|---:|---:|---:|
| excel_01 | 54 | 39 / 10 / 5 | 72.22 | 18.52 | 9.26 | 33.79 | 15.45 |
| file_mgmt_01 | 54 | 37 / 7 / 10 | 68.52 | 12.96 | 18.52 | 35.72 | 18.08 |
| web_01 | 53 | 38 / 4 / 11 | 71.70 | 7.55 | 20.75 | 33.27 | 15.92 |
| 宏平均 | 161 合计 | 114 / 21 / 26 合计 | 70.81 | 13.01 | 16.18 | 34.26 | 16.48 |
| 论文 Table 3 Codex–GPT-5.4-nano | 更广集合 | — | 53.62 | 20.76 | 25.62 | 32.56 | 10.12 |

## 证据与限制

正式结果经过原生提示词、精确 thread ID、输入顺序、附件开放范围、预测/评分对应及仓库聚合指标核对。
本地已通过 5 项回归测试、20 项隔离检查及单独的真实工具验收。
公开 JSON 白名单导出不包含原始对话、逐题 gold、thread ID、主机目录、UID 或凭据；包含源结果文件 SHA-256 以标识导出来源。
该哈希不代替未发布的原始证据，外部读者不能只用本目录独立重建全部审计。

方法配置是自主 harness，但三个正式样本没有观察到工具调用，实际问答主要利用持续会话上下文。
不能把分数归因于显式外部记忆记录、维护、检索或更新；这些生命周期指标未评估。
本文是同指标子集参考，数据范围、backbone、judge 及作者精确 runtime 不同或未核实，不能宣称严格同条件胜过论文。
文件管理运行的 29 条流事件日志告警保留；全部最终 completion 与 QA 有效。

## 本地产物位置

以下是本地路径说明，不是 GitHub 中的已发布文件：

```text
exp_log/codex_persistent_isolated_v1/report/report.md
exp_log/codex_persistent_isolated_v1/report/results.json
exp_log/codex_persistent_isolated_v1/report/validation.json
exp_log/codex_persistent_isolated_v1/report/source_snapshot/
exp_log/codex_persistent_isolated_v1/<sample>/codex_calls/
exp_log/codex_persistent_isolated_v1/<sample>/state_snapshot/
```

运行步骤与依赖见 [协议](../../codex_gpt6_isolated_protocol.md) 和 [脚本导航](../../../scripts/README.md)。
