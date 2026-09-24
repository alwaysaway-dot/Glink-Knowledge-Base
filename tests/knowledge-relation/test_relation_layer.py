#!/usr/bin/env python3

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "knowledge-relation-manager"))

import relation_apply
import relation_common
import relation_discovery


MATERIAL = "material_sha256_" + "a" * 64
REVISION = "revision_sha256_" + "b" * 64
KNOWLEDGE = "asset_sha256_" + "c" * 64


SOURCE_TEXT = f"""---
type: source_asset
status: confirmed
material_id: {MATERIAL}
revision_id: {REVISION}
---

# 来源资产

## 来源信息

完整事实内容。
"""

LEARNING_TEXT = f"""---
type: learning_note
status: published
asset_id: {KNOWLEDGE}
source_asset: {MATERIAL}
source_revision: {REVISION}
source_reference: guanlan://material/{MATERIAL}/revision/{REVISION}
---

# 正式学习笔记

## 核心问题

如何理解事实内容。
"""


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class RelationLayerTests(unittest.TestCase):
    def make_vault(self, root):
        vault = Path(root) / "vault"
        for name in relation_common.SCAN_DIRECTORIES:
            (vault / name).mkdir(parents=True, exist_ok=True)
        write(vault / "10 原始资料/source.md", SOURCE_TEXT)
        write(vault / "20 学习笔记/learning.md", LEARNING_TEXT)
        write(vault / "20 学习笔记/ignored_Draft.md", LEARNING_TEXT.replace("status: published", "status: waiting_user_confirmation"))
        write(vault / "00 收件箱/should-not-scan.md", SOURCE_TEXT)
        return vault

    def registry(self):
        return {"protocol": "relation-registry-v1", "schema_version": "1.0.0", "registry_id": "test", "relations": [], "updated_at": ""}

    def test_scope_status_identity_direction_and_deduplication(self):
        with tempfile.TemporaryDirectory() as temp:
            vault = self.make_vault(temp)
            assets = relation_common.scan_vault(str(vault))
            self.assertEqual(len(assets), 3)
            excluded = [item for item in assets if not item["eligible"]]
            self.assertEqual(excluded[0]["exclusion_reason"], "draft_excluded")
            strong, medium, _, _ = relation_discovery.discover(assets, self.registry(), "2026-08-08T00:00:00Z")
            self.assertEqual(len(strong), 1)
            self.assertEqual(medium, [])
            candidate = strong[0]
            self.assertEqual(candidate["relation_type"], "source_of")
            self.assertEqual(candidate["reciprocal_relation"], "derived_from")
            self.assertEqual(candidate["decision_status"], "suggested")
            self.assertEqual(candidate["source_asset_id"], MATERIAL)
            self.assertEqual(candidate["target_asset_id"], KNOWLEDGE)

            registry = self.registry()
            registry["relations"].append({
                "source_asset_id": MATERIAL, "target_asset_id": KNOWLEDGE,
                "relation_type": "source_of", "reciprocal_relation": "derived_from",
                "approval_status": "executed",
            })
            strong_again = relation_discovery.structural_candidates(assets, registry)
            self.assertEqual(strong_again, [])

    def test_medium_and_weak_semantic_thresholds(self):
        def asset(char, section_count):
            headings = ["核心问题", "核心概念", "论证逻辑", "适用场景"][:section_count]
            return {
                "asset_id": "asset_sha256_" + char * 64,
                "revision": "snapshot_sha256_" + char * 64,
                "file_hash": "sha256:" + char * 64,
                "asset_class": "knowledge", "title": char, "relative_path": f"20 学习笔记/{char}.md",
                "sections": {heading: "资产治理状态转换 稳定身份人工确认" for heading in headings},
            }
        medium, rejection = relation_discovery.semantic_candidate(asset("d", 3), asset("e", 3))
        self.assertIsNone(rejection)
        self.assertEqual(medium["relation_strength"], "medium")
        weak, rejection = relation_discovery.semantic_candidate(asset("f", 2), asset("1", 2))
        self.assertIsNone(weak)
        self.assertEqual(rejection["reason"], "fewer_than_three_semantic_dimensions")

    def test_candidate_identity_ignores_filename(self):
        first = relation_common.candidate_id(MATERIAL, REVISION, KNOWLEDGE, "snapshot_sha256_" + "d" * 64, "source_of")
        second = relation_common.candidate_id(MATERIAL, REVISION, KNOWLEDGE, "snapshot_sha256_" + "d" * 64, "source_of")
        self.assertEqual(first, second)

    def test_apply_defaults_to_dry_run_revision_guard_and_rollback(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            vault = self.make_vault(temp)
            registry_path = base / "registry.json"
            relation_common.atomic_json(registry_path, self.registry())
            assets = relation_common.scan_vault(str(vault))
            candidate = relation_discovery.structural_candidates(assets, self.registry())[0]
            candidate["created_at"] = "2026-08-08T00:00:00Z"
            source = next(item for item in assets if item["asset_class"] == "source")
            target = next(item for item in assets if item["eligible"] and item["asset_class"] == "knowledge")
            plan = relation_apply.dry_run(candidate, source, target)
            self.assertTrue(plan["dry_run"])
            self.assertEqual(plan["links_written"], 0)

            approval = base / "approval.json"
            relation_common.atomic_json(approval, {"confirmed": True, "candidate_id": candidate["candidate_id"], "reviewer": "user", "approved_at": "2026-08-08T00:00:00Z"})
            receipt_path = base / "receipt.json"
            receipt = relation_apply.execute(candidate, source, target, registry_path, approval, base / "rollback", receipt_path)
            self.assertEqual(receipt["status"], "executed")
            self.assertIn("[[learning]]", Path(source["absolute_path"]).read_text(encoding="utf-8"))
            rollback_confirmation = base / "rollback-confirmation.json"
            relation_common.atomic_json(rollback_confirmation, {"confirmed": True, "candidate_id": candidate["candidate_id"]})
            result = relation_apply.rollback(receipt_path, rollback_confirmation, base / "rollback-result.json")
            self.assertEqual(result["status"], "rolled_back")
            self.assertEqual(Path(source["absolute_path"]).read_text(encoding="utf-8"), SOURCE_TEXT)
            self.assertEqual(json.loads(registry_path.read_text(encoding="utf-8"))["relations"], [])

            modified_target = Path(target["absolute_path"])
            modified_target.write_text(modified_target.read_text(encoding="utf-8") + "\n变更", encoding="utf-8")
            changed = relation_common.scan_asset(modified_target, vault, "knowledge")
            with self.assertRaisesRegex(ValueError, "revision changed"):
                relation_apply.validate_revisions(candidate, source, changed)

    def test_structural_strong_can_auto_apply_without_user_approval(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            vault = self.make_vault(temp)
            registry_path = base / "registry.json"
            relation_common.atomic_json(registry_path, self.registry())
            assets = relation_common.scan_vault(str(vault))
            candidate = relation_discovery.structural_candidates(assets, self.registry())[0]
            candidate["created_at"] = "2026-08-08T00:00:00Z"
            source = next(item for item in assets if item["asset_class"] == "source")
            target = next(item for item in assets if item["eligible"] and item["asset_class"] == "knowledge")
            receipt = relation_apply.execute(candidate, source, target, registry_path, None, base / "rollback", base / "receipt.json", auto=True)
            self.assertEqual(receipt["execution_authority"], "auto_strong")
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            self.assertEqual(registry["relations"][0]["approval_status"], "auto_executed")


if __name__ == "__main__":
    unittest.main()
