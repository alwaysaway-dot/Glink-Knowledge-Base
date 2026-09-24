#!/usr/bin/env python3
"""Validate that a production inbox projection contains facts, not AI analysis."""

import argparse
import json
import re
from pathlib import Path

FORBIDDEN = re.compile(
    r"^#{1,6}\s+.*(?:初步摘要|摘要|核心观点|研究问题|值得关注的问题|建议去向|方法提炼|用户启发|AI\s*分析|AI\s*理解)",
    re.M,
)
REQUIRED = ("来源信息", "采集状态")


def validate(text: str):
    missing = [item for item in REQUIRED if item not in text]
    if missing: raise ValueError("capture projection missing factual sections: " + ",".join(missing))
    match = FORBIDDEN.search(text)
    if match: raise ValueError("capture projection contains forbidden analysis section: " + match.group(0))
    return {"status": "passed", "fact_boundary_clean": True, "forbidden_sections": []}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--input", required=True); parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        result = validate(Path(args.input).read_text(encoding="utf-8"))
        Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise SystemExit(f"ERROR: {error}") from error


if __name__ == "__main__": main()
