# Relation Governance v1

状态：`active`  
协议名：`relation-governance-v1`

## 审批边界

- `strong + high + evidence_sufficient` 且通过 Relation Auto-Apply Gate：`auto_execute`。
- `medium`：写入 Observation Pool，状态 `observing`；不通知用户、不写 Markdown。
- `weak`：仅在当次扫描结果中记录为过滤项，不持久化。
- 只有身份冲突、修订无法确认、关系类型等价歧义、高风险 `supersedes/contrasts_with`、Registry/Markdown 冲突、端点不可用、Apply/Rollback 失败才写入 Exception Queue。

## Registry 与 Markdown

Registry 是关系语义事实层，Markdown 是展示层。对于 Registry 已管理、端点与 revision 均一致的关系：展示链接缺失为 `repair_candidate`，可自动修复；人工或历史 Wiki Link 不自动注册、不自动改写。

## Revalidation

Asset revision、资产状态/身份、归档/隔离、人工展示改动或 Markdown 展示变化会触发复核。复核结果仅为 `verified`、`needs_review`、`stale_candidate`；revision 改变绝不直接删除 Registry 关系。

## 发布后增量发现

正式资产发布成功后调用 `relation_publish_hook.py`。Hook 仅比较新发布资产与其他正式资产，不执行全库两两扫描。发布成功与关系扫描独立：扫描状态只能为 `completed`、`completed_no_relation` 或 `failed_retryable`，不得回滚已发布资产。
