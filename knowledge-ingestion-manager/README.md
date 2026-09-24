# Knowledge Ingestion Manager

将已生成的 `learning_note` 草稿在用户明确确认后写入指定 Vault 的 `20 学习笔记`。

未确认时只输出 `waiting_confirmation` 记录，不创建文件；确认时仍要求质量状态为 `passed`，并在正式文件中保留来源、Material ID、Task ID、生成记录和质量报告引用。

本模块提供两个明确、互不混用的正式入口：

- `learning_publish.py`：正式 `learning_note → 20 学习笔记` 事务入口；固定目录、稳定引用、身份幂等、Original Publish Receipt 与回滚边界。
- `source_asset_ingestion.py`：新增 `source_asset → 10 原始资料`，要求 Source Material v3、Manifest、validation receipt和用户approval receipt。

`KnowledgeIngestionManager.swift` 为 historical replay 兼容实现，默认拒绝运行；只有显式 `--legacy-replay true` 才可回放旧测试。它不是正式发布入口。

`intelligence/method/creation`仍为 suggestion-only。本模块不提供自动确认、万能分类路由或跨 Vault 操作。

Source Asset入口执行路径allowlist、material/revision/content hash一致性、永久引用、重名和重复检查，并使用同目录原子写入。显式回滚需要独立确认，移动到项目可恢复区，不永久删除。
