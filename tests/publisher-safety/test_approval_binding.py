#!/usr/bin/env python3
"""AU-C2 independent, deterministic approval-bypass matrix."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "knowledge-ingestion-manager"))
from approval_binding import prepare, verify

SOURCE = {"protocol": "source-material-v3", "material_id": "material_sha256_" + "a" * 64,
          "revision_id": "revision_sha256_" + "b" * 64}
CANDIDATE = {"protocol": "derivative-candidate-v1", "candidate_id": "candidate_fixture",
             "asset_type": "creation_asset", "status": "publishable",
             "source": {"material_id": SOURCE["material_id"], "revision_id": SOURCE["revision_id"]},
             "content": {"title": "方案", "markdown": "# 方案\n\n已确认内容。\n"},
             "provenance": {"stable_references": [f"guanlan://material/{SOURCE['material_id']}/revision/{SOURCE['revision_id']}"]},
             "admission": {"status": "passed", "required_fields": ["audience", "purpose", "deliverable", "version"], "user_output_intent": True}}
QUALITY = {"protocol": "derivative-publish-quality-v1", "status": "passed", "candidate_id": "candidate_fixture", "asset_type": "creation_asset"}
KWARGS = {"candidate": CANDIDATE, "source": SOURCE, "target_folder": "50 输出成果", "filename": "2026-09-21_方案.md",
          "body": CANDIDATE["content"]["markdown"], "title": "方案", "quality": QUALITY}


def write_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


class ApprovalBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="guanlan-approval-binding.", dir="/private/tmp")
        self.base = Path(self.temp.name)
        self.approval = {"protocol": "derivative-publish-approval-v1", "approval_id": "approval_fixture", "confirmed": True,
                         "reviewer": "user", "confirmed_at": "2026-09-21T00:00:00Z", "candidate_id": "candidate_fixture",
                         "asset_type": "creation_asset", "content_hash": prepare(**KWARGS)["snapshot"]["content"]["body_hash"],
                         "stable_references": CANDIDATE["provenance"]["stable_references"], "approval_binding": prepare(**KWARGS)}

    def tearDown(self): self.temp.cleanup()

    def test_C2_01_exact_approval(self): self.assertEqual(verify(self.approval, **KWARGS), self.approval["approval_binding"]["digest"])

    def test_C2_02_body_change(self):
        changed = copy.deepcopy(CANDIDATE); changed["content"]["markdown"] = "# 方案\n\n改动正文。\n"
        with self.assertRaisesRegex(ValueError, "mismatch"): verify(self.approval, **dict(KWARGS, candidate=changed, body=changed["content"]["markdown"]))

    def test_C2_03_same_candidate_id_different_body(self):
        changed = copy.deepcopy(CANDIDATE); changed["content"]["markdown"] += "新观点。\n"
        self.assertEqual(changed["candidate_id"], CANDIDATE["candidate_id"])
        with self.assertRaisesRegex(ValueError, "mismatch"): verify(self.approval, **dict(KWARGS, candidate=changed, body=changed["content"]["markdown"]))

    def test_C2_04_title_change(self):
        changed = copy.deepcopy(CANDIDATE); changed["content"]["title"] = "新标题"
        with self.assertRaisesRegex(ValueError, "mismatch"): verify(self.approval, **dict(KWARGS, candidate=changed, title="新标题"))

    def test_C2_05_source_revision_change(self):
        changed = copy.deepcopy(SOURCE); changed["revision_id"] = "revision_sha256_" + "c" * 64
        candidate = copy.deepcopy(CANDIDATE); candidate["source"]["revision_id"] = changed["revision_id"]
        with self.assertRaisesRegex(ValueError, "mismatch"): verify(self.approval, **dict(KWARGS, candidate=candidate, source=changed))

    def test_C2_06_gate_change(self):
        changed = copy.deepcopy(CANDIDATE); changed["admission"]["user_output_intent"] = False
        with self.assertRaisesRegex(ValueError, "mismatch"): verify(self.approval, **dict(KWARGS, candidate=changed))

    def test_C2_07_target_path_change(self):
        with self.assertRaisesRegex(ValueError, "mismatch"): verify(self.approval, **dict(KWARGS, filename="2026-09-21_另一个方案.md"))

    def test_C2_08_bundle_content_change(self):
        bundle = {"bundle_id": "bundle_fixture", "source": CANDIDATE["source"], "source_candidate": {
            "candidate_id": "source_fixture", "asset_type": "source_asset", "status": "publishable", "source": CANDIDATE["source"]},
            "derivative_candidates": [CANDIDATE]}
        approval = {"approval_binding": prepare(**dict(KWARGS, bundle=bundle))}
        changed = copy.deepcopy(bundle); changed["derivative_candidates"][0]["content"]["markdown"] += " changed"
        with self.assertRaisesRegex(ValueError, "mismatch"): verify(approval, **dict(KWARGS, bundle=changed))

    def test_C2_09_missing_legacy_snapshot(self):
        legacy = dict(self.approval); legacy.pop("approval_binding")
        with self.assertRaisesRegex(ValueError, "approval_binding_missing"): verify(legacy, **KWARGS)

    def test_C2_10_unapproved_prepare_is_not_confirmation(self):
        result = prepare(**KWARGS); self.assertNotIn("confirmed", result)

    def test_C2_11_publisher_integration_and_idempotency(self):
        candidate_path = self.base / "candidate.json"; approval_path = self.base / "approval.json"
        source_path = self.base / "source.json"; quality_path = self.base / "quality.json"
        for path, value in ((candidate_path, CANDIDATE), (approval_path, self.approval), (source_path, SOURCE), (quality_path, QUALITY)):
            write_json(path, value)
        output = self.base / "result.json"
        command = [sys.executable, str(ROOT / "knowledge-ingestion-manager/derivative_publish.py"), "--candidate", str(candidate_path),
                   "--confirmation", str(approval_path), "--quality", str(quality_path), "--source-material", str(source_path),
                   "--vault-root", str(self.base / "vault"), "--asset-root", str(self.base / "asset-library"),
                   "--filename", KWARGS["filename"], "--target-folder", "50 输出成果", "--scope", "test", "--output", str(output)]
        first = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(json.loads(output.read_text())["status"], "published")
        second = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(json.loads(output.read_text())["status"], "already_published")
        changed = copy.deepcopy(CANDIDATE); changed["content"]["title"] = "篡改"
        write_json(candidate_path, changed)
        blocked = subprocess.run(command, capture_output=True, text=True)
        self.assertNotEqual(blocked.returncode, 0); self.assertIn("approval_binding", blocked.stderr)
        self.assertEqual(len(list((self.base / "vault/50 输出成果").glob("*.md"))), 1)

    def test_C2_12_explicit_new_approval(self):
        changed = copy.deepcopy(CANDIDATE); changed["content"]["markdown"] += "新段。\n"
        new_kwargs = dict(KWARGS, candidate=changed, body=changed["content"]["markdown"])
        new_approval = {"approval_binding": prepare(**new_kwargs)}
        self.assertEqual(verify(new_approval, **new_kwargs), new_approval["approval_binding"]["digest"])


if __name__ == "__main__": unittest.main(verbosity=2)
