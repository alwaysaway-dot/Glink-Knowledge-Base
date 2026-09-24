# Generic Web Provider dependencies

- Scrapling 0.4.15 — BSD-3-Clause — <https://github.com/D4Vinci/Scrapling>
- Upstream source review snapshot: commit `2b160ee18bfee79bb0115e2d9e9c746c8d9bf4c9`.

The provider uses only Scrapling's static `Fetcher`. It disables browser impersonation and stealth headers and does not install browser binaries. Scrapling 0.4.15 imports Playwright and Patchright response conversion types from its static import chain, so their Python packages are pinned as unavoidable import-time dependencies; no Dynamic/Stealth browser API is called.

Each transitive package remains governed by its own license. This file is engineering attribution, not legal advice.
