#!/usr/bin/env python3
"""Create a fresh user-owned Vault and asset root; never infer private defaults."""

from __future__ import annotations

import argparse
from pathlib import Path

VAULT_DIRS = (
    "00 收件箱", "10 原始资料", "20 学习笔记", "30 情报简报",
    "40 方法库", "50 输出成果", "90 系统",
)
ASSET_DIRS = ("materials", "objects", "operations", "governance")


def safe_new_directory(value: str, label: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute() or path.exists() or path.is_symlink():
        raise ValueError(f"{label} must be a new absolute path")
    resolved_parent = path.parent.resolve(strict=True)
    if resolved_parent == Path("/") or path.name in {"", ".", ".."}:
        raise ValueError(f"{label} must be a named directory under an existing parent")
    return resolved_parent / path.name


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault", required=True)
    parser.add_argument("--asset-root", required=True)
    args = parser.parse_args()
    vault = safe_new_directory(args.vault, "Vault")
    asset = safe_new_directory(args.asset_root, "asset root")
    if vault == asset or vault in asset.parents or asset in vault.parents:
        raise ValueError("Vault and asset root must be separate directories")
    vault.mkdir()
    asset.mkdir()
    for name in VAULT_DIRS:
        (vault / name).mkdir()
    for name in ASSET_DIRS:
        (asset / name).mkdir()
    print(f"vault_initialized={vault}\nasset_root_initialized={asset}")


if __name__ == "__main__":
    main()
