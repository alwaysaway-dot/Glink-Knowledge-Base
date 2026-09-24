# Source Promotion v1

状态：`active`  
协议名：`source-promotion-v1`

## 正式输入

Source Material v3、Reference Manifest、Readable Source、`source_type`、对应质量结果、Evidence 与用户确认。视频/音频可以记录动态 duration/segment coverage；网页、文章、本地文本和 PDF 不得伪造 Transcript 字段。

## 晋升条件

只判断稳定来源身份、Readable Source 存在、来源类型质量阈值通过、Manifest/Evidence 可验证、用户确认、事实层无分析污染。不得写死标题、语言、时长、Segment 数量或最小 20,000 字。

重复 Material + Revision + Readable 内容必须幂等返回 `already_promoted`；同 Revision 不同内容必须阻断为 identity conflict。

特定视频的固定段数、时长与文本长度仅属于 `fixture_regression`，不得成为生产规则。
