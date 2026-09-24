#!/usr/bin/env python3
"""Plan or apply an approved relation. Default is always dry-run."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from relation_common import atomic_json, atomic_write, canonical_json, current_revision, relation_exists, scan_asset, sha256_bytes


AUTO_SEMANTIC_TYPES = {"extends", "supports", "contrasts_with", "applies", "updates"}


def load_candidate(path, candidate_id):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    candidates = data.get("strong_candidates", []) + data.get("medium_candidates", [])
    match = [item for item in candidates if item.get("candidate_id") == candidate_id]
    if len(match) != 1:
        raise ValueError("candidate_id must identify one strong/medium candidate")
    return match[0]


def endpoint_asset(candidate, side, vault):
    display = candidate[f"{side}_display"]
    path = (vault / display["path"]).resolve()
    if not str(path).startswith(str(vault) + os.sep) or not path.is_file() or path.is_symlink():
        raise ValueError(f"{side} path is outside Vault or missing")
    return scan_asset(path, vault, display["asset_class"])


def proposed_block(candidate, side):
    other = candidate["target_display"] if side == "source" else candidate["source_display"]
    relation = candidate["relation_type"] if side == "source" else candidate["reciprocal_relation"]
    if relation == "source_of":
        heading = "派生知识"
    elif relation == "derived_from":
        heading = "来源资料"
    else:
        heading = "关联知识"
    return heading, f"- [[{Path(other['path']).stem}]] · `{relation}` · `{candidate['candidate_id']}`"


def append_relation(text, heading, line):
    marker = f"## {heading}"
    if line in text:
        return text
    if marker in text:
        marker_start = text.index(marker)
        content_start = marker_start + len(marker)
        following = re.search(r"^#{1,2}\s+", text[content_start:], re.M)
        insert_at = content_start + following.start() if following else len(text)
        prefix = text[:insert_at].rstrip()
        suffix = text[insert_at:].lstrip("\n")
        return prefix + "\n\n" + line + "\n\n" + suffix
    return text.rstrip() + f"\n\n{marker}\n\n{line}\n"


def validate_revisions(candidate, source, target):
    if source["asset_id"] != candidate["source_asset_id"] or target["asset_id"] != candidate["target_asset_id"]:
        raise ValueError("endpoint identity changed")
    if current_revision(source) != candidate["source_revision"] or current_revision(target) != candidate["target_revision"]:
        raise ValueError("endpoint revision changed; regenerate candidate")
    if source["file_hash"] != candidate.get("source_snapshot_hash") or target["file_hash"] != candidate.get("target_snapshot_hash"):
        raise ValueError("endpoint snapshot changed; regenerate candidate")


def has_conflicting_relation(registry, candidate):
    pair = {candidate["source_asset_id"], candidate["target_asset_id"]}
    for item in registry.get("relations", []):
        if item.get("approval_status") not in {"approved", "executed", "auto_executed"}:
            continue
        if {item.get("source_asset_id"), item.get("target_asset_id")} != pair:
            continue
        if item.get("relation_type") != candidate["relation_type"] or item.get("reciprocal_relation") != candidate["reciprocal_relation"]:
            return True
    return False


def auto_apply_gate(candidate, source, target, registry):
    if not source.get("eligible") or not target.get("eligible"):
        raise ValueError("auto apply requires formal eligible endpoints")
    if candidate.get("relation_strength") != "strong" or candidate.get("confidence") != "high":
        raise ValueError("auto apply requires strong high-confidence candidate")
    if candidate.get("relation_type") == "related":
        raise ValueError("related is never auto-applicable")
    if relation_exists(registry, candidate["source_asset_id"], candidate["target_asset_id"], candidate["relation_type"], candidate["reciprocal_relation"]):
        raise ValueError("relation already exists")
    if has_conflicting_relation(registry, candidate):
        raise ValueError("conflicting relation exists for endpoint pair")
    evidence = candidate.get("evidence", [])
    kinds = {item.get("kind") for item in evidence if isinstance(item, dict)}
    if candidate.get("relation_type") == "source_of":
        required = {"stable_identity_match", "stable_reference_match"}
        revision_proof = "revision_match" in kinds or {"derivation_revision_match", "current_source_revision_binding"}.issubset(kinds)
        if not required.issubset(kinds) or not revision_proof:
            raise ValueError("structural auto apply requires identity, revision and stable-reference evidence")
        return "structural_identity"
    if candidate.get("relation_type") not in AUTO_SEMANTIC_TYPES:
        raise ValueError("relation type is not auto-applicable")
    semantic_proof = {item.get("kind") for item in evidence if isinstance(item, dict)}
    required_semantic = {"shared_semantic_object", "source_excerpt", "target_excerpt", "link_usefulness"}
    legacy_proof = sum(item.get("kind") == "semantic_dimension" for item in evidence if isinstance(item, dict)) >= 4
    if not required_semantic.issubset(semantic_proof) and not legacy_proof:
        raise ValueError("semantic auto apply requires pair-specific evidence from both assets")
    if len(candidate.get("rationale", "")) < 40:
        raise ValueError("semantic auto apply requires substantive rationale")
    return "semantic_strong"


def dry_run(candidate, source, target):
    source_heading, source_line = proposed_block(candidate, "source")
    target_heading, target_line = proposed_block(candidate, "target")
    return {
        "protocol": "relation-apply-plan-v1", "dry_run": True, "candidate_id": candidate["candidate_id"],
        "revision_validation": "passed", "registry_update": "planned_not_executed",
        "source_change": {"path": source["relative_path"], "section": source_heading, "line": source_line},
        "target_change": {"path": target["relative_path"], "section": target_heading, "line": target_line},
        "rollback": {"supported": True, "strategy": "hash-guarded restore from recoverable backup"},
        "links_written": 0,
    }


def execute(candidate, source, target, registry_path, approval_path, rollback_root, receipt_path, auto=False):
    approval = {}
    if not auto:
        approval = json.loads(Path(approval_path).read_text(encoding="utf-8"))
        if not approval.get("confirmed") or approval.get("candidate_id") != candidate["candidate_id"] or approval.get("reviewer") != "user":
            raise ValueError("matching explicit user approval is required")
    if candidate.get("decision_status") != "suggested" or candidate.get("relation_strength") not in {"strong", "medium"}:
        raise ValueError("only suggested strong/medium candidates can be approved")
    registry_value = json.loads(Path(registry_path).read_text(encoding="utf-8"))
    if registry_value.get("protocol") != "relation-registry-v1" or not isinstance(registry_value.get("relations"), list):
        raise ValueError("valid relation-registry-v1 is required")
    execution_authority = "user_approved"
    if auto:
        execution_authority = "auto_strong"
        auto_apply_gate(candidate, source, target, registry_value)
    elif relation_exists(registry_value, candidate["source_asset_id"], candidate["target_asset_id"], candidate["relation_type"], candidate["reciprocal_relation"]):
        raise ValueError("approved/executed relation already exists")
    source_path, target_path = Path(source["absolute_path"]), Path(target["absolute_path"])
    registry_before = Path(registry_path).read_bytes()
    source_before, target_before = source_path.read_bytes(), target_path.read_bytes()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    transaction = Path(rollback_root).resolve() / f"{stamp}_{candidate['candidate_id']}"
    transaction.mkdir(parents=True, exist_ok=False)
    atomic_write(transaction / "source.before.md", source_before)
    atomic_write(transaction / "target.before.md", target_before)
    atomic_write(transaction / "registry.before.json", registry_before)
    source_heading, source_line = proposed_block(candidate, "source")
    target_heading, target_line = proposed_block(candidate, "target")
    try:
        source_after = append_relation(source_before.decode("utf-8"), source_heading, source_line).encode("utf-8")
        target_after = append_relation(target_before.decode("utf-8"), target_heading, target_line).encode("utf-8")
        atomic_write(source_path, source_after)
        atomic_write(target_path, target_after)
        registry = json.loads(registry_before)
        relation_id = "relation_sha256_" + sha256_bytes(canonical_json({
            "candidate_id": candidate["candidate_id"], "source_asset_id": candidate["source_asset_id"],
            "source_revision": candidate["source_revision"], "target_asset_id": candidate["target_asset_id"],
            "target_revision": candidate["target_revision"], "relation_type": candidate["relation_type"],
        }))
        now = approval.get("approved_at") or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        # A non-source endpoint may use its Markdown snapshot as revision.  Store the
        # post-projection revision so the system's own display link does not later look
        # like an unexplained semantic content change.
        source_after_asset = scan_asset(source_path, source_path.parents[len(Path(source["relative_path"]).parts) - 1], source["asset_class"])
        target_after_asset = scan_asset(target_path, target_path.parents[len(Path(target["relative_path"]).parts) - 1], target["asset_class"])
        registry["relations"].append({
            "relation_id": relation_id, "candidate_id": candidate["candidate_id"],
            "source_asset_id": candidate["source_asset_id"], "source_revision": current_revision(source_after_asset),
            "target_asset_id": candidate["target_asset_id"], "target_revision": current_revision(target_after_asset),
            "relation_type": candidate["relation_type"], "reciprocal_relation": candidate["reciprocal_relation"],
            "relation_strength": candidate["relation_strength"], "approval_status": "auto_executed" if auto else "executed",
            "created_at": candidate["created_at"], "approved_at": now, "executed_at": now,
            "source_location": source["relative_path"], "target_location": target["relative_path"],
            "execution_authority": execution_authority,
            "rationale": candidate.get("rationale", ""), "evidence": candidate.get("evidence", []),
            "source_anchor": candidate.get("source_anchor", ""), "target_anchor": candidate.get("target_anchor", ""),
            "projection_snapshot_hashes": {"source": source_after_asset["file_hash"], "target": target_after_asset["file_hash"]},
        })
        registry["updated_at"] = now
        atomic_json(Path(registry_path), registry)
        if source_line not in source_path.read_text(encoding="utf-8") or target_line not in target_path.read_text(encoding="utf-8"):
            raise ValueError("Markdown/Registry consistency verification failed")
        receipt = {
            "protocol": "relation-apply-receipt-v1", "candidate_id": candidate["candidate_id"],
            "status": "executed", "execution_authority": execution_authority, "backup_directory": str(transaction),
            "source_path": str(source_path), "target_path": str(target_path), "registry_path": str(Path(registry_path).resolve()),
            "pre_hashes": {"source": "sha256:" + sha256_bytes(source_before), "target": "sha256:" + sha256_bytes(target_before), "registry": "sha256:" + sha256_bytes(registry_before)},
            "post_hashes": {"source": "sha256:" + sha256_bytes(source_after), "target": "sha256:" + sha256_bytes(target_after), "registry": "sha256:" + sha256_bytes(Path(registry_path).read_bytes())},
        }
        atomic_json(Path(receipt_path), receipt)
        return receipt
    except Exception:
        atomic_write(source_path, source_before)
        atomic_write(target_path, target_before)
        atomic_write(Path(registry_path), registry_before)
        raise


def rollback(receipt_path, confirmation_path, output_path):
    receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    confirmation = json.loads(Path(confirmation_path).read_text(encoding="utf-8"))
    if not confirmation.get("confirmed") or confirmation.get("candidate_id") != receipt.get("candidate_id"):
        raise ValueError("matching rollback confirmation is required")
    source, target, registry = Path(receipt["source_path"]), Path(receipt["target_path"]), Path(receipt["registry_path"])
    current = {"source": "sha256:" + sha256_bytes(source.read_bytes()), "target": "sha256:" + sha256_bytes(target.read_bytes()), "registry": "sha256:" + sha256_bytes(registry.read_bytes())}
    if current != receipt["post_hashes"]:
        raise ValueError("rollback hash guard failed")
    backup = Path(receipt["backup_directory"])
    atomic_write(source, (backup / "source.before.md").read_bytes())
    atomic_write(target, (backup / "target.before.md").read_bytes())
    atomic_write(registry, (backup / "registry.before.json").read_bytes())
    result = {"status": "rolled_back", "candidate_id": receipt["candidate_id"], "permanent_deletion": False}
    atomic_json(Path(output_path), result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--command", choices=("apply", "rollback"), default="apply")
    parser.add_argument("--candidates")
    parser.add_argument("--candidate-id")
    parser.add_argument("--vault")
    parser.add_argument("--registry")
    parser.add_argument("--output", required=True)
    parser.add_argument("--execute", action="store_true", help="explicitly enable writes; omitted means dry-run")
    parser.add_argument("--auto", action="store_true", help="execute a Strong Relation only when Relation Auto-Apply Gate passes")
    parser.add_argument("--approval")
    parser.add_argument("--rollback-root")
    parser.add_argument("--receipt")
    parser.add_argument("--rollback-confirmation")
    args = parser.parse_args()
    try:
        if args.command == "rollback":
            if not args.receipt or not args.rollback_confirmation:
                raise ValueError("rollback requires receipt and confirmation")
            result = rollback(args.receipt, args.rollback_confirmation, args.output)
        else:
            if not all((args.candidates, args.candidate_id, args.vault, args.registry)):
                raise ValueError("apply requires candidates, candidate-id, vault and registry")
            vault = Path(args.vault).resolve()
            candidate = load_candidate(args.candidates, args.candidate_id)
            source, target = endpoint_asset(candidate, "source", vault), endpoint_asset(candidate, "target", vault)
            validate_revisions(candidate, source, target)
            if args.auto and not args.execute:
                raise ValueError("--auto requires --execute")
            if not args.execute:
                result = dry_run(candidate, source, target)
                atomic_json(Path(args.output), result)
            else:
                if not args.rollback_root or not args.receipt:
                    raise ValueError("execute requires rollback-root and receipt")
                if not args.auto and not args.approval:
                    raise ValueError("user-approved execute requires approval")
                result = execute(candidate, source, target, args.registry, args.approval, args.rollback_root, args.receipt, auto=args.auto)
                atomic_json(Path(args.output), result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        raise SystemExit(f"ERROR: {error}") from error


if __name__ == "__main__":
    main()
