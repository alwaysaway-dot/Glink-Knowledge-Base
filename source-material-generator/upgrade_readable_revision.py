#!/usr/bin/env python3
"""Create a new Source Material v3 revision with a Readable-first transcript."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import mimetypes
import shutil
from copy import deepcopy
from pathlib import Path


KEEP_OLD_ROLES = {"raw_transcript", "timestamped_transcript", "capture_metadata", "validation_report"}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def asset_id(digest: str) -> str:
    return "asset_sha256_" + digest


def asset_reference(digest: str) -> str:
    return "guanlan://asset/" + asset_id(digest)


def object_relative_path(digest: str) -> str:
    return f"objects/sha256/{digest[:2]}/{digest}"


def atomic_json(value, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def commit_bytes(root: Path, value: bytes):
    digest = sha256_bytes(value)
    destination = root / object_relative_path(digest)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if sha256_file(destination) != digest:
            raise ValueError(f"existing object hash mismatch: {destination}")
    else:
        temporary = destination.with_name(destination.name + ".tmp")
        temporary.write_bytes(value)
        if sha256_file(temporary) != digest:
            raise ValueError("staged object hash mismatch")
        temporary.replace(destination)
    return digest, destination


def commit_file(root: Path, source: Path):
    digest = sha256_file(source)
    destination = root / object_relative_path(digest)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if sha256_file(destination) != digest:
            raise ValueError(f"existing object hash mismatch: {destination}")
    else:
        temporary = destination.with_name(destination.name + ".tmp")
        shutil.copyfile(source, temporary)
        if sha256_file(temporary) != digest:
            raise ValueError("staged object hash mismatch")
        temporary.replace(destination)
    return digest, destination


def manifest_entry(digest, role, media_type, size):
    return {
        "asset_id": asset_id(digest),
        "content_hash": "sha256:" + digest,
        "media_type": media_type,
        "reference": asset_reference(digest),
        "role": role,
        "size_bytes": size,
        "storage_relative_path": object_relative_path(digest),
    }


def sanitize_provider(provider: dict, audio_digest: str):
    normalized = deepcopy(provider)
    normalized["source_reference"] = asset_reference(audio_digest)
    metadata = normalized.get("provider_metadata", {})
    for field in ("python_executable", "model_path"):
        metadata.pop(field, None)
    normalized["provider_metadata"] = metadata
    for chunk in normalized.get("chunking", {}).get("chunks", []):
        chunk.pop("source_file", None)
    warnings = list(normalized.get("warnings", []))
    if any(segment.get("confidence") is None for segment in normalized.get("segments", [])):
        warnings.append("provider confidence unavailable")
    normalized["warnings"] = list(dict.fromkeys(warnings))
    return normalized


def load_foundation_module(project_root: Path):
    path = project_root / "knowledge-foundation-stability" / "foundation_stability.py"
    spec = importlib.util.spec_from_file_location("foundation_stability", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-material", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--provider-transcript", required=True)
    parser.add_argument("--source-audio", required=True)
    parser.add_argument("--readable-json", required=True)
    parser.add_argument("--readable-md", required=True)
    parser.add_argument("--language-decision", required=True)
    parser.add_argument("--asset-root", required=True)
    parser.add_argument("--material-dir", required=True)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--output-summary", required=True)
    args = parser.parse_args()

    source_path = Path(args.source_material).resolve()
    manifest_path = Path(args.manifest).resolve()
    provider_path = Path(args.provider_transcript).resolve()
    audio_path = Path(args.source_audio).resolve()
    readable_json_path = Path(args.readable_json).resolve()
    readable_md_path = Path(args.readable_md).resolve()
    language_path = Path(args.language_decision).resolve()
    asset_root = Path(args.asset_root).resolve()
    material_dir = Path(args.material_dir).resolve()
    project_root = Path(args.project_root).resolve()
    if asset_root not in material_dir.parents:
        raise SystemExit("material directory must be inside asset root")

    old_source = json.loads(source_path.read_text(encoding="utf-8"))
    old_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    provider = json.loads(provider_path.read_text(encoding="utf-8"))
    readable = json.loads(readable_json_path.read_text(encoding="utf-8"))
    language = json.loads(language_path.read_text(encoding="utf-8"))
    if old_source.get("protocol") != "source-material-v3":
        raise SystemExit("source material v3 is required")
    if provider.get("status") != "completed" or provider.get("language") not in {"zh", "zh-CN"}:
        raise SystemExit("completed Chinese provider transcript is required")
    if language.get("selected_candidate_id") != "chinese-asr":
        raise SystemExit("language policy did not select Chinese ASR")
    provider_end_time = (provider.get("timestamp") or {}).get("end_time")
    if provider_end_time is None:
        provider_end_time = max((item.get("end_time", 0) for item in provider.get("segments", [])), default=0)
    if not provider_end_time:
        raise SystemExit("provider transcript requires a positive end time")

    audio_digest, audio_object = commit_file(asset_root, audio_path)
    normalized_provider = sanitize_provider(provider, audio_digest)
    provider_bytes = (json.dumps(normalized_provider, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    provider_digest, provider_object = commit_bytes(asset_root, provider_bytes)
    evidence_record = {
        "protocol": "transcript-protocol-v1",
        "schema_version": "1.1.0",
        "transcript_layer": "evidence",
        "task_id": readable["task_id"],
        "source": deepcopy(readable["source"]),
        "transcript_type": "asr",
        "provider": provider["provider"],
        "raw_reference": asset_reference(provider_digest),
        "segments": deepcopy(readable["segments"]),
        "operations": deepcopy(readable["operations"]),
        "warnings": deepcopy(provider.get("warnings", [])),
    }
    evidence_bytes = (json.dumps(evidence_record, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    evidence_digest, evidence_object = commit_bytes(asset_root, evidence_bytes)
    readable_md_digest, readable_md_object = commit_file(asset_root, readable_md_path)

    source = deepcopy(old_source)
    source["content"]["raw"] = {
        "storage": "reference",
        "reference": asset_reference(provider_digest),
        "content_hash": "sha256:" + provider_digest,
        "media_type": "application/json",
    }
    source["content"]["readable"] = {
        "storage": "reference",
        "reference": asset_reference(readable_md_digest),
        "content_hash": "sha256:" + readable_md_digest,
        "media_type": "text/markdown",
        "operations": readable["operations"],
    }
    evidence = deepcopy(old_source.get("evidence", []))
    evidence.extend(
        [
            {
                "evidence_id": "evidence-transcript-zh",
                "kind": "evidence_transcript",
                "reference": asset_reference(evidence_digest),
                "content_hash": "sha256:" + evidence_digest,
                "start_time": 0,
                "end_time": provider_end_time,
                "uncertainty": "FunASR does not provide calibrated segment confidence.",
            },
            {
                "evidence_id": "evidence-source-audio",
                "kind": "source_audio",
                "reference": asset_reference(audio_digest),
                "content_hash": "sha256:" + audio_digest,
                "start_time": 0,
                "end_time": provider_end_time,
                "uncertainty": "",
            },
        ]
    )
    source["evidence"] = evidence
    source["quality"] = {
        "capture_status": "complete",
        "content_fidelity": "full",
        "transcript_quality": "readable",
        "review_required": True,
        "uncertainties": [
            "FunASR does not provide calibrated segment confidence.",
            "The platform zh-CN subtitle label contains predominantly English text and is retained only as auxiliary evidence.",
            "Professional terms and numeric claims still require human review against audio and source context.",
        ],
    }
    # A new Readable revision has not inherited the old revision's simulated review.
    source["lifecycle"]["status"] = "captured"
    source["lifecycle"]["review_status"] = "pending"
    source["lifecycle"]["updated_at"] = args.created_at
    source["lifecycle"]["processing_history"].append(
        {
            "processor": "transcript-intelligence",
            "version": "readable-transcript-v1.1.0",
            "time": args.created_at,
            "language_decision_reason": language["language_decision_reason"],
        }
    )
    source["understanding_sidecar_reference"] = ""
    foundation = load_foundation_module(project_root)
    source["revision_id"] = foundation.revision_id(source)
    source["asset_manifest_reference"] = f"guanlan://manifest/{source['material_id']}/{source['revision_id']}"

    readable["material_id"] = source["material_id"]
    readable["revision_id"] = source["revision_id"]
    readable["raw_reference"] = asset_reference(provider_digest)
    readable["evidence_reference"] = asset_reference(evidence_digest)
    readable["readable_reference"] = asset_reference(readable_md_digest)
    readable_bytes = (json.dumps(readable, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    readable_json_digest, readable_json_object = commit_bytes(asset_root, readable_bytes)

    entries = []
    for entry in old_manifest.get("entries", []):
        if entry.get("role") not in KEEP_OLD_ROLES:
            continue
        copied = deepcopy(entry)
        if copied.get("role") == "raw_transcript":
            copied["role"] = "auxiliary_subtitle_en"
        elif copied.get("role") == "timestamped_transcript":
            copied["role"] = "auxiliary_timestamped_transcript_en"
        entries.append(copied)
    entries.extend(
        [
            manifest_entry(audio_digest, "source_audio", "audio/webm", audio_path.stat().st_size),
            manifest_entry(provider_digest, "raw_transcript", "application/json", len(provider_bytes)),
            manifest_entry(evidence_digest, "evidence_transcript", "application/json", len(evidence_bytes)),
            manifest_entry(readable_md_digest, "readable_transcript", "text/markdown", readable_md_path.stat().st_size),
            manifest_entry(readable_json_digest, "readable_transcript_record", "application/json", len(readable_bytes)),
        ]
    )
    seen = set()
    unique_entries = []
    for entry in entries:
        key = entry["reference"]
        if key in seen:
            continue
        seen.add(key)
        unique_entries.append(entry)
    manifest = {
        "protocol": "reference-manifest-v1",
        "schema_version": "1.0.0",
        "material_id": source["material_id"],
        "revision_id": source["revision_id"],
        "entries": unique_entries,
    }

    revision_dir = material_dir / "revisions" / source["revision_id"]
    if revision_dir.exists():
        raise SystemExit(f"revision already exists: {revision_dir}")
    revision_dir.mkdir(parents=True)
    atomic_json(source, revision_dir / "source-material-v3.json")
    atomic_json(manifest, revision_dir / "reference-manifest.json")
    atomic_json(readable, revision_dir / "readable-transcript-v1.json")
    shutil.copyfile(readable_md_path, revision_dir / "readable-transcript-v1.md")
    shutil.copyfile(language_path, revision_dir / "language-decision.json")
    summary = {
        "protocol": "readable-revision-upgrade-v1",
        "material_id": source["material_id"],
        "previous_revision_id": old_source["revision_id"],
        "revision_id": source["revision_id"],
        "revision_directory": str(revision_dir),
        "objects": {
            "source_audio": str(audio_object),
            "raw_transcript": str(provider_object),
            "evidence_transcript": str(evidence_object),
            "readable_transcript": str(readable_md_object),
            "readable_record": str(readable_json_object),
        },
        "history_overwritten": False,
    }
    atomic_json(summary, Path(args.output_summary))


if __name__ == "__main__":
    main()
