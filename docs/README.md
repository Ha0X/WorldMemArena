# Codex + GPT-6 实验文档总览

更新：2026-09-29。本目录记录 WorldMemArena 上真实 Codex CLI + `gpt-6-astra` 的评测过程。

GitHub 可直接查看 [公开结果汇总](results/codex_gpt6_gui_subset/README.md) 与 [脚本导航](../scripts/README.md)。
文中标为“本地产物”的 `exp_log/`、论文 PDF 和数据缓存没有上传；其路径仅供本地定位。

**当前结果：三个 GUI 样本已全部完成并通过联合审计。** 共 75 sessions / 15 checkpoints / 161 QA；样本宏平均 QA-C **70.81%**、QA-H 13.01%、QA-O 16.18%、F1 34.26%、BLEU-1 16.48%。这是持续 thread + 外层隔离的本地适配结果，可作论文同指标子集参考，不能据此宣称严格同条件胜负。

## 按问题找文档

| 想了解什么 | 文档 |
|---|---|
| 每天做了什么、当天结论与汇报素材 | [每日工作日志](codex_gpt6_daily_log.md) |
| GitHub 中可以查看哪些正式结果 | [公开聚合结果](results/codex_gpt6_gui_subset/README.md) |
| 现在做到哪一步、还有哪些 TODO | [当前状态与 TODO](codex_gpt6_status_and_todo.md) |
| 当前具体怎么跑、如何复现、哪些数据可见 | [本轮实验协议](codex_gpt6_isolated_protocol.md) |
| N/B 是什么、为什么修复、整个过程怎么演进 | [实验过程与决策记录](codex_gpt6_gui_experiment.md) |
| QA-C/H/O、F1、BLEU-1 是什么意思，如何对照论文 | [指标解释与论文对照](codex_gpt6_paper_comparison.md) |
| 旧原生运行为什么全部拒答，证据在哪里 | [历史故障诊断](codex_native_failure_diagnosis.md) |
| 逐样本/checkpoint 分数与审计细节 | 最终报告（本地产物：`exp_log/codex_persistent_isolated_v1/report/report.md`） |

建议先读“当前状态”，再根据需要查协议、历史或指标。TODO 统一维护在状态页，其他页面不重复维护进度清单。

## 结果与证据入口

- 结构化结果（本地产物：`exp_log/codex_persistent_isolated_v1/report/results.json`）：分样本、checkpoint、题型、token、耗时与工具审计。
- 最终验证清单（本地产物：`exp_log/codex_persistent_isolated_v1/report/validation.json`）：3 样本、161 QA、90 次模型调用的验证状态。
- Judge 两例定性抽查（本地产物：`exp_log/codex_persistent_isolated_v1/excel_01/judge_spotcheck.md`）：保留原始标签，未人工改分。
- [整理前原文归档](archive/2026-09-29-before-cleanup/README.md)：保留五份旧文档的完整原文和校验值。

当前有效实验的产物根目录是 `exp_log/codex_persistent_isolated_v1/`。早期 N/B、未修复原生运行和小型验收均单独保存；实验过程文档说明各自适用范围，不混合计分。
