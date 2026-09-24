# Provider support / Provider 支持范围

| Provider | Status | Conditions / 边界 |
|---|---|---|
| Local synthetic fixture | Verified in this candidate / 已验证 | No network, model or personal data / 无联网、模型或私人资料 |
| Generic Web static HTML | Optional / 可选 | Scrapling lock required; one public HTML/XHTML page. JS-only, login/challenge, PDF and media are not handled here / 需安装 Scrapling；不处理 JS-only、登录、挑战页、PDF、媒体 |
| YouTube | Environment-dependent / 依赖环境 | External downloader/network and source permissions; not verified by this candidate demo / 需外部下载工具、网络与来源权限 |
| Douyin browser-assisted | Restricted optional / 受限可选 | User-owned authenticated Chrome profile; never bundled or used in CI / 用户自己的登录态 Profile，不随包发布、不进 CI |
| Xiaohongshu | Environment-dependent / 依赖环境 | Capture/quality may be partial or blocked; no login bypass or guaranteed transcript / 采集和质量可能部分成功或阻断，不保证转录 |
| FunASR transcript | Optional / 可选 | Separate Python environment/model; no bundled model or automatic download / 外部 Python 环境与模型，不随包提供 |

Dynamic/Stealth browser crawling, arbitrary-platform collection and AU-D1 durable media jobs are **not** included. / Dynamic、Stealth、任意平台采集和 AU-D1 持久媒体任务均未包含。
