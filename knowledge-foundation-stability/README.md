# Knowledge Foundation Stability

观澜 v0.5 的无数据库基础校验模块。

支持：

- 稳定 `material_id` / `asset_id` 计算。
- Source Material v3 Schema 校验。
- Revision identity 校验。
- Reference Manifest 和真实文件哈希校验。
- `/tmp`、绝对路径、缺失资产和路径穿越拒绝。

示例：

```bash
python3 foundation_stability.py identity \
  --platform youtube \
  --source-id ABCdef12345

python3 foundation_stability.py validate-source-material \
  --input source-material.json \
  --manifest manifest.json
```

测试可以在 `/tmp` 生成 fixture，但 `--check-files` 的正式 asset root 会拒绝 `/tmp`。测试套件使用独立的 non-formal 模式验证 Schema，并单独验证临时资产根拒绝。
