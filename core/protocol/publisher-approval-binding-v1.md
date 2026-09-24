# Publisher Approval Binding v1

状态：active，forward-only。此协议是现有 H1 用户确认记录中的不可变审批对象，不是第二套审批系统。

审批前 `approval_binding.py` 对用户实际看到的 Candidate Snapshot 计算规范化 SHA-256，输出未确认对象。只有用户明确 H1 确认后，现有 `knowledge-publish-approval-v1`、`derivative-publish-approval-v1` 或 Candidate Bundle publish plan 才能携带该对象和 `confirmed: true`。Publisher 不得自动补签。

绑定内容：Bundle 身份及候选集合、Candidate ID/类型/状态、标题、正文 hash、Source material/revision、provenance 稳定引用、准入 Gate、质量闸门、目标目录与文件名；Source 候选另绑定正式投影 hash。运行时间、随机临时路径、Operation Envelope ID 与普通日志不纳入摘要。

Publisher 在正式写入前重算并比较完整 `approval_binding`。缺失返回 `approval_binding_missing`，漂移返回 `approval_binding_mismatch`；需重新展示当前候选并由用户再次确认。同一 `candidate_id` 绝不证明同一正文。历史已发布资产保持有效；未发布且无可信快照的旧候选不自动升级或补签。
