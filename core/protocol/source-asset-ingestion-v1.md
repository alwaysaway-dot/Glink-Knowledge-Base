# Source Asset Ingestion Protocol v1

状态：`active`  
协议名：`source-asset-ingestion-v1`  
Schema 版本：`1.0.0`

## 1. 输入

- 通过 formal validation 的 Source Material v3 revision。
- 与 revision 匹配的 Reference Manifest。
- 用户确认合格的 Readable Original。
- `source-asset-validation-v1` receipt。
- `source-asset-approval-v1` receipt。
- 待写入的 Source Asset Markdown projection。

## 2. 输出

```json
{
  "protocol": "source-asset-ingestion-v1",
  "schema_version": "1.0.0",
  "source": {
    "material_id": "material_sha256_...",
    "revision_id": "revision_sha256_...",
    "content_hash": "sha256:...",
    "source_reference": "guanlan://material/.../revision/...",
    "manifest_reference": "guanlan://manifest/.../...",
    "validation_reference": "guanlan://report/asset_sha256_...",
    "approval_reference": "guanlan://report/asset_sha256_..."
  },
  "ingestion": {
    "target_type": "source_asset",
    "target_path": "10 原始资料/...md",
    "status": "completed | duplicate | waiting_confirmation | failed"
  },
  "confirmation": {"confirmed": true, "confirmed_at": ""},
  "transaction": {"atomic_write": true, "projection_sha256": "", "rollback_guard": "sha256:..."}
}
```

## 3. 强制规则

- 生产目标只能是当前 Vault 的 `10 原始资料`根目录。
- material、revision、content hash、manifest、validation和approval必须一致。
- 正式引用不得使用 `/tmp`或裸绝对路径。
- 同一 material/revision 的相同投影返回 `duplicate`，不重复写入；内容不一致时阻断。
- 重名但身份不同必须阻断，不自动追加模糊后缀。
- 文件先写同目录临时文件，再原子替换；receipt失败时只回滚本次新建且哈希匹配的文件。
- 回滚不得自动触发历史删除；显式回滚必须独立确认并保留可恢复副本。

