# Knowledge Ingestion Protocol v1

Knowledge Ingestion 接收用户确认后的知识资产生成结果，转换为正式知识文件并保留来源链路。不自动判断价值、不修改内容观点，也不写入其他系统或其他 Vault。

```json
{
  "protocol": "knowledge-ingestion-v1",
  "source": {
    "asset_id": "",
    "material_id": "",
    "generation_reference": ""
  },
  "ingestion": {
    "target_type": "learning_note",
    "target_path": "20 学习笔记/",
    "status": "waiting_confirmation"
  },
  "confirmation": {
    "confirmed": false,
    "confirmed_at": ""
  }
}
```

## 状态

`waiting_confirmation`、`confirmed`、`ingesting`、`completed`、`failed`。默认状态为 `waiting_confirmation`，不得跳过用户确认。

## 目标类型

- `learning_note` → `20 学习笔记`：唯一正式 Learning Publish 目标，由 `learning_publish.py` 的冻结事务执行。不得传入 00/10/30/40/50/90。
- `source_asset` → `10 原始资料`：由 `source-asset-ingestion-v1` 专用入口执行。
- `intelligence_brief` → `30 情报简报`：由 `derivative_publish.py` 发布；必须通过时效性、外部变化、两项独立来源与不确定性 Gate。
- `method_asset` → `40 方法库`：由 `derivative_publish.py` 发布；必须通过输入、前置条件、步骤、输出、限制、适用场景、失败条件和来源依据 Gate。
- `creation_asset` → `50 输出成果`：由 `derivative_publish.py` 发布；必须通过 audience、purpose、deliverable、version 和用户明确输出意图 Gate。

`learning_note` 不能借由 derivative Publisher 写入 30/40/50；旧值 `method`、`intelligence`、`output` 只作为历史读取别名。

Source Asset 与 Learning Note 使用不同输入协议和执行入口；Candidate Bundle Dispatcher 只按已展示的 `candidate_id + asset_type + status` 分派，不根据文件名或自然语言猜测目标，不建立任意目录写入器。

## 正式文件要求

Learning Note 正式文件必须保留稳定 Source/Revision 身份；如记录 generation、quality、generation record 或 evidence，只能写入 `guanlan://` 或正式 asset-library 可解析引用。`/tmp`、`/private/tmp`、普通本地绝对路径与 run workspace 引用必须在 preflight 阻断。

正式发布按知识正文计算稳定 `asset_id/content_hash`，治理 frontmatter、Graph metadata 与 Relation projection 不改变 Knowledge Identity。同一 Asset/Source Revision 重复执行返回 `already_published`，不得自动生成 `_2/_3`。每个新发布必须产生 `original-publish-receipt-v1` 且与 Markdown 同事务 commit；Relation Hook 在 commit 后非阻塞执行。

Source Asset 按 `source-asset-ingestion-v1` 保留 Material/Revision/Content 身份、稳定来源、验证与确认回执，不强制伪造 Task ID 或生成记录。质量评估 `passed` 不能替代用户确认；未确认、来源缺失或目标类型不支持时不得创建正式文件。
