#!/usr/bin/env python3
"""Synthetic publisher/Relation projection compatibility; all writes are isolated."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "knowledge-ingestion-manager"))
sys.path.insert(0, str(ROOT / "knowledge-relation-manager"))
from approval_binding import prepare
from publisher_core import canonical
from relation_apply import append_relation, proposed_block


def sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def write_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(value))


class ProjectionCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="guanlan-projection-compat.", dir="/private/tmp")
        self.base = Path(self.temp.name)
        self.vault = self.base / "vault"
        self.assets = self.base / "asset-library"
        self.registry_path = self.assets / "relations/relation-registry-v1.json"
        self.filename = "2026-09-21_学习_合成.md"
        self.target = self.vault / "20 学习笔记" / self.filename
        self.source = {"protocol": "source-material-v3", "material_id": "material_sha256_" + "a" * 64,
                       "revision_id": "revision_sha256_" + "b" * 64}
        self.body = "# 合成学习笔记\n\n经用户确认的正文事实。\n\n- 用户手动链接：[[用户自建笔记]]\n"
        self.draft = {"protocol": "knowledge-asset-draft-v1", "asset": {"asset_id": "draft_fixture", "type": "learning_note", "status": "draft"},
                      "source": {"material_id": self.source["material_id"]}}
        self.quality = {"protocol": "knowledge-publish-quality-v1", "status": "passed"}
        refs = [f"guanlan://material/{self.source['material_id']}/revision/{self.source['revision_id']}"]
        self.candidate = {"protocol": "derivative-candidate-v1", "candidate_id": "draft_fixture", "asset_type": "learning_note",
                          "status": "publishable", "source": {"material_id": self.source["material_id"], "revision_id": self.source["revision_id"]},
                          "content": {"title": "合成学习笔记", "markdown": self.body}, "provenance": {"stable_references": refs},
                          "admission": {"status": "passed"}}
        self.approval = {"protocol": "knowledge-publish-approval-v1", "approval_id": "approval-fixture", "confirmed": True,
                         "reviewer": "user", "confirmed_at": "2026-09-21T00:00:00Z", "source_asset_id": self.source["material_id"],
                         "source_revision_id": self.source["revision_id"], "knowledge_content_hash": sha(self.body.encode()),
                         "stable_references": refs,
                         "approval_binding": prepare(candidate=self.candidate, source=self.source, target_folder="20 学习笔记",
                                                     filename=self.filename, body=self.body, title="合成学习笔记", quality=self.quality)}
        for name, value in (("source.json", self.source), ("draft.json", self.draft), ("candidate.json", self.candidate),
                            ("quality.json", self.quality), ("approval.json", self.approval)):
            write_json(self.base / name, value)
        (self.base / "generated.md").write_text(self.body)
        self.command = [sys.executable, str(ROOT / "knowledge-ingestion-manager/learning_publish.py"),
                        "--draft", str(self.base / "draft.json"), "--generated", str(self.base / "generated.md"),
                        "--candidate", str(self.base / "candidate.json"), "--confirmation", str(self.base / "approval.json"),
                        "--quality", str(self.base / "quality.json"), "--source-material", str(self.base / "source.json"),
                        "--vault-root", str(self.vault), "--asset-root", str(self.assets), "--filename", self.filename,
                        "--scope", "test", "--output", str(self.base / "result.json")]
        first = self.run_publish()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.original = self.target.read_bytes()
        self.result = json.loads((self.base / "result.json").read_text())
        write_json(self.registry_path, {"protocol": "relation-registry-v1", "relations": [], "schema_version": "1.0.0"})

    def tearDown(self): self.temp.cleanup()

    def run_publish(self, command=None):
        return subprocess.run(command or self.command, capture_output=True, text=True)

    def assert_conflict(self):
        result = self.run_publish()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue("conflict" in result.stderr or "approval_binding" in result.stderr, result.stderr)

    def add_relation(self, n=1):
        source_loc = f"10 原始资料/来源{n}.md"
        source_path = self.vault / source_loc
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(f"# 来源{n}\n")
        relation = {"relation_id": f"relation_{n}", "candidate_id": f"relation_candidate_{n}",
                    "source_asset_id": f"material_sha256_{n:064x}", "target_asset_id": self.result["asset_id"],
                    "source_location": source_loc, "target_location": "20 学习笔记/" + self.filename,
                    "relation_type": "source_of", "reciprocal_relation": "derived_from", "approval_status": "auto_executed"}
        candidate = {"candidate_id": relation["candidate_id"], "relation_type": "source_of", "reciprocal_relation": "derived_from",
                     "source_display": {"path": source_loc}, "target_display": {"path": relation["target_location"]}}
        source_heading, source_line = proposed_block(candidate, "source")
        target_heading, target_line = proposed_block(candidate, "target")
        source_before, target_before = source_path.read_bytes(), self.target.read_bytes()
        registry_before = self.registry_path.read_bytes()
        source_after = append_relation(source_before.decode(), source_heading, source_line).encode()
        target_after = append_relation(target_before.decode(), target_heading, target_line).encode()
        backup = self.assets / "rollback/relation-curation" / relation["candidate_id"]
        backup.mkdir(parents=True)
        (backup / "source.before.md").write_bytes(source_before)
        (backup / "target.before.md").write_bytes(target_before)
        (backup / "registry.before.json").write_bytes(registry_before)
        relation["projection_snapshot_hashes"] = {"source": sha(source_after), "target": sha(target_after)}
        registry = json.loads(registry_before)
        registry["relations"].append(relation)
        write_json(self.registry_path, registry)
        source_path.write_bytes(source_after); self.target.write_bytes(target_after)
        receipt = {"protocol": "relation-apply-receipt-v1", "status": "executed", "candidate_id": relation["candidate_id"],
                   "execution_authority": "auto_strong", "backup_directory": str(backup),
                   "registry_path": str(self.registry_path), "source_path": str(source_path), "target_path": str(self.target),
                   "pre_hashes": {"source": sha(source_before), "target": sha(target_before), "registry": sha(registry_before)},
                   "post_hashes": {"source": sha(source_after), "target": sha(target_after), "registry": sha(self.registry_path.read_bytes())}}
        receipt_path = self.assets / "relations/receipts" / f"{relation['candidate_id']}.json"
        write_json(receipt_path, receipt)
        return relation, receipt_path

    def test_T01_original_idempotent(self):
        self.assertEqual(self.run_publish().returncode, 0)
        self.assertEqual(json.loads((self.base / "result.json").read_text())["status"], "already_published")

    def test_T02_one_verified_projection(self):
        self.add_relation()
        self.assertEqual(self.run_publish().returncode, 0)
        self.assertEqual(self.target.read_bytes().count(b"relation_candidate_1"), 1)

    def test_T03_two_sequential_projections(self):
        self.add_relation(1); self.add_relation(2)
        self.assertEqual(self.run_publish().returncode, 0)

    def test_T04_projection_replay_not_duplicate(self):
        relation, _ = self.add_relation()
        candidate = {"candidate_id": relation["candidate_id"], "relation_type": "source_of", "reciprocal_relation": "derived_from",
                     "source_display": {"path": relation["source_location"]}, "target_display": {"path": relation["target_location"]}}
        heading, line = proposed_block(candidate, "target")
        self.assertEqual(append_relation(self.target.read_text(), heading, line), self.target.read_text())
        self.assertEqual(self.run_publish().returncode, 0)

    def test_T05_body_single_character_tamper(self):
        self.add_relation(); self.target.write_text(self.target.read_text().replace("正文事实", "正文伪实"))
        self.assert_conflict()

    def test_T06_manual_body_link_tamper(self):
        self.add_relation(); self.target.write_text(self.target.read_text().replace("[[用户自建笔记]]", "[[伪造笔记]]"))
        self.assert_conflict()

    def test_T07_nonmanaged_markdown_added(self):
        self.add_relation(); self.target.write_text(self.target.read_text() + "\n新主张。\n")
        self.assert_conflict()

    def test_T08_extra_managed_section_content(self):
        self.add_relation(); self.target.write_text(self.target.read_text() + "- 人工混入\n")
        self.assert_conflict()

    def test_T09_link_registry_mismatch(self):
        self.add_relation(); self.target.write_text(self.target.read_text().replace("[[来源1]]", "[[错误来源]]"))
        self.assert_conflict()

    def test_T09b_registry_relation_missing(self):
        self.add_relation(); write_json(self.registry_path, {"protocol": "relation-registry-v1", "relations": []})
        self.assert_conflict()

    def test_T09c_registry_relation_without_projection(self):
        self.add_relation(); self.target.write_bytes(self.original)
        self.assert_conflict()

    def test_T10_broken_managed_boundary(self):
        self.add_relation(); self.target.write_text(self.target.read_text().replace("## 来源资料", "### 来源资料"))
        self.assert_conflict()

    def test_T11_original_receipt_projection_unverifiable(self):
        self.add_relation()
        receipt_path = Path(self.result["receipt"]); receipt = json.loads(receipt_path.read_text())
        receipt["projection_hash"] = "sha256:" + "f" * 64; write_json(receipt_path, receipt)
        self.assert_conflict()

    def test_T12_relation_receipt_tamper(self):
        _, path = self.add_relation(); receipt = json.loads(path.read_text())
        receipt["post_hashes"]["target"] = "sha256:" + "f" * 64; write_json(path, receipt)
        self.assert_conflict()

    def test_T15_legacy_approval_remains_valid_for_completed_asset(self):
        self.add_relation()
        approval = copy.deepcopy(self.approval); approval.pop("approval_binding")
        write_json(self.base / "approval.json", approval)
        receipt_path = Path(self.result["receipt"]); receipt = json.loads(receipt_path.read_text()); receipt.pop("approval_binding_hash")
        write_json(receipt_path, receipt)
        self.assertEqual(self.run_publish().returncode, 0)

    def test_T16_T17_retry_preserves_projection_and_single_receipt(self):
        self.add_relation(); before = self.target.read_bytes()
        self.assertEqual(self.run_publish().returncode, 0)
        self.assertEqual(self.run_publish().returncode, 0)
        self.assertEqual(before, self.target.read_bytes())
        self.assertEqual(len(list((self.assets / "governance/knowledge-publish/original-receipts").glob("*.json"))), 1)
        self.assertEqual(len(json.loads((self.assets / "governance/knowledge-publish/publish-index-v1.json").read_text())["publications"]), 1)


if __name__ == "__main__": unittest.main(verbosity=2)
