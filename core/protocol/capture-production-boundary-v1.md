# Capture Production Boundary v1

状态：`active`  
协议名：`capture-production-boundary-v1`

## 唯一生产语义

`采集 + URL/文件 → Capture Provider Router → CaptureResult → Source Material v3 待审投影 → 00 收件箱`。

采集事实层只允许来源信息、Capture 状态、Raw Transcript/OCR/原始正文、Readable Source、Evidence、时间索引、质量与缺失项、Material/Revision Identity。

## 禁止字段

采集投影不得包含摘要、核心观点、研究问题、值得关注的问题、建议去向、方法提炼、用户启发或 AI 分析。上述内容只能由整理后的 Knowledge Generation 产生。

## Legacy 隔离

- `AgentReachRunner` 旧 URL 模式不是生产入口，只能显式 `--legacy-replay true`。
- `KnowledgeGenerationEngine --understanding-package` 不是生产入口，只能显式 `--legacy-replay true`。
- 历史 Agent-Reach 规则和指令仅供追溯，不得作为 active runtime dependency。

Provider 失败、内容缺失或权限阻断必须明确返回状态和原因；不得使用 fallback 内容冒充正式采集结果。
