# Derivative Publish v1

状态：`active`

`derivative_publish.py` 为 Intelligence、Method、Creation 复用发布安全内核：路径 allowlist、稳定 identity、原子写入、duplicate detection、original publish receipt、回滚和 resume。

正式固定映射：

- `intelligence_brief → 30 情报简报`
- `method_asset → 40 方法库`
- `creation_asset → 50 输出成果`

Publisher 只接受 `derivative-candidate-v1`、`derivative-publish-approval-v1`、`derivative-publish-quality-v1` 和匹配的 Source Material v3。Candidate 必须 `publishable`，Gate 与目标目录必须匹配。确认不能绕过缺少来源、验证或用户输出意图的 Gate。

每项 Candidate 独立事务和 Receipt；Bundle Dispatcher 在全量 preflight 后按 Source、Learning、Intelligence、Method、Creation 顺序发布。后续组件失败时返回 `publish_partial`，再次入库只会获得 `already_published` 或重试 pending 项，不会产生 `_2`。
