#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from operation_envelope.operation_envelope import (
    OperationRecorder, find_by_reference, get_operation, new_operation_id,
    reconcile_operation, validate_record,
)


REF_A = "guanlan://material/material_sha256_" + "a" * 64 + "/revision/revision_sha256_" + "b" * 64
REF_B = "guanlan://candidate-bundle/bundle_sha256_" + "c" * 64
REF_C = "guanlan://receipt/receipt_sha256_" + "d" * 64


class OperationEnvelopeContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="guanlan-operation-envelope.", dir="/private/tmp")
        self.root = Path(self.temp.name) / "asset-library" / "operations"

    def tearDown(self): self.temp.cleanup()

    def completed(self, kind="capture", **kwargs):
        recorder = OperationRecorder(self.root, kind, input_refs=[REF_A], **kwargs)
        self.assertIsNone(recorder.finish("completed", output_refs=[REF_B], receipt_refs=[REF_C]))
        return recorder, get_operation(self.root, recorder.operation_id)

    def test_T01_operation_id_unique(self):
        self.assertNotEqual(new_operation_id("capture"), new_operation_id("capture"))

    def test_T02_schema_version_and_required_fields(self):
        _, value = self.completed(); self.assertEqual(value["schema_version"], "1.0.0"); validate_record(value)

    def test_T03_asset_identity_is_not_operation_identity(self):
        recorder, _ = self.completed(); self.assertTrue(recorder.operation_id.startswith("op_capture_")); self.assertNotIn("material_sha256", recorder.operation_id)

    def test_T04_canonical_refs_only(self):
        recorder = OperationRecorder(self.root, "capture", input_refs=["/private/tmp/source.json"])
        self.assertIsNone(recorder.path); self.assertIn("operation_index_write_failed", recorder.warning)

    def test_T05_completed(self):
        _, value = self.completed(); self.assertEqual(value["status"], "completed"); self.assertIsNotNone(value["duration_ms"])

    def test_T06_failed(self):
        value = OperationRecorder(self.root, "transcript"); value.finish("failed", failure_class="provider_failed", failure_detail="provider exit 3"); self.assertEqual(get_operation(self.root, value.operation_id)["status"], "failed")

    def test_T07_partial(self):
        value = OperationRecorder(self.root, "capture"); value.finish("partial", output_refs=[REF_A]); self.assertEqual(get_operation(self.root, value.operation_id)["status"], "partial")

    def test_T08_blocked(self):
        value = OperationRecorder(self.root, "publish"); value.finish("blocked", failure_class="approval_missing"); self.assertEqual(get_operation(self.root, value.operation_id)["status"], "blocked")

    def test_T09_index_write_failure_is_nonthrowing(self):
        blocker = Path(self.temp.name) / "file"; blocker.write_text("x")
        recorder = OperationRecorder(blocker, "capture"); self.assertIsNone(recorder.path); self.assertIn("operation_index_write_failed", recorder.warning); self.assertIsNotNone(recorder.finish("failed"))

    def test_T10_corruption_does_not_break_reference_query(self):
        _, good = self.completed(); bad = self.root / "2026-09" / (new_operation_id("capture") + ".json"); bad.parent.mkdir(parents=True, exist_ok=True); bad.write_text("{")
        found = find_by_reference(self.root, REF_A); self.assertEqual(found["operations"][0]["operation_id"], good["operation_id"]); self.assertEqual(len(found["corrupt_records"]), 1)

    def test_T11_missing_envelope_is_not_missing_asset(self): self.assertIsNone(get_operation(self.root, new_operation_id("capture")))

    def test_T12_canonical_conflict_marks_reconciliation(self):
        recorder, _ = self.completed(); value = reconcile_operation(self.root, recorder.operation_id, canonical_ref=REF_A, canonical_status="failed"); self.assertEqual(value["status"], "needs_reconciliation")

    def test_T13_forward_only_no_backfill(self): self.assertEqual(list(self.root.glob("**/*.json")), [])

    def test_T14_retry_linkage(self):
        first = OperationRecorder(self.root, "transcript"); second = OperationRecorder(self.root, "transcript", retry_of=first.operation_id); self.assertEqual(get_operation(self.root, second.operation_id)["retry_of"], first.operation_id)

    def test_T15_parent_child_linkage(self):
        parent = OperationRecorder(self.root, "capture"); child = OperationRecorder(self.root, "transcript", parent_operation_id=parent.operation_id); self.assertEqual(get_operation(self.root, child.operation_id)["parent_operation_id"], parent.operation_id)

    def test_T16_independent_same_asset_operations(self):
        one = OperationRecorder(self.root, "organize", input_refs=[REF_A]); two = OperationRecorder(self.root, "organize", input_refs=[REF_A]); self.assertNotEqual(one.operation_id, two.operation_id)

    def test_T17_organize_completed_is_independent_of_waiting_confirmation(self):
        value = OperationRecorder(self.root, "organize", input_refs=[REF_A]); value.finish("completed", output_refs=[REF_B]); self.assertEqual(get_operation(self.root, value.operation_id)["status"], "completed")

    def test_T18_source_only_capture_is_partial(self):
        value = OperationRecorder(self.root, "capture"); value.finish("partial", output_refs=[REF_A], failure_class="inbox_projection_absent"); self.assertNotEqual(get_operation(self.root, value.operation_id)["status"], "completed")

    def test_T19_publish_receipt_conflict(self):
        value = OperationRecorder(self.root, "publish", input_refs=[REF_B]); value.finish("failed", failure_class="dispatch_failed"); reconciled = reconcile_operation(self.root, value.operation_id, canonical_ref=REF_C, canonical_status="completed"); self.assertEqual(reconciled["status"], "needs_reconciliation")

    def test_T20_relation_registry_conflict(self):
        registry = "guanlan://relation-registry/v1"; value = OperationRecorder(self.root, "relation_curation", input_refs=[registry]); value.finish("completed", output_refs=[registry]); reconciled = reconcile_operation(self.root, value.operation_id, canonical_ref=registry, canonical_status="failed"); self.assertEqual(reconciled["status"], "needs_reconciliation")

    def test_T21_sensitive_detail_is_redacted(self):
        value = OperationRecorder(self.root, "capture"); value.finish("failed", failure_class="provider", failure_detail="Authorization: bearer-secret Cookie=session-secret")
        raw = next(self.root.glob("**/*.json")).read_text(); self.assertNotIn("bearer-secret", raw); self.assertNotIn("session-secret", raw); self.assertIn("[REDACTED]", raw)

    def test_T22_duplicate_callback_is_idempotent(self):
        value = OperationRecorder(self.root, "publish"); value.finish("completed", output_refs=[REF_A]); before = next(self.root.glob("**/*.json")).read_bytes(); value.finish("completed", output_refs=[REF_A]); self.assertEqual(before, next(self.root.glob("**/*.json")).read_bytes())

    def test_T23_interrupted_unknown_reconciliation(self):
        operation_id = new_operation_id("transcript"); value = reconcile_operation(self.root, operation_id, canonical_ref=REF_A, canonical_status=None); self.assertEqual(value["status"], "needs_reconciliation"); self.assertEqual(value["record_origin"], "canonical_reconciliation")

    def test_T24_rebuild_from_canonical_evidence(self):
        operation_id = new_operation_id("publish"); value = reconcile_operation(self.root, operation_id, canonical_ref=REF_C, canonical_status="completed"); self.assertEqual(value["status"], "completed"); self.assertEqual(value["record_origin"], "canonical_reconciliation")

    def test_T25_reference_type_and_time_query(self):
        self.completed("capture", started_at="2026-08-01T00:00:00Z"); self.completed("publish", started_at="2026-09-01T00:00:00Z")
        value = find_by_reference(self.root, REF_A, "publish", "2026-08-15T00:00:00Z"); self.assertEqual(len(value["operations"]), 1); self.assertEqual(value["operations"][0]["operation_type"], "publish")

    def test_T26_query_cli(self):
        recorder, _ = self.completed(); command = [sys.executable, str(ROOT / "operation_envelope/operation_query.py"), "--root", str(self.root), "get", "--operation-id", recorder.operation_id]
        result = subprocess.run(command, text=True, capture_output=True); self.assertEqual(result.returncode, 0, result.stderr); self.assertEqual(json.loads(result.stdout)["operation_id"], recorder.operation_id)

    def test_T27_all_six_types(self):
        for kind in ("capture", "transcript", "source_reconciliation", "organize", "publish", "relation_curation"):
            value = OperationRecorder(self.root, kind); self.assertIsNotNone(value.path)

    def test_T28_no_domain_payload_fields(self):
        _, value = self.completed(); forbidden = {"html", "transcript_text", "candidate_markdown", "approval_text", "relation_registry"}; self.assertFalse(forbidden & value.keys()); self.assertFalse(value["canonical_authority"])

    def test_T29_domain_payload_field_is_rejected(self):
        _, value = self.completed(); value["transcript_text"] = "domain payload"
        with self.assertRaisesRegex(ValueError, "non-contract fields"): validate_record(value)

    def test_T30_plain_session_word_is_not_a_secret_false_positive(self):
        value = OperationRecorder(self.root, "capture")
        self.assertIsNone(value.finish("failed", failure_class="browser_closed", failure_detail="browser session ended"))
        self.assertEqual(get_operation(self.root, value.operation_id)["status"], "failed")


if __name__ == "__main__": unittest.main(verbosity=2)
