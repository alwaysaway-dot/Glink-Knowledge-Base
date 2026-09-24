#!/usr/bin/env python3
"""Dedicated Source Asset ingestion entrypoint; learning_note remains in Swift MVP."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path


def production_target() -> Path:
    value = os.environ.get("GUANLAN_VAULT_ROOT", "")
    if not value or not Path(value).is_absolute():
        raise ValueError("production requires absolute GUANLAN_VAULT_ROOT")
    return Path(value).resolve() / "10 原始资料"


def rollback_root() -> Path:
    value = os.environ.get("GUANLAN_ROLLBACK_ROOT", "")
    if not value or not Path(value).is_absolute():
        raise ValueError("rollback requires absolute GUANLAN_ROLLBACK_ROOT")
    return Path(value).resolve()
ID_RE = re.compile(r"^(material|revision)_sha256_[0-9a-f]{64}$")
FORMAL_RE = re.compile(r"^guanlan://")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value):
    atomic_write(path, (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def atomic_write(path: Path, value: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    with temporary.open("wb") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def register_receipt(record_path: Path, asset_root: Path, manifest_path: Path):
    """Commit the immutable receipt and register its permanent reference."""
    payload = record_path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    asset_id = "asset_sha256_" + digest
    relative_object = Path("objects") / "sha256" / digest[:2] / digest
    object_path = asset_root / relative_object
    if object_path.exists():
        if sha256_file(object_path) != digest:
            raise ValueError("receipt object collision")
    else:
        atomic_write(object_path, payload)
    manifest = load_json(manifest_path)
    entry = {
        "role": "source_asset_ingestion_receipt",
        "reference": f"guanlan://report/{asset_id}",
        "asset_id": asset_id,
        "content_hash": "sha256:" + digest,
        "media_type": "application/json",
        "size_bytes": len(payload),
        "storage_relative_path": str(relative_object),
    }
    entries = manifest.setdefault("entries", [])
    if not any(item.get("asset_id") == asset_id for item in entries):
        entries.append(entry)
        atomic_json(manifest_path, manifest)
    return entry["reference"]


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def frontmatter(text: str):
    if not text.startswith("---\n"):
        raise ValueError("Source Asset projection requires frontmatter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError("unterminated frontmatter")
    values = {}
    for line in text[4:end].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip().strip('"')
    return values


def validate_filename(filename: str):
    if Path(filename).name != filename or not filename.endswith(".md"):
        raise ValueError("filename must be a single Markdown filename")
    if not re.match(r"^\d{4}-\d{2}-\d{2}_.+\.md$", filename):
        raise ValueError("filename must follow existing date_title rule")
    if len(filename) > 90 or any(item in filename for item in ("/", "\\", ":", "|")):
        raise ValueError("filename is unsafe or too long")


def validate_target(path: str, scope: str):
    target = Path(path).resolve()
    if scope == "production":
        if target != production_target():
            raise ValueError("production Source Asset target must be 10 原始资料")
    else:
        if not str(target).startswith(("/tmp/", "/private/tmp/")) or target.name != "10 原始资料":
            raise ValueError("test target must be a /tmp directory named 10 原始资料")
    return target


def identity_in_file(path: Path):
    try:
        values = frontmatter(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return "", ""
    return values.get("material_id", ""), values.get("revision_id", "")


def validate_committed_revision_inputs(args, revision_id: str):
    named = {
        "source-material-v3.json": Path(args.source_material).resolve(),
        "reference-manifest.json": Path(args.manifest).resolve(),
        "source-asset-projection.md": Path(args.projection).resolve(),
        "source-asset-validation.json": Path(args.validation).resolve(),
        "source-asset-approval.json": Path(args.confirmation).resolve(),
    }
    if any(path.name != expected for expected, path in named.items()):
        raise ValueError("revision_not_committed: Source Ingestion requires canonical revision files")
    parents = {path.parent for path in named.values()}
    if len(parents) != 1:
        raise ValueError("revision_not_committed: Source Ingestion inputs must share one committed revision directory")
    revision_dir = next(iter(parents))
    if (
        revision_dir.name != revision_id
        or revision_dir.parent.name != "revisions"
        or ".staging." in revision_dir.name
        or revision_dir.name.startswith(".")
    ):
        raise ValueError("revision_not_committed: staging or non-canonical revision input is forbidden")
    lock_path = revision_dir.parent / f".{revision_id}.promotion.lock"
    if lock_path.exists():
        raise ValueError("revision_not_committed: Source Promotion transaction has not finished")


def write_receipt(path, source, relative_target, status, confirmation, projection_hash, preexisting):
    receipt = {
        "protocol": "source-asset-ingestion-v1",
        "schema_version": "1.0.0",
        "source": source,
        "ingestion": {"target_type": "source_asset", "target_path": relative_target, "status": status},
        "confirmation": {
            "confirmed": bool(confirmation.get("confirmed")),
            "confirmed_at": confirmation.get("confirmed_at", ""),
            "reviewer": confirmation.get("reviewer", "user"),
        },
        "transaction": {
            "atomic_write": True,
            "projection_sha256": "sha256:" + projection_hash,
            "rollback_guard": "sha256:" + projection_hash,
            "preexisting": preexisting,
            "automatic_deletion_executed": False,
        },
    }
    record_path = Path(path)
    if status == "duplicate" and record_path.exists():
        existing = load_json(record_path)
        if (
            existing.get("protocol") == "source-asset-ingestion-v1"
            and existing.get("source") == source
            and existing.get("ingestion", {}).get("target_path") == relative_target
            and existing.get("ingestion", {}).get("status") == "completed"
            and existing.get("transaction", {}).get("projection_sha256") == "sha256:" + projection_hash
        ):
            result = json.loads(json.dumps(existing))
            result["idempotency"] = {"status": "duplicate", "completed_receipt_preserved": True}
            return result
    atomic_json(record_path, receipt)
    return receipt


def ingest(args):
    target_dir = validate_target(args.vault, args.scope)
    validate_filename(args.filename)
    source_material = load_json(args.source_material)
    manifest = load_json(args.manifest)
    validation = load_json(args.validation)
    approval = load_json(args.confirmation)
    projection_path = Path(args.projection).resolve()
    projection_text = projection_path.read_text(encoding="utf-8")
    fm = frontmatter(projection_text)

    if source_material.get("protocol") != "source-material-v3":
        raise ValueError("source-material-v3 is required")
    material_id, revision_id = source_material.get("material_id", ""), source_material.get("revision_id", "")
    if not ID_RE.fullmatch(material_id) or not ID_RE.fullmatch(revision_id):
        raise ValueError("invalid material/revision identity")
    validate_committed_revision_inputs(args, revision_id)
    if manifest.get("material_id") != material_id or manifest.get("revision_id") != revision_id:
        raise ValueError("manifest identity mismatch")
    if validation.get("status") != "passed" or validation.get("material_id") != material_id or validation.get("revision_id") != revision_id:
        raise ValueError("validation receipt mismatch or failure")
    if not approval.get("confirmed") or approval.get("material_id") != material_id or approval.get("revision_id") != revision_id:
        raise ValueError("explicit matching Source Asset approval is required")
    if not approval.get("confirmed_at") or approval.get("reviewer") != "user":
        raise ValueError("user confirmation record is incomplete")

    readable = source_material["content"]["readable"]
    if validation.get("content_hash") != readable.get("content_hash"):
        raise ValueError("validation content hash mismatch")
    formal_fields = {
        "readable_reference": readable.get("reference", ""),
        "raw_reference": source_material["content"]["raw"].get("reference", ""),
        "manifest_reference": source_material.get("asset_manifest_reference", ""),
        "validation_reference": fm.get("validation_reference", ""),
        "approval_reference": fm.get("approval_reference", ""),
        "source_reference": fm.get("source_reference", ""),
    }
    for name, value in formal_fields.items():
        if not FORMAL_RE.match(value) or value.startswith(("/tmp/", "/private/tmp/")):
            raise ValueError(f"{name} must be a permanent guanlan reference")
    expected_fm = {
        "type": "source_asset", "asset_class": "source", "material_id": material_id,
        "revision_id": revision_id, "content_hash": readable["content_hash"],
        "manifest_reference": source_material["asset_manifest_reference"],
    }
    for key, value in expected_fm.items():
        if fm.get(key) != value:
            raise ValueError(f"projection frontmatter mismatch: {key}")
    if re.search(r"^#{1,6}\s+.*(?:AI\s*分析|核心观点总结|学习笔记|方法抽象|我的思考)", projection_text, re.M):
        raise ValueError("Source Asset projection contains forbidden analysis/knowledge sections")
    if "/tmp/" in projection_text or "/private/tmp/" in projection_text:
        raise ValueError("Source Asset projection contains a temporary reference")

    target_dir.mkdir(parents=True, exist_ok=True)
    projection_hash = sha256_file(projection_path)
    destination = target_dir / args.filename
    for existing in target_dir.glob("*.md"):
        existing_material, existing_revision = identity_in_file(existing)
        if existing_material == material_id and existing_revision == revision_id:
            if sha256_file(existing) != projection_hash:
                raise ValueError("same material/revision already exists with different projection content")
            source_record = {
                "material_id": material_id, "revision_id": revision_id,
                "content_hash": readable["content_hash"], "source_reference": fm["source_reference"],
                "manifest_reference": fm["manifest_reference"],
                "validation_reference": fm["validation_reference"], "approval_reference": fm["approval_reference"],
            }
            return write_receipt(args.record, source_record, f"10 原始资料/{existing.name}", "duplicate", approval, projection_hash, True)
    if destination.exists():
        raise ValueError("target filename exists with a different identity; refusing automatic suffix")

    source_record = {
        "material_id": material_id, "revision_id": revision_id,
        "content_hash": readable["content_hash"], "source_reference": fm["source_reference"],
        "manifest_reference": fm["manifest_reference"],
        "validation_reference": fm["validation_reference"], "approval_reference": fm["approval_reference"],
    }
    created = False
    try:
        atomic_write(destination, projection_path.read_bytes())
        created = True
        receipt = write_receipt(args.record, source_record, f"10 原始资料/{destination.name}", "completed", approval, projection_hash, False)
    except Exception:
        if created and destination.exists() and sha256_file(destination) == projection_hash:
            destination.unlink()
        raise
    return receipt


def rollback(args):
    receipt = load_json(args.record)
    confirmation = load_json(args.rollback_confirmation)
    if receipt.get("protocol") != "source-asset-ingestion-v1" or receipt.get("ingestion", {}).get("status") != "completed":
        raise ValueError("completed Source Asset receipt is required")
    if not confirmation.get("confirmed") or not confirmation.get("reason"):
        raise ValueError("explicit rollback confirmation and reason are required")
    relative = receipt["ingestion"]["target_path"]
    if not relative.startswith("10 原始资料/"):
        raise ValueError("rollback target is outside Source Asset allowlist")
    source = production_target() / Path(relative).name
    expected = receipt["transaction"]["rollback_guard"].split(":", 1)[1]
    if not source.is_file() or sha256_file(source) != expected:
        raise ValueError("rollback guard failed; target missing or changed")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = rollback_root()
    root.mkdir(parents=True, exist_ok=True)
    destination = root / f"{stamp}_{source.name}"
    os.replace(source, destination)
    result = {"status": "rolled_back", "recoverable_copy": str(destination), "permanent_deletion": False}
    atomic_json(Path(args.rollback_output), result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--command", choices=("ingest", "rollback"), default="ingest")
    parser.add_argument("--scope", choices=("test", "production"), default="test")
    parser.add_argument("--source-material")
    parser.add_argument("--manifest")
    parser.add_argument("--projection")
    parser.add_argument("--validation")
    parser.add_argument("--confirmation")
    parser.add_argument("--vault")
    parser.add_argument("--filename")
    parser.add_argument("--record", required=True)
    parser.add_argument("--asset-root")
    parser.add_argument("--manifest-update")
    parser.add_argument("--rollback-confirmation")
    parser.add_argument("--rollback-output")
    args = parser.parse_args()
    try:
        if args.command == "ingest":
            required = (args.source_material, args.manifest, args.projection, args.validation, args.confirmation, args.vault, args.filename)
            if not all(required):
                raise ValueError("ingest requires source, manifest, projection, validation, confirmation, vault and filename")
            result = ingest(args)
            if bool(args.asset_root) != bool(args.manifest_update):
                raise ValueError("receipt registration requires both --asset-root and --manifest-update")
            if args.asset_root:
                result["receipt_reference"] = register_receipt(
                    Path(args.record), Path(args.asset_root).resolve(), Path(args.manifest_update).resolve()
                )
        else:
            if not args.rollback_confirmation or not args.rollback_output:
                raise ValueError("rollback requires confirmation and output")
            result = rollback(args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        raise SystemExit(f"ERROR: {error}") from error


if __name__ == "__main__":
    main()
