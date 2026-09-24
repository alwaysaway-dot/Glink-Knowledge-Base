#!/usr/bin/env python3
"""Classify source input into a Capture Provider; this router never captures media."""
import argparse
import ipaddress
import json
import re
from pathlib import Path
from urllib.parse import urlparse

PROVIDERS = {
    "youtube": {
        "provider": "youtube_yt_dlp", "support_status": "supported",
        "requirements": ["public_or_user_authorized_url", "yt_dlp", "ffmpeg_for_audio_extraction"],
        "next_stage": "media_acquisition",
    },
    "bilibili": {
        "provider": "bilibili_capture", "support_status": "blocked",
        "blocked_reason": "bilibili_capture_provider_not_configured",
        "required_capability": "authorized_bilibili_provider_with_platform_compliant_access_and_explicit_user_authorization",
        "next_stage": "none",
    },
    "xiaohongshu": {
        "provider": "xiaohongshu_capture", "support_status": "partial",
        "requirements": ["public_or_user_authorized_url", "platform_compliant_access", "media_normalization_when_needed"],
        "next_stage": "provider_preflight",
    },
    "local_file": {
        "provider": "local_file", "support_status": "supported",
        "requirements": ["readable_local_media_file"], "next_stage": "media_inspection",
    },
    "douyin": {
        "provider": "douyin", "support_status": "supported",
        "requirements": [
            "public_or_user_authorized_work",
            "guanlan_dedicated_browser_profile",
            "authenticated_browser_session",
            "chrome",
            "ffmpeg",
            "ffprobe",
        ],
        "next_stage": "media_acquisition",
    },
    "generic_web": {
        "provider": "generic_web_static", "support_status": "supported",
        "requirements": ["public_static_html", "scrapling_static_provider"],
        "next_stage": "static_web_capture",
    },
}

DOUYIN_URL_RE = re.compile(
    r"https://(?:v\.douyin\.com/[A-Za-z0-9_-]+/?|(?:www\.)?douyin\.com/video/\d+/?)(?:[^\s<>\"']*)?",
    re.IGNORECASE,
)


def extract_source(value):
    """Return one routable source from a URL or Douyin share text."""
    matches = []
    for match in DOUYIN_URL_RE.findall(value):
        candidate = match.rstrip("，。；、】）》」』")
        if candidate not in matches:
            matches.append(candidate)
    if len(matches) > 1:
        return None, "ambiguous_input"
    if len(matches) == 1:
        return matches[0], None
    return value.strip(), None


def classify(value):
    if value.startswith("file://") or value.startswith("/"):
        return "local_file"
    host = (urlparse(value).hostname or "").lower()
    if host == "v.douyin.com" or host == "douyin.com" or host == "www.douyin.com":
        if host == "v.douyin.com" or re.fullmatch(r"/video/\d+/?", urlparse(value).path):
            return "douyin"
    if host == "youtu.be" or host.endswith("youtube.com"):
        return "youtube"
    if host == "bilibili.com" or host.endswith("bilibili.com") or host == "b23.tv":
        return "bilibili"
    if host.endswith("xiaohongshu.com") or host == "xhslink.com":
        return "xiaohongshu"
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and host and not parsed.username and not parsed.password:
        if host == "localhost" or host.endswith(".localhost"):
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            pass
        return "generic_web"
    return None

def main():
    parser = argparse.ArgumentParser()
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--url")
    inputs.add_argument("--input")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    original_input = args.input if args.input is not None else args.url
    source_url, extraction_error = extract_source(original_input)
    platform = classify(source_url) if not extraction_error else None
    if extraction_error:
        result = {
            "protocol": "capture-router-v1",
            "original_input": original_input,
            "status": "blocked",
            "blocked_reason": extraction_error,
            "required_capability": "single_explicit_douyin_work_url",
        }
    elif not platform:
        result = {"protocol": "capture-router-v1", "source_url": source_url, "original_input": original_input, "status": "blocked", "blocked_reason": "unsupported_source", "required_capability": "registered_capture_provider"}
    else:
        result = {"protocol": "capture-router-v1", "source_url": source_url, "original_input": original_input, "platform": platform, **PROVIDERS[platform]}
        result["status"] = "routed" if result["support_status"] in ("supported", "partial") else "blocked"
    output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

if __name__ == "__main__":
    main()
