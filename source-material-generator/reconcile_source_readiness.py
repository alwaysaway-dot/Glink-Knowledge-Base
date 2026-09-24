#!/usr/bin/env python3
"""Reconcile a validated Source Material revision into canonical/current readiness.

This is deliberately narrower than lifecycle reconciliation: it does not create or
modify revisions.  It validates one explicitly selected committed revision, refreshes
the single inbox projection for that material, and atomically advances the material's
CURRENT_REVISION pointer.  A stable receipt and validation record make the operation
auditable and idempotent.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from operation_envelope import OperationRecorder


def production_inbox() -> Path:
    value = os.environ.get("GUANLAN_VAULT_ROOT", "")
    if not value or not Path(value).is_absolute():
        raise ValueError("production requires absolute GUANLAN_VAULT_ROOT")
    return Path(value).resolve() / "00 收件箱"
ACCEPTABLE_CONTENT_QUALITY = {"usable", "usable_with_warnings"}


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    try:
        with temporary.open("wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def frontmatter_value(path: Path, key: str) -> str:
    match = re.search(rf"(?m)^{re.escape(key)}:\s*(.+?)\s*$", path.read_text(encoding="utf-8"))
    if not match:
        return ""
    value = match.group(1).strip()
    try:
        return str(json.loads(value))
    except json.JSONDecodeError:
        return value.strip("'\"")


def resolve_quality(source: dict, manifest: dict, asset_root: Path) -> tuple[dict, dict]:
    entries = {item.get("reference"): item for item in manifest.get("entries", [])}
    for history in reversed(source.get("lifecycle", {}).get("processing_history", [])):
        reference = str(history.get("report_reference", ""))
        entry = entries.get(reference)
        if not entry or entry.get("role") != "transcript_quality_report":
            continue
        target = (asset_root / entry["storage_relative_path"]).resolve()
        if asset_root not in target.parents:
            raise ValueError("quality report escapes asset root")
        report = load_json(target)
        if report.get("protocol") != "media-transcript-quality-v1":
            raise ValueError("transcript quality protocol mismatch")
        if report.get("transcript_content_hash") != source["content"]["raw"]["content_hash"]:
            raise ValueError("quality report raw transcript hash mismatch")
        if report.get("readable_content_hash") != source["content"]["readable"]["content_hash"]:
            raise ValueError("quality report readable transcript hash mismatch")
        return report, entry
    raise ValueError("stable transcript quality report is missing")


def validate_quality(source: dict, report: dict) -> list[str]:
    if source.get("quality", {}).get("capture_status") != "complete":
        raise ValueError("source capture status is not complete")
    if source.get("quality", {}).get("transcript_quality") != "readable":
        raise ValueError("source transcript is not readable")
    if report.get("ready_for_sorting") is not True or report.get("quality_status") != "ready_for_整理":
        raise ValueError("transcript quality gate is not ready for sorting")
    structural = report.get("transcript_structural_qa", {})
    content = report.get("transcript_content_quality", {})
    if structural.get("status") != "pass":
        raise ValueError("transcript structural QA did not pass")
    if content.get("status") not in ACCEPTABLE_CONTENT_QUALITY:
        raise ValueError("transcript content quality is not usable")
    if report.get("missing_ranges") and content.get("status") != "usable_with_warnings":
        raise ValueError("unexplained transcript missing ranges")
    warnings = list(structural.get("warnings", [])) + list(content.get("warnings", []))
    meta = source.get("source", {})
    for key in ("title", "author"):
        if str(meta.get(key, "")).strip().lower() in {"", "unknown", "none", "null", "unavailable"}:
            warnings.append(f"metadata_incomplete:{key}")
    return warnings


def restore(path: Path, existed: bool, value: bytes) -> None:
    if existed:
        atomic_write(path, value)
    elif path.exists():
        path.unlink()
        fsync_directory(path.parent)


def reconcile(args: argparse.Namespace) -> dict:
    project_root = Path(args.project_root).resolve()
    asset_root = Path(args.asset_root).resolve()
    material_dir = Path(args.material_dir).resolve()
    inbox = Path(args.inbox).resolve()
    requested_output = Path(args.output).resolve()
    receipt_path = Path(args.receipt_output).resolve()
    validation_path = Path(args.validation_output).resolve()
    revision_id = args.revision_id.strip()

    if args.scope == "production":
        if inbox != production_inbox():
            raise ValueError("production reconciliation requires canonical 00 inbox")
        if asset_root not in material_dir.parents or material_dir.parent.name != "materials":
            raise ValueError("material directory is outside the managed asset library")
        governance_root = (asset_root / "governance" / "source-readiness-reconciliation").resolve()
        if governance_root not in receipt_path.parents or governance_root not in validation_path.parents:
            raise ValueError("production receipt and validation must stay in source readiness governance")
    elif not str(inbox).startswith(("/tmp/", "/private/tmp/")):
        raise ValueError("test inbox must be under /tmp")
    if requested_output.parent != inbox or requested_output.suffix.lower() != ".md":
        raise ValueError("inbox projection target is invalid")

    revision_dir = material_dir / "revisions" / revision_id
    source_path = revision_dir / "source-material-v3.json"
    manifest_path = revision_dir / "reference-manifest.json"
    if not revision_dir.is_dir() or revision_dir.is_symlink():
        raise ValueError("selected revision is not a committed revision directory")

    foundation = load_module(
        "foundation_stability_source_readiness",
        project_root / "knowledge-foundation-stability" / "foundation_stability.py",
    )
    completion = load_module(
        "capture_completion_source_readiness",
        project_root / "source-material-generator" / "capture_inbox_completion.py",
    )
    source = load_json(source_path)
    manifest = load_json(manifest_path)
    foundation.validate_source_material(source)
    checked = foundation.validate_manifest(manifest, asset_root, True, args.scope == "test")
    foundation.validate_source_against_manifest(source, manifest, checked)
    if source.get("revision_id") != revision_id or manifest.get("revision_id") != revision_id:
        raise ValueError("selected revision identity mismatch")
    if material_dir.name not in {str(source.get("source", {}).get("source_id", "")), f"douyin-{source.get('source', {}).get('source_id', '')}"}:
        # Material directory names are provider-facing and may include a prefix; the
        # stable material_id remains authoritative.  Reject only an unrelated prefix.
        if str(source.get("source", {}).get("source_id", "")) not in material_dir.name:
            raise ValueError("material directory/source identity mismatch")
    quality, quality_entry = resolve_quality(source, manifest, asset_root)
    warnings = validate_quality(source, quality)
    rendered, completion_state, missing = completion.render_projection(source, manifest, asset_root)
    if completion_state != "capture_completed" or any(item.startswith("Transcript") for item in missing):
        raise ValueError("validated revision is not capture_completed")

    matches = completion.find_existing(inbox, source["material_id"])
    if len(matches) > 1:
        raise ValueError("multiple inbox projections share the material_id")
    target = matches[0] if matches else requested_output
    desired_projection = rendered.encode("utf-8")
    current_path = material_dir / "CURRENT_REVISION"
    old_current_exists = current_path.exists()
    old_current = current_path.read_bytes() if old_current_exists else b""
    old_projection_exists = target.exists()
    old_projection = target.read_bytes() if old_projection_exists else b""
    previous_revision_id = old_current.decode("utf-8", errors="replace").strip()
    previous_projection_revision = frontmatter_value(target, "revision_id") if old_projection_exists else ""

    identity = {
        "material_id": source["material_id"],
        "revision_id": revision_id,
        "projection_path": str(target),
        "operation": "source_readiness_reconciliation",
    }
    idempotency_key = "source_readiness_sha256_" + digest(canonical_json(identity))
    receipt_id = "source_readiness_receipt_sha256_" + digest(canonical_json({"idempotency_key": idempotency_key}))
    if receipt_path.exists():
        existing = load_json(receipt_path)
        if existing.get("receipt_id") != receipt_id or existing.get("idempotency_key") != idempotency_key:
            raise ValueError("reconciliation receipt identity conflict")
        if current_path.read_text(encoding="utf-8").strip() != revision_id or target.read_bytes() != desired_projection:
            raise ValueError("receipt exists but canonical state has drifted")
        return {
            "protocol": "source-readiness-reconciliation-result-v1",
            "status": "already_reconciled",
            "material_id": source["material_id"],
            "revision_id": revision_id,
            "receipt_id": receipt_id,
            "receipt": str(receipt_path),
            "validation": str(validation_path),
            "inbox_projection": str(target),
            "asr_rerun": False,
        }

    snapshot_dir = asset_root / "rollback" / "source-readiness-reconciliation" / receipt_id
    if old_current_exists:
        atomic_write(snapshot_dir / "CURRENT_REVISION.before", old_current)
    if old_projection_exists:
        atomic_write(snapshot_dir / "inbox-projection.before.md", old_projection)
    snapshot = {
        "protocol": "source-readiness-snapshot-v1",
        "material_id": source["material_id"],
        "target_revision_id": revision_id,
        "current_existed": old_current_exists,
        "projection_existed": old_projection_exists,
        "current_sha256": "sha256:" + digest(old_current) if old_current_exists else None,
        "projection_sha256": "sha256:" + digest(old_projection) if old_projection_exists else None,
        "current_path": str(current_path),
        "projection_path": str(target),
    }
    atomic_write(snapshot_dir / "snapshot.json", canonical_json(snapshot))

    validation = {
        "protocol": "source-readiness-validation-v1",
        "schema_version": "1.0.0",
        "status": "passed",
        "material_id": source["material_id"],
        "revision_id": revision_id,
        "manifest_status": "valid",
        "validated_at": args.created_at,
        "checks": {
            "capture_completion_status": completion_state,
            "transcript_structural_qa": quality["transcript_structural_qa"]["status"],
            "transcript_content_quality": quality["transcript_content_quality"]["status"],
            "quality_report_reference": quality_entry["reference"],
            "readable_content_hash": source["content"]["readable"]["content_hash"],
            "missing_ranges": quality.get("missing_ranges", []),
            "metadata_warnings": warnings,
        },
    }
    receipt = {
        "protocol": "source-readiness-reconciliation-v1",
        "schema_version": "1.0.0",
        "receipt_id": receipt_id,
        "receipt_type": "source_readiness_reconciliation",
        "idempotency_key": idempotency_key,
        "material_id": source["material_id"],
        "previous_revision_id": previous_revision_id,
        "previous_projection_revision_id": previous_projection_revision,
        "revision_id": revision_id,
        "observed_facts": {
            "manifest_valid": True,
            "quality_report_reference": quality_entry["reference"],
            "quality_status": quality["quality_status"],
            "content_quality": quality["transcript_content_quality"]["status"],
            "structural_qa": quality["transcript_structural_qa"]["status"],
            "ready_for_sorting": quality["ready_for_sorting"],
        },
        "applied_facts": {
            "current_revision": revision_id,
            "capture_completion_status": completion_state,
            "workflow_state": "pending_review",
            "inbox_projection": str(target),
        },
        "created_at": args.created_at,
        "operator": args.operator,
        "snapshot": str(snapshot_dir / "snapshot.json"),
        "validation_result": "passed",
        "revision_content_modified": False,
        "asr_rerun": False,
    }

    lock = material_dir / ".source-readiness-reconciliation.lock"
    try:
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise ValueError("source readiness reconciliation already active") from error
    try:
        os.write(descriptor, (idempotency_key + "\n").encode("utf-8"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        atomic_write(target, desired_projection)
        atomic_write(current_path, (revision_id + "\n").encode("utf-8"))
        atomic_write(validation_path, canonical_json(validation))
        atomic_write(receipt_path, canonical_json(receipt))
        if current_path.read_text(encoding="utf-8").strip() != revision_id:
            raise ValueError("post-apply current revision validation failed")
        if target.read_bytes() != desired_projection:
            raise ValueError("post-apply inbox projection validation failed")
    except Exception:
        restore(current_path, old_current_exists, old_current)
        restore(target, old_projection_exists, old_projection)
        for artifact in (receipt_path, validation_path):
            if artifact.exists():
                artifact.unlink()
                fsync_directory(artifact.parent)
        raise
    finally:
        if lock.exists():
            lock.unlink()
            fsync_directory(lock.parent)

    return {
        "protocol": "source-readiness-reconciliation-result-v1",
        "status": "reconciled",
        "material_id": source["material_id"],
        "previous_revision_id": previous_revision_id,
        "revision_id": revision_id,
        "receipt_id": receipt_id,
        "receipt": str(receipt_path),
        "validation": str(validation_path),
        "snapshot": str(snapshot_dir),
        "inbox_projection": str(target),
        "projection_sha256": "sha256:" + digest(desired_projection),
        "asr_rerun": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--asset-root", required=True)
    parser.add_argument("--material-dir", required=True)
    parser.add_argument("--revision-id", required=True)
    parser.add_argument("--inbox", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--receipt-output", required=True)
    parser.add_argument("--validation-output", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--operator", default="codex")
    parser.add_argument("--scope", choices=("production", "test"), default="production")
    args = parser.parse_args()
    selected_source = Path(args.material_dir) / "revisions" / args.revision_id / "source-material-v3.json"
    try:
        selected_identity = load_json(selected_source)
        source_refs = [f"guanlan://material/{selected_identity['material_id']}/revision/{selected_identity['revision_id']}"]
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        source_refs = []
    operation = OperationRecorder(Path(args.asset_root) / "operations", "source_reconciliation", input_refs=source_refs)
    try:
        result = reconcile(args)
        canonical_ref = f"guanlan://material/{result['material_id']}/revision/{result['revision_id']}"
        receipt_ref = f"guanlan://receipt/{result['receipt_id']}"
        warning = operation.finish("completed", output_refs=[canonical_ref], receipt_refs=[receipt_ref],
                                   change_refs=[canonical_ref] if result["status"] == "reconciled" else [])
        result["operation_id"] = operation.operation_id
        if warning: result["operation_index_warning"] = warning
        atomic_write(Path(args.result), canonical_json(result))
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        operation.finish("failed", failure_class="source_reconciliation_failed", failure_detail=str(error))
        raise SystemExit(f"ERROR: {error}") from error


if __name__ == "__main__":
    raise SystemExit(main())
