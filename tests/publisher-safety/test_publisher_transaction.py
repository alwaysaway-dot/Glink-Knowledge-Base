#!/usr/bin/env python3
"""Isolated, cross-process transaction and recovery tests; never touches real Vault."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from test_approval_binding import CANDIDATE, QUALITY, ROOT, SOURCE, KWARGS, write_json

sys.path.insert(0, str(ROOT / "knowledge-ingestion-manager"))
from approval_binding import prepare
from publisher_core import digest


class PublisherTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="guanlan-publisher-transaction.", dir="/private/tmp")
        self.base = Path(self.temp.name)
        self.vault = self.base / "vault"
        self.assets = self.base / "assets"
        self.candidate = copy.deepcopy(CANDIDATE)
        self.quality = copy.deepcopy(QUALITY)
        self.approval = self.make_approval(self.candidate, self.quality)
        self.write_inputs()

    def tearDown(self): self.temp.cleanup()

    def make_approval(self, candidate, quality, filename=None):
        return {"protocol": "derivative-publish-approval-v1", "approval_id": "approval-fixture", "confirmed": True,
                "reviewer": "user", "confirmed_at": "2026-09-21T00:00:00Z", "candidate_id": candidate["candidate_id"],
                "asset_type": "creation_asset", "content_hash": "sha256:" + digest((candidate["content"]["markdown"].strip() + "\n").encode()),
                "stable_references": candidate["provenance"]["stable_references"],
                "approval_binding": prepare(candidate=candidate, source=SOURCE, target_folder="50 输出成果",
                                            filename=filename or KWARGS["filename"], body=candidate["content"]["markdown"],
                                            title=candidate["content"]["title"], quality=quality)}

    def write_inputs(self):
        for filename, value in (("candidate.json", self.candidate), ("approval.json", self.approval),
                                ("quality.json", self.quality), ("source.json", SOURCE)):
            write_json(self.base / filename, value)

    def command(self, *, fault="none", output="output.json", filename=None):
        return [sys.executable, str(ROOT / "knowledge-ingestion-manager/derivative_publish.py"),
                "--candidate", str(self.base / "candidate.json"), "--confirmation", str(self.base / "approval.json"),
                "--quality", str(self.base / "quality.json"), "--source-material", str(self.base / "source.json"),
                "--vault-root", str(self.vault), "--asset-root", str(self.assets), "--filename", filename or KWARGS["filename"],
                "--target-folder", "50 输出成果", "--scope", "test", "--fault-injection", fault,
                "--output", str(self.base / output)]

    def run_publish(self, **kwargs): return subprocess.run(self.command(**kwargs), capture_output=True, text=True)

    def ledger(self):
        governance = self.assets / "governance/derivative-publish"
        index = json.loads((governance / "publish-index-v1.json").read_text())
        return governance, index["publications"]

    def assert_committed_once(self):
        governance, publications = self.ledger()
        self.assertEqual(len(publications), 1)
        self.assertEqual(len(list((self.vault / "50 输出成果").glob("*.md"))), 1)
        receipt = json.loads(Path(publications[0]["receipt_path"]).read_text())
        self.assertEqual(receipt["validation_result"], "committed")
        self.assertEqual(receipt["approval_binding_hash"], self.approval["approval_binding"]["digest"])
        self.assertTrue((governance / "transactions" / receipt["transaction_id"] / "commit.json").is_file())

    def test_same_candidate_concurrent_processes(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda i: self.run_publish(output=f"out{i}.json"), range(2)))
        self.assertTrue(all(r.returncode == 0 for r in results), [r.stderr for r in results])
        self.assertEqual({json.loads((self.base / f"out{i}.json").read_text())["status"] for i in range(2)},
                         {"published", "already_published"})
        self.assert_committed_once()

    def test_different_candidate_same_target_conflict(self):
        self.assertEqual(self.run_publish().returncode, 0)
        original_approval = self.approval
        self.candidate["content"]["markdown"] = "# 方案\n\n另一个候选。\n"
        self.candidate["candidate_id"] = "candidate_competitor"
        self.quality["candidate_id"] = "candidate_competitor"
        self.approval = self.make_approval(self.candidate, self.quality)
        self.write_inputs()
        result = self.run_publish(output="competitor.json")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("identity_conflict", result.stderr)
        self.approval = original_approval
        self.assert_committed_once()

    def test_two_candidates_concurrent_same_ledger_distinct_targets(self):
        second = copy.deepcopy(self.candidate)
        second["candidate_id"] = "candidate_second"
        second["content"] = {"title": "第二方案", "markdown": "# 第二方案\n\n独立内容。\n"}
        second_quality = dict(self.quality, candidate_id="candidate_second")
        second_filename = "2026-09-21_第二方案.md"
        second_approval = self.make_approval(second, second_quality)
        second_approval["candidate_id"] = "candidate_second"
        second_approval["content_hash"] = "sha256:" + digest(second["content"]["markdown"].encode())
        second_approval["approval_binding"] = prepare(candidate=second, source=SOURCE, target_folder="50 输出成果",
                                                      filename=second_filename, body=second["content"]["markdown"],
                                                      title=second["content"]["title"], quality=second_quality)
        for name, value in (("candidate-second.json", second), ("quality-second.json", second_quality),
                            ("approval-second.json", second_approval)):
            write_json(self.base / name, value)
        second_cmd = self.command(output="second-result.json", filename=second_filename)
        for flag, filename in (("--candidate", "candidate-second.json"), ("--quality", "quality-second.json"),
                               ("--confirmation", "approval-second.json")):
            second_cmd[second_cmd.index(flag) + 1] = str(self.base / filename)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda cmd: subprocess.run(cmd, capture_output=True, text=True),
                                    (self.command(output="first-result.json"), second_cmd)))
        self.assertTrue(all(result.returncode == 0 for result in results), [result.stderr for result in results])
        governance, publications = self.ledger()
        self.assertEqual(len(publications), 2)
        self.assertEqual(len(list((self.vault / "50 输出成果").glob("*.md"))), 2)
        self.assertEqual(len(list((governance / "original-receipts").glob("*.json"))), 2)

    def test_two_candidates_concurrent_same_target_only_one_commits(self):
        second = copy.deepcopy(self.candidate)
        second["candidate_id"] = "candidate_racer"
        second["content"]["markdown"] = "# 方案\n\n竞争者正文。\n"
        second_quality = dict(self.quality, candidate_id="candidate_racer")
        second_approval = self.make_approval(second, second_quality)
        for name, value in (("candidate-racer.json", second), ("quality-racer.json", second_quality),
                            ("approval-racer.json", second_approval)):
            write_json(self.base / name, value)
        second_cmd = self.command(output="racer-result.json")
        for flag, filename in (("--candidate", "candidate-racer.json"), ("--quality", "quality-racer.json"),
                               ("--confirmation", "approval-racer.json")):
            second_cmd[second_cmd.index(flag) + 1] = str(self.base / filename)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda cmd: subprocess.run(cmd, capture_output=True, text=True),
                                    (self.command(output="original-result.json"), second_cmd)))
        self.assertEqual(sorted(result.returncode == 0 for result in results), [False, True])
        self.assertIn("identity_conflict", next(result.stderr for result in results if result.returncode))
        self.assertEqual(len(self.ledger()[1]), 1)
        self.assertEqual(len(list((self.vault / "50 输出成果").glob("*.md"))), 1)

    def test_bundle_partial_publish_then_retry(self):
        first = copy.deepcopy(self.candidate)
        second = copy.deepcopy(self.candidate)
        second["candidate_id"] = "candidate_bundle_second"
        second["content"] = {"title": "第二方案", "markdown": "# 第二方案\n\n经批准的第二份内容。\n"}
        source_candidate = {"candidate_id": "source_fixture", "asset_type": "source_asset", "status": "publishable",
                            "source": {"material_id": SOURCE["material_id"], "revision_id": SOURCE["revision_id"]}}
        bundle = {"protocol": "candidate-bundle-v1", "bundle_id": "bundle_fixture", "workflow_state": "awaiting_user_confirmation",
                  "source": {"material_id": SOURCE["material_id"], "revision_id": SOURCE["revision_id"]},
                  "source_candidate": source_candidate, "derivative_candidates": [first, second]}
        write_json(self.base / "bundle.json", bundle)
        components, bindings = {}, {}
        rel = lambda path: os.path.relpath(path, self.base)
        for idx, candidate in enumerate((first, second), 1):
            label = f"bundle-{idx}"; filename = f"2026-09-21_方案{idx}.md"
            quality = dict(self.quality, candidate_id=candidate["candidate_id"])
            approval = self.make_approval(candidate, quality, filename)
            for name, value in (("candidate", candidate), ("quality", quality), ("approval", approval)):
                write_json(self.base / f"{label}-{name}.json", value)
            bindings[candidate["candidate_id"]] = prepare(candidate=candidate, source=SOURCE, target_folder="50 输出成果",
                filename=filename, body=candidate["content"]["markdown"], title=candidate["content"]["title"], quality=quality,
                bundle=bundle)
            components[candidate["candidate_id"]] = {"asset_type": "creation_asset", "target_folder": "50 输出成果", "inputs": {
                "candidate": rel(self.base / f"{label}-candidate.json"), "confirmation": rel(self.base / f"{label}-approval.json"),
                "quality": rel(self.base / f"{label}-quality.json"), "source_material": rel(self.base / "source.json"),
                "vault_root": rel(self.vault), "asset_root": rel(self.assets), "filename": filename,
                "target_folder": "50 输出成果", "output": rel(self.base / f"{label}-result.json")}}
        plan = {"protocol": "candidate-bundle-publish-plan-v1", "bundle_id": bundle["bundle_id"],
                "approval": {"confirmed": True, "reviewer": "user", "bindings": bindings},
                "selected_candidate_ids": [first["candidate_id"], second["candidate_id"]], "components": components}
        write_json(self.base / "plan.json", plan)
        conflict = self.vault / "50 输出成果/2026-09-21_方案2.md"
        conflict.parent.mkdir(parents=True, exist_ok=True); conflict.write_text("pre-existing fixture")
        cmd = [sys.executable, str(ROOT / "knowledge-ingestion-manager/bundle_publish.py"),
               "--bundle", str(self.base / "bundle.json"), "--publish-plan", str(self.base / "plan.json"),
               "--scope", "test", "--operation-root", str(self.assets / "operations"),
               "--output", str(self.base / "bundle-result.json")]
        partial = subprocess.run(cmd, cwd=self.base, capture_output=True, text=True)
        self.assertEqual(partial.returncode, 0, partial.stderr)
        self.assertEqual(json.loads((self.base / "bundle-result.json").read_text())["status"], "publish_partial")
        self.assertEqual(len(self.ledger()[1]), 1)
        self.assertEqual(conflict.read_text(), "pre-existing fixture")
        conflict.unlink()  # Test-only fixture repair; no production asset is removed.
        retry = subprocess.run(cmd, cwd=self.base, capture_output=True, text=True)
        self.assertEqual(retry.returncode, 0, retry.stderr)
        self.assertEqual(json.loads((self.base / "bundle-result.json").read_text())["status"], "published")
        self.assertEqual(len(self.ledger()[1]), 2)

    def test_crash_after_asset_new_process_recovers(self):
        first = self.run_publish(fault="kill:after_asset")
        self.assertEqual(first.returncode, 91)
        self.assertFalse((self.assets / "governance/derivative-publish/publish-index-v1.json").exists())
        second = self.run_publish(output="retry.json")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(json.loads((self.base / "retry.json").read_text())["status"], "already_published")
        self.assert_committed_once()

    def test_crash_after_receipt_new_process_recovers(self):
        self.assertEqual(self.run_publish(fault="kill:after_receipt").returncode, 91)
        recovered = self.run_publish(output="retry.json")
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assert_committed_once()

    def test_crash_after_index_new_process_recovers(self):
        self.assertEqual(self.run_publish(fault="kill:after_index").returncode, 91)
        recovered = self.run_publish(output="retry.json")
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assert_committed_once()

    def test_crash_during_recovery_then_resume(self):
        self.assertEqual(self.run_publish(fault="kill:after_asset").returncode, 91)
        self.assertEqual(self.run_publish(fault="kill:during_recovery").returncode, 91)
        recovered = self.run_publish(output="retry.json")
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assert_committed_once()

    def test_learning_publisher_crash_recovery_and_nonblocking_relation(self):
        body = "# 学习事实\n\n用户确认的学习内容。\n"
        draft = {"protocol": "knowledge-asset-draft-v1", "asset": {"asset_id": "learning_fixture", "type": "learning_note", "status": "draft"},
                 "source": {"material_id": SOURCE["material_id"]}}
        quality = {"protocol": "knowledge-publish-quality-v1", "status": "passed"}
        refs = CANDIDATE["provenance"]["stable_references"]
        candidate = {"protocol": "derivative-candidate-v1", "candidate_id": "learning_fixture", "asset_type": "learning_note", "status": "publishable",
                     "source": {"material_id": SOURCE["material_id"], "revision_id": SOURCE["revision_id"]},
                     "content": {"title": "学习事实", "markdown": body}, "provenance": {"stable_references": refs},
                     "admission": {"status": "passed"}}
        approval = {"protocol": "knowledge-publish-approval-v1", "approval_id": "approval-learning", "confirmed": True,
                    "reviewer": "user", "confirmed_at": "2026-09-21T00:00:00Z", "source_asset_id": SOURCE["material_id"],
                    "source_revision_id": SOURCE["revision_id"], "knowledge_content_hash": "sha256:" + digest(body.encode()),
                    "stable_references": refs,
                    "approval_binding": prepare(candidate=candidate, source=SOURCE, target_folder="20 学习笔记",
                                                filename="2026-09-21_学习事实.md", body=body, title="学习事实", quality=quality)}
        for name, value in (("learning-draft.json", draft), ("learning-approval.json", approval),
                            ("learning-quality.json", quality), ("learning-candidate.json", candidate)):
            write_json(self.base / name, value)
        (self.base / "learning-note.md").write_text(body)
        command = [sys.executable, str(ROOT / "knowledge-ingestion-manager/learning_publish.py"),
                   "--draft", str(self.base / "learning-draft.json"), "--generated", str(self.base / "learning-note.md"),
                   "--candidate", str(self.base / "learning-candidate.json"), "--confirmation", str(self.base / "learning-approval.json"),
                   "--quality", str(self.base / "learning-quality.json"), "--source-material", str(self.base / "source.json"),
                   "--vault-root", str(self.vault), "--asset-root", str(self.assets), "--filename", "2026-09-21_学习事实.md",
                   "--scope", "test", "--relation-hook", "fail", "--output", str(self.base / "learning-output.json")]
        first = subprocess.run(command + ["--fault-injection", "kill:after_asset"], capture_output=True, text=True)
        self.assertEqual(first.returncode, 91, first.stderr)
        recovered = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertEqual(json.loads((self.base / "learning-output.json").read_text())["status"], "already_published")
        governance = self.assets / "governance/knowledge-publish"
        publications = json.loads((governance / "publish-index-v1.json").read_text())["publications"]
        self.assertEqual(len(publications), 1)
        self.assertEqual(json.loads(Path(publications[0]["receipt_path"]).read_text())["validation_result"], "committed")

    def test_externally_modified_asset_blocks_recovery(self):
        self.assertEqual(self.run_publish(fault="kill:after_asset").returncode, 91)
        target = self.vault / "50 输出成果" / KWARGS["filename"]
        target.write_text(target.read_text() + "人工修改\n")
        blocked = self.run_publish(output="retry.json")
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("publisher_recovery_conflict", blocked.stderr)
        self.assertIn("人工修改", target.read_text())
        self.assertFalse((self.assets / "governance/derivative-publish/publish-index-v1.json").exists())

    def test_legacy_committed_publication_without_binding_remains_idempotent(self):
        self.assertEqual(self.run_publish().returncode, 0)
        _, publications = self.ledger()
        receipt_path = Path(publications[0]["receipt_path"])
        old_receipt = json.loads(receipt_path.read_text())
        old_receipt.pop("approval_binding_hash")
        write_json(receipt_path, old_receipt)
        self.approval.pop("approval_binding")
        self.write_inputs()
        second = self.run_publish(output="legacy-retry.json")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(json.loads((self.base / "legacy-retry.json").read_text())["status"], "already_published")
        self.assertEqual(len(self.ledger()[1]), 1)

    def test_receipt_tamper_blocks_recovery(self):
        self.assertEqual(self.run_publish(fault="kill:after_receipt").returncode, 91)
        _, publications = self.ledger() if (self.assets / "governance/derivative-publish/publish-index-v1.json").exists() else (None, [])
        self.assertEqual(publications, [])
        receipts = list((self.assets / "governance/derivative-publish/original-receipts").glob("*.json"))
        self.assertEqual(len(receipts), 1)
        receipt = json.loads(receipts[0].read_text()); receipt["projection_hash"] = "sha256:" + "f" * 64
        write_json(receipts[0], receipt)
        blocked = self.run_publish(output="tampered.json")
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("publisher_recovery_conflict", blocked.stderr)
        self.assertTrue((self.vault / "50 输出成果" / KWARGS["filename"]).is_file())

    def test_all_fault_points_are_recoverable_or_guarded(self):
        points = ["before_lock", "after_lock", "after_approval", "after_journal", "after_staging", "before_asset",
                  "after_asset", "prepared_receipt", "committed_receipt_before", "committed_receipt_after",
                  "before_index", "after_index", "after_commit", "before_unlock"]
        for point in points:
            with self.subTest(point=point):
                with tempfile.TemporaryDirectory(prefix="guanlan-fault-point.", dir="/private/tmp") as place:
                    old_base, old_vault, old_assets = self.base, self.vault, self.assets
                    try:
                        self.base = Path(place); self.vault = self.base / "vault"; self.assets = self.base / "assets"
                        self.write_inputs()
                        first = self.run_publish(fault=point)
                        if point not in {"after_commit", "before_unlock"}:
                            self.assertNotEqual(first.returncode, 0, point)
                        second = self.run_publish(output="retry.json")
                        self.assertEqual(second.returncode, 0, (point, second.stderr))
                        self.assert_committed_once()
                    finally:
                        self.base, self.vault, self.assets = old_base, old_vault, old_assets


if __name__ == "__main__": unittest.main(verbosity=2)
