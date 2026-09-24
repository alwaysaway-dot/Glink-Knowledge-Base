#!/usr/bin/env python3
"""Schema-driven promotion of an approved Readable Source to Source Material v3.

Production rules are source-type aware and never contain title, duration, segment-count,
language, or minimum-length constants from a single fixture.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import importlib.util
import json
import os
import re
import shutil
import socket
import time
import uuid
from copy import deepcopy
from pathlib import Path


FORBIDDEN = re.compile(
    r"^#{1,6}\s+.*(?:AI\s*分析|AI\s*理解|摘要|核心观点|研究问题|值得关注|建议去向|"
    r"学习笔记|方法抽象|我的思考|论证结构|推荐)", re.M
)
DROP_ROLES = {"readable_transcript", "readable_transcript_record", "readable_original", "readable_source"}
TRANSCRIPT_SOURCE_TYPES = {"video", "audio"}
REVISION_FILES = (
    "source-material-v3.json",
    "readable-original.md",
    "source-asset-projection.md",
    "reference-manifest.json",
    "source-asset-validation.json",
    "source-asset-approval.json",
)
FAULT_ENV = "GUANLAN_SOURCE_PROMOTION_FAULT"
SIGNAL_FILE_ENV = "GUANLAN_SOURCE_PROMOTION_SIGNAL_FILE"


def canonical_json(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def fsync_directory(path: Path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write(path: Path, value: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    try:
        with temporary.open("wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_json(path: Path, value):
    atomic_write(path, canonical_json(value))


def object_relative(value_digest: str) -> str:
    return f"objects/sha256/{value_digest[:2]}/{value_digest}"


def commit(root: Path, value: bytes):
    value_digest = digest(value)
    target = root / object_relative(value_digest)
    if target.exists() and digest(target.read_bytes()) != value_digest:
        raise ValueError(f"object hash mismatch: {target}")
    if not target.exists():
        atomic_write(target, value)
    return value_digest, target


def reference(value_digest: str, kind="asset") -> str:
    return f"guanlan://{kind}/asset_sha256_{value_digest}"


def entry(value_digest, role, media_type, size, kind="asset"):
    return {
        "asset_id": "asset_sha256_" + value_digest,
        "content_hash": "sha256:" + value_digest,
        "media_type": media_type,
        "reference": reference(value_digest, kind),
        "role": role,
        "size_bytes": size,
        "storage_relative_path": object_relative(value_digest),
    }


def load_foundation(project_root: Path):
    path = project_root / "knowledge-foundation-stability" / "foundation_stability.py"
    spec = importlib.util.spec_from_file_location("foundation_stability_freeze", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_json(path: Path, label: str):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid {label}: {error}") from error


def fault(args, point: str):
    requested = os.environ.get(FAULT_ENV, "")
    if not requested:
        return
    if args.scope != "test":
        raise ValueError("Source Promotion fault injection is test-only")
    if requested != point:
        return
    signal_file = os.environ.get(SIGNAL_FILE_ENV, "")
    if signal_file:
        atomic_write(Path(signal_file), (point + "\n").encode("utf-8"))
    if point.startswith("pause_"):
        time.sleep(float(os.environ.get("GUANLAN_SOURCE_PROMOTION_PAUSE_SECONDS", "60")))
        return
    if point in {"file_write_failure", "disk_write_failure", "manifest_write_failure", "flush_failure"}:
        raise OSError(errno.ENOSPC, f"test fault: {point}")
    if point == "permission_failure":
        raise PermissionError(errno.EACCES, "test fault: final parent is not writable")
    os._exit(86)


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_lock(lock_path: Path) -> dict:
    try:
        value = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"active_unknown: invalid promotion lock {lock_path}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"active_unknown: invalid promotion lock {lock_path}")
    return value


def acquire_lock(lock_path: Path, revision_id: str) -> tuple[str, list[dict]]:
    transaction_id = "source_promotion_tx_" + uuid.uuid4().hex
    stale_locks = []
    metadata = {
        "protocol": "source-promotion-lock-v1",
        "revision_id": revision_id,
        "transaction_id": transaction_id,
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
        "created_at_epoch": time.time(),
    }
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            existing = read_lock(lock_path)
            if existing.get("revision_id") != revision_id:
                raise ValueError("active_unknown: promotion lock identity mismatch")
            if existing.get("hostname") != socket.gethostname():
                raise ValueError("active_unknown: promotion lock belongs to another host")
            pid = existing.get("pid")
            if not isinstance(pid, int) or pid <= 0:
                raise ValueError("active_unknown: promotion lock has no valid owner")
            if process_alive(pid):
                raise ValueError("concurrent_transaction_detected: Source Promotion is already active")
            stale_locks.append(existing)
            lock_path.unlink()
            fsync_directory(lock_path.parent)
            continue
        try:
            payload = canonical_json(metadata)
            os.write(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        fsync_directory(lock_path.parent)
        return transaction_id, stale_locks
    raise ValueError("concurrent_transaction_detected: could not acquire promotion lock")


def release_lock(lock_path: Path, transaction_id: str):
    try:
        existing = read_lock(lock_path)
        if existing.get("transaction_id") == transaction_id:
            lock_path.unlink()
            fsync_directory(lock_path.parent)
    except (OSError, ValueError):
        # A failed release is deliberately detectable as a stale lock on retry.
        pass


def inspect_revision(directory: Path, payloads: dict[str, bytes], foundation, asset_root: Path, scope: str) -> tuple[str, str]:
    if not directory.is_dir() or directory.is_symlink():
        return "partial", "revision path is not a regular directory"
    missing = [name for name in REVISION_FILES if not (directory / name).is_file()]
    if missing:
        return "partial", "missing required files: " + ", ".join(missing)
    for name, expected in payloads.items():
        try:
            actual = (directory / name).read_bytes()
        except OSError as error:
            return "partial", f"cannot read {name}: {error}"
        if actual != expected:
            return "conflict", f"content mismatch: {name}"
    try:
        source = json.loads(payloads["source-material-v3.json"])
        manifest = json.loads(payloads["reference-manifest.json"])
        foundation.validate_source_material(source)
        manifest_result = foundation.validate_manifest(manifest, asset_root, True, scope == "test")
        foundation.validate_source_against_manifest(source, manifest, manifest_result)
    except (ValueError, KeyError, json.JSONDecodeError, foundation.ValidationFailure) as error:
        return "partial", f"validation failed: {error}"
    return "valid", "required files, identity, manifest and hashes are valid"


def remove_staging(path: Path, revisions_dir: Path):
    if path.is_symlink() or path.parent.resolve() != revisions_dir.resolve() or ".staging." not in path.name:
        raise ValueError(f"refusing unsafe staging cleanup: {path}")
    shutil.rmtree(path)
    fsync_directory(revisions_dir)


def recover_staging(revisions_dir: Path, revision_id: str, payloads: dict[str, bytes], foundation, asset_root: Path, scope: str):
    valid = []
    removed = []
    pattern = f".{revision_id}.staging.*"
    for candidate in sorted(revisions_dir.glob(pattern)):
        state, detail = inspect_revision(candidate, payloads, foundation, asset_root, scope)
        if state == "conflict":
            raise ValueError(f"identity_conflict: stale staging differs from requested revision: {candidate}: {detail}")
        if state == "valid":
            valid.append(candidate)
        else:
            remove_staging(candidate, revisions_dir)
            removed.append({"path": str(candidate), "state": "stale_incomplete", "detail": detail})
    if len(valid) > 1:
        keep = valid[0]
        for duplicate in valid[1:]:
            remove_staging(duplicate, revisions_dir)
            removed.append({"path": str(duplicate), "state": "stale_valid_duplicate", "detail": "identical staging removed"})
        valid = [keep]
    return (valid[0] if valid else None), removed


def stage_revision(stage: Path, payloads: dict[str, bytes], args):
    stage.mkdir(mode=0o700)
    fault(args, "crash_after_staging_create")
    fault(args, "file_write_failure")
    atomic_write(stage / "source-material-v3.json", payloads["source-material-v3.json"])
    fault(args, "crash_after_first_file")
    fault(args, "pause_after_first_file")
    atomic_write(stage / "readable-original.md", payloads["readable-original.md"])
    atomic_write(stage / "source-asset-projection.md", payloads["source-asset-projection.md"])
    fault(args, "crash_midway_files")
    fault(args, "crash_before_manifest")
    fault(args, "disk_write_failure")
    fault(args, "manifest_write_failure")
    atomic_write(stage / "reference-manifest.json", payloads["reference-manifest.json"])
    fault(args, "crash_after_manifest")
    atomic_write(stage / "source-asset-validation.json", payloads["source-asset-validation.json"])
    fault(args, "crash_after_validation")
    atomic_write(stage / "source-asset-approval.json", payloads["source-asset-approval.json"])


def commit_revision(revision_dir: Path, stage: Path, payloads: dict[str, bytes], foundation, asset_root: Path, args):
    state, detail = inspect_revision(stage, payloads, foundation, asset_root, args.scope)
    if state != "valid":
        raise ValueError(f"staging_validation_failed: {detail}")
    if os.stat(stage).st_dev != os.stat(stage.parent).st_dev:
        raise ValueError("cross_filesystem_commit_forbidden")
    fault(args, "flush_failure")
    fsync_directory(stage)
    fault(args, "crash_before_atomic_rename")
    fault(args, "pause_before_atomic_rename")
    fault(args, "permission_failure")
    try:
        os.rename(stage, revision_dir)
    except OSError as error:
        if error.errno not in {errno.EEXIST, errno.ENOTEMPTY}:
            raise
        final_state, final_detail = inspect_revision(revision_dir, payloads, foundation, asset_root, args.scope)
        if final_state != "valid":
            raise ValueError(f"identity_conflict: concurrent final revision is invalid: {final_detail}")
        remove_staging(stage, stage.parent)
        return "already_committed"
    fault(args, "crash_after_atomic_rename")
    fsync_directory(revision_dir.parent)
    final_state, final_detail = inspect_revision(revision_dir, payloads, foundation, asset_root, args.scope)
    if final_state != "valid":
        raise ValueError(f"post_commit_validation_failed: {final_detail}")
    return "committed"


def validate_readable(text: str, source_type: str, quality: dict) -> dict:
    if not text.strip():
        raise ValueError("Readable Source is empty")
    if FORBIDDEN.search(text):
        raise ValueError("Readable Source contains analysis/generation content")
    if "/tmp/" in text or "/private/tmp/" in text:
        raise ValueError("Readable Source contains a temporary reference")
    if quality.get("protocol") != "source-promotion-quality-v1" or quality.get("status") != "passed":
        raise ValueError("a passed source-promotion-quality-v1 result is required")
    if quality.get("source_type") != source_type:
        raise ValueError("quality source_type mismatch")
    if quality.get("readability") not in {"ready", "minor_revision"}:
        raise ValueError("Readable Source quality is below promotion threshold")
    if quality.get("evidence_status") != "verified":
        raise ValueError("evidence must be verified before promotion")
    coverage = quality.get("coverage", {})
    if source_type not in TRANSCRIPT_SOURCE_TYPES and any(
        key in coverage for key in ("duration_seconds", "segment_count", "start_time", "end_time")
    ):
        raise ValueError("non-transcript sources must not fabricate duration or segment coverage")
    if source_type in TRANSCRIPT_SOURCE_TYPES:
        duration = coverage.get("duration_seconds")
        segments = coverage.get("segment_count")
        if duration is not None and (not isinstance(duration, (int, float)) or duration <= 0):
            raise ValueError("duration_seconds must be positive when present")
        if segments is not None and (not isinstance(segments, int) or segments <= 0):
            raise ValueError("segment_count must be positive when present")
    return {
        "source_type": source_type,
        "readable_chars": len(text),
        "coverage": coverage,
        "fact_boundary_clean": True,
        "temporary_reference_found": False,
    }


def render_projection(source: dict, readable: str, validation_ref: str, approval_ref: str, checks: dict) -> str:
    meta, quality = source["source"], source["quality"]
    source_ref = f"guanlan://material/{source['material_id']}/revision/{source['revision_id']}"
    title = meta["title"]
    lines = [
        "---", "type: source_asset", "asset_class: source", "asset_subtype: source_material",
        "workflow_state: active", "status: confirmed", "review_required: true",
        f"material_id: {source['material_id']}", f"revision_id: {source['revision_id']}",
        f"content_hash: {source['content']['readable']['content_hash']}",
        f"source_reference: {source_ref}", f"manifest_reference: {source['asset_manifest_reference']}",
        f"validation_reference: {validation_ref}", f"approval_reference: {approval_ref}", "---", "",
        f"# {title}｜可读原文", "", "## 来源信息", "",
        f"- 来源类型：{checks['source_type']}", f"- 平台：{meta['platform']}",
        f"- 作者：{meta['author']}", f"- 原始链接：{meta['source_url']}",
        f"- Material ID：`{source['material_id']}`", f"- Revision ID：`{source['revision_id']}`", "",
        "## 完整可读版原文", "", readable.strip(), "", "## 质量与不确定项", "",
        f"- 内容忠实度：`{quality['content_fidelity']}`", f"- Transcript质量：`{quality['transcript_quality']}`",
        "- 已通过来源类型对应的质量、证据、身份和事实边界检查。",
        "- 本文不包含总结、观点提炼、方法抽象、用户立场或AI分析正文。",
    ]
    coverage = checks.get("coverage", {})
    if coverage:
        lines.append(f"- 动态覆盖记录：`{json.dumps(coverage, ensure_ascii=False, sort_keys=True)}`")
    lines.extend(f"- 不确定项：{item}" for item in quality.get("uncertainties", []))
    lines.extend([
        "", "## 稳定来源与证据入口", "", f"- Source Material：`{source_ref}`",
        f"- Raw Content：`{source['content']['raw']['reference']}`",
        f"- Readable Source：`{source['content']['readable']['reference']}`",
        f"- Manifest：`{source['asset_manifest_reference']}`", f"- Validation：`{validation_ref}`",
        f"- Approval：`{approval_ref}`", "", "## 资产边界", "",
        "- 本文件是 Source Asset，不是 Learning Note。",
        "- 后续知识资产只能从本来源派生候选，不得覆盖或改变本资产类型。", "",
    ])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-material", required=True); parser.add_argument("--manifest", required=True)
    parser.add_argument("--readable-original", required=True); parser.add_argument("--quality-result", required=True)
    parser.add_argument("--approval-input", required=True); parser.add_argument("--source-type", required=True,
        choices=("video", "audio", "webpage", "article", "local_text", "pdf"))
    parser.add_argument("--asset-root", required=True); parser.add_argument("--material-dir", required=True)
    parser.add_argument("--project-root", required=True); parser.add_argument("--created-at", required=True)
    parser.add_argument("--output-summary", required=True); parser.add_argument("--scope", choices=("production", "test"), default="production")
    args = parser.parse_args()
    if os.environ.get(FAULT_ENV) and args.scope != "test":
        raise ValueError("Source Promotion fault injection is test-only")
    paths = {name: Path(getattr(args, name.replace("-", "_"))).resolve() for name in ()}
    source_path, manifest_path = Path(args.source_material).resolve(), Path(args.manifest).resolve()
    readable_path, quality_path = Path(args.readable_original).resolve(), Path(args.quality_result).resolve()
    approval_path = Path(args.approval_input).resolve(); asset_root = Path(args.asset_root).resolve()
    material_dir, project_root = Path(args.material_dir).resolve(), Path(args.project_root).resolve()
    source, old_manifest = load_json(source_path, "source material"), load_json(manifest_path, "manifest")
    quality, approval = load_json(quality_path, "quality result"), load_json(approval_path, "approval")
    readable_bytes = readable_path.read_bytes(); readable_text = readable_bytes.decode("utf-8")
    foundation = load_foundation(project_root)
    foundation.validate_source_material(source)
    manifest_result = foundation.validate_manifest(old_manifest, asset_root, True, args.scope == "test")
    foundation.validate_source_against_manifest(source, old_manifest, manifest_result)
    checks = validate_readable(readable_text, args.source_type, quality)
    readable_digest = digest(readable_bytes)
    if approval.get("protocol") != "source-promotion-approval-v1" or approval.get("confirmed") is not True:
        raise SystemExit("explicit source-promotion-approval-v1 confirmation is required")
    if approval.get("material_id") != source["material_id"] or approval.get("revision_id") != source["revision_id"]:
        raise SystemExit("approval source identity mismatch")
    if approval.get("readable_content_hash") != "sha256:" + readable_digest or approval.get("reviewer") != "user":
        raise SystemExit("approval must bind the exact readable content hash and reviewer=user")
    readable_digest, readable_object = commit(asset_root, readable_bytes)
    promoted = deepcopy(source)
    promoted["content"]["readable"] = {
        "storage": "reference", "reference": reference(readable_digest),
        "content_hash": "sha256:" + readable_digest, "media_type": "text/markdown",
        "operations": quality.get("operations", ["source_order_preserved", "readability_repair", "no_summary", "no_analysis"]),
    }
    promoted["quality"].update({
        "content_fidelity": quality.get("content_fidelity", promoted["quality"]["content_fidelity"]),
        "transcript_quality": quality.get("transcript_quality", "not_applicable" if args.source_type not in TRANSCRIPT_SOURCE_TYPES else "readable"),
        "review_required": True,
        "uncertainties": quality.get("uncertainties", promoted["quality"].get("uncertainties", [])),
    })
    promoted["lifecycle"]["status"] = "reviewed"; promoted["lifecycle"]["review_status"] = "reviewed"
    promoted["lifecycle"]["updated_at"] = args.created_at
    promoted["lifecycle"]["processing_history"].append({
        "processor": "schema-driven-source-promotion", "version": "pre-v1.2",
        "time": args.created_at, "source_type": args.source_type, "approval": "explicit_user_confirmation",
    })
    promoted["understanding_sidecar_reference"] = ""
    promoted["revision_id"] = foundation.revision_id(promoted)
    promoted["asset_manifest_reference"] = f"guanlan://manifest/{promoted['material_id']}/{promoted['revision_id']}"
    source_ref = f"guanlan://material/{promoted['material_id']}/revision/{promoted['revision_id']}"
    approval_record = {
        **approval, "protocol": "source-asset-approval-v1", "schema_version": "1.0.0",
        "previous_revision_id": source["revision_id"], "revision_id": promoted["revision_id"],
        "confirmed_at": approval.get("confirmed_at", args.created_at), "source_reference": source_ref,
    }
    approval_bytes = canonical_json(approval_record); approval_digest, approval_object = commit(asset_root, approval_bytes)
    approval_ref = reference(approval_digest, "report")
    validation = {
        "protocol": "source-asset-validation-v1", "schema_version": "1.0.0", "status": "passed",
        "material_id": promoted["material_id"], "revision_id": promoted["revision_id"],
        "content_hash": promoted["content"]["readable"]["content_hash"], "source_reference": source_ref,
        "manifest_reference": promoted["asset_manifest_reference"], "checks": checks, "validated_at": args.created_at,
    }
    validation_bytes = canonical_json(validation); validation_digest, validation_object = commit(asset_root, validation_bytes)
    validation_ref = reference(validation_digest, "report")
    entries = [deepcopy(item) for item in old_manifest["entries"] if item.get("role") not in DROP_ROLES]
    entries += [entry(readable_digest, "readable_source", "text/markdown", len(readable_bytes)),
                entry(validation_digest, "source_asset_validation", "application/json", len(validation_bytes), "report"),
                entry(approval_digest, "source_asset_approval", "application/json", len(approval_bytes), "report")]
    manifest = {"protocol": "reference-manifest-v1", "schema_version": "1.0.0",
                "material_id": promoted["material_id"], "revision_id": promoted["revision_id"],
                "entries": list({item["reference"]: item for item in entries}.values())}
    revision_dir = material_dir / "revisions" / promoted["revision_id"]
    projection = render_projection(promoted, readable_text, validation_ref, approval_ref, checks).encode("utf-8")
    payloads = {
        "source-material-v3.json": canonical_json(promoted),
        "readable-original.md": readable_bytes,
        "source-asset-projection.md": projection,
        "reference-manifest.json": canonical_json(manifest),
        "source-asset-validation.json": validation_bytes,
        "source-asset-approval.json": approval_bytes,
    }
    revisions_dir = revision_dir.parent
    revisions_dir.mkdir(parents=True, exist_ok=True)
    lock_path = revisions_dir / f".{promoted['revision_id']}.promotion.lock"
    transaction_id, stale_locks = acquire_lock(lock_path, promoted["revision_id"])
    recovery = {"stale_locks": stale_locks, "staging_actions": []}
    try:
        stale_valid, staging_actions = recover_staging(
            revisions_dir, promoted["revision_id"], payloads, foundation, asset_root, args.scope
        )
        recovery["staging_actions"] = staging_actions
        if revision_dir.exists():
            state, detail = inspect_revision(revision_dir, payloads, foundation, asset_root, args.scope)
            if state == "partial":
                raise ValueError(f"partial_revision_detected: {revision_dir}: {detail}")
            if state == "conflict":
                raise ValueError(f"identity_conflict: revision exists with different content: {detail}")
            if stale_valid:
                remove_staging(stale_valid, revisions_dir)
                recovery["staging_actions"].append({
                    "path": str(stale_valid), "state": "stale_valid_after_commit", "detail": "final revision already committed"
                })
            transaction_status = "already_committed"
        else:
            stage = stale_valid
            if stage is None:
                stage = revisions_dir / f".{promoted['revision_id']}.staging.{transaction_id}"
                stage_revision(stage, payloads, args)
            else:
                recovery["staging_actions"].append({
                    "path": str(stage), "state": "stale_valid", "detail": "revalidated and selected for atomic commit"
                })
            transaction_status = commit_revision(revision_dir, stage, payloads, foundation, asset_root, args)
        result_status = "already_promoted" if transaction_status == "already_committed" else "promoted"
    finally:
        release_lock(lock_path, transaction_id)
    foundation.validate_source_material(promoted)
    manifest_check = foundation.validate_manifest(manifest, asset_root, True, args.scope == "test")
    foundation.validate_source_against_manifest(promoted, manifest, manifest_check)
    summary = {
        "protocol": "source-promotion-result-v1", "status": result_status,
        "source_type": args.source_type, "material_id": promoted["material_id"],
        "previous_revision_id": source["revision_id"], "revision_id": promoted["revision_id"],
        "revision_directory": str(revision_dir), "source_asset_projection": str(revision_dir / "source-asset-projection.md"),
        "readable_reference": reference(readable_digest), "validation_reference": validation_ref,
        "approval_reference": approval_ref, "checks": checks,
        "objects": [str(readable_object), str(validation_object), str(approval_object)],
        "transaction": {
            "transaction_id": transaction_id,
            "idempotency_key": f"{promoted['material_id']}:{promoted['revision_id']}",
            "status": transaction_status,
            "atomic_directory_rename": True,
            "same_filesystem_staging": True,
            "recovery": recovery,
        },
    }
    atomic_json(Path(args.output_summary), summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, UnicodeDecodeError, ValueError, KeyError) as error:
        raise SystemExit(f"ERROR: {error}") from error
