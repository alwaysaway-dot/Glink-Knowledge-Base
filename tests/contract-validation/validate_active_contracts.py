#!/usr/bin/env python3
"""Validate checked-in production contracts without reviving legacy modules."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=False)


def record(checks: list[dict], check_id: str, passed: bool, detail: str) -> None:
    checks.append({"id": check_id, "status": "pass" if passed else "fail", "detail": detail})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    manifest = load_json(args.manifest)
    checks: list[dict] = []

    for group in ("active_modules", "active_protocols", "active_contract_tests"):
        missing = [item for item in manifest[group] if not (root / item).is_file()]
        record(
            checks,
            f"{group}_present",
            not missing,
            "all declared active paths exist" if not missing else f"missing: {missing}",
        )

    # Historical files may remain for replay. The active contract must not load
    # them, even when the production checkout contains those files.
    active = manifest["active_modules"] + manifest["active_contract_tests"]
    legacy = manifest["legacy_exclusions"]
    restored = []
    for item in legacy:
        path = item["path"]
        basename = Path(path).name
        if path in active or any(
            marker in (root / module).read_text(encoding="utf-8")
            for module in active if (root / module).is_file()
            for marker in (path, basename)
        ):
            restored.append(path)
    record(
        checks,
        "legacy_runtime_excluded",
        not restored,
        "historical files are not active runtime dependencies" if not restored else f"active legacy dependencies: {restored}",
    )

    with tempfile.TemporaryDirectory(prefix="guanlan-active-contracts.", dir="/tmp") as temporary:
        temp = Path(temporary)
        router_out = temp / "router"
        router = run(["bash", str(root / "tests/capture-provider-router/run-router-contracts.sh"), str(router_out)])
        routed = False
        if router.returncode == 0:
            youtube = load_json(router_out / "youtube.json")
            douyin = load_json(router_out / "douyin-short.json")
            local = load_json(router_out / "local.json")
            routed = (
                youtube.get("provider") == "youtube_yt_dlp"
                and douyin.get("provider") == "douyin"
                and local.get("provider") == "local_file"
            )
        record(checks, "capture_router_contract", router.returncode == 0 and routed, router.stderr.strip() or "specific provider routing is intact")

        good_projection = temp / "capture.md"
        good_projection.write_text(
            "# Fixture\n\n## 来源信息\n\n- URL: https://example.test/article\n\n"
            "## 采集状态\n\ncomplete\n\n## 原始正文\n\n事实正文。\n",
            encoding="utf-8",
        )
        good = run([
            "python3", str(root / "source-material-generator/capture_projection_validator.py"),
            "--input", str(good_projection), "--output", str(temp / "good.json"),
        ])
        polluted_projection = temp / "polluted.md"
        polluted_projection.write_text(good_projection.read_text(encoding="utf-8") + "\n## 初步摘要\n\n不应进入事实层。\n", encoding="utf-8")
        polluted = run([
            "python3", str(root / "source-material-generator/capture_projection_validator.py"),
            "--input", str(polluted_projection), "--output", str(temp / "polluted.json"),
        ])
        record(
            checks,
            "capture_fact_boundary",
            good.returncode == 0 and polluted.returncode != 0,
            "fact projection passes and analysis pollution fails closed",
        )

        foundation_out = temp / "foundation"
        foundation = run(["bash", str(root / "tests/knowledge-foundation-stability/run-validation.sh"), str(foundation_out)])
        record(
            checks,
            "source_material_identity_reference_contract",
            foundation.returncode == 0,
            foundation.stderr.strip() or "Source Material v3 identity/reference validation passed",
        )

    failed = [item for item in checks if item["status"] != "pass"]
    report = {
        "protocol": "guanlan-contract-validation-v2",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "manifest": args.manifest.relative_to(root).as_posix(),
        "checks": checks,
        "summary": {
            "status": "failed" if failed else "passed",
            "passed": len(checks) - len(failed),
            "failed": len(failed),
            "legacy_runtime_restored": False,
            "production_asset_library_required": False,
            "vault_required": False,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if failed:
        for item in failed:
            print(f"FAIL {item['id']}: {item['detail']}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
