# 指标解释与论文对照

更新：2026-09-29。返回 [文档总览](README.md)。本页只对照当前有效实验；旧 N/B 和原生故障分数见 [实验过程](codex_gpt6_gui_experiment.md)，不混入主表。

## 指标各自表示什么

这些指标评测 checkpoint 问答，不是 GUI 操作成功率。

| 指标 | 含义与计算方式 | 趋势 |
|---|---|---|
| QA-C（Correct） | Judge 判定答案正确的比例 | 越高越好 |
| QA-H（Hallucination） | Judge 判定答案有错误、矛盾或缺乏给定证据支持的比例 | 越低越好 |
| QA-O（Omission） | Judge 判定答案遗漏必要信息或未充分回答的比例 | 越低越好 |
| F1 | 预测与标准答案的词语重合，综合 precision 与 recall；仓库做归一化和词干处理 | 越高越好 |
| BLEU-1 | 单词级匹配精度，含短答案惩罚；仓库实现带平滑 | 越高越好 |

QA-C/H/O 是 judge 的语义标签，三类比例之和为 100%；F1/BLEU-1 由程序计算，不使用 judge 标签。同义改写和简短回答即使语义正确，词面分数也可能较低。

拒答不一定是 Omission：如果 gold 表明信息未被记录，正确拒答可以判为 Correct。QA-H 也不等同于经完整原始轨迹人工核定的事实错误率。

### 聚合方式

按论文 Appendix B.1，先在每个样本内汇总，再跨样本求算术平均。以 QA-C 为例：

```text
样本 QA-C = 该样本 Correct 题数 / 该样本有效 QA 数
宏平均 QA-C = (Excel QA-C + 文件管理 QA-C + Web QA-C) / 3
```

F1/BLEU-1 也是先取样本内题目均值，再对样本均值取平均。当前 161 题全部有效；样本宏平均与直接合并所有题目的 micro 比例概念不同。所有展示值为百分数，四舍五入至两位小数。

## 当前结果与论文参考

| 方法 / 范围 | QA-C ↑ | QA-H ↓ | QA-O ↓ | F1 ↑ | BLEU-1 ↑ |
|---|---:|---:|---:|---:|---:|
| Codex + gpt-6-astra，本地 3 个 GUI 样本宏平均 | 70.81 | 13.01 | 16.18 | 34.26 | 16.48 |
| 论文 Table 3 Codex–GPT-5.4-nano，更广数据范围 | 53.62 | 20.76 | 25.62 | 32.56 | 10.12 |

本地完整逐样本/checkpoint 分数见 最终报告（本地产物：`exp_log/codex_persistent_isolated_v1/report/report.md`），精确值与题型统计见 results.json（本地产物：`exp_log/codex_persistent_isolated_v1/report/results.json`）。来源为 论文（本地产物：`WorldMemArena_paper.pdf`） Table 3 / Appendix B 及仓库 [QA evaluator](../eval_framework/evaluators/qa.py)。

## 哪些可比，哪些不能据此下结论

| 维度 | 当前情况 |
|---|---|
| 方法范式 | 顺序输入 sessions、阶段性 QA，使用真实 Codex harness |
| 指标与聚合 | 沿用仓库 QA-C/H/O、F1、BLEU-1，按样本宏平均 |
| 数据范围 | 本地只有 3 个 GUI 样本；论文表覆盖更广范围，未取得同子集官方预测 |
| Backbone | 本地固定 gpt-6-astra；论文表写 GPT-5.4-nano，正文另写 GPT-5.4，保留原表名称 |
| Judge | 本地请求 gpt-5.4-mini，返回 gpt-5.6-terra；不宣称身份与论文一致 |
| Runtime | 本地每样本持续 thread 与外层隔离；作者确切持久化实现未确认 |
| 工具 / 图片 | 工具可用但正式样本未主动调用；输入保留原生 caption/路径，不主动附图 |
| 稳定性 | 每样本一次完整运行，不支持多 seed 方差或显著性推断 |

因此主表是**同指标的子集参考**，不能把分差解释成严格同条件的模型胜负，也不能据此宣称测出了自主磁盘记忆管理效果。

## Judge 抽查与解释边界

仓库 judge 接收问题、参考答案、所选 gold memory evidence 和预测答案，不接收完整已见轨迹。Excel 两例中，预测提到的 double_click、Numbers tab 确实在已见输入中出现，但 judge 因参考摘要未涵盖而判为 Hallucination。

两例证据（本地产物：`exp_log/codex_persistent_isolated_v1/excel_01/judge_spotcheck.md`） 单独保存；主表保留原始标签和评分，没有人工加分。这是定性抽查，不是全面重评，不能推断其余错误标签也有问题。“更强 judge”也不保证分数更高或每个标签更准确。

## 未评估的论文指标

Memory Recall、Correctness、Hallucination、Irrelevance、Update Handling、Interference Rejection，以及 retrieval coverage / ranking，需要逐 session 记忆项或检索记录与 gold 对齐。本轮使用 harness answer-only 评分，这些指标记为**未评估**，不填 0，也不能用 QA-C 替代。

更严格对照和复核的候选工作统一维护在 [状态与 TODO](codex_gpt6_status_and_todo.md)。
