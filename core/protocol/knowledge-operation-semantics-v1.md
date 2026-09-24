# Knowledge Operation Semantics v1

状态：`active`  
策略名：`knowledge-operation-semantics-v1`

## 1. 采集

```text
外部来源 → Capture → Source Material待审投影 → 00 收件箱
```

允许来源信息、Raw Transcript、Evidence Transcript、质量、缺失项和待整理状态。禁止把AI分析冒充原文，禁止自动进入 `10/20/30/40/50`。

## 2. 整理

```text
00中的来源素材 → Source Candidate + Derivative Candidate Set → 用户预览
```

整理先产生 Readable Original / Source Candidate；随后在独立 Candidate 中按材料与用户上下文生成 Learning、Intelligence、Method、Creation 候选。允许ASR错字校正、断句和标点修复、碎片与相邻重复合并、连贯段落整理和忠实翻译。

Source Candidate 禁止总结、观点提炼、方法抽象、用户立场和AI分析正文。派生 Candidate 可以包含 AI 理解，但不得回写 Source；整理不得正式写入 `10/20/30/40/50`，也不得要求额外正式确认。

## 3. 入库

```text
当前 Candidate Bundle → 一次用户确认 → 按类型分别发布
```

- Learning Note → `20 学习笔记`
- Intelligence Brief → `30 情报简报`
- Method Asset → `40 方法库`
- Creation Asset → `50 输出成果`

只发布实际存在、已展示、`publishable` 且通过本类型 Gate 的候选。`needs_corroboration`、`needs_validation`、`blocked`、`not_applicable` 和 `generation_failed` 均不得因确认而绕过 Gate。AI只能生成 Candidate；派生资产拥有独立身份，不得覆盖或改变 Source Asset。

## 4. 当前能力

正式支持 `source_asset → 10`、`learning_note → 20`、`intelligence_brief → 30`、`method_asset → 40`、`creation_asset → 50`。各 Publisher 共享发布安全内核，但使用独立 schema 与准入 Gate。
