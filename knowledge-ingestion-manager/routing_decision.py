#!/usr/bin/env python3
"""Create a truthful routing-decision-v2 without executing knowledge ingestion."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


def sha256_bytes(value: bytes):
    return hashlib.sha256(value).hexdigest()


def object_path(root: Path, digest: str):
    return root / "objects" / "sha256" / digest[:2] / digest


def commit(root: Path, value: bytes):
    digest = sha256_bytes(value)
    path = object_path(root, digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
        temporary.write_bytes(value)
        os.replace(temporary, path)
    elif sha256_bytes(path.read_bytes()) != digest:
        raise ValueError("asset object hash mismatch")
    return digest, path


def atomic_json(path: Path, value):
    data = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def manifest_entry(digest: str, role: str, media_type: str, size: int, kind: str):
    return {
        "asset_id": "asset_sha256_" + digest,
        "content_hash": "sha256:" + digest,
        "media_type": media_type,
        "reference": f"guanlan://{kind}/asset_sha256_{digest}",
        "role": role,
        "size_bytes": size,
        "storage_relative_path": f"objects/sha256/{digest[:2]}/{digest}",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-material", required=True)
    parser.add_argument("--learning-draft", required=True)
    parser.add_argument("--quality-review", required=True)
    parser.add_argument("--asset-root", required=True)
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--manifest")
    args = parser.parse_args()
    source = json.loads(Path(args.source_material).read_text(encoding="utf-8"))
    draft_bytes = Path(args.learning_draft).read_bytes()
    quality_bytes = Path(args.quality_review).read_bytes()
    root = Path(args.asset_root).resolve()
    draft_digest, _ = commit(root, draft_bytes)
    quality_digest, _ = commit(root, quality_bytes)
    material_id, revision_id = source["material_id"], source["revision_id"]
    result = {
        "protocol": "routing-decision-v2",
        "schema_version": "2.0.0",
        "source": {
            "asset_class": "source",
            "material_id": material_id,
            "revision_id": revision_id,
            "source_reference": f"guanlan://material/{material_id}/revision/{revision_id}",
        },
        "recommendation": {
            "asset_class": "knowledge",
            "asset_subtype": "learning_note",
            "candidate_asset_id": "asset_draft_sha256_" + draft_digest,
            "candidate_reference": "guanlan://asset/asset_sha256_" + draft_digest,
            "quality_reference": "guanlan://report/asset_sha256_" + quality_digest,
            "target_path": "20 学习笔记/",
            "reason": [
                "完整Source Asset和时间证据可追溯",
                "Draft已区分作者内容、AI理解和待用户确认判断",
                "质量评估建议进入人工确认候选队列",
            ],
            "confidence": "medium",
        },
        "execution": {
            "capability": "supported",
            "decision_status": "suggested",
            "confirmation_status": "waiting_user_confirmation",
            "executed": False,
        },
        "method_candidate_assessment": {
            "exists": True,
            "title": "视频转述材料的证据分层与原典核查流程",
            "capability": "suggestion_only",
            "target_path": "40 方法库/",
            "executed": False,
            "reason": "Draft包含证据分层和原典核查候选，但尚无独立方法结构与真实复用验证。",
        },
        "not_recommended": [
            {"asset_subtype": "intelligence_brief", "reason": "本素材不是多来源时效情报"},
            {"asset_subtype": "creation_asset", "reason": "本轮没有明确受众和交付目标"},
        ],
        "capability_matrix": {
            "source_asset": "supported", "learning_note": "supported",
            "intelligence_brief": "suggestion_only", "method_asset": "suggestion_only",
            "creation_asset": "suggestion_only",
        },
        "created_at": args.created_at,
    }
    output = Path(args.output)
    atomic_json(output, result)
    decision_bytes = output.read_bytes()
    decision_digest, _ = commit(root, decision_bytes)
    if args.manifest:
        manifest_path = Path(args.manifest)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("material_id") != material_id or manifest.get("revision_id") != revision_id:
            raise ValueError("manifest identity mismatch")
        additions = [
            manifest_entry(draft_digest, "learning_note_draft", "text/markdown", len(draft_bytes), "asset"),
            manifest_entry(quality_digest, "learning_note_quality_review", "text/markdown", len(quality_bytes), "report"),
            manifest_entry(decision_digest, "routing_decision_v2", "application/json", len(decision_bytes), "report"),
        ]
        entries = manifest.setdefault("entries", [])
        known = {item.get("reference") for item in entries}
        entries.extend(item for item in additions if item["reference"] not in known)
        atomic_json(manifest_path, manifest)


if __name__ == "__main__":
    main()
