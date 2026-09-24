# Original Publish Receipt v1

状态：`active`  
协议名：`original-publish-receipt-v1`

## 定位

每个新正式 Learning Publish 必须在同一受控事务中产生一条 `receipt_type: original_publish` 的原始发布凭据。它记录正常发布事件，不得由历史 reconciliation receipt 替代。

## 必填字段

`receipt_id`、`receipt_type`、`knowledge_asset_id`、`knowledge_revision_id`、`source_asset_id`、`source_revision_id`、`target_path`、`content_hash`、`stable_references`、`approval_evidence`、`published_at`、`transaction_id`、`validation_result`。

`validation_result=committed` 才证明发布完成；`prepared/rolled_back` 不代表正式发布。Relation Hook 在 commit 后运行并保持非阻塞。

## 事务

`Preflight → Prepare → Receipt prepared → Markdown write → Validation → Receipt committed → Index commit → non-blocking Relation Hook`。

任何 Markdown 或 Receipt 失败必须回滚已写入的 Markdown，保留可重试事务记录。重复的 `knowledge_asset_id + source_revision_id` 返回 `already_published`，不得生成 `_2/_3`。
