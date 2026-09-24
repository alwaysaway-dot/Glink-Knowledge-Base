# Asset Identity Protocol v1

状态：`active`（v0.5-C 冻结）  
协议名：`asset-identity-v1`

## 1. 目标

为 Source Material、内容资产和 revision 提供与运行路径无关、可重复计算的稳定身份。

## 2. content_hash

```text
sha256:<64-lowercase-hex>
```

计算对象是文件原始字节或 inline 文本的 UTF-8 字节。不得对内容做换行、编码或格式归一化后再声称是原文件哈希。

## 3. asset_id

```text
asset_sha256_<64-lowercase-hex>
```

`asset_id` 由 `content_hash` 一一确定：

```text
asset_id = "asset_sha256_" + content_hash 去掉 "sha256:" 前缀
```

文件名、绝对路径和创建时间不参与计算。

## 4. source_key

平台来源：

```text
<normalized-platform>:<platform-source-id>
```

本地文件：

```text
local:<content_hash>
```

无法获得平台 source ID 时：

```text
url:sha256:<sha256(canonical-url)>
```

`source_key` 不保存认证信息、Cookie、临时签名或跟踪参数。

## 5. material_id

```text
material_sha256_<sha256(source_key)>
```

同一来源重复采集保持相同 `material_id`；不同事实版本通过 `revision_id` 区分。

`task_id`、采集时间、Provider、临时文件名不得参与计算。

## 6. revision_id

```text
revision_sha256_<sha256(canonical-revision-payload)>
```

Canonical revision payload 包含：

- `schema_version`
- `material_id`
- 规范化 source metadata
- Raw content hash
- Readable content hash
- 排序后的 evidence identity、hash、时间范围
- 事实层 quality 字段

不包含：

- `revision_id`
- `created_at` / `updated_at`
- processing history 的运行时间
- review status
- Understanding Sidecar

事实内容不变时，审阅状态变化不会产生新 revision。

## 7. sidecar_id

```text
sidecar_sha256_<sha256(material_id|revision_id|provider|model|prompt_version|evidence_set_hash)>
```

Sidecar 可重算，不改变 Source Material revision。

## 8. 校验

必须验证：

- ID 前缀和 64 位小写十六进制。
- `asset_id` 与 `content_hash` 一致。
- `material_id` 可由 `source_key` 重算。
- `revision_id` 可由规范 payload 重算。
- 同一输入重复运行结果相同。
