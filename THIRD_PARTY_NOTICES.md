# Third-party notices / 第三方声明

Guanlan's MIT license covers only project-owned material that the confirmed copyright holder can license. Dependencies retain their own licenses. This release candidate does not vendor the libraries below or redistribute browser/model binaries.

- Scrapling 0.4.15: optional static HTML Provider dependency; BSD-3-Clause. Copyright (c) 2024, Karim shoair. [Upstream license](https://github.com/D4Vinci/Scrapling/blob/main/LICENSE). Its installed distribution retains this license. `capture-provider-router/requirements-static-web.txt` pins optional transitive packages; their licenses remain separate, including MPL-2.0 (`certifi`), MPL-2.0 plus Apache/MIT terms (`orjson`), and `tld`'s MPL-1.1/GPL-2.0-only/LGPL-2.1-or-later alternatives. No installed package or browser binary is redistributed in this source-only candidate; binary redistribution would require a fresh per-package notice review.
- claude-obsidian: transaction design reference only; no bundled dependency. [MIT license](https://github.com/AgriciDaniel/claude-obsidian/blob/main/LICENSE). Independent-implementation provenance still needs final review.
- SurfSense: run-history design reference only; no bundled dependency or copied source. Its [repository LICENSE](https://github.com/MODSetter/SurfSense/blob/main/LICENSE) assigns Apache-2.0 to content outside `surfsense_backend/app/proprietary/`, while that directory is under Business Source License 1.1; incorporated third-party components keep their own terms. Guanlan does not import the proprietary directory.
- tldw_server: durable-job research reference only; AU-D1 is not implemented or bundled. Its [GPL-3.0 license file](https://github.com/rmusser01/tldw_server/blob/main/LICENSE) is not replaced by Guanlan's MIT license; no GPL source is intentionally included.

This notice is engineering attribution, not a legal opinion. No third-party video, article or transcript is included in the synthetic demo.
