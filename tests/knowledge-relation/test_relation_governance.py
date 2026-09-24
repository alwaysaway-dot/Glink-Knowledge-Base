#!/usr/bin/env python3
"""Regression tests for Observation, Exception and Markdown governance."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "knowledge-relation-manager"))
from relation_apply import append_relation, proposed_block  # noqa: E402
from relation_governance import audit_registry_markdown, reconcile_exceptions, reconcile_observations, repair_markdown, scan_manual_links  # noqa: E402


SOURCE_ID = "material_sha256_" + "a" * 64
SOURCE_REV = "revision_sha256_" + "b" * 64
TARGET_ID = "asset_sha256_" + "c" * 64


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class RelationGovernanceTests(unittest.TestCase):
    def fixture(self, root):
        vault = root / "vault"
        source = vault / "10 原始资料/source.md"
        target = vault / "20 学习笔记/target.md"
        write(source, f"---\ntype: source_asset\nstatus: confirmed\nmaterial_id: {SOURCE_ID}\nrevision_id: {SOURCE_REV}\n---\n# Source\n")
        write(target, f"---\ntype: learning_note\nstatus: published\nasset_id: {TARGET_ID}\nsource_asset: {SOURCE_ID}\nsource_revision: {SOURCE_REV}\nsource_reference: guanlan://material/{SOURCE_ID}/revision/{SOURCE_REV}\n---\n# Target\n")
        relation = {"relation_id": "relation-1", "candidate_id": "candidate-1", "source_asset_id": SOURCE_ID, "source_revision": SOURCE_REV, "target_asset_id": TARGET_ID, "target_revision": "snapshot_sha256_" + "0" * 64, "relation_type": "source_of", "reciprocal_relation": "derived_from", "approval_status": "auto_executed", "source_location": "10 原始资料/source.md", "target_location": "20 学习笔记/target.md"}
        candidate = {"candidate_id": "candidate-1", "relation_type": "source_of", "reciprocal_relation": "derived_from", "source_display": {"path": relation["source_location"]}, "target_display": {"path": relation["target_location"]}}
        for side, path in (("source", source), ("target", target)):
            heading, line = proposed_block(candidate, side)
            path.write_text(append_relation(path.read_text(encoding="utf-8"), heading, line), encoding="utf-8")
        # Snapshot revision after the managed display projection is the healthy baseline.
        import relation_common
        relation["target_revision"] = relation_common.scan_asset(target, vault, "knowledge")["revision"]
        return vault, relation

    def test_managed_link_is_healthy_and_manual_link_is_not_registered(self):
        with tempfile.TemporaryDirectory() as temp:
            vault, relation = self.fixture(Path(temp))
            manual = vault / "40 方法库/manual.md"
            write(manual, "# Manual\n\n[[不应自动注册]]\n")
            assets, checks, exceptions, repairs = audit_registry_markdown(vault, {"relations": [relation]})
            self.assertEqual(checks[0]["status"], "healthy")
            self.assertEqual(exceptions, [])
            self.assertEqual(repairs, [])
            managed, legacy = scan_manual_links(vault, {"relations": [relation]})
            self.assertEqual(managed, 2)
            self.assertEqual(len(legacy), 1)

    def test_missing_managed_display_is_receipt_verified_repair_candidate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            vault, relation = self.fixture(root)
            target = vault / "20 学习笔记/target.md"
            target.write_text(target.read_text(encoding="utf-8").replace(" · `derived_from` · `candidate-1`", ""), encoding="utf-8")
            source = vault / "10 原始资料/source.md"
            candidate = {"candidate_id": "candidate-1", "relation_type": "source_of", "reciprocal_relation": "derived_from", "source_display": {"path": relation["source_location"]}, "target_display": {"path": relation["target_location"]}}
            _, target_line = proposed_block(candidate, "target")
            target_heading, _ = proposed_block(candidate, "target")
            receipt_root = root / "receipts"; receipt_root.mkdir()
            import hashlib
            expected_target = append_relation(target.read_text(encoding="utf-8"), target_heading, target_line).encode("utf-8")
            (receipt_root / "receipt.json").write_text(json.dumps({"protocol": "relation-apply-receipt-v1", "candidate_id": "candidate-1", "post_hashes": {"source": "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest(), "target": "sha256:" + hashlib.sha256(expected_target).hexdigest()}}), encoding="utf-8")
            _, checks, exceptions, repairs = audit_registry_markdown(vault, {"relations": [relation]}, receipt_root)
            self.assertEqual(checks[0]["status"], "repair_candidate")
            self.assertEqual(exceptions, [])
            self.assertEqual(len(repairs), 1)
            repaired = repair_markdown({"repair_candidates": repairs}, vault)
            self.assertEqual([Path(item).resolve() for item in repaired], [target.resolve()])
            self.assertIn("`derived_from` · `candidate-1`", target.read_text(encoding="utf-8"))

    def test_observation_and_exception_are_persistent_without_user_notifications(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            medium = {"candidate_id": "medium-1", "source_asset_id": SOURCE_ID, "target_asset_id": TARGET_ID, "relation_type": "explains", "confidence": "medium", "evidence": [{"kind": "semantic_dimension"}]}
            pool = reconcile_observations(root / "pool.json", [medium], [], "2026-08-08T00:00:00Z")
            pool = reconcile_observations(root / "pool.json", [medium], [], "2026-08-09T00:00:00Z")
            self.assertEqual(pool["observations"][0]["current_status"], "observing")
            self.assertEqual(pool["observations"][0]["times_detected"], 2)
            exception = {"exception_id": "exception-1", "assets": [SOURCE_ID, TARGET_ID], "existing_relation": "", "problem": "identity_conflict", "evidence": {}, "system_recommendation": "review", "risk": "high", "available_actions": ["inspect"], "status": "open", "first_seen": "", "last_seen": ""}
            queue = reconcile_exceptions(root / "queue.json", [exception])
            self.assertEqual(queue["exceptions"][0]["status"], "open")
            queue = reconcile_exceptions(root / "queue.json", [])
            self.assertEqual(queue["exceptions"][0]["status"], "resolved")


if __name__ == "__main__":
    unittest.main(verbosity=2)
