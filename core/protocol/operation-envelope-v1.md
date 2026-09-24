# Unified Operation Envelope v1

`operation-envelope-v1` 是对一次 Guanlan 操作的轻量审计索引，不是资产、候选、发布、关系或生命周期事实源。冲突时始终以领域 canonical record 为准，Envelope 可删除并从可验证 canonical evidence 重建。

## 类型与身份

首版 `operation_type` 仅允许：`capture`、`transcript`、`source_reconciliation`、`organize`、`publish`、`relation_curation`。`operation_id` 格式为 `op_<type>_<uuid4hex>`，表示一次具体执行，不得代替 Material/Asset/Candidate/Receipt/Relation Identity。`parent_operation_id`、`retry_of`、`resume_of` 仅在真实关系存在时写入。

## 状态

`started`、`completed`、`failed`、`partial`、`blocked`、`interrupted`、`needs_reconciliation`。状态只描述操作执行。Organize 成功生成 Bundle 时 operation 为 `completed`，即使 Bundle 仍为 `waiting_user_confirmation`。超时或陈旧不能单独证明 `failed`。

## Schema

必填：`schema_version`、`operation_id`、`operation_type`、`implementation_version`、`started_at`、`status`、`input_refs`、`output_refs`、`receipt_refs`、`stage_refs`、`change_refs`、`warnings`。

可空：`completed_at`、`parent_operation_id`、`retry_of`、`resume_of`、`failure_class`、`failure_detail`、`failure_ref`、`duration_ms`。`record_origin` 为 `live_operation` 或 `canonical_reconciliation`；`canonical_authority` 永远为 `false`。

全部 refs 必须是稳定 `guanlan://` 引用。Envelope 不复制网页 HTML、Transcript 正文、Candidate 正文、审批原文、Cookie、Token、认证头或堆栈。没有真实证据的 change/stage/link 字段保持空值或 null。

## Storage 与故障边界

位置：`asset-library/operations/YYYY-MM/<operation_id>.json`。每操作一文件，canonical JSON、原子替换。索引写入失败只产生 `operation_index_write_failed`，不能回滚或降级已完成的领域操作。第一版 forward-only，不回填历史操作。

查询支持 operation_id、类型/时间过滤及 canonical reference 的轻量扫描。损坏 Envelope 被隔离为查询警告，不影响 canonical record。缺失或未终结 Envelope 只有在显式验证 canonical evidence 后才可 reconciliation；未知结果保持 `needs_reconciliation`。
