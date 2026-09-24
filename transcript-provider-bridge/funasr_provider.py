#!/usr/bin/env python3

import argparse
import json
import os
import platform
import re
import sys
import time
from pathlib import Path


def timestamp_text(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def clean_text(value: str) -> str:
    text = " ".join(str(value or "").split()).strip()
    return re.sub(r"(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])", "", text)


def timestamp_bounds(result: dict):
    raw = result.get("timestamp") or result.get("timestamps") or []
    valid = []
    for item in raw:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            try:
                valid.append((float(item[0]) / 1000.0, float(item[1]) / 1000.0))
            except (TypeError, ValueError):
                continue
        elif isinstance(item, dict):
            try:
                valid.append((float(item["start"]), float(item["end"])))
            except (KeyError, TypeError, ValueError):
                continue
    if not valid:
        return None
    return min(item[0] for item in valid), max(item[1] for item in valid)


def build_segments(result: dict, text: str):
    sentence_info = result.get("sentence_info") or []
    segments = []
    for index, item in enumerate(sentence_info, start=1):
        segment_text = clean_text(item.get("sentence") or item.get("text"))
        if not segment_text:
            continue
        start = float(item.get("start", 0)) / 1000.0
        end = float(item.get("end", 0)) / 1000.0
        if end <= start:
            continue
        segments.append(
            {
                "segment_id": f"transcript-{index:03d}",
                "start_time": start,
                "end_time": end,
                "start_timestamp": timestamp_text(start),
                "end_timestamp": timestamp_text(end),
                "text": segment_text,
                "confidence": None,
            }
        )
    if segments:
        return segments
    bounds = timestamp_bounds(result)
    if not text or bounds is None or bounds[1] <= bounds[0]:
        return []
    return [
        {
            "segment_id": "transcript-001",
            "start_time": bounds[0],
            "end_time": bounds[1],
            "start_timestamp": timestamp_text(bounds[0]),
            "end_timestamp": timestamp_text(bounds[1]),
            "text": text,
            "confidence": None,
        }
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--audio", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    config_path = Path(args.config).expanduser().resolve()
    audio_path = Path(args.audio).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    model_path = Path(config["model_path"]).expanduser().resolve()

    if config.get("provider") != "funasr":
        raise RuntimeError("provider must be funasr")
    if config.get("model") != "paraformer-zh":
        raise RuntimeError("model must be paraformer-zh")
    if not config.get("enabled"):
        raise RuntimeError("provider is disabled")
    if not audio_path.is_file():
        raise RuntimeError(f"audio file not found: {audio_path}")
    if not model_path.is_dir():
        raise RuntimeError(f"external model path not found: {model_path}")
    if config.get("network_access") is not False:
        raise RuntimeError("Phase 15-C-R2 requires network_access=false")

    os.environ["MODELSCOPE_OFFLINE"] = "1"
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

    import funasr
    from funasr import AutoModel

    load_started = time.monotonic()
    model = AutoModel(
        model=str(model_path),
        device=config.get("device", "cpu"),
        disable_update=True,
        trust_remote_code=False,
    )
    load_seconds = time.monotonic() - load_started

    inference_started = time.monotonic()
    raw = model.generate(
        input=str(audio_path),
        batch_size=1,
        sentence_timestamp=True,
        output_timestamp=True,
        return_time_stamps=True,
    )
    inference_seconds = time.monotonic() - inference_started
    if not raw or not isinstance(raw[0], dict):
        raise RuntimeError("FunASR returned no result")

    item = raw[0]
    text = clean_text(item.get("text", ""))
    segments = build_segments(item, text)
    bounds = timestamp_bounds(item)
    status = "completed" if text and segments else "failed_missing_timestamp_or_text"
    timestamp = (
        {
            "start_time": bounds[0],
            "end_time": bounds[1],
            "start_timestamp": timestamp_text(bounds[0]),
            "end_timestamp": timestamp_text(bounds[1]),
            "unit": "seconds",
            "source": "funasr",
        }
        if bounds is not None
        else None
    )

    result = {
        "protocol": "transcript-provider-v1",
        "result_type": "TranscriptResult",
        "provider": "funasr",
        "model": config["model"],
        "language": "zh",
        "status": status,
        "source_reference": str(audio_path),
        "text": text,
        "timestamp": timestamp,
        "segments": segments,
        "timestamps": timestamp is not None,
        "provider_metadata": {
            "bridge_version": "funasr-provider-bridge-v1",
            "funasr_version": getattr(funasr, "__version__", "unknown"),
            "python_version": platform.python_version(),
            "python_executable": sys.executable,
            "model_path": str(model_path),
            "model_location": "external",
            "environment_location": "external",
            "device": config.get("device", "cpu"),
            "network_access": False,
            "load_seconds": round(load_seconds, 3),
            "inference_seconds": round(inference_seconds, 3),
        },
        "warnings": [] if status == "completed" else ["missing_text_or_provider_timestamp"],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    if status != "completed":
        raise RuntimeError(status)


if __name__ == "__main__":
    main()
