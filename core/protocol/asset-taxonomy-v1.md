# Asset Taxonomy Protocol v1

状态：`active`  
协议名：`asset-taxonomy-v1`  
Schema 版本：`1.0.0`

## 1. 三个正交维度

- `asset_class`：资产长期职责，只能是 `source | knowledge | intelligence | creation`。
- `asset_subtype`：具体类型，如 `source_material | learning_note | method_asset | intelligence_brief | creation_asset`。
- `workflow_state`：当前处理状态，不参与资产类型判断。
- `storage_projection`：用户可见投影位置，不参与 Asset Identity v1 的哈希计算。

`00 收件箱`是待审队列，不是资产类型；Readable Original 是 Source Asset 的可读表现，不是 Learning Note。

## 2. Source Asset

- 目的：保存外部来源的第一份可信副本和长期证据入口。
- 特征：来源可追溯；Raw、Evidence、Readable 分层；不含总结、观点提炼或方法抽象。
- 生命周期：`captured → processed → source_material_created → source_asset_created → archived/clean_candidate`。
- 投影：待审投影进入 `00 收件箱`；用户确认的长期来源投影进入 `10 原始资料`。
- 自动化：允许采集、格式整理、忠实翻译、质量与引用校验。
- 人工确认：正式进入 `10`、归档或清理必须确认。

## 3. Knowledge Asset

- `learning_note`：理解概念、原理和知识连接，正式进入 `20 学习笔记`。
- `method_asset`：具备输入、步骤、输出、限制和验证记录的可复用程序性知识，正式进入 `40 方法库`。
- 生命周期：`draft → reviewing → approved → active/stable → needs_review/outdated → archived`。
- AI只能生成 Draft 或候选；用户确认前不得标记为用户观点或正式知识资产。

## 4. Intelligence Asset

- 目的：描述外部世界在观察窗口内发生的变化、影响候选和不确定性。
- 特征：默认多来源或权威来源加历史基线；有时效与复核条件。
- 生命周期：`signal_collected → brief_draft → approved → active_monitoring → superseded/outdated → archived`。
- 正式投影进入 `30 情报简报`；AI可生成 Draft，不得自动形成用户判断。

## 5. Creation Asset

- 目的：为明确受众、用途和完成标准形成可交付成果。
- 特征：有受众、目标、输入资产、版本和发布状态。
- 生命周期：`brief → draft → review → approved/released → revised → archived`。
- 正式投影继续使用 `50 输出成果`；本协议不授权目录改名。

## 6. 不变原则

- 派生新资产不得覆盖、移动或改变 Source Asset 的类型。
- 一个 Source Asset 可以派生多个候选，但每个派生资产拥有独立身份和审核状态。
- 本协议兼容旧 `type/status` 字段；新产物同时写 `asset_class/asset_subtype/workflow_state`，旧字段继续可读。
- 本协议不修改 Source Material v3、Asset Identity v1 或 Reference Stability v1。

