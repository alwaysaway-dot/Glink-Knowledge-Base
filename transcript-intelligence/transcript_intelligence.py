#!/usr/bin/env python3
"""Build a human-readable transcript without summarising or changing meaning."""

from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path


LOGICAL_REFERENCE_RE = re.compile(r"^guanlan://")
SENTENCE_END = "。！？!?；;：:."
DISCOURSE_MARKERS = (
    "那么", "所以", "但是", "不过", "然而", "因此", "同时", "当然",
    "比如", "例如", "首先", "其次", "最后", "简单来说", "总之", "接下来",
    "其中", "注意", "如果", "虽然", "甚至", "否则", "之后",
)
ADJACENT_PHRASE_REPEAT_RE = re.compile(r"(.{2,16})\1+")


def as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def timestamp(seconds):
    total = int(max(0, seconds))
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def normalize_language(value: str) -> str:
    normalized = str(value or "").strip().replace("_", "-").lower()
    aliases = {
        "zh": "zh-CN",
        "zh-cn": "zh-CN",
        "zh-hans": "zh-CN",
        "chinese": "zh-CN",
        "en": "en",
        "en-us": "en",
        "en-gb": "en",
        "english": "en",
    }
    return aliases.get(normalized, value or "unknown")


def detect_language(text: str) -> str:
    han = len(re.findall(r"[\u3400-\u9fff]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if han >= max(20, latin * 0.2):
        return "zh-CN"
    if latin >= max(20, han * 2):
        return "en"
    return "mixed" if han or latin else "unknown"


def clean_text(value: str):
    text = re.sub(r"\s+", " ", str(value or "").replace("\u00a0", " ")).strip()
    applied = []
    before = text
    text = ADJACENT_PHRASE_REPEAT_RE.sub(lambda match: match.group(1), text)
    if text != before:
        applied.append("adjacent_exact_phrase_repetition_removed")
    if re.search(r"[\u3400-\u9fff]", text):
        before = text
        for marker in DISCOURSE_MARKERS:
            text = re.sub(rf"(?<=[^。！？!?；;：:.\s])(?={re.escape(marker)})", "。", text)
        if text != before:
            applied.append("discourse_marker_punctuation_restored")
    if text and text[-1] not in SENTENCE_END:
        text += "。" if re.search(r"[\u3400-\u9fff]", text) else "."
        applied.append("terminal_punctuation_restored")
    return text, applied


def segment_record(item: dict, index: int) -> dict:
    return {
        "segment_id": item.get("segment_id") or f"transcript-{index:04d}",
        "start_time": as_float(item.get("start_time")),
        "end_time": as_float(item.get("end_time")),
        "text": str(item.get("text", "")),
        "confidence": item.get("confidence"),
    }


def parse_json(data: dict):
    items = data.get("segments") or [
        {
            "segment_id": "transcript-0001",
            "start_time": (data.get("timestamp") or {}).get("start_time", 0),
            "end_time": (data.get("timestamp") or {}).get("end_time", 0),
            "text": data.get("text", ""),
            "confidence": None,
        }
    ]
    return [segment_record(item, index) for index, item in enumerate(items, start=1)]


def parse_markdown(path):
    text = Path(path).read_text(encoding="utf-8")
    pattern = re.compile(
        r"\[(\d{2}):(\d{2}):(\d{2}(?:\.\d+)?)\s*-\s*"
        r"(\d{2}):(\d{2}):(\d{2}(?:\.\d+)?)\]\s*\n"
        r"(.*?)(?=\n\[\d{2}:|\Z)",
        re.S,
    )
    output = []
    for index, match in enumerate(pattern.finditer(text), start=1):
        start = int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3))
        end = int(match.group(4)) * 3600 + int(match.group(5)) * 60 + float(match.group(6))
        output.append(
            {
                "segment_id": f"transcript-{index:04d}",
                "start_time": start,
                "end_time": end,
                "text": match.group(7).strip(),
                "confidence": None,
            }
        )
    return output


def fingerprint(text: str) -> str:
    return re.sub(r"[^\w\u3400-\u9fff]+", "", text).lower()


