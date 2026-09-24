#!/usr/bin/env python3
"""Create a minimal readable layer from timestamped ASR evidence without summarising."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path


def load_intelligence():
    target = Path(__file__).with_name("transcript_intelligence.py")
    spec = importlib.util.spec_from_file_location("transcript_intelligence_hygiene", target)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build(transcript: dict, target_chars: int, max_chars: int) -> dict:
    intelligence = load_intelligence()
    source_segments = intelligence.parse_json(transcript)
    segments, operations = intelligence.normalize_segments(source_segments)
    if not segments:
        raise ValueError("no readable transcript segments")
    paragraphs = intelligence.build_paragraphs(
        segments, target_chars=target_chars, max_chars=max_chars, max_seconds=90,
    )
    text = intelligence.readable_text(paragraphs).strip() + "\n"
    raw_text = str(transcript.get("text", "")).strip()
    return {
        "protocol": "media-transcript-hygiene-v1", "schema_version": "1.0.0",
        "provider": transcript.get("provider", "unknown"), "model": transcript.get("model", "unknown"),
        "language": transcript.get("language", "unknown"), "provider_status": transcript.get("status", "unknown"),
        "readable_text": text, "paragraphs": paragraphs, "segments": segments,
        "missing_ranges": transcript.get("missing_ranges", []),
        "operations": operations + ["chunk_boundary_punctuation", "no_summary", "no_semantic_rewrite"],
        "raw_and_readable_byte_identical": raw_text.encode("utf-8") == text.encode("utf-8"),
    }


def render_markdown(result: dict) -> str:
    lines = [
        "# Media Readable Transcript", "",
        "> 本文仅做 ASR 转录卫生处理：时间排序、机械去重、保守标点和段落组织。未总结、扩写或猜测听辨不清内容。", "",
        "## 连续可读原文", "", result["readable_text"].strip(), "",
        "## 时间证据", "",
    ]
    for item in result["segments"]:
        lines.append(f"- `{item['start_time']:.3f}–{item['end_time']:.3f}` `{item['segment_id']}` {item['text']}")
    if result["missing_ranges"]:
        lines.extend(["", "## 缺失区间", ""])
        for item in result["missing_ranges"]:
            lines.append(f"- `{item['start_time']:.3f}–{item['end_time']:.3f}`：{item['reason']}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--transcript", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-text", required=True)
    parser.add_argument("--output-md", required=True)
    parser.add_argument("--paragraph-target-chars", type=int, default=300)
    parser.add_argument("--paragraph-max-chars", type=int, default=520)
    args = parser.parse_args()
    transcript = json.loads(Path(args.transcript).read_text(encoding="utf-8"))
    result = build(transcript, args.paragraph_target_chars, args.paragraph_max_chars)
    outputs = {
        Path(args.output_json): json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        Path(args.output_text): result["readable_text"],
        Path(args.output_md): render_markdown(result),
    }
    for path, value in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
    print(json.dumps({
        "status": "completed", "segment_count": len(result["segments"]),
        "paragraph_count": len(result["paragraphs"]),
        "raw_and_readable_byte_identical": result["raw_and_readable_byte_identical"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        raise SystemExit(f"ERROR: {error}") from error
