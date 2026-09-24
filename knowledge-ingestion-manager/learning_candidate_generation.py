#!/usr/bin/env python3
"""Create a non-published Learning candidate from a ready Source candidate.

The wrapper is intentionally the only user-workflow bridge to the existing
KnowledgeGenerationEngine.  It writes candidate artifacts under the asset
library operation directory, never to Vault.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from publisher_core import atomic_json, canonical, digest, has_temp, load_json


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROMPT_VERSION = "learning-note-generation-v2"


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def source_ready(source: dict, validation: dict, readable: Path):
    if source.get("protocol") != "source-material-v3":
        raise ValueError("source-material-v3 is required")
    if validation.get("status") != "passed":
        raise ValueError("Source validation must pass before derivative generation")
    if validation.get("material_id") != source.get("material_id") or validation.get("revision_id") != source.get("revision_id"):
        raise ValueError("validation/source identity mismatch")
    quality = source.get("quality", {})
    if quality.get("capture_status") != "complete" or quality.get("transcript_quality") in {"failed", "raw", "unusable"}:
        raise ValueError("organize_blocked_source_not_ready")
    if not readable.is_file() or not readable.read_text(encoding="utf-8").strip():
        raise ValueError("readable source unavailable")
    if has_temp(source):
        raise ValueError("temporary source reference is forbidden")


def markdown_h1(markdown: str) -> str:
    headings = [line[2:].strip() for line in markdown.splitlines() if line.startswith("# ")]
    if len(headings) != 1 or not headings[0] or headings[0].lower() == "unknown":
        raise ValueError("generation_metadata_inconsistent: exactly one non-empty generated H1 is required")
    return headings[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-material", required=True); parser.add_argument("--source-validation", required=True)
    parser.add_argument("--readable-source", required=True); parser.add_argument("--operation-dir", required=True)
    parser.add_argument("--provider", choices=("codex", "file", "codex-replay", "local"), required=True)
    parser.add_argument("--model", default="none"); parser.add_argument("--llm-output")
    parser.add_argument("--prompt-version", default=DEFAULT_PROMPT_VERSION,
                        choices=("learning-note-generation-v1", "learning-note-generation-v2"))
    parser.add_argument("--source-language"); parser.add_argument("--output-language")
    parser.add_argument("--translation-policy", choices=("not_required", "required"), default="not_required")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        source = load_json(Path(args.source_material), "source material")
        validation = load_json(Path(args.source_validation), "source validation")
        readable = Path(args.readable_source).resolve(); source_ready(source, validation, readable)
        operation = Path(args.operation_dir).resolve(); operation.mkdir(parents=True, exist_ok=True)
        source_ref = source["source"]["source_url"]
        seed = canonical({"material_id": source["material_id"], "revision_id": source["revision_id"], "asset_type": "learning_note"})
        draft_id = "candidate_sha256_" + digest(seed)
        original_title = source["source"].get("title")
        draft = {
            "protocol": "knowledge-asset-draft-v1",
            "asset": {"asset_id": draft_id, "type": "learning_note", "status": "draft"},
            "source": {"material_id": source["material_id"], "task_id": "organize_" + draft_id[-16:], "source_reference": source_ref,
                       "original_title": original_title},
            "content": {"title": "待生成知识标题", "original_title": original_title,
                        "references": [f"guanlan://material/{source['material_id']}/revision/{source['revision_id']}"]},
            "review": {"need_confirmation": True, "confirmed": False},
        }
        plan = {
            "protocol": "knowledge-generation-v1",
            "input": {"asset_draft_id": draft_id, "material_id": source["material_id"], "source_reference": source_ref,
                      "source_material_reference": f"guanlan://material/{source['material_id']}/revision/{source['revision_id']}", "material_revision_id": source["revision_id"], "understanding_sidecar_reference": ""},
            "generation": {"asset_type": "learning_note", "template": "learning_note", "requirements": ["source_preserving", "candidate_only"]},
            "output": {"draft_reference": f"guanlan://candidate/{draft_id}", "need_confirmation": True},
        }
        draft_path = operation / "learning-draft-input.json"; plan_path = operation / "learning-plan.json"
        generated = operation / "learning-draft.md"; quality_path = operation / "learning-generation-quality.json"
        metadata_path = operation / "learning-generation-metadata.json"; record_path = operation / "learning-generation-record.json"
        atomic_json(draft_path, draft); atomic_json(plan_path, plan)
        engine_binary = operation / "knowledge-generation-engine"
        compile_result = subprocess.run(["swiftc", "-parse-as-library", str(ROOT / "knowledge-generation-engine" / "KnowledgeGenerationEngine.swift"), "-o", str(engine_binary)], text=True, capture_output=True)
        if compile_result.returncode != 0:
            raise ValueError("knowledge_generation_engine_compile_failed: " + compile_result.stderr.strip())
        command = [str(engine_binary),
                   "--draft", str(draft_path), "--plan", str(plan_path), "--source-material", str(Path(args.source_material).resolve()),
                   "--source-validation", str(Path(args.source_validation).resolve()), "--readable-source", str(readable),
                   "--candidate-generation", "true", "--provider", args.provider, "--model", args.model,
                   "--prompt-version", args.prompt_version, "--prompt-file", str(ROOT / "core" / "prompt" / f"{args.prompt_version}.md"),
                   "--translation-policy", args.translation_policy,
                   "--output", str(generated), "--quality", str(quality_path), "--metadata", str(metadata_path), "--record", str(record_path)]
        if args.source_language:
            command.extend(["--source-language", args.source_language])
        if args.output_language:
            command.extend(["--output-language", args.output_language])
        if args.llm_output:
            command.extend(["--llm-output", str(Path(args.llm_output).resolve())])
        completed = subprocess.run(command, text=True, capture_output=True)
        if completed.returncode != 0:
            raise ValueError("learning_generation_failed: " + completed.stderr.strip())
        output = generated.read_text(encoding="utf-8").strip() + "\n"
        if args.provider == "local" or "本地回退未生成知识正文" in output:
            raise ValueError("learning_generation_failed: provider produced no usable knowledge content")
        generated_title = markdown_h1(output)
        draft["content"]["title"] = generated_title
        atomic_json(draft_path, draft)
        quality = load_json(quality_path, "generation quality")
        quality_check = quality.get("generation-quality-check", {})
        title_consistent = quality_check.get("generated_title") == generated_title and quality_check.get("title_consistency") == "passed"
        if not title_consistent:
            status = "generation_metadata_inconsistent"
        elif quality_check.get("publishable") is not True:
            status = "generation_quality_blocked"
        else:
            status = "publishable"
        publish_quality_path = operation / "learning-publish-quality.json"
        atomic_json(publish_quality_path, {"protocol": "knowledge-publish-quality-v1",
                                          "status": "passed" if status == "publishable" else "blocked",
                                          "candidate_id": draft_id, "source_traceability": quality_check.get("source_traceability", "unknown"),
                                          "source_copy_check": "passed" if quality_check.get("cognitive_delta") == "passed" else "blocked",
                                          "title_consistency": "passed" if title_consistent else "failed"})
        candidate = {
            "protocol": "derivative-candidate-v1", "schema_version": "1.0.0", "candidate_id": draft_id,
            "asset_type": "learning_note", "status": status,
            "source": {"material_id": source["material_id"], "revision_id": source["revision_id"],
                       "source_reference": f"guanlan://material/{source['material_id']}/revision/{source['revision_id']}",
                       "original_title": original_title},
            "content": {"title": generated_title, "generated_title": generated_title, "markdown": output},
            "provenance": {"stable_references": [f"guanlan://material/{source['material_id']}/revision/{source['revision_id']}", source["asset_manifest_reference"]]},
            "generation": {"provider": args.provider, "model": args.model, "prompt_version": args.prompt_version,
                           "record_path": str(record_path), "quality": quality},
            "publish_inputs": {"candidate": str(Path(args.output).resolve()), "draft": str(draft_path),
                               "generated": str(generated), "quality": str(publish_quality_path)},
            "admission": {"status": "passed" if status == "publishable" else "blocked",
                          "source_traceability": quality_check.get("source_traceability", "unknown"),
                          "not_source_copy": quality_check.get("cognitive_delta") == "passed"},
            "created_at": now(),
        }
        atomic_json(Path(args.output), candidate)
        print(json.dumps({"status": status, "candidate_id": draft_id, "generated_title": generated_title,
                          "output": args.output}, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, UnicodeDecodeError) as error:
        raise SystemExit(f"ERROR: {error}") from error


if __name__ == "__main__":
    main()
