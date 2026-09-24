# Architecture / 架构

The canonical asset chain is **external source → Capture fact → 00 inbox review → Readable Original → Source Asset in 10 → Candidate Bundle → user approval → derivative asset in 20/30/40/50 → Relation Registry → Markdown projection**. `90 系统` stores rules; it is not an ingestion destination. In Chinese: **外部来源 → 采集事实 → 00 审阅队列 → 可读原文 → 10 来源资产 → 候选包 → 人工批准 → 20/30/40/50 派生资产 → 关系注册 → Markdown 展示**。

| Directory | Meaning / 职责 |
|---|---|
| 00 收件箱 | Review queue / 待审队列 |
| 10 原始资料 | Confirmed Source Asset / 已确认来源资产 |
| 20 学习笔记 | Learning Note / 学习笔记 |
| 30 情报简报 | Time-sensitive Intelligence / 情报 |
| 40 方法库 | Method Asset, a Knowledge derivative / 方法型知识 |
| 50 输出成果 | Creation Asset / 创造成果 |
| 90 系统 | Rules and instructions / 系统规则 |

`asset_class` is a canonical taxonomy field (`source`, `knowledge`, `intelligence`, `creation`); `graph_group` is display metadata. Method belongs to `knowledge`, not a fifth canonical asset class. Source content must not silently contain AI analysis. AI Structural Synthesis in Learning Notes is an `AI_candidate`, never an invented user-confirmed view. Relation Registry is the semantic fact store; Obsidian links are projections. Operation Envelope is an audit index, not a second asset truth source.

The fixture demo uses prewritten candidate text and synthetic approval to validate mechanics. Real capture, model calls, user confirmation and media processing must be supplied separately; the demo makes no claim to automate those decisions.
