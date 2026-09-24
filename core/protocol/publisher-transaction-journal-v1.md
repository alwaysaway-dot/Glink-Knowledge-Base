# Publisher Transaction Journal v1

适用范围：Learning 与 Derivative Publisher 的单资产正式发布。Source Promotion 使用既有独立原子性机制。本协议不是第二个 Publish Receipt，也不决定知识事实。

## 一致性边界

- 同一 Publisher ledger 的 `flock` 覆盖最终审批校验、目标和索引前置检查、写入、恢复。锁由内核随进程退出释放；`lock-owner.json` 仅用于诊断，不作为 stale 判据。
- 每个事务写入 `transactions/<transaction_id>/journal.json` 与 `receipt.prepared.json`。prepared 文件不能作为正式发布凭据；正式凭据仍是 `original-receipts/<receipt_id>.json` 且 `validation_result=committed`。
- Journal 只含身份、审批绑定摘要、目标与索引路径、前置 hash、目标投影 hash、阶段完成列表和恢复状态；不保存 Source 或候选正文。staging 与目标同目录、同文件系统。
- 新目标由同目录 staging 通过原子 create-only hard link 发布，避免覆盖外部写入；`commit.json` 是完成标记。跨多个文件的写入不被宣称为单一原子操作。读者应同时核验目标投影、正式 Receipt、索引与提交标记。
- Bundle 是顺序可重试调度，不是多资产全局原子事务。部分成功须显示 `publish_partial`。

## 状态与恢复

- `prepared`：Journal 已持久化，可能已有 staging、资产、Receipt 或索引；下次进程持锁核验后恢复。
- `safe_to_discard`：无正式目标且无 committed Receipt；有效 staging 留存于事务目录，可安全重试。
- `rolled_back`：受控异常下仅回滚本事务自有且 hash 匹配的目标；备份保留在事务目录。
- `committed`：目标、Receipt、索引已匹配，Journal 完成。
- `conflict`：目标被外部改动或关键凭据不一致；不得覆盖，需人工核对。

恢复在任何新发布前运行。外部修改后的目标绝不自动覆盖；进程终止后的 staging/Journal 保留。重试前旧 rolled-back 事务移入 `transactions/history/`，不能直接清除证据。

## 故障注入

仅 `scope=test` 可通过 `--fault-injection <point>` 抛出异常，或 `kill:<point>` 强制退出独立进程。生产模式忽略该参数。Receipt/Index 写失败不得生成不带 Receipt 的成功发布；Relation Hook 与 Operation Envelope 不控制正式事务提交。
