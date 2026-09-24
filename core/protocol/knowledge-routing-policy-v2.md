# Knowledge Routing Policy v2

状态：`active`  
策略名：`knowledge-routing-policy-v2`  
Schema 版本：`2.0.0`

## 1. 定位

AI只生成路由建议；用户确认后，且目标类型存在正式 Ingestion 实现时，系统才允许执行。

```json
{
  "protocol": "routing-decision-v2",
  "schema_version": "2.0.0",
  "source": {"material_id": "", "revision_id": ""},
  "recommendation": {
    "asset_class": "knowledge",
    "asset_subtype": "learning_note",
    "target_path": "20 学习笔记/",
    "reason": [],
    "confidence": "medium"
  },
  "execution": {
    "capability": "supported | suggestion_only | blocked",
    "decision_status": "suggested",
    "confirmation_status": "waiting_user_confirmation",
    "executed": false
  },
  "alternatives": []
}
```

AI阶段的 `decision_status`只能是 `suggested`。

## 2. 目录判断

- `10 原始资料`：主要价值是来源保真、未来核对和长期引用。
- `20 学习笔记`：形成概念、原理和理解，但必须区分来源事实、AI候选与用户理解。
- `30 情报简报`：时效性、多来源的外部变化；单篇新闻摘要不自动成立。
- `40 方法库`：输入、步骤、输出、限制和真实验证完整；否则仅为 `method_candidate`。
- `50 输出成果`：有明确受众、用途、版本与交付标准；“内容完整”不是充分条件。

## 3. 当前执行能力

| asset_subtype | target | capability |
|---|---|---|
| `source_asset` | `10 原始资料` | `supported` |
| `learning_note` | `20 学习笔记` | `supported` |
| `intelligence_brief` | `30 情报简报` | `supported`（多来源时效 Gate） |
| `method_asset` | `40 方法库` | `supported`（程序性知识 Gate） |
| `creation_asset` | `50 输出成果` | `supported`（明确交付意图 Gate） |

输入无稳定来源、质量阻断或越界时显示 `blocked`；单来源时效信号显示 `needs_corroboration`，未经验证的方法显示 `needs_validation`。不得声称存在统一万能路由器。

## 4. 派生边界

同一 Source Asset 可产生多个建议，但执行时必须创建独立资产。生成 Learning Note、Method、Intelligence 或 Creation 不改变 Source Asset 的 `material_id/revision_id/asset_class`，也不构成删除来源的理由。
