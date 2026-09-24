#!/usr/bin/env python3
"""Complete a user-level capture by projecting a validated Source Material v3 to 00.

This module is deliberately provider-neutral.  A provider or Source creator is not
allowed to report user-level capture completion until this boundary succeeds.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
from pathlib import Path


def production_inbox() -> Path:
    value = os.environ.get("GUANLAN_VAULT_ROOT", "")
    if not value or not Path(value).is_absolute():
        raise ValueError("production requires absolute GUANLAN_VAULT_ROOT")
    return Path(value).resolve() / "00 收件箱"
TRANSCRIPT_SOURCE_PLATFORMS = {"douyin", "youtube", "bilibili", "xiaohongshu", "video", "audio"}
TRANSCRIPT_EVIDENCE_KINDS = {"transcript", "raw_transcript", "evidence_transcript"}
UNKNOWN_VALUES = {"", "unknown", "none", "unavailable", "null"}


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def atomic_write(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    try:
        with temporary.open("wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if temporary.exists():
            temporary.unlink()


def load_foundation(project_root: Path):
    target = project_root / "knowledge-foundation-stability" / "foundation_stability.py"
    spec = importlib.util.spec_from_file_location("foundation_stability_capture_completion", target)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def reference_entry(manifest: dict, reference: str) -> dict:
    matches = [item for item in manifest["entries"] if item["reference"] == reference]
    if len(matches) != 1:
        raise ValueError(f"reference must resolve exactly once in manifest: {reference}")
    return matches[0]


def read_object(asset_root: Path, entry: dict) -> bytes:
    target = (asset_root / entry["storage_relative_path"]).resolve()
    root = asset_root.resolve()
    if root not in target.parents:
        raise ValueError("manifest object escapes asset root")
    return target.read_bytes()


def readable_text(source: dict, manifest: dict, asset_root: Path) -> str:
    block = source["content"]["readable"]
    if block["storage"] == "inline":
        return block["text"].strip()
    entry = reference_entry(manifest, block["reference"])
    raw = read_object(asset_root, entry)
    media_type = str(block.get("media_type", entry.get("media_type", ""))).lower()
    if "json" in media_type:
        try:
            value = json.loads(raw.decode("utf-8"))
            if isinstance(value, dict):
                text = value.get("text") or value.get("readable_text") or value.get("content")
                if isinstance(text, str):
                    return text.strip()
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
    return raw.decode("utf-8", errors="replace").strip()


def time_index(source: dict, manifest: dict, asset_root: Path) -> list[dict]:
    raw_block = source["content"]["raw"]
    if raw_block["storage"] != "reference" or "json" not in raw_block.get("media_type", "").lower():
        return []
    try:
        value = json.loads(read_object(asset_root, reference_entry(manifest, raw_block["reference"])).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, OSError, ValueError):
        return []
    if not isinstance(value, dict) or not isinstance(value.get("segments"), list):
        return []
    result = []
    for item in value["segments"]:
        if not isinstance(item, dict) or not str(item.get("text", "")).strip():
            continue
        result.append({
            "start": item.get("start_timestamp", item.get("start_time", "")),
            "end": item.get("end_timestamp", item.get("end_time", "")),
            "text": " ".join(str(item["text"]).split()),
        })
    return result


def transcript_quality_result(source: dict, manifest: dict, asset_root: Path) -> dict | None:
    """Resolve the latest stable media transcript gate report, if present."""
    for history in reversed(source.get("lifecycle", {}).get("processing_history", [])):
        reference = str(history.get("report_reference", ""))
        if not reference:
            continue
        entry = reference_entry(manifest, reference)
        if entry.get("role") != "transcript_quality_report":
            continue
        value = json.loads(read_object(asset_root, entry).decode("utf-8"))
        if value.get("protocol") != "media-transcript-quality-v1":
            raise ValueError("transcript quality report protocol mismatch")
        if value.get("transcript_content_hash") != source["content"]["raw"]["content_hash"]:
            raise ValueError("transcript quality report does not bind current raw transcript")
        if value.get("readable_content_hash") != source["content"]["readable"]["content_hash"]:
            raise ValueError("transcript quality report does not bind current readable transcript")
        return value
    return None


def display_title(source: dict) -> str:
    title = str(source["source"].get("title", "")).strip()
    if title.lower() in UNKNOWN_VALUES:
        platform = source["source"].get("platform", "来源")
        source_id = source["source"].get("source_id", "未知")
        return f"{platform} 素材 {source_id}（标题待补充）"
    return title


def missing_items(source: dict, manifest: dict, asset_root: Path) -> list[str]:
    meta = source["source"]
    missing = []
    if str(meta.get("title", "")).strip().lower() in UNKNOWN_VALUES:
        missing.append("标题元数据缺失")
    if str(meta.get("author", "")).strip().lower() in UNKNOWN_VALUES:
        missing.append("作者元数据缺失")
    platform = str(meta.get("platform", "")).lower()
    evidence_kinds = {str(item.get("kind", "")).lower() for item in source.get("evidence", [])}
    transcript_expected = platform in TRANSCRIPT_SOURCE_PLATFORMS or any(
        item.get("kind") == "source_media" and str(item.get("reference", "")) for item in source.get("evidence", [])
    )
    if transcript_expected and not (evidence_kinds & TRANSCRIPT_EVIDENCE_KINDS):
        missing.append("Transcript 尚未取得")
    if transcript_expected and (evidence_kinds & TRANSCRIPT_EVIDENCE_KINDS):
        quality = transcript_quality_result(source, manifest, asset_root)
        if quality is None:
            missing.append("Transcript 尚未通过可用性质量闸门")
        elif not quality.get("ready_for_sorting"):
            missing.append(f"Transcript 质量未达整理门槛：{quality.get('quality_status', 'unknown')}")
    return missing


def completion_state(source: dict, missing: list[str]) -> str:
    blocking_missing = any(item.startswith("Transcript") for item in missing)
    if source["quality"].get("capture_status") == "partial" or blocking_missing:
        return "capture_partial"
    return "capture_completed"


def yaml_scalar(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def render_projection(source: dict, manifest: dict, asset_root: Path) -> tuple[str, str, list[str]]:
    text = readable_text(source, manifest, asset_root)
    missing = missing_items(source, manifest, asset_root)
    state = completion_state(source, missing)
    meta = source["source"]
    source_reference = f"guanlan://material/{source['material_id']}/revision/{source['revision_id']}"
    lines = [
        "---",
        "type: source_material_v3",
        "graph_group: 00_inbox",
        f"material_id: {source['material_id']}",
        f"revision_id: {source['revision_id']}",
        f"source_reference: {source_reference}",
        f"manifest_reference: {source['asset_manifest_reference']}",
        f"capture_completion_status: {state}",
        f"workflow_state: {'pending_review' if state == 'capture_completed' else 'transcript_retry_required'}",
        "review_required: true",
        f"platform: {yaml_scalar(meta['platform'])}",
        f"source_url: {yaml_scalar(meta['source_url'])}",
        f"missing_content: {yaml_scalar(missing)}",
        "---",
        "",
        f"# {display_title(source)}",
        "",
        "## 来源信息",
        "",
        f"- 平台：{meta['platform']}",
        f"- 作者：{meta['author']}",
        f"- 原始链接：{meta['source_url']}",
        f"- 来源 ID：`{meta['source_id']}`",
        f"- 采集时间：{meta['captured_at']}",
        f"- Material ID：`{source['material_id']}`",
        f"- Revision ID：`{source['revision_id']}`",
        "",
        "## 采集状态",
        "",
        f"- 用户级完成状态：`{state}`",
        f"- Source 状态：`{source['quality']['capture_status']}`",
        f"- 当前阶段：{'可进入人工整理' if state == 'capture_completed' else 'Transcript 补采或修复中'}",
        "",
        "## 当前可读内容",
        "",
        text or "当前仅保存已取得的来源与证据，尚无可读正文。",
        "",
        "## 原始内容与证据引用",
        "",
        f"- Source Material：`{source_reference}`",
        f"- Raw Content：`{source['content']['raw'].get('reference', 'inline')}`",
        f"- Readable Content：`{source['content']['readable'].get('reference', 'inline')}`",
        f"- Manifest：`{source['asset_manifest_reference']}`",
    ]
    index = time_index(source, manifest, asset_root)
    if index:
        lines += ["", "## 时间索引", "", "<details>", "<summary>展开时间证据</summary>", ""]
        for item in index:
            lines.append(f"- `{item['start']}–{item['end']}` {item['text']}")
        lines += ["", "</details>"]
    lines += ["", "## 质量与缺失项", ""]
    if missing:
        lines.extend(f"- {item}" for item in missing)
    else:
        lines.append("- 未发现阻断采集投影的缺失项。")
    for item in source["quality"].get("uncertainties", []):
        lines.append(f"- 不确定项：{item}")
    lines += [
        "",
        "## 后续处理状态",
        "",
        "- 本文件是采集事实投影，等待人工执行“整理”。",
        "- 本阶段不会自动进入 10/20/30/40/50，也不会生成知识资产。",
        "",
    ]
    return "\n".join(lines), state, missing


def frontmatter_value(path: Path, key: str) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    match = re.search(rf"(?m)^{re.escape(key)}:\s*(.+?)\s*$", text)
    if not match:
        return ""
    value = match.group(1).strip()
    try:
        decoded = json.loads(value)
        return str(decoded)
    except json.JSONDecodeError:
        return value.strip("'\"")


def find_existing(inbox: Path, material_id: str) -> list[Path]:
    return sorted(path for path in inbox.glob("*.md") if frontmatter_value(path, "material_id") == material_id)


def validate_destination(inbox: Path, requested: Path, scope: str) -> None:
    if requested.suffix.lower() != ".md" or requested.parent.resolve() != inbox.resolve():
        raise ValueError("projection must be a Markdown file directly inside the selected inbox")
    if scope == "production" and inbox.resolve() != production_inbox():
        raise ValueError("production projection must target the canonical 00 inbox")
    if scope == "test" and not str(inbox.resolve()).startswith(("/tmp/", "/private/tmp/")):
        raise ValueError("test inbox must be under /tmp")


def complete_capture(
    *, source_path: Path, manifest_path: Path, asset_root: Path, inbox: Path,
    requested_output: Path, project_root: Path, scope: str, fault: str = "",
    refresh_projection: bool = False,
) -> tuple[dict, int]:
    foundation = load_foundation(project_root)
    try:
        validate_destination(inbox, requested_output, scope)
        source = load_json(source_path)
        manifest = load_json(manifest_path)
        foundation.validate_source_material(source)
        checked = foundation.validate_manifest(manifest, asset_root, True, scope == "test")
        foundation.validate_source_against_manifest(source, manifest, checked)
        rendered, state, missing = render_projection(source, manifest, asset_root)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, foundation.ValidationFailure) as error:
        return ({"status": "capture_blocked", "reason": str(error), "projection_written": False}, 3)

    existing = find_existing(inbox, source["material_id"])
    if len(existing) > 1:
        return ({
            "status": "capture_incomplete_projection_pending",
            "reason": "multiple inbox projections share the same material_id",
            "projection_written": False,
            "conflicts": [str(path) for path in existing],
        }, 4)
    target = existing[0] if existing else requested_output
    desired = rendered.encode("utf-8")
    previous_revision = frontmatter_value(target, "revision_id") if target.exists() else ""
    if target.exists() and previous_revision == source["revision_id"]:
        if target.read_bytes() != desired:
            if refresh_projection:
                try:
                    atomic_write(target, desired)
                except OSError as error:
                    return ({
                        "status": "capture_incomplete_projection_pending",
                        "reason": f"projection refresh failed: {error}",
                        "projection_written": False,
                        "path": str(target),
                    }, 6)
                return ({
                    "status": state,
                    "action": "refreshed",
                    "material_id": source["material_id"],
                    "revision_id": source["revision_id"],
                    "path": str(target),
                    "projection_sha256": "sha256:" + sha256_bytes(desired),
                    "projection_written": True,
                    "missing_content": missing,
                }, 0)
            return ({
                "status": "capture_incomplete_projection_pending",
                "reason": "same revision projection content drift detected",
                "projection_written": False,
                "path": str(target),
            }, 5)
        return ({
            "status": "already_projected",
            "completion_state": state,
            "material_id": source["material_id"],
            "revision_id": source["revision_id"],
            "path": str(target),
            "projection_written": False,
            "missing_content": missing,
        }, 0)
    if fault == "projection_write_failure":
        return ({
            "status": "capture_incomplete_projection_pending",
            "reason": "injected projection write failure",
            "material_id": source["material_id"],
            "revision_id": source["revision_id"],
            "projection_written": False,
        }, 6)
    try:
        atomic_write(target, desired)
    except OSError as error:
        return ({
            "status": "capture_incomplete_projection_pending",
            "reason": f"projection write failed: {error}",
            "material_id": source["material_id"],
            "revision_id": source["revision_id"],
            "projection_written": False,
        }, 6)
    action = "updated" if previous_revision else "created"
    return ({
        "status": state,
        "action": action,
        "material_id": source["material_id"],
        "revision_id": source["revision_id"],
        "previous_revision_id": previous_revision,
        "source_reference": f"guanlan://material/{source['material_id']}/revision/{source['revision_id']}",
        "path": str(target),
        "projection_sha256": "sha256:" + sha256_bytes(desired),
        "projection_written": True,
        "missing_content": missing,
    }, 0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-material", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--asset-root", required=True)
    parser.add_argument("--inbox", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--scope", choices=("production", "test"), default="production")
    parser.add_argument("--fault", choices=("", "projection_write_failure"), default="")
    parser.add_argument("--refresh-projection", action="store_true")
    args = parser.parse_args()
    result, code = complete_capture(
        source_path=Path(args.source_material).resolve(),
        manifest_path=Path(args.manifest).resolve(),
        asset_root=Path(args.asset_root).resolve(),
        inbox=Path(args.inbox).resolve(),
        requested_output=Path(args.output).resolve(),
        project_root=Path(args.project_root).resolve(),
        scope=args.scope,
        fault=args.fault,
        refresh_projection=args.refresh_projection,
    )
    atomic_write(Path(args.result), canonical_json(result))
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
