"""Shared safety primitives for formal derivative-asset publishers.

This module deliberately contains only publisher mechanics.  Per-asset meaning
and admission rules stay in the caller-specific quality gates.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path


def production_vault() -> Path:
    value = os.environ.get("GUANLAN_VAULT_ROOT", "")
    if not value or not Path(value).is_absolute():
        raise ValueError("production requires absolute GUANLAN_VAULT_ROOT")
    return Path(value).resolve()
TEMP_MARKERS = ("/tmp/", "/private/tmp/", "file:///tmp/", "file:///private/tmp/")
STABLE_REF = re.compile(r"^guanlan://(?:asset|material|manifest|report|candidate)/")

TARGETS = {
    "learning_note": "20 学习笔记",
    "intelligence_brief": "30 情报简报",
    "method_asset": "40 方法库",
    "creation_asset": "50 输出成果",
}
ASSET_CLASSES = {
    "learning_note": "knowledge",
    "intelligence_brief": "intelligence",
    "method_asset": "knowledge",
    "creation_asset": "creation",
}
GRAPH_GROUPS = {
    "learning_note": "20_learning",
    "intelligence_brief": "30_intelligence",
    "method_asset": "40_method",
    "creation_asset": "50_creation",
}


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def atomic_write(path: Path, value: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    temporary.write_bytes(value)
    os.replace(temporary, path)


def atomic_json(path: Path, value):
    atomic_write(path, canonical(value))


def load_json(path: Path, label: str):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid {label}: {error}") from error


def has_temp(value) -> bool:
    if isinstance(value, dict):
        return any(has_temp(item) for item in value.values())
    if isinstance(value, list):
        return any(has_temp(item) for item in value)
    return isinstance(value, str) and any(marker in value for marker in TEMP_MARKERS)


def strip_frontmatter(text: str) -> str:
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end >= 0:
            return text[end + 5:].lstrip("\n")
    return text


def resolve_target(vault_root: Path, asset_type: str, target_folder: str, scope: str) -> Path:
    expected = TARGETS.get(asset_type)
    if expected is None:
        raise ValueError(f"unsupported formal asset type: {asset_type}")
    if target_folder != expected:
        raise ValueError(f"{asset_type} only supports {expected}")
    root = vault_root.resolve()
    if scope == "production" and root != production_vault():
        raise ValueError("production Vault root mismatch")
    target = (root / target_folder).resolve()
    if target.parent != root:
        raise ValueError("target escapes Vault root")
    return target


def require_stable_references(references, label: str):
    if not isinstance(references, list) or not references:
        raise ValueError(f"{label} requires stable references")
    for value in references:
        if not isinstance(value, str) or not STABLE_REF.match(value):
            raise ValueError(f"{label} has unstable reference: {value}")


def identity(body: bytes, source: dict, asset_type: str):
    body_hash = digest(body)
    asset_id = "asset_sha256_" + body_hash
    revision_payload = canonical({
        "asset_id": asset_id,
        "asset_subtype": asset_type,
        "content_hash": "sha256:" + body_hash,
        "source_asset_id": source["material_id"],
        "source_revision_id": source["revision_id"],
    })
    return asset_id, "revision_sha256_" + digest(revision_payload), "sha256:" + body_hash