def normalize_segments(source_segments):
    segments = []
    operations = [
        "time_order_restored",
        "whitespace_normalized",
        "adjacent_exact_duplicates_removed",
        "paragraph_structure_restored",
        "no_semantic_rewrite",
    ]
    previous_fingerprint = ""
    for item in sorted(source_segments, key=lambda value: (value["start_time"], value["end_time"])):
        text, applied = clean_text(item["text"])
        current_fingerprint = fingerprint(text)
        if not text or (current_fingerprint and current_fingerprint == previous_fingerprint):
            continue
        previous_fingerprint = current_fingerprint
        segment = dict(item)
        segment["text"] = text
        segments.append(segment)
        operations.extend(applied)
    return segments, list(dict.fromkeys(operations))


def join_fragment(left: str, right: str) -> str:
    if not left:
        return right
    left_han = bool(re.search(r"[\u3400-\u9fff]", left[-4:]))
    right_han = bool(re.search(r"[\u3400-\u9fff]", right[:4]))
    separator = "" if left_han and right_han else " "
    return left.rstrip() + separator + right.lstrip()


def split_oversized_text(text: str, target_chars: int, max_chars: int):
    """Split a run-on segment without claiming finer timestamps than the evidence provides."""
    pieces = []
    remaining = text.strip()
    minimum = max(40, int(target_chars * 0.6))
    while len(remaining) > max_chars:
        window = remaining[: max_chars + 1]
        split_at = -1
        for index in range(len(window) - 1, minimum - 1, -1):
            if window[index - 1] in SENTENCE_END:
                split_at = index
                break
        if split_at < 0:
            marker_positions = [window.rfind(marker, minimum) for marker in DISCOURSE_MARKERS]
            split_at = max(marker_positions, default=-1)
        if split_at < minimum:
            split_at = max_chars
        piece = remaining[:split_at].strip()
        if piece and piece[-1] not in SENTENCE_END:
            piece += "。" if re.search(r"[\u3400-\u9fff]", piece) else "."
        if piece:
            pieces.append(piece)
        remaining = remaining[split_at:].strip()
    if remaining:
        pieces.append(remaining)
    return pieces


def build_paragraphs(segments, target_chars=420, max_chars=760, max_seconds=180):
    paragraphs = []
    current_text = ""
    current_ids = []
    start_time = 0.0
    end_time = 0.0

    def flush():
        nonlocal current_text, current_ids, start_time, end_time
        if not current_text:
            return
        paragraphs.append(
            {
                "paragraph_id": f"paragraph-{len(paragraphs) + 1:04d}",
                "start_time": start_time,
                "end_time": end_time,
                "text": current_text.strip(),
                "evidence_segment_ids": list(current_ids),
            }
        )
        current_text, current_ids = "", []
        start_time = end_time = 0.0

    for segment in segments:
        if len(segment["text"]) > max_chars:
            flush()
            for piece in split_oversized_text(segment["text"], target_chars, max_chars):
                paragraphs.append(
                    {
                        "paragraph_id": f"paragraph-{len(paragraphs) + 1:04d}",
                        "start_time": segment["start_time"],
                        "end_time": segment["end_time"],
                        "text": piece,
                        "evidence_segment_ids": [segment["segment_id"]],
                    }
                )
            continue
        if not current_text:
            start_time = segment["start_time"]
        candidate = join_fragment(current_text, segment["text"])
        duration = max(segment["end_time"], end_time) - start_time
        if current_text and len(candidate) > max_chars:
            flush()
            start_time = segment["start_time"]
            candidate = segment["text"]
        current_text = candidate
        current_ids.append(segment["segment_id"])
        end_time = max(end_time, segment["end_time"])
        natural_end = current_text.endswith(tuple(SENTENCE_END))
        if (len(current_text) >= target_chars and natural_end) or duration >= max_seconds:
            flush()
    flush()
    return paragraphs


def load_language_decision(path: str | None, text: str, provider: str) -> dict:
    detected = detect_language(text)
    if path:
        decision = json.loads(Path(path).read_text(encoding="utf-8"))
        return {
            "declared_language": decision.get("declared_language", detected),
            "detected_language": decision.get("selected_language", detected),
            "output_language": decision.get("selected_language", detected),
            "language_decision_reason": decision["language_decision_reason"],
            "selected_candidate_id": decision.get("selected_candidate_id", ""),
        }
    return {
        "declared_language": detected,
        "detected_language": detected,
        "output_language": detected,
        "language_decision_reason": f"single {provider} transcript selected; detected_language={detected}",
        "selected_candidate_id": "",
    }


def readable_text(paragraphs):
    return "\n\n".join(item["text"] for item in paragraphs)


