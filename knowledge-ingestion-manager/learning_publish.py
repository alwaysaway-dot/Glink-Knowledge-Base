#!/usr/bin/env python3
"""Transactional, identity-idempotent publication of Learning Notes to Vault/20 only."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PUBLISHER_DIR = Path(__file__).resolve().parent
if str(PUBLISHER_DIR) not in sys.path:
    sys.path.insert(0, str(PUBLISHER_DIR))
from publisher_core import atomic_json, atomic_write, canonical, digest, has_temp, resolve_target, strip_frontmatter
from approval_binding import prepare as prepare_binding, verify as verify_binding
from publisher_transaction import archive_retryable, commit, durable_json, file_hash, guarded_abort, inject, ledger_lock, recover_pending
from publisher_relation_projection import verify_managed_projection


TEMP_MARKERS = ("/tmp/", "/private/tmp/", "file:///tmp/", "file:///private/tmp/")
STABLE_REF = re.compile(r"^guanlan://(?:asset|material|manifest|report)/")


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load(path: Path, label: str):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid {label}: {error}") from error


def markdown_h1(markdown: str) -> str:
    headings = [line[2:].strip() for line in markdown.splitlines() if line.startswith("# ")]
    if len(headings) != 1 or not headings[0] or headings[0].lower() == "unknown":
        raise ValueError("published Learning Note requires one non-empty H1")
    return headings[0]


def validate_inputs(args, draft, confirmation, quality, source, candidate=None):
    if draft.get("protocol") != "knowledge-asset-draft-v1": raise ValueError("draft protocol mismatch")
    asset = draft.get("asset", {})
    if asset.get("type") != "learning_note" or asset.get("status") != "draft":
        raise ValueError("only unconfirmed learning_note draft is publishable")
    if confirmation.get("protocol") != "knowledge-publish-approval-v1" or confirmation.get("confirmed") is not True:
        raise ValueError("explicit knowledge-publish-approval-v1 is required")
    if confirmation.get("reviewer") != "user" or not confirmation.get("confirmed_at"):
        raise ValueError("approval must be explicit reviewer=user confirmation")
    if quality.get("protocol") != "knowledge-publish-quality-v1" or quality.get("status") != "passed":
        raise ValueError("passed knowledge-publish-quality-v1 is required")
    if source.get("protocol") != "source-material-v3": raise ValueError("Source Material v3 is required")
    if candidate is not None:
        if candidate.get("protocol") != "derivative-candidate-v1" or candidate.get("asset_type") != "learning_note":
            raise ValueError("Learning publisher candidate protocol mismatch")
        if candidate.get("status") != "publishable":
            raise ValueError("Learning candidate is not publishable")
        if candidate.get("candidate_id") != asset.get("asset_id"):
            raise ValueError("Learning candidate/draft identity mismatch")
    source_identity = draft.get("source", {})
    if source_identity.get("material_id") != source.get("material_id"):
        raise ValueError("draft/source material identity mismatch")
    if confirmation.get("source_asset_id") != source["material_id"] or confirmation.get("source_revision_id") != source["revision_id"]:
        raise ValueError("approval/source revision mismatch")
    if has_temp(draft) or has_temp(confirmation) or has_temp(quality) or has_temp(source) or (candidate is not None and has_temp(candidate)):
        raise ValueError("temporary reference is forbidden")
    for value in confirmation.get("stable_references", []):
        if not isinstance(value, str) or not STABLE_REF.match(value):
            raise ValueError(f"unstable reference: {value}")
    if args.scope == "production":
        for path_value in (args.generated, args.draft, args.confirmation, args.quality, args.source_material, getattr(args, "candidate", None)):
            if not path_value:
                continue
            resolved = str(Path(path_value).resolve())
            if resolved.startswith(("/tmp/", "/private/tmp/")):
                raise ValueError(f"production input cannot originate from temporary path: {resolved}")


def identity(body: bytes, source: dict, subtype="learning_note"):
    body_hash = digest(body)
    asset_id = "asset_sha256_" + body_hash
    revision_payload = canonical({
        "asset_id": asset_id, "asset_subtype": subtype, "content_hash": "sha256:" + body_hash,
        "source_asset_id": source["material_id"], "source_revision_id": source["revision_id"],
    })
    return asset_id, "revision_sha256_" + digest(revision_payload), "sha256:" + body_hash


def frontmatter(asset_id, revision_id, content_hash, source, confirmation, stable_refs):
    source_ref = f"guanlan://material/{source['material_id']}/revision/{source['revision_id']}"
    lines = [
        "---", "type: learning_note", "asset_class: knowledge", "asset_subtype: learning_note",
        "workflow_state: active", "status: published", f"asset_id: {asset_id}",
        f"revision_id: {revision_id}", f"content_hash: {content_hash}",
        f"source_asset: {source['material_id']}", f"source_revision: {source['revision_id']}",
        f"source_reference: {source_ref}", f"published_at: {confirmation['confirmed_at']}",
        "confirmation_mode: explicit_user_instruction", "graph_group: 20_learning",
    ]
    for index, value in enumerate(stable_refs, 1): lines.append(f"governance_reference_{index}: {value}")
    return "\n".join(lines + ["---", "", ""]).encode("utf-8")


def _publish_locked(args):
    draft = load(Path(args.draft), "draft"); confirmation = load(Path(args.confirmation), "confirmation")
    quality = load(Path(args.quality), "quality"); source = load(Path(args.source_material), "source material")
    candidate = load(Path(args.candidate), "candidate") if args.candidate else None
    validate_inputs(args, draft, confirmation, quality, source, candidate)
    target_dir = resolve_target(Path(args.vault_root), "learning_note", args.target_folder, args.scope)
    body_text = strip_frontmatter(Path(args.generated).read_text(encoding="utf-8")).strip() + "\n"
    generated_title = markdown_h1(body_text)
    expected_title = (candidate or {}).get("content", {}).get("title") or draft.get("content", {}).get("title")
    if expected_title is not None and (not isinstance(expected_title, str) or expected_title.strip() != generated_title):
        raise ValueError("generation_metadata_inconsistent: Markdown H1 must equal candidate content.title")
    body = body_text.encode("utf-8")
    if not body_text.strip(): raise ValueError("generated Learning Note is empty")
    if has_temp(body_text): raise ValueError("Learning Note contains temporary reference")
    asset_id, revision_id, content_hash = identity(body, source)
    if confirmation.get("knowledge_content_hash") != content_hash:
        raise ValueError("approval does not bind the exact knowledge content hash")
    stable_refs = confirmation.get("stable_references", [])
    filename = args.filename
    if not filename.endswith(".md") or Path(filename).name != filename:
        raise ValueError("filename must be one safe Markdown basename")
    target = target_dir / filename
    binding_candidate = candidate or {
        "candidate_id": draft.get("asset", {}).get("asset_id"), "asset_type": "learning_note", "status": "publishable",
        "source": {"material_id": source["material_id"], "revision_id": source["revision_id"]},
        "content": {"title": generated_title, "markdown": body_text},
        "provenance": {"stable_references": stable_refs}, "admission": {"status": quality.get("status")},
    }
    binding_kwargs = {"candidate": binding_candidate, "source": source, "target_folder": args.target_folder,
                      "filename": filename, "body": body_text, "title": generated_title, "quality": quality}
    target_bytes = frontmatter(asset_id, revision_id, content_hash, source, confirmation, stable_refs) + body
    governance = Path(args.asset_root).resolve() / "governance" / "knowledge-publish"
    receipts = governance / "original-receipts"; transactions = governance / "transactions"
    index_path = governance / "publish-index-v1.json"
    index = load(index_path, "publish index") if index_path.exists() else {
        "protocol": "knowledge-publish-index-v1", "schema_version": "1.0.0", "publications": []
    }
    same = [item for item in index["publications"] if item.get("knowledge_asset_id") == asset_id and item.get("source_revision_id") == source["revision_id"]]
    if len(same) > 1: raise ValueError("identity conflict: duplicate index entries")
    if same:
        item = same[0]; existing = Path(item["target_path"])
        if (existing.resolve() != target.resolve() or item.get("source_asset_id") != source["material_id"] or
                item.get("source_revision_id") != source["revision_id"] or
                item.get("knowledge_revision_id") != revision_id or item.get("content_hash") != content_hash):
            raise ValueError("identity conflict: published target or source differs")
        if not existing.is_file() or existing.is_symlink():
            raise ValueError("identity conflict: published Markdown missing or unsafe")
        receipt_path = Path(item["receipt_path"])
        existing_receipt = load(receipt_path, "existing receipt") if receipt_path.is_file() else {}
        if (receipt_path.resolve().parent != receipts.resolve() or
                existing_receipt.get("receipt_type") != "original_publish" or
                existing_receipt.get("validation_result") != "committed" or
                existing_receipt.get("knowledge_asset_id") != asset_id or
                existing_receipt.get("knowledge_revision_id") != revision_id or
                existing_receipt.get("source_asset_id") != source["material_id"] or
                existing_receipt.get("source_revision_id") != source["revision_id"] or
                existing_receipt.get("content_hash") != content_hash or
                existing_receipt.get("projection_hash") != "sha256:" + digest(target_bytes) or
                existing_receipt.get("target_path") != str(target) or
                existing_receipt.get("transaction_id") != item.get("transaction_id")):
            raise ValueError("identity conflict: original publish receipt differs from approved publication")
        verify_managed_projection(original=target_bytes, current=existing.read_bytes(), asset_id=asset_id,
                                  target=target, asset_root=Path(args.asset_root), vault_root=Path(args.vault_root))
        if confirmation.get("approval_binding") is not None:
            verify_binding(confirmation, **binding_kwargs)
        elif existing_receipt.get("approval_binding_hash"):
            raise ValueError("approval_binding_missing: bound publication requires bound approval")
        return {"status": "already_published", "target": str(existing), "receipt": str(receipt_path), "asset_id": asset_id, "revision_id": revision_id}
    binding_digest = verify_binding(confirmation, **binding_kwargs)
    if target.exists():
        raise ValueError("identity_conflict: target filename exists; automatic _2 suffix is forbidden")
    same_source = [item for item in index["publications"] if item.get("source_asset_id") == source["material_id"] and item.get("asset_subtype") == "learning_note"]
    if same_source and not args.allow_additional_learning:
        raise ValueError("revision_candidate: source already has a different Learning Note; explicit review required")
    transaction_id = "publish_tx_sha256_" + digest(canonical({"asset_id": asset_id, "revision_id": revision_id, "target": str(target)}))
    receipt_id = "publish_receipt_sha256_" + digest(canonical({"transaction_id": transaction_id, "receipt_type": "original_publish"}))
    receipt_path = receipts / f"{receipt_id}.json"; tx_dir = transactions / transaction_id
    receipt = {
        "protocol": "original-publish-receipt-v1", "schema_version": "1.0.0", "receipt_id": receipt_id,
        "receipt_type": "original_publish", "knowledge_asset_id": asset_id,
        "knowledge_revision_id": revision_id, "asset_subtype": "learning_note",
        "source_asset_id": source["material_id"], "source_revision_id": source["revision_id"],
        "target_path": str(target), "content_hash": content_hash, "projection_hash": "sha256:" + digest(target_bytes),
        "stable_references": stable_refs, "approval_evidence": confirmation.get("approval_id", "explicit_user_confirmation"),
        "published_at": confirmation["confirmed_at"], "transaction_id": transaction_id,
        "validation_result": "prepared", "relation_hook_status": "pending", "approval_binding_hash": binding_digest,
    }
    archive_retryable(tx_dir)
    item = {
        "knowledge_asset_id": asset_id, "knowledge_revision_id": revision_id, "asset_subtype": "learning_note",
        "source_asset_id": source["material_id"], "source_revision_id": source["revision_id"],
        "content_hash": content_hash, "target_path": str(target), "receipt_path": str(receipt_path),
        "transaction_id": transaction_id, "status": "published",
    }
    fault = {"receipt_prepare_failure": "after_journal", "receipt_commit_failure": "after_asset"}.get(args.fault_injection, args.fault_injection)
    try:
        inject("after_approval", fault, args.scope)
        committed = commit(governance=governance, vault_root=Path(args.vault_root), target=target,
                           target_bytes=target_bytes, receipt=receipt, receipt_path=receipt_path,
                           index_path=index_path, index=index, index_item=item, tx_dir=tx_dir,
                           fault=fault, scope=args.scope)
    except Exception as error:
        recovery = guarded_abort(tx_dir, target=target, receipt_path=receipt_path)
        if recovery == "already_committed":
            return {"status": "published", "target": str(target), "receipt": str(receipt_path),
                    "asset_id": asset_id, "revision_id": revision_id, "relation_hook_status": "failed_non_blocking",
                    "warning": str(error)}
        if recovery == "safe_to_resume":
            raise ValueError(f"publisher_recovery_required: {error}") from error
        if recovery == "needs_reconciliation":
            raise ValueError(f"publisher_recovery_conflict: {error}") from error
        raise
    try:
        if args.relation_hook == "fail": receipt["relation_hook_status"] = "failed_non_blocking"
        elif args.relation_hook == "skip": receipt["relation_hook_status"] = "not_requested"
        else: receipt["relation_hook_status"] = "queued_non_blocking"
        durable_json(receipt_path, receipt)
        committed["relation_hook_status"] = receipt["relation_hook_status"]
    except Exception as error:
        committed["relation_hook_status"] = "failed_non_blocking"; committed["warning"] = str(error)
    committed.update({"asset_id": asset_id, "revision_id": revision_id})
    return committed


def publish(args):
    governance = Path(args.asset_root).resolve() / "governance" / "knowledge-publish"
    fault = {"receipt_prepare_failure": "after_journal", "receipt_commit_failure": "after_asset"}.get(args.fault_injection, args.fault_injection)
    inject("before_lock", fault, args.scope)
    with ledger_lock(governance):
        inject("after_lock", fault, args.scope)
        recover_pending(governance, Path(args.vault_root), fault=fault, scope=args.scope)
        result = _publish_locked(args)
        try: inject("before_unlock", fault, args.scope)
        except OSError as error: result["warning"] = str(error)
        return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--draft", required=True); parser.add_argument("--generated", required=True)
    parser.add_argument("--candidate")
    parser.add_argument("--confirmation", required=True); parser.add_argument("--quality", required=True)
    parser.add_argument("--source-material", required=True); parser.add_argument("--vault-root", required=True)
    parser.add_argument("--asset-root", required=True); parser.add_argument("--filename", required=True)
    parser.add_argument("--target-folder", default="20 学习笔记")
    parser.add_argument("--scope", choices=("production", "test"), default="production")
    parser.add_argument("--allow-additional-learning", action="store_true")
    parser.add_argument("--fault-injection", default="none")
    parser.add_argument("--relation-hook", choices=("queue", "skip", "fail"), default="queue")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        result = publish(args); atomic_json(Path(args.output), result); print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, UnicodeDecodeError) as error:
        raise SystemExit(f"ERROR: {error}") from error


if __name__ == "__main__": main()
