# Transcript Quality Gate v1

> v0.2 补充：本协议原有 `pass / warning / blocked` 继续服务于知识生成前的质量判断，保持兼容。
> 对“来源素材写入收件箱”另采用 `readable-transcript-v1` 的准入映射：`ready` 写入、
> `minor_revision` 写入且 `review_required=true`、`major_revision` 阻断。写入收件箱不是知识生成。

质量闸门位于 Material Package 与 Knowledge Generation 之间，防止低质量 Transcript 进入知识生成。

## 状态

- `pass`：允许生成。
- `warning`：需要人工确认；未确认不得生成。
- `blocked`：禁止生成。

## 分层

- Raw Transcript：原始 OCR / 字幕结果，只作为来源引用保存。
- Clean Transcript：排序、去重、断行和质量标记后的文本；Knowledge Generation 只能读取 `content.cleaned_transcript`。

## 规则

- OCR `medium` 默认 `warning`。
- OCR `low` 默认 `blocked`。
- 空文本、过短文本、重复率过高、连贯性过低或异常字符比例过高时，直接 `blocked`。
- 闸门必须写入 `transcript-quality-gate-v1` 结构，并随 Transcript 输出和 Material Package 传递。

## 媒体采集完成契约（v1.2-A 补充）

本节约束音频、视频 Source Material 的采集完成状态，不增加新的知识生成能力。

媒体 Transcript 必须依次经过：

`bounded audio segments → segment ASR → Raw Transcript Evidence → minimal hygiene → Readable Transcript → structural QA → content quality gate`

- 单段 ASR 必须有超时、有限重试与失败隔离；已成功分段不得因其他分段失败而丢失。
- Raw Transcript 与 Readable Transcript 必须是独立对象。Readable 只允许时间排序、机械去重、保守标点和段落组织；禁止总结、语义补全或外部知识纠错。
- `capture_completed` 不以“存在文本文件”为依据，必须同时满足：时间结构有效、无超长单段、覆盖率达标、正文非占位符、内容密度和重复污染通过确定性检查、无缺失分段。
- 未通过时只能为 `capture_partial`，并记录明确原因；不得标记为可进入“整理”。
- Quality Report 必须绑定当前 Raw / Readable 的 content hash，并通过稳定 `guanlan://report/` 引用进入 Reference Manifest。

媒体质量结果最小结构：

```yaml
protocol: media-transcript-quality-v1
transcript_content_hash: sha256:...
readable_content_hash: sha256:...
transcript_structural_qa:
  status: pass | warning | fail
transcript_content_quality:
  status: usable | usable_with_warnings | unusable
quality_status: ready_for_整理 | transcript_partial | transcript_quality_failed
ready_for_sorting: true | false
capture_completion_status: capture_completed | capture_partial
missing_ranges: []
```
