# Candidate Bundle v1

状态：`active`

Candidate Bundle 是一次“整理”操作的候选集合，不是资产类型，不是正式 Vault 文件，也不改变 Source 的身份或生命周期。

```json
{
  "protocol": "candidate-bundle-v1",
  "bundle_id": "bundle_sha256_<hash>",
  "source": {"material_id": "", "revision_id": "", "source_reference": "guanlan://material/..."},
  "source_candidate": {"candidate_id": "", "asset_type": "source_asset", "target": "10 原始资料", "status": "publishable"},
  "derivative_candidates": [],
  "workflow_state": "awaiting_user_confirmation"
}
```

每个 Candidate 必须拥有独立 `candidate_id`，并稳定引用 Source 的 `material_id/revision_id`。允许状态仅为 `publishable`、`candidate`、`needs_corroboration`、`needs_validation`、`blocked`、`not_applicable`、`generation_failed`。

“入库”表示用户批准当前 Bundle 中所有已展示且 `publishable` 的 Candidate；用户也可显式排除其中某项。多个待确认 Bundle 时不得猜测，必须返回 `USER_COMMAND_ROUTING_AMBIGUITY`。
