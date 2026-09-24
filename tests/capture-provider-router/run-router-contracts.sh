#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${1:?usage: run-router-contracts.sh OUTPUT_DIR}"
mkdir -p "$OUT"
python3 "$ROOT/capture-provider-router/source_router.py" --url 'https://www.youtube.com/watch?v=ABCdef12345' --output "$OUT/youtube.json"
python3 "$ROOT/capture-provider-router/source_router.py" --url 'https://www.bilibili.com/video/BV1SYNTH1234' --output "$OUT/bilibili.json"
python3 "$ROOT/capture-provider-router/source_router.py" --url 'https://www.xiaohongshu.com/explore/synthetic1234567890' --output "$OUT/xiaohongshu.json"
python3 "$ROOT/capture-provider-router/source_router.py" --url 'file:///tmp/example.mp4' --output "$OUT/local.json"
python3 "$ROOT/capture-provider-router/source_router.py" --url 'https://v.douyin.com/synthetic123/' --output "$OUT/douyin-short.json"
python3 "$ROOT/capture-provider-router/source_router.py" --input '复制打开抖音，查看【合成测试素材】 https://v.douyin.com/synthetic123/' --output "$OUT/douyin-share-text.json"
python3 "$ROOT/capture-provider-router/source_router.py" --input 'ordinary text mentioning douyin but containing no URL' --output "$OUT/plain-text.json"
python3 "$ROOT/capture-provider-router/source_router.py" --url 'https://example.org/public-article' --output "$OUT/generic-web.json"
