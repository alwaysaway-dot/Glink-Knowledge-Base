#!/usr/bin/env python3
"""Fault-isolated FunASR pipeline for long local audio/video.

Each bounded audio segment is handled by an independently timeout-controlled
provider process. Successful segment results are cached by content identity, so a
single failure never discards earlier work and retries do not re-run valid segments.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from funasr_provider import timestamp_text


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def atomic_write(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    try:
        with temporary.open("wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def file_sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def chunk_cache_identity(audio: Path, chunk_seconds: int) -> dict:
    audio_hash = file_sha256(audio)
    cache_key = hashlib.sha256(
        f"{audio_hash}|{audio.stat().st_size}|{chunk_seconds}|pcm_s16le|16000|mono".encode()
    ).hexdigest()
    return {
        "cache_key": cache_key, "audio_sha256": audio_hash,
        "audio_size": audio.stat().st_size, "chunk_seconds": chunk_seconds,
        "audio_format": "pcm_s16le/16000/mono",
    }


def probe_duration(path: Path) -> float:
    completed = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        check=True, capture_output=True, text=True,
    )
    return float(completed.stdout.strip())


def split_audio(audio: Path, work_dir: Path, chunk_seconds: int):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("audio_prepare_failed: ffmpeg is required")
    identity = chunk_cache_identity(audio, chunk_seconds)
    chunks_dir = work_dir / "chunks" / identity["cache_key"]
    chunks_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = chunks_dir / "chunk-cache-manifest.json"
    existing = sorted(chunks_dir.glob("chunk-*.wav"))
    if existing:
        if not manifest_path.is_file():
            raise RuntimeError("audio_prepare_failed: chunk cache manifest is missing")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest != identity:
            raise RuntimeError("audio_prepare_failed: chunk cache identity mismatch")
        for chunk in existing:
            if probe_duration(chunk) <= 0:
                raise RuntimeError(f"audio_prepare_failed: invalid cached chunk {chunk.name}")
        return existing, identity
    try:
        subprocess.run(
            [
                ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(audio),
                "-f", "segment", "-segment_time", str(chunk_seconds), "-reset_timestamps", "1",
                "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
                str(chunks_dir / "chunk-%03d.wav"),
            ],
            check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError as error:
        raise RuntimeError(f"audio_prepare_failed: {error.stderr.strip()}") from error
    chunks = sorted(chunks_dir.glob("chunk-*.wav"))
    if not chunks:
        raise RuntimeError("audio_prepare_failed: audio split produced no chunks")
    atomic_write(manifest_path, canonical_json(identity))
    return chunks, identity


def shift_segment(segment: dict, offset: float, index: int) -> dict:
    start = float(segment["start_time"]) + offset
    end = float(segment["end_time"]) + offset
    return {
        "segment_id": f"transcript-{index:04d}", "start_time": round(start, 3),
        "end_time": round(end, 3), "start_timestamp": timestamp_text(start),
        "end_timestamp": timestamp_text(end), "text": str(segment.get("text", "")).strip(),
        "confidence": segment.get("confidence"),
    }


def valid_cached_result(result_path: Path, meta_path: Path, chunk_hash: str, provider_identity: dict) -> dict | None:
    if not result_path.is_file() or not meta_path.is_file():
        return None
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if metadata != {"chunk_sha256": chunk_hash, "provider_identity": provider_identity}:
        return None
    if result.get("protocol") != "transcript-provider-v1" or result.get("status") != "completed":
        return None
    if not str(result.get("text", "")).strip() or not result.get("segments"):
        return None
    return result


def transcribe_segment(
    *, chunk: Path, chunk_index: int, config_path: Path, config: dict,
    provider_script: Path, results_dir: Path, timeout_seconds: int, max_retries: int,
) -> tuple[dict | None, dict]:
    chunk_hash = file_sha256(chunk)
    provider_identity = {
        "provider": config.get("provider"), "model": config.get("model"),
        "provider_script_sha256": file_sha256(provider_script),
    }
    result_path = results_dir / f"chunk-{chunk_index:03d}.json"
    meta_path = results_dir / f"chunk-{chunk_index:03d}.meta.json"
    cached = valid_cached_result(result_path, meta_path, chunk_hash, provider_identity)
    if cached is not None:
        return cached, {"asr_status": "completed_cached", "retry_count": 0, "failure_reason": ""}

    # Preserve a virtualenv launcher path. Resolving the symlink to the base
    # interpreter discards the venv prefix and can make the Provider disappear.
    python_path = Path(config.get("python_path", sys.executable)).expanduser()
    if not python_path.is_absolute():
        python_path = (Path.cwd() / python_path).absolute()
    if not python_path.is_file():
        raise RuntimeError(f"asr_process_failed: python executable missing: {python_path}")
    failures = []
    for attempt in range(max_retries + 1):
        attempt_path = results_dir / f"chunk-{chunk_index:03d}.attempt-{attempt}.json"
        command = [str(python_path), str(provider_script), "--config", str(config_path), "--audio", str(chunk), "--output", str(attempt_path)]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            failures.append("segment_timeout")
            continue
        if completed.returncode != 0:
            failures.append("asr_process_failed")
            continue
        try:
            value = json.loads(attempt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            failures.append("transcript_parse_failed")
            continue
        if value.get("status") != "completed" or not str(value.get("text", "")).strip() or not value.get("segments"):
            failures.append("transcript_parse_failed")
            continue
        atomic_write(result_path, canonical_json(value))
        atomic_write(meta_path, canonical_json({"chunk_sha256": chunk_hash, "provider_identity": provider_identity}))
        return value, {
            "asr_status": "completed" if attempt == 0 else "completed_after_retry",
            "retry_count": attempt, "failure_reason": failures[-1] if failures else "",
        }
    return None, {
        "asr_status": "failed", "retry_count": max_retries,
        "failure_reason": failures[-1] if failures else "asr_process_failed",
        "attempt_failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True); parser.add_argument("--audio", required=True)
    parser.add_argument("--output", required=True); parser.add_argument("--work-dir", required=True)
    parser.add_argument("--chunk-seconds", type=int, default=60)
    parser.add_argument("--segment-timeout-seconds", type=int, default=120)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--provider-script", default=str(Path(__file__).with_name("funasr_provider.py")))
    args = parser.parse_args()

    if not 15 <= args.chunk_seconds <= 120:
        raise RuntimeError("chunk-seconds must be between 15 and 120")
    if args.segment_timeout_seconds < 5 or not 0 <= args.max_retries <= 3:
        raise RuntimeError("invalid timeout or retry limit")
    config_path = Path(args.config).expanduser().resolve()
    audio_path = Path(args.audio).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    work_dir = Path(args.work_dir).expanduser().resolve()
    provider_script = Path(args.provider_script).expanduser().resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config.get("provider") != "funasr" or config.get("model") != "paraformer-zh":
        raise RuntimeError("FunASR paraformer-zh config is required")
    if not config.get("enabled") or config.get("network_access") is not False:
        raise RuntimeError("enabled offline Provider config is required")
    if not audio_path.is_file() or not provider_script.is_file():
        raise RuntimeError("audio_prepare_failed: audio or provider script is missing")

    started = time.monotonic()
    chunks, chunk_cache = split_audio(audio_path, work_dir, args.chunk_seconds)
    results_dir = work_dir / "segment-results" / chunk_cache["cache_key"]
    results_dir.mkdir(parents=True, exist_ok=True)
    merged_segments, chunk_records, missing_ranges = [], [], []
    offset = 0.0
    for chunk_index, chunk in enumerate(chunks):
        duration = probe_duration(chunk)
        local, execution = transcribe_segment(
            chunk=chunk, chunk_index=chunk_index, config_path=config_path, config=config,
            provider_script=provider_script, results_dir=results_dir,
            timeout_seconds=args.segment_timeout_seconds, max_retries=args.max_retries,
        )
        shifted = []
        if local is not None:
            shifted = [
                shift_segment(segment, offset, len(merged_segments) + index)
                for index, segment in enumerate(local["segments"], start=1)
                if str(segment.get("text", "")).strip()
            ]
            merged_segments.extend(shifted)
        else:
            missing_ranges.append({"start_time": round(offset, 3), "end_time": round(offset + duration, 3), "reason": execution["failure_reason"]})
        chunk_records.append({
            "segment_id": f"audio-segment-{chunk_index:04d}", "start_time": round(offset, 3),
            "end_time": round(offset + duration, 3), "duration": round(duration, 3),
            "asr_status": execution["asr_status"], "retry_count": execution["retry_count"],
            "failure_reason": execution.get("failure_reason", ""),
            "asr_text": "" if local is None else str(local.get("text", "")).strip(),
            "transcript_segment_count": len(shifted),
        })
        offset += duration

    merged_text = "".join(segment["text"] for segment in merged_segments)
    status = "completed" if merged_text and not missing_ranges else ("partial" if merged_text else "failed")
    result = {
        "protocol": "transcript-provider-v1", "result_type": "TranscriptResult",
        "provider": "funasr", "model": config["model"], "language": "zh-CN",
        "status": status, "source_reference": str(audio_path), "text": merged_text,
        "timestamp": {"start_time": 0, "end_time": round(offset, 3), "start_timestamp": timestamp_text(0), "end_timestamp": timestamp_text(offset), "unit": "seconds", "source": "funasr_fault_isolated_chunks"},
        "segments": merged_segments, "timestamps": True, "missing_ranges": missing_ranges,
        "chunking": {
            "strategy": "bounded_fixed_chunks", "chunk_seconds": args.chunk_seconds,
            "chunk_count": len(chunks), "segment_timeout_seconds": args.segment_timeout_seconds,
            "max_retries": args.max_retries, "cache_identity": chunk_cache, "chunks": chunk_records,
        },
        "provider_metadata": {
            "bridge_version": "funasr-chunked-provider-v2", "model_location": "external",
            "environment_location": "external", "device": config.get("device", "cpu"),
            "network_access": False, "elapsed_seconds": round(time.monotonic() - started, 3),
        },
        "warnings": (["partial_transcript_missing_ranges"] if missing_ranges else []),
    }
    atomic_write(output_path, canonical_json(result))
    print(json.dumps({"status": status, "chunk_count": len(chunks), "transcript_segments": len(merged_segments), "missing_ranges": missing_ranges, "output": str(output_path)}, ensure_ascii=False, indent=2))
    return 0 if status in {"completed", "partial"} else 3


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, json.JSONDecodeError, RuntimeError) as error:
        raise SystemExit(f"ERROR: {error}") from error
