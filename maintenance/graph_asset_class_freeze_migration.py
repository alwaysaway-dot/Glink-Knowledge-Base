#!/usr/bin/env python3
"""One-time, hash-guarded Graph metadata compatibility migration for freeze closure."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path


CANONICAL = {
    "10 原始资料": "source", "20 学习笔记": "knowledge", "30 情报简报": "intelligence",
    "40 方法库": "knowledge", "50 输出成果": "creation",
}
REMOVE_ONLY = {"00 收件箱", "90 系统"}


def sha(value: bytes): return hashlib.sha256(value).hexdigest()
def now(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
def atomic(path: Path, value: bytes):
    path.parent.mkdir(parents=True, exist_ok=True); temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    temporary.write_bytes(value); os.replace(temporary, path)
def atomic_json(path: Path, value): atomic(path, (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode())


def split(text: str):
    if not text.startswith("---\n"): return None
    end = text.find("\n---\n", 4)
    if end < 0: return None
    return text[4:end].splitlines(), text[end + 5:]


def migrate_text(text: str, folder: str):
    parts = split(text)
    if not parts: return text, False, ""
    lines, body = parts; desired = CANONICAL.get(folder); output = []; found = False; previous = ""
    for line in lines:
        if line.startswith("asset_class:"):
            found = True; previous = line.split(":", 1)[1].strip()
            if desired: output.append(f"asset_class: {desired}")
            continue
        output.append(line)
    if desired and not found: output.append(f"asset_class: {desired}")
    result = "---\n" + "\n".join(output) + "\n---\n" + body
    return result, result != text, previous


def load_relation_common(project: Path):
    path = project / "knowledge-relation-manager" / "relation_common.py"
    spec = importlib.util.spec_from_file_location("relation_common_freeze", path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--vault", required=True); parser.add_argument("--project", required=True)
    parser.add_argument("--registry", required=True); parser.add_argument("--governance-root", required=True)
    parser.add_argument("--execute", action="store_true"); parser.add_argument("--output", required=True); args = parser.parse_args()
    vault, project = Path(args.vault).resolve(), Path(args.project).resolve(); registry_path = Path(args.registry).resolve()
    governance = Path(args.governance_root).resolve(); changes = []
    for folder in list(CANONICAL) + sorted(REMOVE_ONLY):
        root = vault / folder
        if not root.exists(): continue
        for path in sorted(root.rglob("*.md")):
            before = path.read_bytes(); text = before.decode("utf-8"); after_text, changed, previous = migrate_text(text, folder)
            if not changed: continue
            after = after_text.encode("utf-8"); before_body = split(text)[1].encode(); after_body = split(after_text)[1].encode()
            if sha(before_body) != sha(after_body): raise SystemExit(f"body drift detected: {path}")
            changes.append({"path": str(path), "relative_path": str(path.relative_to(vault)), "folder": folder,
                "previous_asset_class": previous, "new_asset_class": CANONICAL.get(folder, "removed"),
                "before_hash": "sha256:" + sha(before), "after_hash": "sha256:" + sha(after),
                "body_hash": "sha256:" + sha(before_body), "after_bytes": after})
    result = {"protocol": "graph-asset-class-migration-receipt-v1", "created_at": now(),
        "mode": "execute" if args.execute else "dry_run", "changes": [{k:v for k,v in item.items() if k != "after_bytes"} for item in changes],
        "canonical_values": sorted(set(CANONICAL.values())), "body_modified": False, "registry_rebased": []}
    if args.execute:
        snapshot_root = governance / "snapshots"; receipt_root = governance / "receipts"
        registry_before = registry_path.read_bytes(); registry = json.loads(registry_before)
        registry_snapshot = snapshot_root / "relation-registry.before.json"
        atomic(registry_snapshot, registry_before)
        result["registry_snapshot_path"] = str(registry_snapshot)
        for item in changes:
            path = Path(item["path"]); current = path.read_bytes()
            if "sha256:" + sha(current) != item["before_hash"]: raise SystemExit(f"preflight hash drift: {path}")
            atomic(snapshot_root / (sha(current) + ".md"), current); atomic(path, item["after_bytes"])
            if "sha256:" + sha(path.read_bytes()) != item["after_hash"]: raise SystemExit(f"write verification failed: {path}")
        common = load_relation_common(project); assets = {x["relative_path"]: x for x in common.scan_vault(str(vault))}
        for relation in registry.get("relations", []):
            source, target = assets.get(relation["source_location"]), assets.get(relation["target_location"])
            if not source or not target: continue
            touched = {item["relative_path"] for item in changes}
            if relation["source_location"] not in touched and relation["target_location"] not in touched: continue
            if source["asset_id"] != relation["source_asset_id"] or target["asset_id"] != relation["target_asset_id"]:
                raise SystemExit("relation endpoint identity changed during metadata migration")
            relation["source_revision"] = source["revision"]; relation["target_revision"] = target["revision"]
            relation["projection_snapshot_hashes"] = {"source": source["file_hash"], "target": target["file_hash"]}
            relation["revalidation_status"] = "verified"; relation["revalidated_at"] = now()
            relation["revision_change_reason"] = "graph_metadata_canonicalization_nonsemantic"
            result["registry_rebased"].append(relation["relation_id"])
        if result["registry_rebased"]:
            registry["updated_at"] = now(); atomic_json(registry_path, registry)
        result["registry_before_hash"] = "sha256:" + sha(registry_before)
        result["registry_after_hash"] = "sha256:" + sha(registry_path.read_bytes())
        result["validation_result"] = "committed"
        receipt_id = "graph_migration_sha256_" + sha(json.dumps(result, ensure_ascii=False, sort_keys=True).encode())
        result["receipt_id"] = receipt_id; receipt_path = receipt_root / f"{receipt_id}.json"
        atomic_json(receipt_path, result); result["receipt_path"] = str(receipt_path)
    atomic_json(Path(args.output), result); print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
