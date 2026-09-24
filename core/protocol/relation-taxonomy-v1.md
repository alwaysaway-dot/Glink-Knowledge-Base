# Relation Taxonomy v1

状态：`active`（v0.9-A 冻结）  
协议名：`relation-taxonomy-v1`  
Schema 版本：`1.0.0`

## 1. 定位

Relation Layer 记录正式资产之间有知识价值的语义关系。相同关键词、标签或大类不构成关系；无法说明“阅读 A 时为什么值得跳转到 B”时不得产生候选。

关系事实保存在 Relation Registry；Obsidian `[[链接]]` 只是经批准后的展示投影，不是唯一事实来源。

## 2. 正式关系类型

| forward relation | 含义 | reciprocal relation |
|---|---|---|
| `source_of` | A 是 B 的事实来源 | `derived_from` |
| `derived_from` | A 从 B 派生 | `source_of` |
| `explains` | A 帮助解释 B 的概念、机制或问题 | `explained_by` |
| `extends` | A 在 B 基础上增加新范围、条件或结论 | `extended_by` |
| `supports` | A 为 B 提供证据、案例或论据 | `supported_by` |
| `contrasts_with` | A 与 B 有重要差异、冲突或不同适用条件 | `contrasts_with` |
| `applies` | A 中明确记录的实践实际应用了 B 的知识或方法 | `applied_by` |
| `updates` | A 对 B 的时效事实、状态或判断作出实质更新 | `updated_by` |
| `method_for` | A 是处理 B 所述问题的可复用方法 | `uses_method` |
| `supersedes` | A 在明确版本或时效范围内取代 B | `superseded_by` |
| `related` | 已确认有直接价值但无法安全归入更具体类型 | `related` |

`explained_by`、`extended_by`、`supported_by`、`applied_by`、`updated_by`、`uses_method`、`superseded_by` 是反向语义值，只用于 reciprocal relation。旧值 `receives_application_from` 仅作为历史兼容读取，不再用于新关系。

`related` 不是默认值。不能判断具体关系时应拒绝候选，而不是降级为 `related`。

## 3. 关系强度

- `strong`：语义关系明确；理由可验证；从任一端跳转都显著帮助理解。默认仅 strong 推荐进入未来双链审批。
- `medium`：关系有实际价值，但证据、适用范围或方向仍需讨论；进入观察区。
- `weak`：只有词面、标签、大类或模糊相似；默认过滤，不进入可审批候选。

Strong 至少同时满足：

1. 能明确给出 relation type 和 reciprocal relation；
2. 有正文锚点、稳定身份字段或其他可复核证据；
3. rationale 能回答“为什么用户阅读 A 时值得跳转 B”；
4. 不依赖文件名、标签或单一关键词作为判断依据。

## 4. 方向与去重

关系使用 canonical endpoint pair 去重。`A source_of B / B derived_from A` 是同一关系事实，不得产生两组候选。自反关系禁止。

## 5. 自动化边界

满足 Relation Auto-Apply Gate 的 Strong Relation 可由系统从 `suggested` 自动进入 `executed`，Registry 标记 `auto_executed`。其中 `source_of/derived_from` 在 material、revision、created_from/source_reference 三重证明时允许最高自动化等级。

v1.2-B 自动语义关系仅开放 `extends/supports/contrasts_with/applies/updates`，且必须有双方正文的 pair-specific evidence。`supersedes` 等高风险语义只进入观察或异常复核；`related` 永不自动执行。Medium 只进入 observation pool，Weak 丢弃。删除、改型、批量修补和异常情况仍须用户介入。
