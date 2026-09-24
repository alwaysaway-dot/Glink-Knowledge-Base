#!/usr/bin/env python3
"""Production boundary for media transcript acquisition, QA, revision and Inbox projection."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from operation_envelope import OperationRecorder

_ACTIVE_OPERATION = None


def run(command: list[str], allowed: set[int] = {0}) -> subprocess.CompletedProcess:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode not in allowed:
        raise RuntimeError(
            f"command_failed:{result.returncode}:{Path(command[1]).name}:"
            f"{(result.stderr or result.stdout).strip()}"
        )
    return result


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _main() -> int:
    global _ACTIVE_OPERATION
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--media", required=True)
    parser.add_argument("--source-material", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--asset-root", required=True)
    parser.add_argument("--material-dir", required=True)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--inbox", required=True)
    parser.add_argument("--inbox-output", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--chunk-seconds", type=int, default=60)
    parser.add_argument("--segment-timeout-seconds", type=int, default=120)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--scope", choices=("production", "test"), default="production")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    try:
        source_identity = json.loads(Path(args.source_material).read_text(encoding="utf-8"))
        transcript_input_refs = [f"guanlan://material/{source_identity['material_id']}/revision/{source_identity['revision_id']}"]
    except (OSError, KeyError, json.JSONDecodeError):
        transcript_input_refs = []
    operation = OperationRecorder(Path(args.asset_root) / "operations", "transcript", input_refs=transcript_input_refs)
    _ACTIVE_OPERATION = operation
    run_dir = Path(args.run_dir).resolve(); run_dir.mkdir(parents=True, exist_ok=True)
    provider_result = run_dir / "raw-transcript.json"
    readable_record = run_dir / "readable-transcript.json"
    readable_text = run_dir / "readable-transcript.txt"
    readable_md = run_dir / "readable-transcript.md"
    quality_result = run_dir / "transcript-quality.json"
    revision_result = run_dir / "revision-result.json"
    inbox_result = run_dir / "inbox-result.json"

    ffprobe = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", args.media])
    duration = float(ffprobe.stdout.strip())
    provider = run([
        sys.executable, str(root / "transcript-provider-bridge/funasr_chunked_provider.py"),
        "--config", args.config, "--audio", args.media, "--output", str(provider_result),
        "--work-dir", str(run_dir / "work"), "--chunk-seconds", str(args.chunk_seconds),
        "--segment-timeout-seconds", str(args.segment_timeout_seconds), "--max-retries", str(args.max_retries),
    ], {0, 3})
    provider_value = json.loads(provider_result.read_text(encoding="utf-8"))
    if provider_value.get("status") == "failed":
        result = {"status": "transcript_failed", "reason": "all_segments_failed", "provider_exit": provider.returncode,
                  "source_revision_created": False, "inbox_updated": False, "operation_id": operation.operation_id}
        warning = operation.finish("failed", failure_class="transcript_provider_failed", failure_detail=result["reason"])
        if warning: result["operation_index_warning"] = warning
        write_json(Path(args.output), result); print(json.dumps(result, ensure_ascii=False, indent=2)); return 3

    run([
        sys.executable, str(root / "transcript-intelligence/media_transcript_hygiene.py"),
        "--transcript", str(provider_result), "--output-json", str(readable_record),
        "--output-text", str(readable_text), "--output-md", str(readable_md),
    ])
    gate = run([
        sys.executable, str(root / "transcript-quality-gate/media_transcript_quality.py"),
        "--transcript", str(provider_result), "--readable", str(readable_text),
        "--media-duration", str(duration), "--output", str(quality_result),
    ], {0, 4})
    quality = json.loads(quality_result.read_text(encoding="utf-8"))
    if quality["quality_status"] == "transcript_quality_failed":
        result = {"status": "transcript_quality_failed", "quality_status": quality["quality_status"],
                  "gate_exit": gate.returncode, "source_revision_created": False, "inbox_updated": False,
                  "operation_id": operation.operation_id}
        warning = operation.finish("blocked", failure_class="transcript_quality_failed", failure_detail=quality.get("failure_reason"))
        if warning: result["operation_index_warning"] = warning
        write_json(Path(args.output), result); print(json.dumps(result, ensure_ascii=False, indent=2)); return 4

    revision_command = [
        sys.executable, str(root / "source-material-generator/add_transcript_revision.py"),
        "--source-material", args.source_material, "--manifest", args.manifest,
        "--provider-result", str(provider_result), "--readable-text", str(readable_text),
        "--quality-result", str(quality_result), "--asset-root", args.asset_root,
        "--material-dir", args.material_dir, "--project-root", str(root),
        "--created-at", args.created_at, "--output-summary", str(revision_result), "--scope", args.scope,
    ]
    if quality["quality_status"] == "transcript_partial":
        revision_command.append("--allow-partial")
    run(revision_command)
    revision = json.loads(revision_result.read_text(encoding="utf-8"))
    run([
        sys.executable, str(root / "source-material-generator/capture_inbox_completion.py"),
        "--source-material", revision["source_material"], "--manifest", revision["manifest"],
        "--asset-root", args.asset_root, "--inbox", args.inbox, "--output", args.inbox_output,
        "--project-root", str(root), "--result", str(inbox_result), "--scope", args.scope,
    ])
    inbox = json.loads(inbox_result.read_text(encoding="utf-8"))
    result = {
        "status": inbox["status"], "quality_status": quality["quality_status"],
        "material_id": revision["material_id"], "revision_id": revision["revision_id"],
        "source_revision_status": revision["status"], "source_revision_created": True,
        "inbox_updated": inbox.get("projection_written", False), "inbox_path": inbox["path"],
        "missing_ranges": quality.get("missing_ranges", []), "operation_id": operation.operation_id,
    }
    source_ref = f"guanlan://material/{revision['material_id']}/revision/{revision['revision_id']}"
    status = "completed" if inbox["status"] in {"capture_completed", "already_projected"} else "partial"
    warning = operation.finish(status, output_refs=[source_ref], change_refs=[source_ref],
                               warnings=quality.get("warnings", []),
                               failure_class=None if status == "completed" else "capture_completion_partial")
    if warning: result["operation_index_warning"] = warning
    write_json(Path(args.output), result); print(json.dumps(result, ensure_ascii=False, indent=2)); return 0


def main() -> int:
    global _ACTIVE_OPERATION
    try:
        return _main()
    except (OSError, ValueError, KeyError, json.JSONDecodeError, RuntimeError) as error:
        if _ACTIVE_OPERATION is not None:
            _ACTIVE_OPERATION.finish("failed", failure_class="transcript_pipeline_failed", failure_detail=str(error))
        raise
    finally:
        _ACTIVE_OPERATION = None


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, json.JSONDecodeError, RuntimeError) as error:
        raise SystemExit(f"ERROR: {error}") from error
