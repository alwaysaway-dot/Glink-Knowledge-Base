# Reference Stability Protocol v1

状态：`active`（v0.5-C 冻结）  
协议名：`reference-stability-v1`

## 1. 原则

正式资产使用逻辑引用和内容哈希，不直接依赖运行时文件路径。

测试可以使用 `/tmp`，正式 Source Material、Transcript、Evidence 和 Report 禁止使用 `/tmp` 或 `/private/tmp`。

## 2. Reference URI

```text
guanlan://asset/<asset_id>
guanlan://manifest/<material_id>/<revision_id>
guanlan://report/<asset_id>
guanlan://sidecar/<sidecar_id>
guanlan://material/<material_id>/revision/<revision_id>
```

URI 中不得包含文件系统绝对路径。

## 3. Reference Manifest

```json
{
  "protocol": "reference-manifest-v1",
  "schema_version": "1.0.0",
  "material_id": "material_sha256_<64-hex>",
  "revision_id": "revision_sha256_<64-hex>",
  "entries": [
    {
      "reference": "guanlan://asset/asset_sha256_<64-hex>",
      "asset_id": "asset_sha256_<64-hex>",
      "role": "raw_transcript",
      "storage_relative_path": "objects/sha256/ab/<64-hex>",
      "content_hash": "sha256:<64-hex>",
      "media_type": "text/vtt",
      "size_bytes": 0
    }
  ]
}
```

## 4. 持久资产根

资产根必须：

- 位于 Vault 和 Git 仓库之外。
- 不位于 `/tmp` 或 `/private/tmp`。
- 由配置显式指定。
- 可被备份。

正式位置必须在首次迁移前由用户确认。本协议不自动创建默认目录。

## 5. 存储路径

Manifest 中只保存 root-relative path：

```text
objects/sha256/<first-two-hex>/<full-hex>
```

禁止：

- 绝对路径。
- `..` 路径穿越。
- 符号链接逃逸资产根。
- Manifest 指向自身之外的未受管文件。

## 6. 支持对象

- Source Material：通过 manifest URI 引用一个 revision。
- Transcript：作为 `asset` entry，role 为 `raw_transcript` 或 `readable_transcript`。
- Evidence：作为 `asset` entry，role 为 `evidence_frame`、`ocr_output`、`audio_segment` 等。
- Report：通过 `guanlan://report/<asset_id>` 引用，仍需 content hash。

## 7. 提交流程

1. 计算源文件哈希。
2. 复制到资产根 staging。
3. 对目标重新计算哈希。
4. 源目标一致后原子提交对象。
5. 最后提交 manifest。
6. 不删除源文件。

## 8. 验证

- URI 语法有效。
- Reference 在 manifest 唯一。
- `asset_id` 与 `content_hash` 一致。
- 相对路径安全。
- 文件存在、大小和 SHA-256 匹配。
- Source Material 中的每个正式引用都能在 manifest 解析。
- Manifest 不含临时路径。