def render_markdown(output: dict) -> str:
    language = output["language"]
    lines = [
        "# Readable Transcript",
        "",
        f"> 输出语言：{language['output_language']}。{language['language_decision_reason']}",
        "> 本文只做断句、相邻去重和段落整理；未总结、扩写或改变作者立场。",
        "",
        "## 连续可读正文",
        "",
    ]
    for paragraph in output["paragraphs"]:
        lines.extend(
            [
                f"### {timestamp(paragraph['start_time'])}–{timestamp(paragraph['end_time'])}",
                "",
                paragraph["text"],
                "",
            ]
        )
    lines.extend(["## 时间证据", "", "<details>", "<summary>展开逐段时间证据</summary>", ""])
    for segment in output["segments"]:
        safe_text = html.escape(segment["text"])
        lines.append(
            f"- `{timestamp(segment['start_time'])}–{timestamp(segment['end_time'])}` "
            f"`{segment['segment_id']}` {safe_text}"
        )
    lines.extend(["", "</details>", ""])
    return "\n".join(lines)


def validate_formal_references(args):
    if args.scope != "production":
        return
    for name, value in (
        ("raw_reference", args.raw_reference),
        ("evidence_reference", args.evidence_reference or args.raw_reference),
        ("readable_reference", args.readable_reference),
    ):
        if not value or not LOGICAL_REFERENCE_RE.match(value):
            raise SystemExit(f"{name} must use guanlan:// in production scope")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--input-kind", choices=("provider", "merged", "timestamped", "markdown"), required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--material-id", default="")
    parser.add_argument("--revision-id", default="")
    parser.add_argument("--title", required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--provider", default="funasr")
    parser.add_argument("--raw-reference", required=True)
    parser.add_argument("--evidence-reference", default="")
    parser.add_argument("--readable-reference", default="")
    parser.add_argument("--language-decision")
    parser.add_argument("--quality", choices=("ready", "minor_revision", "major_revision"), required=True)
    parser.add_argument("--manual-cost", choices=("low", "medium", "high"), required=True)
    parser.add_argument("--paragraph-target-chars", type=int, default=420)
    parser.add_argument("--paragraph-max-chars", type=int, default=760)
    parser.add_argument("--scope", choices=("test", "production"), default="test")
    args = parser.parse_args()

    if not args.readable_reference:
        args.readable_reference = str(Path(args.output_md).resolve())
    validate_formal_references(args)

    if args.input_kind == "markdown":
        source_segments = parse_markdown(args.input)
    else:
        data = json.loads(Path(args.input).read_text(encoding="utf-8"))
        source_segments = parse_json(data)
    if not source_segments:
        raise SystemExit("no transcript segments found")

    segments, operations = normalize_segments(source_segments)
    if not segments:
        raise SystemExit("no readable transcript segments found")
    paragraphs = build_paragraphs(
        segments,
        target_chars=args.paragraph_target_chars,
        max_chars=args.paragraph_max_chars,
    )
    if any(len(segment["text"]) > args.paragraph_max_chars for segment in segments):
        operations.append("oversized_segments_conservatively_split_without_finer_timestamp_claim")
    readable = readable_text(paragraphs)
    language = load_language_decision(args.language_decision, readable, args.provider)
    reasons = {
        "ready": ["readable_transcript_ready_for_inbox"],
        "minor_revision": ["readable_but_source_ambiguities_require_human_review"],
        "major_revision": ["transcript_quality_insufficient_for_inbox"],
    }[args.quality]

    output = {
        "protocol": "readable-transcript-v1",
        "schema_version": "1.1.0",
        "task_id": args.task_id,
        "material_id": args.material_id,
        "revision_id": args.revision_id,
        "source": {"title": args.title, "url": args.source_url, "platform": args.platform},
        "provider": args.provider,
        "raw_reference": args.raw_reference,
        "evidence_reference": args.evidence_reference or args.raw_reference,
        "readable_reference": args.readable_reference,
        "language": language,
        "readable_transcript": readable,
        "paragraphs": paragraphs,
        "segments": segments,
        "operations": operations,
        "quality": {
            "level": args.quality,
            "review_required": True,
            "manual_revision_cost": args.manual_cost,
            "reasons": reasons,
        },
    }
    json_path, md_path = Path(args.output_json), Path(args.output_md)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(output), encoding="utf-8")


if __name__ == "__main__":
    main()
