# Relation Registry v1

状态：`active`（v0.9-A 冻结）  
协议名：`relation-registry-v1`  
Schema 版本：`1.0.0`

## 1. 定位

Registry 是正式关系语义的权威记录。Markdown 链接是展示层；缺少链接不等于关系不存在，存在链接也不自动等于已批准的语义关系。

## 2. 结构

```json
{
  "protocol": "relation-registry-v1",
  "schema_version": "1.0.0",
  "registry_id": "guanlan-relation-registry",
  "relations": [
    {
      "relation_id": "relation_sha256_<64-hex>",
      "candidate_id": "relation_candidate_sha256_<64-hex>",
      "source_asset_id": "",
      "source_revision": "",
      "target_asset_id": "",
      "target_revision": "",
      "relation_type": "source_of",
      "reciprocal_relation": "derived_from",
      "relation_strength": "strong",
      "approval_status": "approved | executed | auto_executed | rejected | revoked",
      "created_at": "",
      "approved_at": "",
      "executed_at": "",
      "source_location": "",
      "target_location": "",
      "rationale": "",
      "evidence": [],
      "source_anchor": "",
      "target_anchor": "",
      "projection_snapshot_hashes": {"source": "sha256:<64-hex>", "target": "sha256:<64-hex>"},
      "revalidation_status": "verified | needs_review | stale_candidate"
    }
  ],
  "updated_at": ""
}
```

## 3. 一致性约束

- 两端资产 ID 与 revision 是主键语义；路径仅用于定位。
- canonical pair + relation semantics 不能重复。
- 自关系禁止；每条自动语义关系必须保留双方正文证据、rationale 与 link usefulness，不能只保存置信度。
- 执行前必须比较当前 revision 与候选 revision；变化时阻断并重新发现。
- `executed` 必须有用户批准记录；`auto_executed` 必须有 Relation Auto-Apply Gate 通过记录。两者都必须有执行回执、Markdown 与 Registry 一致性校验。
- 已存在 `approved/executed/auto_executed` 关系不得再次建议。
- 删除、撤销或改型必须保留历史，不得静默覆盖。
- 系统写入 Markdown 展示链接导致的快照 revision 变化，只有执行回执可证明两端 post-hash 一致时，才允许自动 rebase 并标记 `system_managed_markdown_projection`；任何其他 revision 变化进入 revalidation，不得自动删除。

## 4. Apply 与回滚

`relation-apply` 默认 `dry_run=true`。人工执行必须显式 `--execute`、匹配 candidate_id 的批准文件和 revision 校验；自动执行必须显式 `--execute --auto` 且通过 Relation Auto-Apply Gate；先保存可恢复备份，再写展示链接，最后更新 Registry。

回滚必须使用执行回执、校验当前文件 hash，并恢复备份与 Registry 前态。回滚是显式命令，不等于永久删除。

## 5. v0.9-B 自动执行状态

满足 Gate 的 Strong Relation 可以自动写入；Medium/Weak 不写 Markdown。Registry 必须记录执行来源、回执与可回滚位置。
