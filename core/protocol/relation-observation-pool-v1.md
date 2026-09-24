# Relation Observation Pool v1

状态：`active`  
协议名：`relation-observation-pool-v1`

Medium Candidate 的持久化观察记录至少包含：`candidate_id`、`asset_a`、`asset_b`、`candidate_relation`、`why_medium`、`confidence`、`evidence`、`first_seen`、`last_seen`、`review_count`、`current_status`。`times_detected` 作为旧字段兼容保留。

`current_status` 仅允许：`observing`、`promoted`、`expired`、`rejected`。同一候选再次发现只更新 `last_seen/review_count`；升级为 Strong 时标为 `promoted` 并交给 Auto-Apply Gate；超过保留期未获足够证据时标为 `expired`。观察池不触发用户通知，也不写正式 Markdown projection。
