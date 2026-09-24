# Capture Provider Router

`source_router.py` 只负责选择 Provider，不采集媒体。正式入口仍是统一的“采集”，平台差异由 Router 处理。

## Generic Web Static Provider

未命中特定平台、且目标为公开 `http(s)` 网页时，Router 选择 `generic_web_static`。该 Provider 只支持单个公开静态 HTML/XHTML 页面：保留 Raw HTML，使用确定性解析产生 Readable Source，再进入 Source Material v3 与既有 Capture Completion Contract。

安装隔离依赖：

```bash
python3 -m venv .venv-web-provider
.venv-web-provider/bin/pip install -r capture-provider-router/requirements-static-web.txt
```

v1 不启用 DynamicFetcher、StealthyFetcher、Spider、代理、登录 Cookie、AI 提取或批量抓取。JS-only、登录和 challenge 页面会明确失败；PDF/媒体只返回 handoff 类型，不在此 Provider 内处理。

## Douyin Browser Provider

`douyin_browser_capture.mjs` 是 `CAPTURE ONCE → PRESERVE LOCALLY` 的薄适配器：

```text
Douyin 分享文本或作品 URL
→ Guanlan 专用 Chrome Profile
→ 页面身份与播放验证
→ 浏览器实际媒体响应
→ FFmpeg 封装与 ffprobe 验证
→ capture-protocol-v2
→ 现有 Local / Transcript 流程
```

它不读取 Cookie 内容，不使用用户日常浏览器 Profile，不生成摘要，不修改 Source Material 或知识资产。

### 首次登录

```bash
node capture-provider-router/douyin_browser_capture.mjs auth-init
```

在打开的 Guanlan 专用 Chrome 中由用户本人完成抖音官方登录，然后执行：

```bash
node capture-provider-router/douyin_browser_capture.mjs auth-check
```

默认 Profile 位于 macOS Application Support，不在 Git、Vault 或 asset-library 中。

### 单条采集

```bash
node capture-provider-router/douyin_browser_capture.mjs capture \
  --input '抖音分享文本或 https://v.douyin.com/.../'
```

成功产物进入 Guanlan Application Support 的独立 run 目录。每次运行使用不同 `run_id`；长期去重继续由 Asset Identity / Source Material 负责。

v1 只支持单条视频作品。作者主页、合集、直播、私密内容、Feed、批量采集和图文均不宣称支持。
