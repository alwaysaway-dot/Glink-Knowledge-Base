#!/usr/bin/env python3
"""Create an immutable Source Material v3 revision from provider transcript evidence."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import shutil
import socket
import time
import uuid
from pathlib import Path


DROP_ROLES = {
    "raw_transcript", "evidence_transcript", "readable_transcript",
    "readable_transcript_record", "readable_availability_note", "transcript_quality_report",
}
DROP_EVIDENCE_KINDS = {"transcript", "raw_transcript", "evidence_transcript"}


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def compact_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


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


def atomic_json(path: Path, value: object) -> None:
    atomic_write(path, canonical_json(value))


def load_foundation(project_root: Path):
    target = project_root / "knowledge-foundation-stability" / "foundation_stability.py"
    spec = importlib.util.spec_from_file_location("foundation_stability_transcript_revision", target)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def object_relative(value_digest: str) -> str:
    return f"objects/sha256/{value_digest[:2]}/{value_digest}"


def asset_reference(value_digest: str) -> str:
    return f"guanlan://asset/asset_sha256_{value_digest}"


def report_reference(value_digest: str) -> str:
    return f"guanlan://report/asset_sha256_{value_digest}"


def commit_object(asset_root: Path, value: bytes) -> tuple[str, Path]:
    value_digest = digest(value)
    target = asset_root / object_relative(value_digest)
    if target.exists() and digest(target.read_bytes()) != value_digest:
        raise ValueError(f"content-addressed object mismatch: {target}")
    if not target.exists():
        atomic_write(target, value)
    return value_digest, target


def manifest_entry(value_digest: str, role: str, media_type: str, size: int) -> dict:
    return {
        "asset_id": "asset_sha256_" + value_digest,
        "content_hash": "sha256:" + value_digest,
        "media_type": media_type,
        "reference": asset_reference(value_digest),
        "role": role,
        "size_bytes": size,
        "storage_relative_path": object_relative(value_digest),
    }


def sanitize_provider(value: dict, media_reference: str) -> dict:
    if value.get("protocol") != "transcript-provider-v1" or value.get("status") not in {"completed", "partial"}:
        raise ValueError("completed or partial transcript-provider-v1 input is required")
    if not str(value.get("text", "")).strip():
        raise ValueError("provider transcript text is empty")
    segments = []
    for index, item in enumerate(value.get("segments", []), start=1):
        if not isinstance(item, dict) or not str(item.get("text", "")).strip():
            continue
        start = float(item.get("start_time", 0))
        end = float(item.get("end_time", 0))
        if end <= start:
            continue
        segments.append({
            "segment_id": str(item.get("segment_id") or f"transcript-{index:03d}"),
            "start_time": start,
            "end_time": end,
            "start_timestamp": str(item.get("start_timestamp", "")),
            "end_timestamp": str(item.get("end_timestamp", "")),
            "text": " ".join(str(item["text"]).split()),
            "confidence": item.get("confidence"),
        })
    if not segments:
        raise ValueError("provider transcript has no valid timestamped segments")
    provider_meta = value.get("provider_metadata", {})
    stable_meta = {
        key: provider_meta[key]
        for key in (
            "bridge_version", "funasr_version", "model_location",
            "environment_location", "device", "network_access",
        )
        if key in provider_meta
    }
    return {
        "protocol": "transcript-provider-v1",
        "result_type": "TranscriptResult",
        "provider": value.get("provider", "unknown"),
        "model": value.get("model", "unknown"),
        "language": value.get("language", "unknown"),
        "status": value["status"],
        "source_reference": media_reference,
        "text": " ".join(str(value["text"]).split()),
        "timestamp": value.get("timestamp"),
        "segments": segments,
        "timestamps": True,
        "provider_metadata": stable_meta,
        "missing_ranges": copy.deepcopy(value.get("missing_ranges", [])),
        "chunking": {
            key: copy.deepcopy(value.get("chunking", {}).get(key))
            for key in ("strategy", "chunk_seconds", "chunk_count", "segment_timeout_seconds", "max_retries", "chunks")
            if key in value.get("chunking", {})
        },
        "warnings": list(value.get("warnings", [])),
    }


def acquire_lock(lock: Path, revision_id: str) -> tuple[int, str]:
    transaction_id = "capture_revision_tx_" + uuid.uuid4().hex
    metadata = canonical_json({
        "protocol": "capture-revision-lock-v1",
        "revision_id": revision_id,
        "transaction_id": transaction_id,
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
        "created_at_epoch": time.time(),
    })
    try:
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise ValueError(f"concurrent capture revision transaction: {lock}") from error
    os.write(descriptor, metadata)
    os.fsync(descriptor)
    return descriptor, transaction_id


def release_lock(lock: Path, descriptor: int) -> None:
    os.close(descriptor)
    if lock.exists():
        lock.unlink()
        fsync_directory(lock.parent)


def stage_and_commit(
    revisions_dir: Path, revision_id: str, payloads: dict[str, bytes],
    foundation, asset_root: Path, allow_temp_root: bool,
) -> str:
    final = revisions_dir / revision_id
    if final.exists():
        existing_source_path = final / "source-material-v3.json"
        existing_manifest_path = final / "reference-manifest.json"
        if not existing_source_path.is_file() or not existing_manifest_path.is_file():
            raise ValueError("identity_conflict: existing revision is incomplete")
        existing_source = json.loads(existing_source_path.read_text(encoding="utf-8"))
        existing_manifest = json.loads(existing_manifest_path.read_text(encoding="utf-8"))
        expected_source = json.loads(payloads["source-material-v3.json"])
        if foundation.revision_payload(existing_source) != foundation.revision_payload(expected_source):
            raise ValueError("identity_conflict: existing revision content differs")
        checked = foundation.validate_manifest(existing_manifest, asset_root, True, allow_temp_root)
        foundation.validate_source_against_manifest(existing_source, existing_manifest, checked)
        return "already_committed"
    stage = revisions_dir / f".{revision_id}.staging.{uuid.uuid4().hex}"
    stage.mkdir(mode=0o700)
    try:
        for name, value in payloads.items():
            atomic_write(stage / name, value)
        source = json.loads(payloads["source-material-v3.json"])
        manifest = json.loads(payloads["reference-manifest.json"])
        foundation.validate_source_material(source)
        checked = foundation.validate_manifest(manifest, asset_root, True, allow_temp_root)
        foundation.validate_source_against_manifest(source, manifest, checked)
        fsync_directory(stage)
        os.rename(stage, final)
        fsync_directory(revisions_dir)
        return "committed"
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-material", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--provider-result", required=True)
    parser.add_argument("--readable-text", required=True)
    parser.add_argument("--quality-result", required=True)
    parser.add_argument("--asset-root", required=True)
    parser.add_argument("--material-dir", required=True)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--output-summary", required=True)
    parser.add_argument("--scope", choices=("production", "test"), default="production")
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()

    asset_root = Path(args.asset_root).resolve()
    material_dir = Path(args.material_dir).resolve()
    revisions_dir = material_dir / "revisions"
    revisions_dir.mkdir(parents=True, exist_ok=True)
    source = json.loads(Path(args.source_material).read_text(encoding="utf-8"))
    old_manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    provider_input = json.loads(Path(args.provider_result).read_text(encoding="utf-8"))
    readable_bytes = Path(args.readable_text).read_bytes()
    quality_input = json.loads(Path(args.quality_result).read_text(encoding="utf-8"))
    foundation = load_foundation(Path(args.project_root).resolve())
    foundation.validate_source_material(source)
    old_checked = foundation.validate_manifest(old_manifest, asset_root, True, args.scope == "test")
    foundation.validate_source_against_manifest(source, old_manifest, old_checked)

    media_evidence = next((item for item in source["evidence"] if item["kind"] == "source_media"), None)
    if media_evidence is None:
        raise SystemExit("ERROR: source media evidence is required")
    expected_provider_hash = "sha256:" + digest(compact_json(provider_input))
    expected_readable_hash = "sha256:" + digest(readable_bytes)
    if quality_input.get("protocol") != "media-transcript-quality-v1":
        raise ValueError("media-transcript-quality-v1 result is required")
    if quality_input.get("transcript_content_hash") != expected_provider_hash:
        raise ValueError("quality result does not bind the provider transcript input")
    if quality_input.get("readable_content_hash") != expected_readable_hash:
        raise ValueError("quality result does not bind the readable transcript input")
    partial_allowed = args.allow_partial and quality_input.get("quality_status") == "transcript_partial"
    if not quality_input.get("ready_for_sorting") and not partial_allowed:
        raise ValueError(f"transcript is not usable: {quality_input.get('quality_status', 'unknown')}")
    provider = sanitize_provider(provider_input, media_evidence["reference"])
    provider_bytes = canonical_json(provider)
    if not readable_bytes.strip():
        raise ValueError("readable transcript is empty")
    quality_input["provider_input_hash"] = quality_input["transcript_content_hash"]
    quality_input["transcript_content_hash"] = "sha256:" + digest(provider_bytes)
    quality_bytes = canonical_json(quality_input)
    provider_digest, provider_object = commit_object(asset_root, provider_bytes)
    readable_digest, readable_object = commit_object(asset_root, readable_bytes)
    quality_digest, quality_object = commit_object(asset_root, quality_bytes)

    updated = copy.deepcopy(source)
    updated["content"]["raw"] = {
        "storage": "reference",
        "reference": asset_reference(provider_digest),
        "content_hash": "sha256:" + provider_digest,
        "media_type": "application/json",
    }
    updated["content"]["readable"] = {
        "storage": "reference",
        "reference": asset_reference(readable_digest),
        "content_hash": "sha256:" + readable_digest,
        "media_type": "text/plain; charset=utf-8",
        "operations": ["time_ordering", "mechanical_deduplication", "conservative_punctuation", "paragraph_grouping", "no_summary", "no_analysis", "no_semantic_rewrite"],
    }
    updated["evidence"] = [
        item for item in updated["evidence"] if item.get("kind") not in DROP_EVIDENCE_KINDS
    ]
    updated["evidence"].append({
        "evidence_id": "evidence-transcript-001",
        "kind": "transcript",
        "reference": asset_reference(provider_digest),
        "content_hash": "sha256:" + provider_digest,
        "start_time": provider["segments"][0]["start_time"],
        "end_time": provider["segments"][-1]["end_time"],
        "uncertainty": "Provider transcript is unreviewed and may contain recognition errors.",
    })
    retained_uncertainties = [
        item for item in updated["quality"].get("uncertainties", [])
        if "No transcript" not in item and "transcript generation" not in item
    ]
    if quality_input.get("ready_for_sorting"):
        retained_uncertainties.append("FunASR transcript passed deterministic usability checks but remains unreviewed and may contain recognition errors.")
    else:
        retained_uncertainties.append("FunASR transcript is partial; missing ranges remain and it is not ready for sorting.")
        for item in quality_input.get("missing_ranges", []):
            retained_uncertainties.append(
                f"Transcript missing range {item.get('start_time')}–{item.get('end_time')}: {item.get('reason', 'unknown')}"
            )
    updated["quality"].update({
        "capture_status": "complete" if quality_input.get("ready_for_sorting") else "partial",
        "content_fidelity": "full" if quality_input.get("ready_for_sorting") else "partial",
        "transcript_quality": "readable" if quality_input.get("ready_for_sorting") else "partial",
        "review_required": True,
        "uncertainties": list(dict.fromkeys(retained_uncertainties)),
    })
    updated["lifecycle"]["updated_at"] = args.created_at
    updated["lifecycle"]["processing_history"].append({
        "processor": "source-transcript-revision",
        "version": "2.0",
        "time": args.created_at,
        "provider": provider["provider"],
        "model": provider["model"],
        "report_reference": report_reference(quality_digest),
        "quality_status": quality_input["quality_status"],
    })
    updated["revision_id"] = foundation.revision_id(updated)
    updated["asset_manifest_reference"] = (
        f"guanlan://manifest/{updated['material_id']}/{updated['revision_id']}"
    )
    entries = [copy.deepcopy(item) for item in old_manifest["entries"] if item.get("role") not in DROP_ROLES]
    entries.extend([
        manifest_entry(provider_digest, "raw_transcript", "application/json", len(provider_bytes)),
        manifest_entry(readable_digest, "readable_transcript", "text/plain; charset=utf-8", len(readable_bytes)),
        {
            **manifest_entry(quality_digest, "transcript_quality_report", "application/json", len(quality_bytes)),
            "reference": report_reference(quality_digest),
        },
    ])
    manifest = {
        "protocol": "reference-manifest-v1",
        "schema_version": "1.0.0",
        "material_id": updated["material_id"],
        "revision_id": updated["revision_id"],
        "entries": list({item["reference"]: item for item in entries}.values()),
    }
    payloads = {
        "source-material-v3.json": canonical_json(updated),
        "reference-manifest.json": canonical_json(manifest),
    }
    lock_path = revisions_dir / ".capture-revision.lock"
    descriptor, transaction_id = acquire_lock(lock_path, updated["revision_id"])
    try:
        transaction_status = stage_and_commit(
            revisions_dir, updated["revision_id"], payloads, foundation, asset_root, args.scope == "test"
        )
        current_path = material_dir / "CURRENT_REVISION"
        current_value = (updated["revision_id"] + "\n").encode("utf-8")
        if not current_path.exists() or current_path.read_bytes() != current_value:
            atomic_write(current_path, current_value)
    finally:
        release_lock(lock_path, descriptor)

    revision_dir = revisions_dir / updated["revision_id"]
    committed_manifest = json.loads((revision_dir / "reference-manifest.json").read_text(encoding="utf-8"))

    def committed_reference(role: str, fallback: str) -> str:
        return next((item["reference"] for item in committed_manifest["entries"] if item.get("role") == role), fallback)

    summary = {
        "protocol": "source-transcript-revision-result-v1",
        "status": "already_enriched" if transaction_status == "already_committed" else "revision_created",
        "material_id": updated["material_id"],
        "previous_revision_id": source["revision_id"],
        "revision_id": updated["revision_id"],
        "revision_directory": str(revision_dir),
        "source_material": str(revision_dir / "source-material-v3.json"),
        "manifest": str(revision_dir / "reference-manifest.json"),
        "provider_reference": committed_reference("raw_transcript", asset_reference(provider_digest)),
        "readable_reference": committed_reference("readable_transcript", asset_reference(readable_digest)),
        "quality_report_reference": committed_reference("transcript_quality_report", report_reference(quality_digest)),
        "reused_media_reference": media_evidence["reference"],
        "objects": [str(provider_object), str(readable_object), str(quality_object)],
        "transaction": {
            "transaction_id": transaction_id,
            "idempotency_key": f"{updated['material_id']}:{updated['revision_id']}",
            "status": transaction_status,
            "atomic_revision_directory": True,
        },
    }
    atomic_json(Path(args.output_summary), summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        raise SystemExit(f"ERROR: {error}") from error
