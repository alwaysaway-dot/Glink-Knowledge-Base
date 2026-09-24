#!/usr/bin/env python3
"""Render a Readable-first Source Material v3 Markdown projection."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
from pathlib import Path


def production_inbox() -> Path:
    value = os.environ.get("GUANLAN_VAULT_ROOT", "")
    if not value or not Path(value).is_absolute():
        raise ValueError("production requires absolute GUANLAN_VAULT_ROOT")
    return Path(value).resolve() / "00 收件箱"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def timestamp(seconds):
    total = int(max(0, float(seconds)))
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def render(source_material: dict, readable: dict) -> str:
    if source_material.get("protocol") != "source-material-v3":
        raise ValueError("source material must use source-material-v3")
    if readable.get("protocol") != "readable-transcript-v1":
        raise ValueError("readable input must use readable-transcript-v1")
    if readable.get("material_id") and readable["material_id"] != source_material["material_id"]:
        raise ValueError("readable material_id mismatch")
    if readable.get("revision_id") and readable["revision_id"] != source_material["revision_id"]:
        raise ValueError("readable revision_id mismatch")

    source = source_material["source"]
    content = source_material["content"]
    quality = source_material["quality"]
    lifecycle = source_material["lifecycle"]
    language = readable["language"]
    lines = [
        "---",
        "type: source_material_v3",
        f"material_id: {source_material['material_id']}",
        f"revision_id: {source_material['revision_id']}",
        f"manifest_reference: {source_material['asset_manifest_reference']}",
        f"readable_reference: {content['readable']['reference']}",
        f"evidence_reference: {readable['evidence_reference']}",
        f"language: {language['output_language']}",
        f"status: {lifecycle['status']}",
        f"review_status: {lifecycle['review_status']}",
        "review_required: true",
        f"source_url: {source['source_url']}",
        "---",
        "",
        f"# {source['title']}",
        "",
        "## 来源信息",
        "",
        f"- 平台：{source['platform']}",
        f"- 作者：{source['author']}",
        f"- 原始链接：{source['source_url']}",
        f"- 发布时间：{source.get('published_at', '')}",
        f"- 采集时间：{source['captured_at']}",
        f"- Material ID：`{source_material['material_id']}`",
        f"- Revision ID：`{source_material['revision_id']}`",
        "",
        "## 连续可读正文",
        "",
        "> 以下内容由 Evidence Transcript 保守整理为连续段落；未总结、扩写或改变作者立场。",
        "",
    ]
    for paragraph in readable["paragraphs"]:
        lines.extend(
            [
                f"### {timestamp(paragraph['start_time'])}–{timestamp(paragraph['end_time'])}",
                "",
                paragraph["text"],
                "",
            ]
        )

    lines.extend(
        [
            "## 语言与质量说明",
            "",
            f"- 输出语言：`{language['output_language']}`",
            f"- 语言决策：{language['language_decision_reason']}",
            f"- Transcript 质量：`{quality['transcript_quality']}`",
            "- 是否需要人工复核：`true`",
        ]
    )
    for uncertainty in quality.get("uncertainties", []):
        lines.append(f"- 不确定项：{uncertainty}")

    lines.extend(["", "## 时间证据", "", "<details>", "<summary>展开逐段时间证据</summary>", ""])
    for segment in readable["segments"]:
        safe_text = html.escape(segment["text"])
        lines.append(
            f"- `{timestamp(segment['start_time'])}–{timestamp(segment['end_time'])}` "
            f"`{segment['segment_id']}` {safe_text}"
        )
    lines.extend(
        [
            "",
            "</details>",
            "",
            "## 原始内容与证据引用",
            "",
            f"- Raw Transcript：`{content['raw']['reference']}`",
            f"- Readable Transcript：`{content['readable']['reference']}`",
            f"- Evidence Transcript：`{readable['evidence_reference']}`",
            f"- Manifest：`{source_material['asset_manifest_reference']}`",
            "",
            "## 处理记录",
            "",
        ]
    )
    for item in lifecycle.get("processing_history", []):
        lines.append(
            f"- {item.get('time', item.get('created_at', ''))} "
            f"{item.get('processor', 'unknown')} {item.get('version', '')}".rstrip()
        )
    lines.extend(
        [
            "",
            "## 人工审阅状态",
            "",
            f"- 当前状态：`{lifecycle['status']}`",
            f"- 审阅状态：`{lifecycle['review_status']}`",
            "- 本投影不会自动生成或写入学习笔记。",
            "",
        ]
    )
    return "\n".join(lines)


def validate_output(output: Path, scope: str, asset_root: str):
    resolved = output.resolve()
    if resolved.suffix != ".md":
        raise ValueError("output must be Markdown")
    if scope == "production" and resolved.parent != production_inbox():
        raise ValueError("production projection must be written directly inside 00 inbox")
    if scope == "test" and not str(resolved).startswith(("/tmp/", "/private/tmp/")):
        raise ValueError("test projection must be under /tmp")
    if scope == "asset":
        if not asset_root:
            raise ValueError("asset scope requires --asset-root")
        root = Path(asset_root).resolve()
        if resolved != root and root not in resolved.parents:
            raise ValueError("asset projection must stay inside asset root")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-material", required=True)
    parser.add_argument("--readable", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--scope", choices=("test", "asset", "production"), default="test")
    parser.add_argument("--asset-root", default="")
    parser.add_argument("--replace-projection", action="store_true")
    parser.add_argument("--expected-existing-sha256", default="")
    args = parser.parse_args()
    output = Path(args.output)
    validate_output(output, args.scope, args.asset_root)
    if output.exists():
        if not args.replace_projection:
            raise SystemExit("refusing to overwrite existing projection")
        actual = sha256_file(output)
        if not args.expected_existing_sha256 or actual != args.expected_existing_sha256:
            raise SystemExit("existing projection hash does not match expected baseline")
    source_material = json.loads(Path(args.source_material).read_text(encoding="utf-8"))
    readable = json.loads(Path(args.readable).read_text(encoding="utf-8"))
    text = render(source_material, readable)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + f".tmp-{os.getpid()}")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(output)


if __name__ == "__main__":
    main()
