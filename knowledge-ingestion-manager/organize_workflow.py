#!/usr/bin/env python3
"""User-level organize orchestration: Source candidate + derivative bundle.

It has no Vault write capability.  It writes only candidate governance records
to an asset-library operation directory and awaits the single `入库` approval.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from publisher_core import atomic_json, canonical, digest, has_temp, load_json, require_stable_references


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from operation_envelope import OperationRecorder
ALLOWED_TYPES = {"learning_note", "intelligence_brief", "method_asset", "creation_asset"}
ALLOWED_STATUS = {"publishable", "candidate", "needs_corroboration", "needs_validation", "blocked", "not_applicable", "generation_failed", "generation_quality_blocked", "generation_metadata_inconsistent"}


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def require_ready_source(source: dict, validation: dict, readable: Path):
    if source.get("protocol") != "source-material-v3":
        raise ValueError("source-material-v3 is required")
    if validation.get("status") != "passed" or validation.get("material_id") != source.get("material_id") or validation.get("revision_id") != source.get("revision_id"):
        raise ValueError("organize_blocked_source_not_ready")
    quality = source.get("quality", {})
    if quality.get("capture_status") != "complete" or quality.get("transcript_quality") in {"failed", "raw", "unusable"}:
        raise ValueError("organize_blocked_source_not_ready")
    if not readable.is_file() or not readable.read_text(encoding="utf-8").strip() or has_temp(source):
        raise ValueError("organize_blocked_source_not_ready")


def candidate_id(source: dict, asset_type: str, content: str) -> str:
    return "candidate_sha256_" + digest(canonical({"material_id": source["material_id"], "revision_id": source["revision_id"], "asset_type": asset_type, "content_hash": "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()}))


def validate_derivative(candidate: dict, source: dict):
    asset_type = candidate.get("asset_type")
    status = candidate.get("status")
    if asset_type not in ALLOWED_TYPES or status not in ALLOWED_STATUS:
        raise ValueError("derivative type or status invalid")
    if candidate.get("source", {}).get("material_id") != source["material_id"] or candidate.get("source", {}).get("revision_id") != source["revision_id"]:
        raise ValueError("derivative source identity mismatch")
    if status == "publishable":
        if not candidate.get("content", {}).get("markdown"):
            raise ValueError("publishable derivative needs content")
        require_stable_references(candidate.get("provenance", {}).get("stable_references", []), "derivative provenance")
    if has_temp(candidate):
        raise ValueError("temporary derivative reference forbidden")


def build_source_candidate(source: dict, readable: Path):
    content_hash = "sha256:" + hashlib.sha256(readable.read_bytes()).hexdigest()
    return {
        "candidate_id": candidate_id(source, "source_asset", readable.read_text(encoding="utf-8")),
        "asset_type": "source_asset", "target": "10 原始资料", "status": "publishable", "quality": "passed",
        "source": {"material_id": source["material_id"], "revision_id": source["revision_id"], "source_reference": f"guanlan://material/{source['material_id']}/revision/{source['revision_id']}"},
        "content_hash": content_hash, "readable_reference": source["content"]["readable"]["reference"],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-material", required=True); parser.add_argument("--source-validation", required=True)
    parser.add_argument("--readable-source", required=True); parser.add_argument("--asset-root", required=True)
    parser.add_argument("--bundle-id"); parser.add_argument("--derivative-signals")
    parser.add_argument("--learning-provider", choices=("codex", "file", "codex-replay", "local"))
    parser.add_argument("--learning-model", default="none"); parser.add_argument("--learning-llm-output")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    operation_index = None
    try:
        source = load_json(Path(args.source_material), "source material")
        source_ref = f"guanlan://material/{source['material_id']}/revision/{source['revision_id']}"
        operation_index = OperationRecorder(Path(args.asset_root) / "operations", "organize", input_refs=[source_ref])
        validation = load_json(Path(args.source_validation), "source validation")
        readable = Path(args.readable_source).resolve(); require_ready_source(source, validation, readable)
        bundle_id = args.bundle_id or "bundle_sha256_" + digest(canonical({"material_id": source["material_id"], "revision_id": source["revision_id"], "created_at": now()}))
        candidate_dir = Path(args.asset_root).resolve() / "operations" / "candidate-bundles" / bundle_id
        candidate_dir.mkdir(parents=True, exist_ok=True)
        derivatives = []
        if args.learning_provider:
            learning_path = candidate_dir / "learning-candidate.json"
            command = [sys.executable, str(ROOT / "knowledge-ingestion-manager" / "learning_candidate_generation.py"),
                       "--source-material", str(Path(args.source_material).resolve()), "--source-validation", str(Path(args.source_validation).resolve()),
                       "--readable-source", str(readable), "--operation-dir", str(candidate_dir / "learning-generation"),
                       "--provider", args.learning_provider, "--model", args.learning_model, "--output", str(learning_path)]
            if args.learning_llm_output:
                command.extend(["--llm-output", str(Path(args.learning_llm_output).resolve())])
            result = subprocess.run(command, text=True, capture_output=True)
            if result.returncode == 0:
                derivatives.append(load_json(learning_path, "learning candidate"))
            else:
                derivatives.append({"protocol": "derivative-candidate-v1", "schema_version": "1.0.0", "candidate_id": candidate_id(source, "learning_note", "generation_failed"), "asset_type": "learning_note", "status": "generation_failed", "source": {"material_id": source["material_id"], "revision_id": source["revision_id"]}, "reason": result.stderr.strip()})
        if args.derivative_signals:
            signals = load_json(Path(args.derivative_signals), "derivative signals")
            if signals.get("protocol") != "derivative-signals-v1":
                raise ValueError("derivative-signals-v1 is required")
            for item in signals.get("candidates", []):
                candidate = dict(item)
                candidate.setdefault("protocol", "derivative-candidate-v1"); candidate.setdefault("schema_version", "1.0.0")
                candidate.setdefault("source", {"material_id": source["material_id"], "revision_id": source["revision_id"]})
                content = candidate.get("content", {}).get("markdown", "")
                candidate.setdefault("candidate_id", candidate_id(source, candidate.get("asset_type", "unknown"), content))
                validate_derivative(candidate, source); derivatives.append(candidate)
        present_types = {item["asset_type"] for item in derivatives}
        for asset_type in ALLOWED_TYPES - present_types:
            derivatives.append({"protocol": "derivative-candidate-v1", "schema_version": "1.0.0", "candidate_id": candidate_id(source, asset_type, "not_applicable"), "asset_type": asset_type, "status": "not_applicable", "source": {"material_id": source["material_id"], "revision_id": source["revision_id"]}, "reason": "no qualified derivative signal or user output intent"})
        for candidate in derivatives:
            if candidate.get("status") != "publishable" or candidate.get("asset_type") == "learning_note":
                continue
            quality_path = candidate_dir / f"{candidate['candidate_id']}-publish-quality.json"
            atomic_json(quality_path, {"protocol": "derivative-publish-quality-v1", "status": "passed", "candidate_id": candidate["candidate_id"], "asset_type": candidate["asset_type"], "gate_reference": f"guanlan://candidate/{candidate['candidate_id']}"})
            candidate["publish_inputs"] = {"quality": str(quality_path)}
        bundle = {
            "protocol": "candidate-bundle-v1", "schema_version": "1.0.0", "bundle_id": bundle_id,
            "source": {"material_id": source["material_id"], "revision_id": source["revision_id"], "source_reference": f"guanlan://material/{source['material_id']}/revision/{source['revision_id']}"},
            "source_candidate": build_source_candidate(source, readable), "derivative_candidates": derivatives,
            "created_at": now(), "workflow_state": "awaiting_user_confirmation", "vault_writes": False,
        }
        atomic_json(candidate_dir / "candidate-bundle.json", bundle); atomic_json(Path(args.output), bundle)
        bundle_ref = f"guanlan://candidate-bundle/{bundle_id}"
        warning = operation_index.finish("completed", output_refs=[bundle_ref], change_refs=[bundle_ref])
        bundle["operation_id"] = operation_index.operation_id
        if warning: bundle["operation_index_warning"] = warning
        atomic_json(candidate_dir / "candidate-bundle.json", bundle); atomic_json(Path(args.output), bundle)
        print(json.dumps({"status": "awaiting_user_confirmation", "bundle_id": bundle_id, "output": args.output}, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, UnicodeDecodeError) as error:
        if operation_index is not None:
            operation_index.finish("blocked", failure_class="organize_failed", failure_detail=str(error))
        raise SystemExit(f"ERROR: {error}") from error


if __name__ == "__main__":
    main()
