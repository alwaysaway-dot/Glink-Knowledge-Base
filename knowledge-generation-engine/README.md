# Knowledge Generation Engine MVP

第一版只支持 `learning_note`。

新整理操作默认使用 `learning-note-generation-v2`：以来源约束下的认知压缩、论证/机制关系、低重复正文和语言感知质量检查为目标。历史 `learning-note-generation-v1` 保留用于候选重放、A/B 与审计，必须显式传入 `--prompt-version learning-note-generation-v1`。

v0.5 主模式读取资产草稿、生成计划和已经人工 `convert_approved` 的
`source-material-v3`。`understanding-sidecar-v1` 是可选输入，只有
`status=validated` 且 Material/Revision 完全匹配时才能作为辅助参考。
没有 Sidecar 不得阻断生成。

主模式还必须提供稳定性模块生成的 `--source-validation`，并且 Schema、
Identity、Manifest 和 Reference 校验均为 valid。

历史 `video-understanding-package-v1` 路径保留为 legacy compatibility mode，
只用于旧回归，不再是 v0.5 的必需输入。

```text
knowledge-generation-engine \
  --draft knowledge-asset-draft.json \
  --plan generation-plan.json \
  --source-material source-material-v3.json \
  --source-validation source-validation.json \
  --understanding-sidecar optional-sidecar.json \
  --output learning-note-generated.md \
  --quality quality-report.json \
  --quality-reference quality-report.json \
  --metadata generation-metadata.json \
  --record generation-record.json \
  --provider codex \
  --model gpt-5.6-sol \
  --model-version gpt-5.6-sol \
  --prompt-version learning-note-generation-v2 \
  --prompt-file core/prompt/learning-note-generation-v2.md
```

省略 `--understanding-sidecar` 仍是合法的 v0.5 调用。

Legacy 模式继续使用 `--understanding-package`，并保留原有 Package Gate。

支持 `codex` 真实模型、`codex-replay` 已捕获 Codex 结果复用、`file` 通用结果复用和 `local` 无模型回退。无论哪种模式，都不会写入 Vault 或执行入库；模型调用必须记录模型、版本、时间和 Prompt 版本。

v2 的生成标题来自 Markdown 唯一 H1。候选 `content.title` 必须与 H1 一致；原始标题只保存在 `source.original_title`。质量报告区分真实来源缺失与 `external_verification_not_requested`，不会把同语言内容误报为“缺少中文翻译”。
