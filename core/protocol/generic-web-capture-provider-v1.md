# Generic Web Capture Provider v1

## Scope

This provider captures one user-requested, public, static HTML/XHTML page. It retrieves facts; it does not summarize, infer knowledge, create routing decisions, or publish assets.

Specific Providers always win. YouTube, Douyin, Bilibili and Xiaohongshu URLs must never fall back to Generic Web after a Provider failure.

## Input

- `capture_request_id`
- absolute public `http`/`https` URL without credentials
- `requested_at`
- bounded timeout
- optional language hint

## Provider result

`generic-web-provider-result-v1` records Provider identity/version, requested/final URL, retrieval time, HTTP status, allowlisted response metadata, explicit title/author/published time, stable raw HTML and readable text references, deterministic extraction method, warnings and one typed failure.

The Provider adapter must not create `material_id`, `revision_id`, `asset_id`, candidate identity, lifecycle state, routing decisions or relations. Existing Guanlan Source/Identity code creates those facts after the adapter returns.

## Accepted content

Only `text/html` and `application/xhtml+xml` are parsed. PDF, image, audio, video and binary responses return `unsupported_content_type` with a handoff kind. No PDF or media ingestion is created here.

## Failure classes

`invalid_url`, `dns_error`, `network_error`, `timeout`, `redirect_error`, `http_4xx`, `http_429`, `http_5xx`, `unsupported_content_type`, `empty_html`, `no_readable_content`, `javascript_required`, `authentication_required`, `challenge_page`, `provider_error`.

Login, challenge and JS-only pages fail closed. v1 never activates a browser, stealth, proxy rotation, authenticated cookies, crawler, Spider, adaptive selector, MCP, AI extractor or RAG.

## Evidence and extraction

Raw HTML is committed through the existing content-addressed asset store and remains auditable. Readable Source uses deterministic parsing only: explicit metadata, noise-tag removal, paragraph reconstruction and whitespace normalization. It performs no summary, translation, semantic rewrite or factual completion.

The Provider performs one HTTP attempt. Guanlan owns retry policy. Scrapling `robots.txt` handling is not claimed; v1 is a single-URL, user-triggered fetch rather than a crawler.

## Completion

Successful production capture enters Source Material v3 and the existing Capture Completion Contract, including a `00 收件箱` projection. It must not organize, generate Learning Notes or ingest into 10/20/30/40/50.

Production capture must supply the canonical `00 收件箱` projection before fetching. Asset and projection destinations are validated before any write; a Provider Result alone is not a successful user-level production capture. Provider-only smoke remains a non-canonical diagnostic path.
