# Derivative Candidate v1

状态：`active`

派生 Candidate 是 Source 的独立候选资产，不得写回 Source 正文。

```json
{
  "protocol": "derivative-candidate-v1",
  "candidate_id": "candidate_sha256_<hash>",
  "asset_type": "learning_note | intelligence_brief | method_asset | creation_asset",
  "status": "publishable",
  "source": {"material_id": "", "revision_id": ""},
  "content": {"title": "", "markdown": ""},
  "provenance": {"stable_references": ["guanlan://material/..."]},
  "admission": {"status": "passed"}
}
```

- Learning：必须有真实知识理解、来源追溯、非 Source 大段复制和 AI/来源边界。
- Intelligence：必须有时效性、外部变化和至少两项独立来源；单来源只可 `needs_corroboration`。
- Method：必须有用途、输入、前置条件、步骤、输出、限制、适用场景、失败条件和来源依据；AI 凭空设计不得 publishable。
- Creation：必须有 audience、purpose、deliverable、version 和用户明确输出意图；默认 `not_applicable`。

所有长期 provenance 只能使用 `guanlan://` 或正式可解析引用，禁止 `/tmp`、`/private/tmp` 和临时工作目录。
