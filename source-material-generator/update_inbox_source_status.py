#!/usr/bin/env python3
"""Atomically update Source Material inbox frontmatter without changing its body."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


def sha(value: bytes):
    return hashlib.sha256(value).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--source-asset-reference", required=True)
    parser.add_argument("--source-asset-projection", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    path = Path(args.input).resolve()
    before = path.read_bytes()
    if sha(before) != args.expected_sha256:
        raise SystemExit("inbox projection baseline hash mismatch")
    text = before.decode("utf-8")
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise SystemExit("inbox projection frontmatter is invalid")
    end = text.find("\n---\n", 4)
    front = text[4:end].splitlines()
    body = text[end + 5:]
    updates = {
        "workflow_state": "processed",
        "source_asset_created": "true",
        "source_asset_reference": args.source_asset_reference,
        "source_asset_projection": f'"{args.source_asset_projection}"',
        "cleanup_candidate": "true",
        "learning_asset_created": "false",
    }
    found = set()
    output = []
    for line in front:
        if ":" in line:
            key = line.split(":", 1)[0].strip()
            if key in updates:
                output.append(f"{key}: {updates[key]}")
                found.add(key)
                continue
        output.append(line)
    for key, value in updates.items():
        if key not in found:
            output.append(f"{key}: {value}")
    after_text = "---\n" + "\n".join(output) + "\n---\n" + body
    after = after_text.encode("utf-8")
    if body.encode("utf-8") != after_text.split("\n---\n", 1)[1].encode("utf-8"):
        raise SystemExit("body changed during frontmatter update")
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    temporary.write_bytes(after)
    os.replace(temporary, path)
    report = {
        "protocol": "inbox-source-status-update-v1",
        "path": str(path),
        "before_sha256": sha(before),
        "after_sha256": sha(after),
        "body_sha256": sha(body.encode("utf-8")),
        "body_changed": False,
        "source_asset_reference": args.source_asset_reference,
        "source_asset_projection": args.source_asset_projection,
        "cleanup_candidate": True,
        "deleted": False,
    }
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

