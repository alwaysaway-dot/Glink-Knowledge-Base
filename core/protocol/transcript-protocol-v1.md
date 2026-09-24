# Transcript Protocol v1

`transcript-protocol-v1` 是字幕、OCR 和 ASR 转录结果的统一输入/输出协议。历史数据中的 `transcript-v1`（输入别名）和 `transcript-output-v1`（输出别名）继续兼容，但新产出必须使用本协议名称。

v0.6-B 增加可选的 `schema_version=1.1.0` 与 `transcript_layer=raw | evidence`。旧数据没有这两个字段时继续按 v1.0 读取。

## 输入字段

```json
{
  "protocol": "transcript-protocol-v1",
  "source": { "task_id": "", "platform": "", "title": "", "url": "" },
  "transcript_type": "subtitle | ocr | whisper | asr",
  "segments": [{ "start_time": "00:00:00.000", "end_time": "00:00:02.000", "text": "", "confidence": "high" }]
}
```

输入必需字段为 `protocol`、`source`、`transcript_type`、`segments`。`transcript_type` 可以是 `subtitle`、`ocr`、`whisper` 或通用 `asr`；FunASR 等非 Whisper Provider 必须使用 `asr`，不得冒充 Whisper。

`transcript_layer=evidence` 表示已完成时间排序、保守规范化和相邻精确去重的可引用证据层。它必须通过 `raw_reference` 指回不可变 Raw Transcript，并保留逐段时间范围；不能包含摘要或语义补全。

## 输出字段

```json
{
  "protocol": "transcript-protocol-v1",
  "task_id": "",
  "quality": { "level": "high", "confidence": "high", "manual_review": "not_required" },
  "content": { "raw_reference": "", "cleaned_transcript": "", "character_count": 0 },
  "warnings": [],
  "quality_gate": { "status": "pass", "level": "high", "text_length": 0, "duplicate_rate": 0, "coherence": 1, "abnormal_character_ratio": 0, "reasons": [], "requires_confirmation": false }
}
```

`content.raw_reference` 是 Raw Transcript 的原始来源引用；`content.cleaned_transcript` 是唯一允许下游 Knowledge Generation 使用的 Clean Transcript。`quality_gate.status` 只能是 `pass`、`warning` 或 `blocked`：`warning` 必须人工确认，`blocked` 禁止生成。`quality` 只描述整理质量和人工复核状态，不代表知识价值判断。
