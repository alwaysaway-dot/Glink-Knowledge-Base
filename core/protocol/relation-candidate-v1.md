# Relation Candidate v1

状态：`active`（v0.9-A 冻结）  
协议名：`relation-candidate-v1`  
Schema 版本：`1.0.0`

## 1. 结构

```json
{
  "protocol": "relation-candidate-v1",
  "schema_version": "1.0.0",
  "candidate_id": "relation_candidate_sha256_<64-hex>",
  "source_asset_id": "material_sha256_... | asset_sha256_...",
  "source_revision": "revision_sha256_... | snapshot_sha256_...",
  "source_snapshot_hash": "sha256:<64-hex>",
  "target_asset_id": "material_sha256_... | asset_sha256_...",
  "target_revision": "revision_sha256_... | snapshot_sha256_...",
  "target_snapshot_hash": "sha256:<64-hex>",
  "relation_type": "source_of",
  "relation_strength": "strong",
  "confidence": "high",
  "rationale": "",
  "evidence": [],
  "source_anchor": "",
  "target_anchor": "",
  "directionality": "directed | symmetric",
  "reciprocal_relation": "derived_from",
  "decision_status": "suggested",
  "created_at": ""
}
```

## 2. 身份规则

- Source Asset endpoint 使用 `material_id`，并单独记录 `revision_id`。
- Knowledge/Intelligence/Method/Creation endpoint 使用 `asset_id`。
- 正式资产尚无显式 revision 时，扫描器记录 `snapshot_sha256_<file-bytes-hash>`；它只用于变更检测，不创造或替代 Asset Identity。
- 路径和文件名可作为 display/location metadata，但不得参与 `candidate_id` 或成为唯一身份。
- 两端 `snapshot_hash` 用于执行前检测 Markdown 投影在候选生成后是否被改动；它不替代资产 revision。

`candidate_id` 由 canonical endpoint pair、方向化 relation type、两端 revision 计算；创建时间和路径不参与。

## 3. Evidence 与 Anchor

Evidence 必须是可复核数组，可包括稳定字段匹配、正文 section、限定条件和已有 Registry relation。`source_anchor`、`target_anchor` 指向语义段落或结构字段；不得只写标题相似或标签重合。

## 4. 状态

`suggested`、`approved`、`rejected`、`executed`。

自动发现先写 `suggested`。满足 Relation Auto-Apply Gate 的 Strong Candidate 可以不经逐条确认转为 `executed`，并写入 `execution_authority: auto_strong` 与 Registry `approval_status: auto_executed`。其他 `approved/rejected` 必须有用户决定记录；所有 `executed` 必须同时有 Registry 记录和 Markdown/Registry 一致性验证。

## 5. 候选集合

Dry run 输出可包含：

- `strong_candidates`
- `medium_candidates`
- `filtered_candidates`（weak、重复、身份无效、状态不合格等审计记录）
- `excluded_assets`

Weak 不得伪装为可审批候选。
