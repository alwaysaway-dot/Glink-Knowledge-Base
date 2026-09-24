#!/usr/bin/env python3
"""Maintain Relation governance without treating Markdown as semantic authority."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from relation_apply import append_relation, proposed_block
from relation_common import atomic_json, atomic_write, candidate_id, scan_asset, scan_vault, sha256_bytes
from relation_discovery import semantic_candidate, structural_candidates
from relation_registry import validate


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_or_initialize(path: Path, protocol: str, collection: str):
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("protocol") != protocol or not isinstance(data.get(collection), list):
            raise ValueError(f"{protocol} is required")
        return data
    return {"protocol": protocol, "schema_version": "1.0.0", collection: [], "updated_at": ""}


def endpoint_map(assets):
    return {item["asset_id"]: item for item in assets if item.get("asset_id")}


def expected_line(relation, side):
    candidate = {
        "candidate_id": relation["candidate_id"], "relation_type": relation["relation_type"],
        "reciprocal_relation": relation["reciprocal_relation"],
        "source_display": {"path": relation["source_location"]},
        "target_display": {"path": relation["target_location"]},
    }
    return proposed_block(candidate, side)


def exception_id(problem, relation):
    raw = "|".join((problem, relation.get("relation_id", ""), relation.get("source_asset_id", ""), relation.get("target_asset_id", "")))
    from relation_common import sha256_bytes
    return "relation_exception_sha256_" + sha256_bytes(raw.encode("utf-8"))


def make_exception(problem, relation, evidence, recommendation, risk, actions):
    return {
        "exception_id": exception_id(problem, relation),
        "assets": [relation.get("source_asset_id", ""), relation.get("target_asset_id", "")],
        "existing_relation": relation.get("relation_id", ""), "problem": problem, "evidence": evidence,
        "system_recommendation": recommendation, "risk": risk, "available_actions": actions,
        "status": "open", "first_seen": now(), "last_seen": now(),
    }


def matching_receipt(receipt_root: Path | None, candidate_id_value: str):
    if not receipt_root or not receipt_root.is_dir():
        return None
    for path in receipt_root.rglob("*.json"):
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
            if receipt.get("protocol") == "relation-apply-receipt-v1" and receipt.get("candidate_id") == candidate_id_value:
                return receipt
        except (OSError, json.JSONDecodeError):
            continue
    return None


def normalize_nonsemantic_projection(text: str, candidate_id_value: str):
    """Remove only graph-role metadata and this system-managed relation projection."""
    frontmatter, body = text.split("\n---\n", 1) if text.startswith("---\n") and "\n---\n" in text[4:] else ("", text)
    if frontmatter:
        frontmatter = "\n".join(line for line in frontmatter.splitlines() if not re.match(r"^(asset_class|graph_group):", line))
        text = frontmatter + "\n---\n" + body
    headings = list(re.finditer(r"^##\s+.+$", text, re.M))
    for match in reversed(headings):
        end = next((later.start() for later in headings if later.start() > match.start()), len(text))
        section = text[match.start():end]
        if candidate_id_value not in section:
            continue
        retained = "\n".join(line for line in section.splitlines() if candidate_id_value not in line).strip()
        replacement = "" if retained == match.group(0) else retained + "\n\n"
        text = text[:match.start()].rstrip() + ("\n\n" if text[:match.start()].strip() and replacement else "") + replacement + text[end:].lstrip("\n")
    return text.strip()


def receipt_proves_nonsemantic_projection(receipt, source, target, relation):
    if not receipt:
        return False
    backup = Path(receipt.get("backup_directory", ""))
    try:
        source_before = (backup / "source.before.md").read_text(encoding="utf-8")
        target_before = (backup / "target.before.md").read_text(encoding="utf-8")
    except OSError:
        return False
    return (
        normalize_nonsemantic_projection(Path(source["absolute_path"]).read_text(encoding="utf-8"), relation["candidate_id"]) == normalize_nonsemantic_projection(source_before, relation["candidate_id"])
        and normalize_nonsemantic_projection(Path(target["absolute_path"]).read_text(encoding="utf-8"), relation["candidate_id"]) == normalize_nonsemantic_projection(target_before, relation["candidate_id"])
    )


def audit_registry_markdown(vault: Path, registry: dict, receipt_root: Path | None = None):
    assets = scan_vault(str(vault))
    endpoints = endpoint_map(assets)
    checks, exceptions, repairs = [], [], []
    for relation in registry.get("relations", []):
        if relation.get("approval_status") not in {"approved", "executed", "auto_executed"}:
            continue
        source, target = endpoints.get(relation.get("source_asset_id")), endpoints.get(relation.get("target_asset_id"))
        if not source or not target:
            evidence = {"source_present": bool(source), "target_present": bool(target)}
            exceptions.append(make_exception("asset_unavailable", relation, evidence, "保留 Registry 事实，待确认资产位置或生命周期状态。", "high", ["locate_asset", "mark_stale_candidate", "revoke_with_record"]))
            checks.append({"relation_id": relation["relation_id"], "status": "needs_review", "reason": "asset_unavailable"})
            continue
        source_heading, source_line = expected_line(relation, "source")
        target_heading, target_line = expected_line(relation, "target")
        source_text, target_text = Path(source["absolute_path"]).read_text(encoding="utf-8"), Path(target["absolute_path"]).read_text(encoding="utf-8")
        source_has, target_has = source_line in source_text, target_line in target_text
        candidate_marker = relation["candidate_id"]
        receipt = matching_receipt(receipt_root, relation["candidate_id"])
        receipt_hashes = (receipt or {}).get("post_hashes", {})
        safely_rebased = source_has and target_has and receipt_hashes == {"source": source["file_hash"], "target": target["file_hash"], "registry": receipt_hashes.get("registry", "")}
        # The registry hash necessarily changes during this rebase, so only compare the
        # two Vault endpoints against the execution receipt.
        safely_rebased = source_has and target_has and receipt_hashes.get("source") == source["file_hash"] and receipt_hashes.get("target") == target["file_hash"]
        safe_source_repair = not source_has and receipt_hashes.get("source") == "sha256:" + sha256_bytes(append_relation(source_text, source_heading, source_line).encode("utf-8"))
        safe_target_repair = not target_has and receipt_hashes.get("target") == "sha256:" + sha256_bytes(append_relation(target_text, target_heading, target_line).encode("utf-8"))
        if safe_source_repair or safe_target_repair:
            repairs.append({"relation_id": relation["relation_id"], "candidate_id": candidate_marker, "source": {"path": source["relative_path"], "heading": source_heading, "line": source_line, "missing": not source_has}, "target": {"path": target["relative_path"], "heading": target_heading, "line": target_line, "missing": not target_has}})
            checks.append({"relation_id": relation["relation_id"], "status": "repair_candidate", "reason": "receipt_verified_missing_projection"})
            continue
        safe_nonsemantic_rebase = source_has and target_has and receipt_proves_nonsemantic_projection(receipt, source, target, relation)
        if (source["revision"] != relation.get("source_revision") or target["revision"] != relation.get("target_revision")) and (safely_rebased or safe_nonsemantic_rebase):
            relation["source_revision"], relation["target_revision"] = source["revision"], target["revision"]
            relation["projection_snapshot_hashes"] = {"source": source["file_hash"], "target": target["file_hash"]}
            relation["revalidation_status"] = "verified"
            relation["revalidated_at"] = now()
            relation["revision_change_reason"] = "system_managed_nonsemantic_projection"
            checks.append({"relation_id": relation["relation_id"], "status": "verified", "reason": "system_projection_revision_rebased"})
            continue
        if source["revision"] != relation.get("source_revision") or target["revision"] != relation.get("target_revision"):
            evidence = {"registry": {"source_revision": relation.get("source_revision"), "target_revision": relation.get("target_revision")}, "current": {"source_revision": source["revision"], "target_revision": target["revision"]}}
            exceptions.append(make_exception("revision_changed", relation, evidence, "重新发现并评估关系；不要直接删除旧关系。", "medium", ["revalidate", "keep_verified_history", "mark_stale_candidate"]))
            checks.append({"relation_id": relation["relation_id"], "status": "needs_review", "reason": "revision_changed"})
            continue
        if source_has and target_has:
            checks.append({"relation_id": relation["relation_id"], "status": "healthy"})
        elif candidate_marker in source_text or candidate_marker in target_text:
            exceptions.append(make_exception("registry_markdown_conflict", relation, {"source_has_expected": source_has, "target_has_expected": target_has}, "不要自动修复语义冲突；人工核对展示行。", "medium", ["inspect_markdown", "repair_after_confirmation", "revalidate"]))
            checks.append({"relation_id": relation["relation_id"], "status": "conflict", "reason": "managed_marker_mismatch"})
        else:
            repair = {"relation_id": relation["relation_id"], "candidate_id": candidate_marker, "source": {"path": source["relative_path"], "heading": source_heading, "line": source_line, "missing": not source_has}, "target": {"path": target["relative_path"], "heading": target_heading, "line": target_line, "missing": not target_has}}
            repairs.append(repair)
            checks.append({"relation_id": relation["relation_id"], "status": "repair_candidate"})
    return assets, checks, exceptions, repairs


def scan_manual_links(vault: Path, registry: dict):
    managed = {item.get("candidate_id") for item in registry.get("relations", [])}
    manual, managed_count = [], 0
    for path in sorted(vault.rglob("*.md")):
        if path.is_symlink():
            continue
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "[[" not in line:
                continue
            if any(marker and marker in line for marker in managed):
                managed_count += 1
            else:
                manual.append({"path": str(path.relative_to(vault)), "line": line_no, "text": line.strip()})
    return managed_count, manual


def reconcile_observations(path: Path, medium, strong, observed_at: str, expiry_days: int = 90):
    pool = load_or_initialize(path, "relation-observation-pool-v1", "observations")
    before = json.dumps(pool, ensure_ascii=False, sort_keys=True)
    existing = {item["candidate_id"]: item for item in pool["observations"]}
    strong_ids = {item["candidate_id"] for item in strong}
    seen = set()
    for candidate in medium:
        seen.add(candidate["candidate_id"])
        record = existing.get(candidate["candidate_id"])
        if record:
            count = int(record.get("review_count", record.get("times_detected", 0))) + 1
            record.update({"last_seen": observed_at, "times_detected": count, "review_count": count, "confidence": candidate["confidence"], "evidence": candidate["evidence"], "why_medium": candidate.get("rationale", ""), "current_status": "observing"})
        else:
            pool["observations"].append({"candidate_id": candidate["candidate_id"], "asset_a": candidate["source_asset_id"], "asset_b": candidate["target_asset_id"], "asset_a_display": candidate.get("source_display", {}), "asset_b_display": candidate.get("target_display", {}), "candidate_relation": candidate["relation_type"], "confidence": candidate["confidence"], "why_medium": candidate.get("rationale", ""), "evidence": candidate["evidence"], "first_seen": observed_at, "last_seen": observed_at, "times_detected": 1, "review_count": 1, "current_status": "observing"})
    cutoff = datetime.now(timezone.utc) - timedelta(days=expiry_days)
    for record in pool["observations"]:
        if record["candidate_id"] in strong_ids and record.get("current_status") == "observing":
            record["current_status"] = "promoted"; record["last_seen"] = observed_at
        elif record.get("current_status") == "observing" and record["candidate_id"] not in seen:
            try:
                if datetime.fromisoformat(record["last_seen"].replace("Z", "+00:00")) < cutoff:
                    record["current_status"] = "expired"; record["last_seen"] = observed_at
            except ValueError:
                record["current_status"] = "expired"; record["last_seen"] = observed_at
    if json.dumps(pool, ensure_ascii=False, sort_keys=True) != before:
        pool["updated_at"] = observed_at
        atomic_json(path, pool)
    return pool


def reconcile_exceptions(path: Path, exceptions):
    queue = load_or_initialize(path, "relation-exception-queue-v1", "exceptions")
    existing = {item["exception_id"]: item for item in queue["exceptions"]}
    active = {item["exception_id"] for item in exceptions}
    for item in exceptions:
        if item["exception_id"] in existing:
            existing[item["exception_id"]].update({**item, "first_seen": existing[item["exception_id"]].get("first_seen", item["first_seen"])})
        else:
            queue["exceptions"].append(item)
    for item in queue["exceptions"]:
        if item.get("status") == "open" and item["exception_id"] not in active:
            item["status"] = "resolved"; item["last_seen"] = now()
    queue["updated_at"] = now()
    atomic_json(path, queue)
    return queue


def incremental_discover(vault: Path, registry: dict, relative_path: str, created_at: str):
    assets = scan_vault(str(vault))
    trigger = next((item for item in assets if item["relative_path"] == relative_path), None)
    if not trigger or not trigger["eligible"]:
        raise ValueError("published asset must be a formal asset with stable identity")
    eligible = [item for item in assets if item["eligible"] and item["asset_id"] != trigger["asset_id"]]
    structural = []
    for candidate in structural_candidates([trigger] + eligible, registry):
        if candidate["source_asset_id"] == trigger["asset_id"] or candidate["target_asset_id"] == trigger["asset_id"]:
            candidate["created_at"] = created_at; structural.append(candidate)
    strong, medium, filtered, seen = structural, [], [], {candidate_id(x["source_asset_id"], x["source_revision"], x["target_asset_id"], x["target_revision"], x["relation_type"]) for x in structural}
    for other in eligible:
        candidate, rejection = semantic_candidate(trigger, other)
        if candidate is None:
            filtered.append({"other_asset_id": other["asset_id"], "classification": "weak", **rejection}); continue
        if candidate["candidate_id"] in seen:
            continue
        candidate["created_at"] = created_at
        (strong if candidate["relation_strength"] == "strong" else medium).append(candidate)
        seen.add(candidate["candidate_id"])
    return {"protocol": "relation-incremental-discovery-v1", "schema_version": "1.0.0", "mode": "incremental", "trigger_asset": trigger["asset_id"], "trigger_path": relative_path, "created_at": created_at, "strong_candidates": strong, "medium_candidates": medium, "filtered_candidates": filtered, "summary": {"compared_assets": len(eligible), "strong_candidates": len(strong), "medium_candidates": len(medium), "weak_filtered": len(filtered)}}


def repair_markdown(audit_result, vault: Path):
    repaired = []
    assets = endpoint_map(scan_vault(str(vault)))
    for item in audit_result["repair_candidates"]:
        relation = item
        for side in ("source", "target"):
            info = relation[side]
            if not info["missing"]:
                continue
            path = (vault / info["path"]).resolve()
            if not path.is_file() or path.is_symlink():
                raise ValueError("repair endpoint unavailable")
            old = path.read_text(encoding="utf-8")
            atomic_write(path, append_relation(old, info["heading"], info["line"]).encode("utf-8"))
            repaired.append(str(path))
    return repaired


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--command", choices=("audit", "incremental", "repair"), required=True)
    parser.add_argument("--vault", required=True); parser.add_argument("--registry", required=True); parser.add_argument("--output", required=True)
    parser.add_argument("--observation-pool"); parser.add_argument("--exception-queue"); parser.add_argument("--asset-path"); parser.add_argument("--audit"); parser.add_argument("--receipt-root"); parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(); vault = Path(args.vault).resolve(); registry = json.loads(Path(args.registry).read_text(encoding="utf-8")); validate(registry)
    try:
        if args.command == "audit":
            if not args.observation_pool or not args.exception_queue: raise ValueError("audit requires observation-pool and exception-queue")
            assets, checks, exceptions, repairs = audit_registry_markdown(vault, registry, Path(args.receipt_root).resolve() if args.receipt_root else None)
            managed, manual = scan_manual_links(vault, registry)
            result = {"protocol": "relation-governance-audit-v1", "schema_version": "1.0.0", "created_at": now(), "registry_checks": checks, "repair_candidates": repairs, "manual_or_legacy_links": manual, "summary": {"formal_assets_scanned": len(assets), "registry_relations": len(registry.get("relations", [])), "healthy": sum(x["status"] == "healthy" for x in checks), "repair_candidates": len(repairs), "exceptions": len(exceptions), "managed_markdown_links": managed, "legacy_or_manual_links": len(manual)}}
            reconcile_exceptions(Path(args.exception_queue), exceptions)
            reconcile_observations(Path(args.observation_pool), [], [], result["created_at"])
            if any(item["status"] == "verified" and item.get("reason") == "system_projection_revision_rebased" for item in checks):
                registry["updated_at"] = result["created_at"]
                atomic_json(Path(args.registry), registry)
        elif args.command == "incremental":
            if not args.asset_path or not args.observation_pool: raise ValueError("incremental requires asset-path and observation-pool")
            result = incremental_discover(vault, registry, args.asset_path, now())
            reconcile_observations(Path(args.observation_pool), result["medium_candidates"], result["strong_candidates"], result["created_at"])
        else:
            if not args.execute or not args.audit: raise ValueError("repair requires --execute and --audit")
            result = json.loads(Path(args.audit).read_text(encoding="utf-8")); result = {"status": "repaired", "paths": repair_markdown(result, vault)}
        atomic_json(Path(args.output), result); print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        raise SystemExit(f"ERROR: {error}") from error


if __name__ == "__main__": main()
