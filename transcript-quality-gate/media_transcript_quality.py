#!/usr/bin/env python3
"""Deterministic structural and content usability gate for media transcripts."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path


PLACEHOLDERS = (
    "no transcript acquired", "transcript unavailable", "missing transcript",
    "暂无转录", "未取得字幕", "无转录内容",
)
PUNCTUATION_RE = re.compile(r"[。！？!?；;，,、：:.]")
CJK_RE = re.compile(r"[\u3400-\u9fff]")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffd]")
REPEAT_RUN_RE = re.compile(r"(.)\1{2,}")
REPEAT_PHRASE_RE = re.compile(r"(.{2,8})\1+")


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * ratio) - 1))
    return ordered[index]


def coverage_seconds(intervals: list[tuple[float, float]], duration: float) -> float:
    clipped = sorted((max(0.0, start), min(duration, end)) for start, end in intervals if end > start)
    total = 0.0
    current_start = current_end = None
    for start, end in clipped:
        if current_start is None:
            current_start, current_end = start, end
        elif start <= current_end:
            current_end = max(current_end, end)
        else:
            total += current_end - current_start
            current_start, current_end = start, end
    if current_start is not None:
        total += current_end - current_start
    return max(0.0, total)


def longest_without_punctuation(text: str) -> int:
    return max((len(item) for item in PUNCTUATION_RE.split(text)), default=0)


def repeat_pollution(text: str) -> tuple[int, int]:
    run_chars = sum(len(match.group(0)) for match in REPEAT_RUN_RE.finditer(text))
    phrase_chars = sum(len(match.group(0)) for match in REPEAT_PHRASE_RE.finditer(text))
    return run_chars, phrase_chars


def evaluate(transcript: dict, readable_text: str, media_duration: float) -> dict:
    segments = transcript.get("segments") if isinstance(transcript.get("segments"), list) else []
    structural_failures, structural_warnings = [], []
    intervals, durations = [], []
    empty = 0
    previous_start = -1.0
    invalid_timestamp = False
    for item in segments:
        try:
            start, end = float(item.get("start_time", 0)), float(item.get("end_time", 0))
        except (TypeError, ValueError):
            invalid_timestamp = True
            continue
        if start < previous_start or end <= start:
            invalid_timestamp = True
        previous_start = start
        intervals.append((start, end)); durations.append(max(0.0, end - start))
        if not str(item.get("text", "")).strip():
            empty += 1
    raw_text = str(transcript.get("text", "")).strip()
    normalized_readable = " ".join(str(readable_text or "").split())
    lower = normalized_readable.lower()
    placeholder = any(value in lower for value in PLACEHOLDERS)
    coverage = coverage_seconds(intervals, media_duration) if media_duration > 0 else 0.0
    coverage_ratio = coverage / media_duration if media_duration > 0 else 0.0
    max_segment = max(durations, default=0.0)
    p95_segment = percentile(durations, 0.95)
    empty_ratio = empty / len(segments) if segments else 1.0

    if not raw_text or not segments:
        structural_failures.append("transcript_empty")
    if placeholder:
        structural_failures.append("placeholder_text")
    if invalid_timestamp:
        structural_failures.append("invalid_or_unordered_timestamps")
    if media_duration >= 180 and len(segments) <= 1 and max_segment >= media_duration * 0.8:
        structural_failures.append("giant_single_segment")
    elif max_segment > 180:
        structural_failures.append("oversized_segment")
    elif max_segment > 75:
        structural_warnings.append("long_segment")
    if empty_ratio > 0.5:
        structural_failures.append("excessive_empty_segments")
    if media_duration > 0:
        if coverage_ratio < 0.70:
            structural_failures.append("timestamp_coverage_severely_incomplete")
        elif coverage_ratio < 0.90:
            structural_warnings.append("timestamp_coverage_incomplete")
    missing_ranges = transcript.get("missing_ranges") if isinstance(transcript.get("missing_ranges"), list) else []
    if missing_ranges:
        structural_warnings.append("missing_ranges_present")
    if transcript.get("status") == "failed":
        structural_failures.append("provider_failed")
    elif transcript.get("status") == "partial":
        structural_warnings.append("provider_partial")

    content_failures, content_warnings = [], []
    text_length = len(normalized_readable)
    punctuation_count = len(PUNCTUATION_RE.findall(normalized_readable))
    punctuation_per_100 = punctuation_count * 100 / max(1, text_length)
    abnormal_count = len(CONTROL_RE.findall(normalized_readable))
    abnormal_ratio = abnormal_count / max(1, text_length)
    cjk = CJK_RE.findall(normalized_readable)
    lexical_diversity = len(set(cjk)) / max(1, len(cjk))
    repeat_run_chars, repeat_phrase_chars = repeat_pollution(normalized_readable)
    repeat_ratio = max(repeat_run_chars, repeat_phrase_chars) / max(1, text_length)
    no_punctuation_run = longest_without_punctuation(normalized_readable)
    chars_per_minute = text_length / max(media_duration / 60.0, 1 / 60.0)

    if not normalized_readable or placeholder:
        content_failures.append("content_missing_or_placeholder")
    if media_duration >= 30 and chars_per_minute < 20:
        content_failures.append("content_density_too_low")
    if abnormal_ratio > 0.02:
        content_failures.append("abnormal_character_ratio")
    if repeat_ratio > 0.015:
        content_failures.append("mechanical_repetition_pollution")
    elif repeat_ratio > 0.006:
        content_warnings.append("repetition_warning")
    # Type/token ratio naturally falls as transcripts grow; only flag a genuinely
    # collapsed vocabulary, while mechanical repetition is handled separately.
    if len(cjk) >= 200 and lexical_diversity < 0.02 and len(set(cjk)) < 20:
        content_failures.append("lexical_diversity_abnormally_low")
    if text_length >= 500 and punctuation_per_100 < 0.15:
        content_failures.append("punctuation_absent_in_long_text")
    elif text_length >= 300 and punctuation_per_100 < 0.35:
        content_warnings.append("punctuation_sparse")
    if no_punctuation_run > 800:
        content_failures.append("extreme_run_on_text")
    elif no_punctuation_run > 400:
        content_warnings.append("long_run_on_text")

    structural_status = "fail" if structural_failures else ("warning" if structural_warnings else "pass")
    content_status = "unusable" if content_failures else ("usable_with_warnings" if content_warnings else "usable")
    ready = structural_status != "fail" and content_status != "unusable" and not missing_ranges and transcript.get("status") == "completed"
    gate_status = "ready_for_整理" if ready else (
        "transcript_partial" if raw_text and (missing_ranges or transcript.get("status") == "partial") else "transcript_quality_failed"
    )
    return {
        "protocol": "media-transcript-quality-v1", "schema_version": "1.0.0",
        "transcript_content_hash": sha256_bytes(json.dumps(transcript, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()),
        "readable_content_hash": sha256_bytes((readable_text or "").encode("utf-8")),
        "media_duration": media_duration,
        "transcript_structural_qa": {
            "status": structural_status,
            "failures": list(dict.fromkeys(structural_failures)),
            "warnings": list(dict.fromkeys(structural_warnings)),
            "metrics": {
                "segment_count": len(segments), "timestamp_coverage_seconds": round(coverage, 3),
                "timestamp_coverage_ratio": round(coverage_ratio, 4),
                "max_segment_duration": round(max_segment, 3), "p95_segment_duration": round(p95_segment, 3),
                "empty_segment_ratio": round(empty_ratio, 4), "missing_range_count": len(missing_ranges),
            },
        },
        "transcript_content_quality": {
            "status": content_status,
            "failures": list(dict.fromkeys(content_failures)),
            "warnings": list(dict.fromkeys(content_warnings)),
            "dimensions": {
                "human_readability": "low" if content_failures else ("medium" if content_warnings else "high"),
                "sentence_completeness": "low" if "extreme_run_on_text" in content_failures else ("medium" if no_punctuation_run > 400 else "high"),
                "encoding_quality": "low" if abnormal_ratio > 0.02 else "high",
                "repetition_quality": "low" if "mechanical_repetition_pollution" in content_failures else ("medium" if repeat_ratio > 0.006 else "high"),
                "punctuation_quality": "low" if "punctuation_absent_in_long_text" in content_failures else ("medium" if punctuation_per_100 < 0.35 else "high"),
                "content_continuity": "low" if not normalized_readable else ("medium" if no_punctuation_run > 400 else "high"),
                "asr_error_density": "unknown_without_token_confidence_or_reference_transcript",
            },
            "metrics": {
                "text_length": text_length, "characters_per_minute": round(chars_per_minute, 2),
                "punctuation_per_100_chars": round(punctuation_per_100, 3),
                "longest_unpunctuated_run": no_punctuation_run,
                "mechanical_repetition_ratio": round(repeat_ratio, 4),
                "abnormal_character_ratio": round(abnormal_ratio, 4),
                "cjk_lexical_diversity": round(lexical_diversity, 4),
            },
        },
        "quality_status": gate_status,
        "ready_for_sorting": ready,
        "capture_completion_status": "capture_completed" if ready else "capture_partial",
        "missing_ranges": missing_ranges,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--transcript", required=True)
    parser.add_argument("--readable", required=True)
    parser.add_argument("--media-duration", type=float, required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    transcript_path, readable_path = Path(args.transcript), Path(args.readable)
    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    result = evaluate(transcript, readable_path.read_text(encoding="utf-8"), args.media_duration)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["ready_for_sorting"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
