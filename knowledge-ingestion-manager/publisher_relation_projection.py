#!/usr/bin/env python3
"""Verify only receipt-backed Relation Registry Markdown projections during publish retry.

This does not edit Markdown, Registry, or receipts. It replays the exact existing
Relation projection implementation from the original published bytes and accepts
only a byte-for-byte match with the current file.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from publisher_transaction import sha

RELATION_DIR = Path(__file__).resolve().parents[1] / "knowledge-relation-manager"
if str(RELATION_DIR) not in sys.path:
    sys.path.insert(0, str(RELATION_DIR))
from relation_apply import append_relation, proposed_block  # noqa: E402


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"publisher_relation_projection_conflict: invalid evidence {path}") from error


def _within(path: Path, root: Path) -> bool:
    return path.resolve().is_relative_to(root.resolve())


def _section_has_line(text: str, heading: str, line: str) -> bool:
    matches = list(re.finditer(r"^#{1,2} .+$", text, re.M))
    selected = [index for index, match in enumerate(matches) if match.group(0) == f"## {heading}"]
    if len(selected) != 1:
        return False
    index = selected[0]
    start = matches[index].end()
    end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
    return text[start:end].splitlines().count(line) == 1


def verify_managed_projection(*, original: bytes, current: bytes, asset_id: str,
                              target: Path, asset_root: Path, vault_root: Path) -> str:
    """Return unchanged/verified, or fail closed on any non-replayable difference."""
    asset_root, vault_root, target = asset_root.resolve(), vault_root.resolve(), target.resolve()
    if not _within(target, vault_root) or target.suffix != ".md":
        raise ValueError("publisher_relation_projection_conflict: target outside Vault")
    registry_path = asset_root / "relations/relation-registry-v1.json"
    receipt_root = asset_root / "relations/receipts"
    if current == original and not registry_path.exists():
        return "unchanged"
    registry = _read_json(registry_path)
    if registry.get("protocol") != "relation-registry-v1" or not isinstance(registry.get("relations"), list):
        raise ValueError("publisher_relation_projection_conflict: invalid Relation Registry")
    if current == original:
        if any(relation.get("approval_status") in {"executed", "auto_executed"} and
               asset_id in {relation.get("source_asset_id"), relation.get("target_asset_id")}
               for relation in registry["relations"]):
            raise ValueError("publisher_relation_projection_conflict: executed relation missing from Markdown")
        return "unchanged"
    relative = target.relative_to(vault_root).as_posix()
    relevant = []
    for relation in registry["relations"]:
        source = relation.get("source_asset_id") == asset_id
        target_side = relation.get("target_asset_id") == asset_id
        if not source and not target_side:
            continue
        if source == target_side:
            raise ValueError("publisher_relation_projection_conflict: ambiguous relation endpoint")
        side = "source" if source else "target"
        if relation.get(f"{side}_location") != relative or relation.get("approval_status") not in {"executed", "auto_executed"}:
            raise ValueError("publisher_relation_projection_conflict: endpoint or relation state differs")
        candidate_id = relation.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id:
            raise ValueError("publisher_relation_projection_conflict: candidate marker missing")
        receipts = []
        if receipt_root.is_dir():
            for path in receipt_root.rglob("*.json"):
                if path.is_symlink() or not _within(path, receipt_root):
                    raise ValueError("publisher_relation_projection_conflict: unsafe relation receipt")
                receipt = _read_json(path)
                if receipt.get("candidate_id") == candidate_id and receipt.get("protocol") == "relation-apply-receipt-v1":
                    receipts.append(receipt)
        if len(receipts) != 1:
            raise ValueError("publisher_relation_projection_conflict: execution receipt missing or duplicated")
        receipt = receipts[0]
        if receipt.get("status") != "executed" or receipt.get("registry_path") != str(registry_path):
            raise ValueError("publisher_relation_projection_conflict: execution receipt invalid")
        for endpoint in ("source", "target"):
            expected_path = vault_root / relation[f"{endpoint}_location"]
            if receipt.get(f"{endpoint}_path") != str(expected_path):
                raise ValueError("publisher_relation_projection_conflict: execution endpoint path differs")
            if not _within(expected_path, vault_root):
                raise ValueError("publisher_relation_projection_conflict: relation endpoint outside Vault")
        backup = Path(receipt.get("backup_directory", ""))
        if not _within(backup, asset_root):
            raise ValueError("publisher_relation_projection_conflict: backup outside asset library")
        before_path = backup / f"{side}.before.md"
        registry_before = backup / "registry.before.json"
        if not before_path.is_file() or not registry_before.is_file():
            raise ValueError("publisher_relation_projection_conflict: predecessor snapshot missing")
        pre_hashes, post_hashes = receipt.get("pre_hashes", {}), receipt.get("post_hashes", {})
        if sha(before_path.read_bytes()) != pre_hashes.get(side) or sha(registry_before.read_bytes()) != pre_hashes.get("registry"):
            raise ValueError("publisher_relation_projection_conflict: predecessor snapshot changed")
        if receipt.get("execution_authority") not in {"auto_strong", "user_approved"}:
            raise ValueError("publisher_relation_projection_conflict: execution authority invalid")
        relevant.append((relation, receipt, side, before_path))
    if not relevant:
        raise ValueError("publisher_relation_projection_conflict: no executed managed relation")
    state = original
    pending = relevant
    last_relation = None
    while pending:
        matching = [item for item in pending if item[1]["pre_hashes"].get(item[2]) == sha(state)]
        if len(matching) != 1:
            raise ValueError("publisher_relation_projection_conflict: relation history is incomplete or ambiguous")
        relation, receipt, side, before_path = matching[0]
        if before_path.read_bytes() != state:
            raise ValueError("publisher_relation_projection_conflict: predecessor bytes differ")
        candidate = {"candidate_id": relation["candidate_id"], "relation_type": relation["relation_type"],
                     "reciprocal_relation": relation["reciprocal_relation"],
                     "source_display": {"path": relation["source_location"]},
                     "target_display": {"path": relation["target_location"]}}
        heading, line = proposed_block(candidate, side)
        other_side = "target" if side == "source" else "source"
        other_path = vault_root / relation[f"{other_side}_location"]
        other_heading, other_line = proposed_block(candidate, other_side)
        if (not other_path.is_file() or other_path.is_symlink() or
                not _section_has_line(other_path.read_text(encoding="utf-8"), other_heading, other_line)):
            raise ValueError("publisher_relation_projection_conflict: reciprocal projection missing")
        after = append_relation(state.decode("utf-8"), heading, line).encode("utf-8")
        if after == state or sha(after) != receipt.get("post_hashes", {}).get(side):
            raise ValueError("publisher_relation_projection_conflict: managed projection does not match receipt")
        state, last_relation = after, (relation, side)
        pending.remove(matching[0])
    if state != current:
        raise ValueError("publisher_relation_projection_conflict: current Markdown has non-managed changes")
    relation, side = last_relation
    if relation.get("projection_snapshot_hashes", {}).get(side) != sha(current):
        raise ValueError("publisher_relation_projection_conflict: Registry projection snapshot differs")
    return "verified"
