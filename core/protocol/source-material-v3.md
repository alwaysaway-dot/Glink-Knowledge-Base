# Source Material Protocol v3

状态：`active`（v0.5-C 冻结）  
协议名：`source-material-v3`  
Schema 版本：`3.0.0`

## 1. 定位

Source Material v3 是外部信息进入观澜后的第一份可信事实副本。它保存来源、原始内容、可读内容、证据、质量和生命周期，不保存 AI 总结、核心观点、论证重构、价值判断或方法论。

JSON 是规范数据形态；Markdown 只是可读投影，不能拥有 JSON 中不存在的事实字段。

## 2. 规范结构

```json
{
  "protocol": "source-material-v3",
  "schema_version": "3.0.0",
  "material_id": "material_sha256_<64-hex>",
  "revision_id": "revision_sha256_<64-hex>",
  "source": {
    "platform": "youtube",
    "source_id": "ABCdef12345",
    "source_url": "https://www.youtube.com/watch?v=ABCdef12345",
    "title": "",
    "author": "",
    "published_at": "",
    "captured_at": ""
  },
  "content": {
    "raw": {
      "storage": "reference",
      "reference": "guanlan://asset/asset_sha256_<64-hex>",
      "content_hash": "sha256:<64-hex>",
      "media_type": "text/vtt"
    },
    "readable": {
      "storage": "reference",
      "reference": "guanlan://asset/asset_sha256_<64-hex>",
      "content_hash": "sha256:<64-hex>",
      "media_type": "text/markdown",
      "operations": []
    }
  },
  "evidence": [
    {
      "evidence_id": "evidence-001",
      "kind": "transcript_segment",
      "reference": "guanlan://asset/asset_sha256_<64-hex>",
      "content_hash": "sha256:<64-hex>",
      "start_time": 0,
      "end_time": 12.5,
      "uncertainty": ""
    }
  ],
  "quality": {
    "capture_status": "complete",
    "content_fidelity": "full",
    "transcript_quality": "readable",
    "review_required": true,
    "uncertainties": []
  },
  "lifecycle": {
    "status": "captured",
    "review_status": "pending",
    "created_at": "",
    "updated_at": "",
    "processing_history": []
  },
  "asset_manifest_reference": "guanlan://manifest/material_sha256_<64-hex>/revision_sha256_<64-hex>",
  "understanding_sidecar_reference": ""
}
```

## 3. 身份字段

- `material_id`：由稳定 `source_key` 计算，同一外部来源重复采集保持不变。
- `revision_id`：由来源身份、Raw/Readable 内容哈希、证据哈希和事实质量字段计算；不包含更新时间等易变字段。
- `schema_version`：固定使用语义版本；v3 第一版为 `3.0.0`。
- `task_id` 仅可写入 `processing_history`，不得参与 `material_id`。

身份算法由 `asset-identity-v1` 定义。

## 4. Source Metadata

必需字段：

- `platform`
- `source_id`
- `source_url`
- `title`
- `author`
- `captured_at`

`published_at` 可为空。未知值使用空字符串或 `unknown`，不得编造。

平台来源优先使用平台稳定 ID；本地文件使用内容哈希作为 `source_id`。

## 5. Raw Content

Raw 是不可覆盖的原始事实快照。

支持：

- `storage=inline`：必须包含 `text` 和其 UTF-8 SHA-256。
- `storage=reference`：必须包含永久逻辑引用、`content_hash` 和 `media_type`。

Raw 不得进行总结、润色、语义补全或观点改写。

## 6. Readable Content

Readable 只能由 Raw 派生，允许：

- 标点和空白规范化。
- 时间排序。
- 连续重复清理。
- 口语断句和段落整理。
- 有明确证据的专名修正。

必须记录 `operations`。禁止摘要、扩写、补充来源不存在的信息或删除重要限定条件。

## 7. Evidence References

每项证据必须包含：

- 稳定 `evidence_id`
- `kind`
- `reference`
- `content_hash`
- 可用时的 `start_time` / `end_time`
- `uncertainty`

`reference` 必须符合 `reference-stability-v1`，不得是 `/tmp`、`/private/tmp`、普通绝对路径或未受管 URL 文件地址。

## 8. Quality

`quality` 只描述事实素材质量：

- `capture_status`：`complete | partial`
- `content_fidelity`：`full | partial`
- `transcript_quality`：`not_applicable | raw | readable | partial`
- `review_required`：固定为 `true`
- `uncertainties`：事实缺失和质量不确定项

禁止用单一 `quality` 同时表达采集、理解置信度和知识价值。

`capture_status=failed` 不生成 Source Material。

## 9. Lifecycle

- `status`：`captured | partial | reviewed | archived`
- `review_status`：`pending | reviewed | convert_approved | archived`
- `processing_history`：记录处理器、版本、时间、输入和输出引用

未经用户确认，系统不得生成 `convert_approved`。

生命周期变化不修改已有 revision 的事实内容；事实内容变化时创建新 revision。

## 10. 理解辅助层

`understanding_sidecar_reference` 可为空。非空时必须指向 `understanding-sidecar-v1`。

Sidecar：

- 不属于 Source Material 正文。
- 不影响 Source Material 是否成立。
- 不得覆盖事实字段。
- 不得单独触发知识生成。

## 11. 永久引用

允许的正式引用：

```text
guanlan://asset/<asset_id>
guanlan://manifest/<material_id>/<revision_id>
guanlan://report/<asset_id>
guanlan://sidecar/<sidecar_id>
guanlan://material/<material_id>/revision/<revision_id>
```

禁止：

- `/tmp/...`
- `/private/tmp/...`
- 其他裸绝对文件路径
- 不带内容哈希的文件引用

外部网页来源保存在 `source.source_url`，不替代本地事实资产。

## 12. Markdown 投影

Markdown 投影遵循 `source-material-readable-policy-v1`。默认首屏显示 Readable Transcript 的连续段落；逐句时间字幕保留为折叠证据或附件，不再作为正文默认展示。

固定区块：

```text
来源信息
原始内容
连续可读正文
语言与质量说明
时间证据（折叠或附件）
媒体与证据引用
采集质量
不确定性与缺失
处理记录
人工审阅状态
```

禁止增加“视频主题”“核心观点”“论证结构”“价值判断”“建议去向”等理解或创造层正文。

Readable 内容变化属于事实投影变化，必须创建新 `revision_id`；不得覆盖旧 revision 的规范 JSON。

## 13. 兼容

- v1、v2 历史文件保持只读。
- v1 转 v3 时创建新文件，不覆盖历史文件。
- v2 必须拆分为 v3 事实内容与 draft Understanding Sidecar。
- 新产物只写 v3。
