# Guanlan / 观澜

[English](README.md) · [架构与工作流](docs/architecture.md) · [第三方声明](THIRD_PARTY_NOTICES.md)

观澜是面向兼容 Obsidian 的 Markdown Vault、以来源证据和人工审批为核心的知识工作流。它将来源事实与 AI 派生知识候选分开：**采集 → 整理 → 审阅 → 发布 → 关系整理**。仓库包含基于夹具的本地演示；它**不是**实时 AI 生成或实时网页采集演示。

GitHub 仓库为 [`Glink-Knowledge-Base`](https://github.com/alwaysaway-dot/Glink-Knowledge-Base)，项目名称仍是 Guanlan / 观澜。首次公开版本线为 **v1**，版本元数据与源码归档通过 GitHub Releases 管理。

## 已实现能力

- Source Material v3、稳定身份/引用、证据和可读来源晋升。
- Candidate Bundle 与多资产路由；来源资产和派生资产相互独立。
- Learning Note v2，对 AI 结构化抽象标注权威边界，并将发布绑定用户审批。
- Publisher 事务/Receipt、Relation Registry/Curation，以及非 canonical 的操作历史索引。
- 可选 Scrapling 依赖提供公开静态 HTML 采集。平台专项采集和媒体转录需要另行安装工具、凭据、权限或模型。

观澜**不是**自主研究 Agent、万能爬虫、自动知识发布服务、RAG 系统，也没有任意阶段的持久化媒体任务编排；AU-D1 暂缓。Draft 与来源事实不会自动变成正式知识。

## 支持环境与安装

此候选已在 macOS、CPython 3.14 上验证。测试使用 `bash`、部分旧脚本使用 `jq`，并需要普通文件系统访问。Obsidian 可打开 Markdown Vault，但合成演示不依赖它。其他操作系统尚未验证。核心 Python 测试不需要付费模型账号。Swift、FFmpeg、FunASR、yt-dlp、Agent Reach 和登录态浏览器采集均是可选外部能力；见[Provider 限制](docs/providers.md)。

在本目录检查 `python3 --version`，运行 `bash scripts/run_core_tests.sh`。仅当使用可选静态网页采集时，另建虚拟环境安装 `capture-provider-router/requirements-static-web.txt`；该锁定依赖基于 macOS arm64 / CPython 3.14。核心测试不需要浏览器 Profile、API Key 或真实媒体。

## 快速开始：隔离合成工作流

```bash
demo_parent="$(mktemp -d /tmp/guanlan-public-demo.XXXXXX)"
python3 scripts/init_local.py --vault "$demo_parent/empty-vault" --asset-root "$demo_parent/empty-assets"
python3 examples/synthetic-demo/run_demo.py --output-root "$demo_parent/run"
```

初始化脚本创建新的空 Vault 和资产根，并拒绝已有路径。演示会在 `run/` 下创建**自己的**隔离夹具 Vault，展示合成证据、00 收件箱投影、10 来源资产、预制 Learning 候选及**测试审批**、20 学习笔记、原始 Publish Receipt、结构关系与链接投影。结果路径见 `run/demo-summary.json`。`empty-vault` 与演示 Vault 分离，供查看空白目录结构。演示不会真实联网采集、调用模型/API、登录或写入已有 Vault。

查看后，仅清理刚创建且确认路径为 `/tmp/guanlan-public-demo.*` 的 `demo_parent`（例如在变量仍指向该目录时执行 `rm -r "$demo_parent"`）。不要对个人 Vault 执行清理。

## 正式运行配置边界

正式入口必须指定使用者自己的绝对路径。`GUANLAN_VAULT_ROOT` 用于 00/10/20/30/40/50 目标，`GUANLAN_ASSET_ROOT` 用于 Generic Web 受管资产根；显式回滚 Source 前还需 `GUANLAN_ROLLBACK_ROOT`。其他 asset-root/project-root 通过 CLI 参数传入。缺少正式 Vault 配置会明确失败，不会回退到开发者私人路径。公开配置样例位于 `core/config/`。

创建目录不等于获得发布授权。Source 晋升需要验证过的 Manifest/Evidence 与用户确认；派生资产发布需要候选、质量闸门和绑定用户批准的记录。输入真实素材前，应先运行合成演示并阅读模块 README。包含所有可选 Provider 的真实用户生产安装，**尚未**在空白环境完整复现。

## 隐私与已知限制

Vault 与运行时 asset-library 是用户数据，不属于仓库。不要提交它们、日志、模型缓存、浏览器 Profile、Cookie、Token、真实 Transcript 或 Receipt。Provider 调用可能按各自条款访问第三方。静态 HTML 仅适用于公开页面；JS/登录/challenge/PDF/媒体等情况会明确报告不支持。平台采集受可用性、权限和本地配置限制，不是默认 CI 要求。见[Provider 限制](docs/providers.md)和[架构说明](docs/architecture.md)。

## 许可证

用户已确认公开版权持有人 alwaysaway 有权将项目自有代码和文档以 MIT 授权；这不覆盖第三方内容。依赖保持各自许可，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。公开 v1 与私人开发冻结版本不是同一个版本标签。
