# Guanlan / 观澜

[简体中文](README.zh-CN.md) · [Architecture and workflow](docs/architecture.md) · [Third-party notices](THIRD_PARTY_NOTICES.md)

Guanlan is an evidence-grounded, human-approved knowledge workflow for an Obsidian-compatible Markdown Vault. It separates source facts from AI-derived knowledge candidates: **capture → organize → review → publish → curate relations**. A fixture-based local demo is included; it is **not** a live AI generation or live web capture demonstration.

The GitHub repository is [`Glink-Knowledge-Base`](https://github.com/alwaysaway-dot/Glink-Knowledge-Base); the project remains Guanlan / 观澜. The initial public release line is **v1**, with version-specific metadata and source archives managed through GitHub Releases.

## What is implemented

- Source Material v3, stable identities/references, evidence and readable-source promotion.
- Candidate Bundle and multi-asset routing; source and derivative assets remain distinct.
- Learning Note v2 with authority labels for AI structural synthesis, plus user approval binding.
- Publisher transactions/receipts, Relation Registry/Curation and a non-canonical operation-history index.
- A static public HTML Provider via optional Scrapling dependency. Platform-specific capture and media transcription need separate tools, credentials, permissions or models.

Guanlan is **not** an autonomous research agent, universal crawler, automatic knowledge-publishing service, RAG system, or durable arbitrary-stage media-job orchestrator. AU-D1 is deferred. Drafts and source facts are not automatically promoted to formal knowledge.

## Supported environment and installation

The release candidate is validated on macOS with CPython 3.14. `bash`, `jq` (for selected legacy scripts), and standard filesystem access are used by tests. Obsidian can open the Markdown Vault, but is not required for the synthetic demo. Other operating systems are unverified. Core Python tests need no paid model account. Swift, FFmpeg, FunASR, yt-dlp, Agent Reach and authenticated browser capture are optional external capabilities; see [provider limits](docs/providers.md).

From this directory, check `python3 --version` and run `bash scripts/run_core_tests.sh`. For optional static web capture only, create a separate virtual environment and install `capture-provider-router/requirements-static-web.txt`; the pinned lock was resolved on macOS arm64 / CPython 3.14. No browser profile, API key or real media is needed for core tests.

## Quick start: isolated synthetic workflow

```bash
demo_parent="$(mktemp -d /tmp/guanlan-public-demo.XXXXXX)"
python3 scripts/init_local.py --vault "$demo_parent/empty-vault" --asset-root "$demo_parent/empty-assets"
python3 examples/synthetic-demo/run_demo.py --output-root "$demo_parent/run"
```

The initializer creates a new empty Vault and asset root; it refuses existing paths. The demo creates its **own** isolated fixture Vault under `run/` and shows synthetic evidence, a 00 inbox projection, a 10 Source Asset, a prewritten Learning candidate with a **test approval**, a 20 Learning Note, an original publish receipt and a structural relation/projection. `run/demo-summary.json` lists the results. The initialized `empty-vault` is separate so that users can inspect a clean directory layout. The demo performs no real network fetch, no model/API call, no login and no write to an existing Vault.

After inspection, remove only the exact `demo_parent` directory you just created (for example `rm -r "$demo_parent"` while that variable still points to the printed `/tmp/guanlan-public-demo.*` path). Do not run cleanup against a personal Vault.

## Production configuration boundary

Production entry points must be given the user's own absolute paths. Set `GUANLAN_VAULT_ROOT` for 00/10/20/30/40/50 targets, `GUANLAN_ASSET_ROOT` for Generic Web's managed asset root, and `GUANLAN_ROLLBACK_ROOT` before an explicit Source rollback. Other asset-root/project-root paths are explicit CLI arguments. Missing production Vault configuration fails closed; no developer-private default is used. The public sample config is in `core/config/`.

Initialization does not grant permission to publish. Source promotion requires a verified manifest/evidence and approval; derivative publication requires a candidate, quality gate and binding to a user approval. Start with the synthetic demo and module READMEs before supplying real material. Real-user production setup across all optional Providers has **not** been reproduced in an empty environment.

## Privacy and limitations

The Vault and runtime asset-library are user data, not repository content. Never commit them, logs, model caches, browser profiles, cookies, tokens, real transcripts or receipts. Provider calls may contact third-party services under their own terms. Static HTML works only for public pages and explicitly reports unsupported JS/login/challenge/PDF/media cases. Platform capture depends on availability, permissions and local setup; it is not a default CI requirement. See [provider limits](docs/providers.md) and [architecture](docs/architecture.md).

## License

Project-owned code and documentation are licensed under MIT by the user-confirmed public copyright holder, alwaysaway. This does not relicense third-party material. Dependencies retain their own terms; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Public v1 is distinct from the private development freeze label.
