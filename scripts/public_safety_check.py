#!/usr/bin/env python3
"""Fail closed on obvious private release artifacts; report categories, never values."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_USERNAME = "liu" + "xinyang"
PRIVATE_TITLE = "聪明的" + "投资者"
PRIVATE_VAULT = "自生长" + "知识库"
SENSITIVE = {
    "private_home": re.compile(re.escape("/Users/" + PRIVATE_USERNAME)),
    "private_vault": re.compile(re.escape(PRIVATE_VAULT)),
    "private_case": re.compile(re.escape(PRIVATE_TITLE)),
    "token_shape": re.compile(r"(?:gh[pousr]_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,})"),
    "private_key": re.compile("-----BEGIN " + "PRIVATE KEY-----"),
}
EXCLUDED_DIRS = {"__pycache__", ".venv", ".venv-web-provider"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-license-placeholder", action="store_true")
    args = parser.parse_args()
    issues: list[tuple[str, str]] = []
    for path in ROOT.rglob("*"):
        relative = path.relative_to(ROOT)
        if any(part in EXCLUDED_DIRS for part in relative.parts):
            continue
        if path.is_symlink():
            issues.append((relative.as_posix(), "symlink"))
            continue
        if not path.is_file():
            continue
        if path.stat().st_size > 1_000_000:
            issues.append((relative.as_posix(), "large_file"))
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            issues.append((relative.as_posix(), "binary_file"))
            continue
        for category, pattern in SENSITIVE.items():
            if pattern.search(content):
                issues.append((relative.as_posix(), category))
    if (ROOT / ".git").exists():
        issues.append((".git", "private_git_history"))
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    if not args.allow_license_placeholder and "COPYRIGHT_HOLDER_CONFIRMATION_REQUIRED" in license_text:
        issues.append(("LICENSE", "copyright_holder_unconfirmed"))
    for path, category in sorted(set(issues)):
        print(f"{path}: {category}")
    print(f"release_safety_issues={len(set(issues))}")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
