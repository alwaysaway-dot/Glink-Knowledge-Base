#!/usr/bin/env python3
"""Shared identity, parsing and relation helpers for Knowledge Relation Layer."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path


HEX64 = r"[0-9a-f]{64}"
ASSET_ID_RE = re.compile(rf"^asset_sha256_{HEX64}$")
MATERIAL_ID_RE = re.compile(rf"^material_sha256_{HEX64}$")
REVISION_ID_RE = re.compile(rf"^revision_sha256_{HEX64}$")
SNAPSHOT_RE = re.compile(rf"^snapshot_sha256_{HEX64}$")
ELIGIBLE_STATES = {"formal", "confirmed", "published", "active"}
SCAN_DIRECTORIES = {
    "10 原始资料": "source",
    "20 学习笔记": "knowledge",
    "30 情报简报": "intelligence",
    "40 方法库": "method",
    "50 输出成果": "creation",
}
FORWARD_RELATIONS = {
    "source_of": "derived_from",
    "derived_from": "source_of",
    "explains": "explained_by",
    "extends": "extended_by",
    "supports": "supported_by",
    "contrasts_with": "contrasts_with",
    "applies": "applied_by",
    "updates": "updated_by",
    "method_for": "uses_method",
    "supersedes": "superseded_by",
    "related": "related",
}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_json(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def atomic_write(path: Path, value: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    with temporary.open("wb") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def atomic_json(path: Path, value):
    atomic_write(path, canonical_json(value))


def parse_scalar(value: str):
    value = value.strip().strip('"').strip("'")
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return value


def parse_frontmatter(text: str):
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text
    values = {}
    for line in text[4:end].splitlines():
        if not line or line[0].isspace() or ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = parse_scalar(value)
    return values, text[end + 5 :]


def title_from_text(path: Path, body: str):
    match = re.search(r"^#\s+(.+)$", body, re.M)
    return match.group(1).strip() if match else path.stem


def section_map(body: str):
    matches = list(re.finditer(r"^#{1,6}\s+(.+?)\s*$", body, re.M))
    sections = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections.setdefault(match.group(1).strip(), "")
        sections[match.group(1).strip()] += body[start:end].strip() + "\n"
    return sections


def state_values(frontmatter):
    keys = ("status", "workflow_state", "review_status", "ingestion_status")
    return {str(frontmatter.get(key, "")).strip().lower() for key in keys if frontmatter.get(key) is not None}


def scan_asset(path: Path, vault: Path, asset_class: str):
    path = path.resolve()
    vault = vault.resolve()
    payload = path.read_bytes()
    file_hash = sha256_bytes(payload)
    text = payload.decode("utf-8")
    frontmatter, body = parse_frontmatter(text)
    relative_path = str(path.relative_to(vault))
    states = state_values(frontmatter)
    type_value = str(frontmatter.get("type", "")).lower()
    exclusion = ""
    if "draft" in path.name.lower() or "草稿" in path.name or "draft" in type_value:
        exclusion = "draft_excluded"
    elif any("waiting" in state or "draft" in state or "candidate" in state for state in states):
        exclusion = "non_formal_state"
    elif frontmatter.get("cleanup_candidate") is True:
        exclusion = "cleanup_candidate_projection"
    elif not states.intersection(ELIGIBLE_STATES):
        exclusion = "formal_state_missing"

    endpoint_id = ""
    endpoint_revision = ""
    if asset_class == "source":
        material_id = str(frontmatter.get("material_id", ""))
        revision_id = str(frontmatter.get("revision_id", ""))
        if MATERIAL_ID_RE.fullmatch(material_id) and REVISION_ID_RE.fullmatch(revision_id):
            endpoint_id, endpoint_revision = material_id, revision_id
        elif not exclusion:
            exclusion = "stable_source_identity_missing"
    else:
        asset_id = str(frontmatter.get("asset_id", ""))
        if ASSET_ID_RE.fullmatch(asset_id):
            endpoint_id = asset_id
            explicit_revision = str(frontmatter.get("revision_id", ""))
            endpoint_revision = explicit_revision if REVISION_ID_RE.fullmatch(explicit_revision) else "snapshot_sha256_" + file_hash
        elif not exclusion:
            exclusion = "stable_asset_identity_missing"

    return {
        "asset_id": endpoint_id,
        "revision": endpoint_revision,
        "asset_class": asset_class,
        "type": frontmatter.get("type", ""),
        "title": title_from_text(path, body),
        "relative_path": relative_path,
        "absolute_path": str(path),
        "file_hash": "sha256:" + file_hash,
        "frontmatter": frontmatter,
        "sections": section_map(body),
        "body": body,
        "eligible": not exclusion,
        "exclusion_reason": exclusion,
    }


def scan_vault(vault_path: str):
    vault = Path(vault_path).resolve()
    assets = []
    for directory, asset_class in SCAN_DIRECTORIES.items():
        root = vault / directory
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.md")):
            if path.is_symlink():
                continue
            assets.append(scan_asset(path, vault, asset_class))
    return assets


def candidate_id(source_id, source_revision, target_id, target_revision, relation_type):
    payload = "|".join((source_id, source_revision, relation_type, target_id, target_revision)).encode("utf-8")
    return "relation_candidate_sha256_" + sha256_bytes(payload)


def canonical_pair(left_id: str, right_id: str):
    return tuple(sorted((left_id, right_id)))


def relation_exists(registry, source, target, relation_type, reciprocal):
    candidate_pair = canonical_pair(source, target)
    semantics = {relation_type, reciprocal}
    for item in registry.get("relations", []):
        if item.get("approval_status") not in {"approved", "executed", "auto_executed"}:
            continue
        if canonical_pair(item.get("source_asset_id", ""), item.get("target_asset_id", "")) != candidate_pair:
            continue
        if {item.get("relation_type"), item.get("reciprocal_relation")} == semantics:
            return True
    return False


def current_revision(asset):
    # scan_asset already prefers an explicit stable revision and falls back to
    # a snapshot revision only for legacy assets. Reuse that canonical choice.
    return asset["revision"]
