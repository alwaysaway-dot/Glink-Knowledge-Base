#!/usr/bin/env python3
"""Generate a source_material Markdown file only inside the configured Vault inbox."""
import argparse
import json
import os
from pathlib import Path

def production_inbox() -> Path:
    value = os.environ.get("GUANLAN_VAULT_ROOT", "")
    if not value or not Path(value).is_absolute():
        raise ValueError("production requires absolute GUANLAN_VAULT_ROOT")
    return Path(value).resolve() / "00 收件箱"


def timestamp(seconds):
    total = int(float(seconds))
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--readable-json", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--captured-at", required=True)
    parser.add_argument("--source-type", choices=("video", "audio"), default="video")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if output.parent != production_inbox() or output.suffix != ".md":
        raise SystemExit("refusing write outside the Vault 00 inbox root")
    data = json.loads(Path(args.readable_json).read_text(encoding="utf-8"))
    quality = data["quality"]
    if quality["level"] == "major_revision":
        raise SystemExit("quality gate blocked this source material")
    source = data["source"]
    timeline = "\n".join(f"- {timestamp(s['start_time'])}–{timestamp(s['end_time'])}" for s in data["segments"])
    warnings = "\n".join(f"- {item}" for item in quality["reasons"])
    text = f'''---
type: source_material
source_type: {args.source_type}
provider: {data["provider"]}
status: captured
quality: {quality["level"]}
review_required: {str(quality["review_required"]).lower()}
task_id: {data["task_id"]}
captured_at: {args.captured_at}
---

# {source["title"]}

## 来源信息

- 平台：{source["platform"]}
- 原始链接：{source["url"]}
- 原始转录引用：{data["raw_reference"]}
- 可读转录引用：{data["readable_reference"]}
- 处理方式：Transcript Intelligence Layer（保守整理；不总结、不改写观点）

## Transcript

{data["readable_transcript"]}

## 时间引用

{timeline}

## 质量报告

- 质量等级：{quality["level"]}
- 是否需要人工复核：{str(quality["review_required"]).lower()}
- 预估人工修改成本：{quality["manual_revision_cost"]}
- 处理操作：{", ".join(data["operations"])}
{warnings}

## 后续处理状态

- 当前仅作为来源素材进入 `00 收件箱`。
- 未生成学习笔记，未写入 `20 学习笔记`，未自动正式入库。
'''
    output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
