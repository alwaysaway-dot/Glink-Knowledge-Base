#!/usr/bin/env python3
"""Publish Intelligence, Method and Creation candidates with shared safeguards."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from publisher_core import (
    ASSET_CLASSES, GRAPH_GROUPS, TARGETS, atomic_json, atomic_write, canonical,
    digest, has_temp, identity, load_json, require_stable_references, resolve_target,
    strip_frontmatter,
)
from approval_binding import verify as verify_binding
from publisher_transaction import archive_retryable, commit, file_hash, guarded_abort, inject, ledger_lock, recover_pending


SUPPORTED = {"intelligence_brief", "method_asset", "creation_asset"}


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def validate_gate(candidate: dict):
    asset_type = candidate.get("asset_type")
    gate = candidate.get("admission", {})
    content = candidate.get("content", {})
    if candidate.get("protocol") != "derivative-candidate-v1":
        raise ValueError("derivative-candidate-v1 is required")
    if asset_type not in SUPPORTED:
        raise ValueError("derivative publisher only supports intelligence_brief/method_asset/creation_asset")
    if candidate.get("status") != "publishable" or gate.get("status") != "passed":
        raise ValueError("only publishable candidates with passed admission gate can publish")
    if not isinstance(content.get("title"), str) or not content["title"].strip():
        raise ValueError("candidate title is required")
    if not isinstance(content.get("markdown"), str) or not content["markdown"].strip():
        raise ValueError("candidate Markdown is required")
    references = candidate.get("provenance", {}).get("stable_references", [])
    require_stable_references(references, "candidate provenance")
    if asset_type == "intelligence_brief":
        if not gate.get("time_sensitive") or not gate.get("external_change"):
            raise ValueError("Intelligence requires time sensitivity and an external change")
        if gate.get("independent_source_count", 0) < 2:
            raise ValueError("Intelligence requires at least two independent sources")
    elif asset_type == "method_asset":
        required = {"purpose", "inputs", "preconditions", "steps", "outputs", "limitations", "applicability", "failure_conditions", "source_basis"}
        if not required.issubset(set(gate.get("required_fields", []))):
            raise ValueError("Method gate lacks required procedural fields")
        if gate.get("ai_invented") is True or gate.get("validation_status") not in {"passed", "not_required"}:
            raise ValueError("Method is invented or lacks required validation")
    elif asset_type == "creation_asset":
        required = {"audience", "purpose", "deliverable", "version"}
        if not required.issubset(set(gate.get("required_fields", []))):
            raise ValueError("Creation gate lacks audience/purpose/deliverable/version")
        if gate.get("user_output_intent") is not True:
            raise ValueError("Creation requires explicit user output intent")


def frontmatter(asset_id, revision_id, content_hash, candidate, confirmation):
    asset_type = candidate["asset_type"]
    source = candidate["source"]
    source_ref = f"guanlan://material/{source['material_id']}/revision/{source['revision_id']}"
    lines = [
        "---", f"type: {asset_type}", f"asset_class: {ASSET_CLASSES[asset_type]}",
        f"asset_subtype: {asset_type}", "workflow_state: active", "status: published",
        f"asset_id: {asset_id}", f"revision_id: {revision_id}", f"content_hash: {content_hash}",
        f"source_asset: {source['material_id']}", f"source_revision: {source['revision_id']}",
        f"source_reference: {source_ref}", f"published_at: {confirmation['confirmed_at']}",
        "confirmation_mode: explicit_user_instruction", f"graph_group: {GRAPH_GROUPS[asset_type]}",
    ]
    for index, value in enumerate(candidate["provenance"]["stable_references"], 1):
        lines.append(f"governance_reference_{index}: {value}")
    return "\n".join(lines + ["---", "", ""]).encode("utf-8")


def validate_inputs(args, candidate, confirmation, quality, source):
    validate_gate(candidate)
    asset_type = candidate["asset_type"]
    if confirmation.get("protocol") != "derivative-publish-approval-v1" or confirmation.get("confirmed") is not True:
        raise ValueError("explicit derivative-publish-approval-v1 is required")
    if confirmation.get("reviewer") != "user" or not confirmation.get("confirmed_at"):
        raise ValueError("approval must be explicit reviewer=user confirmation")
    if confirmation.get("candidate_id") != candidate.get("candidate_id") or confirmation.get("asset_type") != asset_type:
        raise ValueError("approval/candidate mismatch")
    if quality.get("protocol") != "derivative-publish-quality-v1" or quality.get("status") != "passed":
        raise ValueError("passed derivative-publish-quality-v1 is required")
    if quality.get("candidate_id") != candidate.get("candidate_id") or quality.get("asset_type") != asset_type:
        raise ValueError("quality/candidate mismatch")
    if source.get("protocol") != "source-material-v3":
        raise ValueError("Source Material v3 is required")
    candidate_source = candidate.get("source", {})
    if candidate_source.get("material_id") != source.get("material_id") or candidate_source.get("revision_id") != source.get("revision_id"):
        raise ValueError("candidate/source identity mismatch")
    if has_temp(candidate) or has_temp(confirmation) or has_temp(quality) or has_temp(source):
        raise ValueError("temporary reference is forbidden")
    require_stable_references(confirmation.get("stable_references", []), "approval")
    if args.scope == "production":
        for value in (args.candidate, args.confirmation, args.quality, args.source_material):
            if str(Path(value).resolve()).startswith(("/tmp/", "/private/tmp/")):
                raise ValueError("production input cannot originate from temporary path")


def _publish_locked(args):
    candidate = load_json(Path(args.candidate), "candidate")
    confirmation = load_json(Path(args.confirmation), "confirmation")
    quality = load_json(Path(args.quality), "quality")
    source = load_json(Path(args.source_material), "source material")
    validate_inputs(args, candidate, confirmation, quality, source)
    asset_type = candidate["asset_type"]
    target_dir = resolve_target(Path(args.vault_root), asset_type, args.target_folder, args.scope)
    filename = args.filename
    if not filename.endswith(".md") or Path(filename).name != filename:
        raise ValueError("filename must be one safe Markdown basename")
    body_text = strip_frontmatter(candidate["content"]["markdown"]).strip() + "\n"
    if has_temp(body_text):
        raise ValueError("published content contains a temporary reference")
    body = body_text.encode("utf-8")
    asset_id, revision_id, content_hash = identity(body, source, asset_type)
    if confirmation.get("content_hash") != content_hash:
        raise ValueError("approval does not bind exact content hash")
    target = target_dir / filename
    governance = Path(args.asset_root).resolve() / "governance" / "derivative-publish"
    receipts = governance / "original-receipts"; transactions = governance / "transactions"
    index_path = governance / "publish-index-v1.json"
    index = load_json(index_path, "publish index") if index_path.exists() else {
        "protocol": "derivative-publish-index-v1", "schema_version": "1.0.0", "publications": []
    }
    same = [item for item in index["publications"] if item.get("asset_id") == asset_id and item.get("asset_type") == asset_type]
    if len(same) > 1: raise ValueError("identity conflict: duplicate index entries")
    if same:
        item = same[0]; existing = Path(item["target_path"])
        if existing.resolve() != target.resolve() or item.get("source_asset_id") != source["material_id"] or item.get("source_revision_id") != source["revision_id"]:
            raise ValueError("identity conflict: published target or source differs")
        receipt = Path(item["receipt_path"])
        prior = load_json(receipt, "receipt") if receipt.is_file() else {}
        old_body_hash = "sha256:" + digest((strip_frontmatter(existing.read_text(encoding="utf-8")).strip() + "\n").encode("utf-8")) if existing.is_file() else None
        projection_ok = file_hash(existing) == prior["projection_hash"] if prior.get("projection_hash") else old_body_hash == content_hash
        if not existing.is_file() or prior.get("validation_result") != "committed" or prior.get("content_hash") != content_hash or not projection_ok:
            raise ValueError("identity conflict: existing publication incomplete")
        if confirmation.get("approval_binding") is not None:
            verify_binding(confirmation, candidate=candidate, source=source, target_folder=args.target_folder,
                           filename=filename, body=body_text, title=candidate["content"]["title"], quality=quality)
        elif prior.get("approval_binding_hash"):
            raise ValueError("approval_binding_missing: bound publication requires bound approval")
        return {"status": "already_published", "asset_id": asset_id, "revision_id": revision_id, "target": str(existing), "receipt": str(receipt)}
    binding_digest = verify_binding(confirmation, candidate=candidate, source=source, target_folder=args.target_folder,
                                    filename=filename, body=body_text, title=candidate["content"]["title"], quality=quality)
    if target.exists():
        raise ValueError("identity_conflict: target filename exists; _2 suffix forbidden")
    transaction_id = "publish_tx_sha256_" + digest(canonical({"asset_id": asset_id, "revision_id": revision_id, "target": str(target)}))
    receipt_id = "publish_receipt_sha256_" + digest(canonical({"transaction_id": transaction_id, "receipt_type": "original_publish"}))
    receipt_path = receipts / f"{receipt_id}.json"; tx_dir = transactions / transaction_id
    projection = frontmatter(asset_id, revision_id, content_hash, candidate, confirmation) + body
    receipt = {
        "protocol": "original-publish-receipt-v1", "schema_version": "1.0.0", "receipt_id": receipt_id,
        "receipt_type": "original_publish", "asset_id": asset_id, "revision_id": revision_id,
        "asset_type": asset_type, "source_asset_id": source["material_id"], "source_revision_id": source["revision_id"],
        "candidate_id": candidate["candidate_id"], "target_path": str(target), "content_hash": content_hash,
        "projection_hash": "sha256:" + digest(projection),
        "stable_references": candidate["provenance"]["stable_references"], "approval_evidence": confirmation.get("approval_id", "explicit_user_confirmation"),
        "published_at": confirmation["confirmed_at"], "transaction_id": transaction_id, "validation_result": "prepared",
        "approval_binding_hash": binding_digest,
    }
    archive_retryable(tx_dir)
    item = {
        "asset_id": asset_id, "revision_id": revision_id, "asset_type": asset_type, "candidate_id": candidate["candidate_id"],
        "source_asset_id": source["material_id"], "source_revision_id": source["revision_id"], "content_hash": content_hash,
        "target_path": str(target), "receipt_path": str(receipt_path), "transaction_id": transaction_id, "status": "published",
    }
    fault = {"receipt_prepare_failure": "after_journal", "receipt_commit_failure": "after_asset"}.get(args.fault_injection, args.fault_injection)
    try:
        inject("after_approval", fault, args.scope)
        result = commit(governance=governance, vault_root=Path(args.vault_root), target=target,
                        target_bytes=projection, receipt=receipt, receipt_path=receipt_path,
                        index_path=index_path, index=index, index_item=item, tx_dir=tx_dir,
                        fault=fault, scope=args.scope)
        return dict(result, asset_id=asset_id, revision_id=revision_id)
    except Exception as error:
        recovery = guarded_abort(tx_dir, target=target, receipt_path=receipt_path)
        if recovery == "already_committed":
            return {"status": "published", "target": str(target), "receipt": str(receipt_path),
                    "asset_id": asset_id, "revision_id": revision_id, "warning": str(error)}
        if recovery == "safe_to_resume":
            raise ValueError(f"publisher_recovery_required: {error}") from error
        if recovery == "needs_reconciliation":
            raise ValueError(f"publisher_recovery_conflict: {error}") from error
        raise


def publish(args):
    governance = Path(args.asset_root).resolve() / "governance" / "derivative-publish"
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
    parser.add_argument("--candidate", required=True); parser.add_argument("--confirmation", required=True)
    parser.add_argument("--quality", required=True); parser.add_argument("--source-material", required=True)
    parser.add_argument("--vault-root", required=True); parser.add_argument("--asset-root", required=True)
    parser.add_argument("--filename", required=True); parser.add_argument("--target-folder", required=True)
    parser.add_argument("--scope", choices=("production", "test"), default="production")
    parser.add_argument("--fault-injection", default="none")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        result = publish(args); atomic_json(Path(args.output), result); print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, UnicodeDecodeError) as error:
        raise SystemExit(f"ERROR: {error}") from error


if __name__ == "__main__":
    main()
