#!/usr/bin/env python3
"""Build isolated v0.5-C validation fixtures under the requested test directory."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "knowledge-foundation-stability"))
import foundation_stability as foundation  # noqa: E402


def write_json(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def add_asset(asset_root: Path, role: str, name: str, data: bytes) -> dict:
    content_hash = foundation.sha256_bytes(data)
    asset_id = foundation.asset_id_from_hash(content_hash)
    digest = content_hash.split(":", 1)[1]
    relative = Path("objects") / "sha256" / digest[:2] / digest
    target = asset_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    kind = "report" if role == "validation_report" else "asset"
    return {
        "reference": f"guanlan://{kind}/{asset_id}",
        "asset_id": asset_id,
        "role": role,
        "storage_relative_path": relative.as_posix(),
        "content_hash": content_hash,
        "media_type": "text/markdown" if name.endswith(".md") else "text/plain",
        "size_bytes": len(data),
    }


def main() -> None:
    output = Path(sys.argv[1]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    asset_root = output / "asset-root"

    raw = add_asset(
        asset_root,
        "raw_transcript",
        "raw.txt",
        "00:00:00 这是观澜 Source Material v3 验证文本。\n".encode("utf-8"),
    )
    readable = add_asset(
        asset_root,
        "readable_transcript",
        "readable.md",
        "# Transcript\n\n这是观澜 Source Material v3 验证文本。\n".encode("utf-8"),
    )
    report = add_asset(
        asset_root,
        "validation_report",
        "report.md",
        "# Validation Report\n\nfixture only\n".encode("utf-8"),
    )

    key = foundation.source_key(
        "youtube",
        "ABCdef12345",
        "https://www.youtube.com/watch?v=ABCdef12345",
    )
    material_id = foundation.material_id_from_source_key(key)
    record = {
        "protocol": "source-material-v3",
        "schema_version": "3.0.0",
        "material_id": material_id,
        "revision_id": "revision_sha256_" + "0" * 64,
        "source": {
            "platform": "youtube",
            "source_id": "ABCdef12345",
            "source_url": "https://www.youtube.com/watch?v=ABCdef12345",
            "title": "观澜 v0.5-C 验证素材",
            "author": "fixture",
            "published_at": "",
            "captured_at": "2026-07-31T00:00:00Z",
        },
        "content": {
            "raw": {
                "storage": "reference",
                "reference": raw["reference"],
                "content_hash": raw["content_hash"],
                "media_type": raw["media_type"],
            },
            "readable": {
                "storage": "reference",
                "reference": readable["reference"],
                "content_hash": readable["content_hash"],
                "media_type": readable["media_type"],
                "operations": ["punctuation_restored", "paragraphs_normalized"],
            },
        },
        "evidence": [
            {
                "evidence_id": "evidence-001",
                "kind": "transcript_segment",
                "reference": raw["reference"],
                "content_hash": raw["content_hash"],
                "start_time": 0,
                "end_time": 8,
                "uncertainty": "",
            }
        ],
        "quality": {
            "capture_status": "complete",
            "content_fidelity": "full",
            "transcript_quality": "readable",
            "review_required": True,
            "uncertainties": [],
        },
        "lifecycle": {
            "status": "reviewed",
            "review_status": "convert_approved",
            "created_at": "2026-07-31T00:00:00Z",
            "updated_at": "2026-07-31T00:00:00Z",
            "processing_history": [
                {
                    "processor": "fixture",
                    "version": "1",
                    "report_reference": report["reference"],
                }
            ],
        },
        "asset_manifest_reference": "",
        "understanding_sidecar_reference": "",
    }
    record["revision_id"] = foundation.revision_id(record)
    record["asset_manifest_reference"] = (
        f"guanlan://manifest/{material_id}/{record['revision_id']}"
    )

    provider = "fixture"
    model = "none"
    prompt_version = "fixture-v1"
    evidence_set_hash = foundation.sha256_bytes(
        foundation.canonical_json([raw["content_hash"]])
    )
    sidecar_digest = hashlib.sha256(
        "|".join(
            [
                material_id,
                record["revision_id"],
                provider,
                model,
                prompt_version,
                evidence_set_hash,
            ]
        ).encode("utf-8")
    ).hexdigest()
    sidecar_id = "sidecar_sha256_" + sidecar_digest
    record["understanding_sidecar_reference"] = (
        f"guanlan://sidecar/{sidecar_id}"
    )

    manifest = {
        "protocol": "reference-manifest-v1",
        "schema_version": "1.0.0",
        "material_id": material_id,
        "revision_id": record["revision_id"],
        "entries": [raw, readable, report],
    }
    sidecar = {
        "protocol": "understanding-sidecar-v1",
        "schema_version": "1.0.0",
        "sidecar_id": sidecar_id,
        "material_id": material_id,
        "revision_id": record["revision_id"],
        "status": "validated",
        "topic_candidate": "验证主题",
        "claim_candidates": [],
        "argument_structure_candidate": [],
        "evidence_bindings": [],
        "confidence": {},
        "uncertainties": [],
        "provider": {
            "name": provider,
            "model": model,
            "prompt_version": prompt_version,
        },
        "created_at": "2026-07-31T00:00:00Z",
    }
    asset_draft = {
        "protocol": "knowledge-asset-draft-v1",
        "asset": {
            "asset_id": "asset-draft-v05c",
            "type": "learning_note",
            "status": "draft",
        },
        "source": {
            "material_id": material_id,
            "task_id": "fixture-task",
            "source_reference": record["source"]["source_url"],
        },
        "content": {
            "title": record["source"]["title"],
            "draft_content": "",
            "key_points": [],
            "references": [record["asset_manifest_reference"]],
        },
        "generation": {
            "method": "fixture",
            "created_at": "2026-07-31T00:00:00Z",
            "model_used": "none",
        },
        "review": {"need_confirmation": True, "confirmed": False},
    }
    plan = {
        "protocol": "knowledge-generation-v1",
        "input": {
            "asset_draft_id": asset_draft["asset"]["asset_id"],
            "material_id": material_id,
            "source_reference": record["source"]["source_url"],
        },
        "generation": {
            "asset_type": "learning_note",
            "template": "learning_note",
            "requirements": [],
        },
        "output": {"draft_reference": "", "need_confirmation": True},
    }

    pending = copy.deepcopy(record)
    pending["lifecycle"]["review_status"] = "pending"
    bad_revision = copy.deepcopy(record)
    bad_revision["revision_id"] = "revision_sha256_" + "f" * 64
    temp_reference = copy.deepcopy(record)
    temp_reference["content"]["raw"]["reference"] = "/tmp/raw.txt"
    forbidden_analysis = copy.deepcopy(record)
    forbidden_analysis["analysis"] = {"summary": "Source Material 不允许包含分析"}
    bad_sidecar = copy.deepcopy(sidecar)
    bad_sidecar["revision_id"] = "revision_sha256_" + "e" * 64

    write_json(output / "source-material.json", record)
    write_json(output / "manifest.json", manifest)
    write_json(output / "sidecar.json", sidecar)
    write_json(output / "draft.json", asset_draft)
    write_json(output / "plan.json", plan)
    write_json(output / "pending-source-material.json", pending)
    write_json(output / "bad-revision-source-material.json", bad_revision)
    write_json(output / "temp-reference-source-material.json", temp_reference)
    write_json(output / "forbidden-analysis-source-material.json", forbidden_analysis)
    write_json(output / "bad-sidecar.json", bad_sidecar)


if __name__ == "__main__":
    main()
