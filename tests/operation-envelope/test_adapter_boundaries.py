#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "capture-provider-router"))

from generic_web_capture import capture  # noqa: E402
from operation_envelope import find_by_reference, get_operation  # noqa: E402
from operation_envelope.operation_envelope import operation_files  # noqa: E402
from providers.generic_web_contract import GenericWebCaptureRequest  # noqa: E402
sys.path.insert(0, str(ROOT / "knowledge-ingestion-manager"))
from approval_binding import prepare as prepare_binding, sha as binding_sha  # noqa: E402

MATERIAL = "material_sha256_" + "a" * 64
REVISION = "revision_sha256_" + "b" * 64


def load_script(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class FakeResponse:
    status = 200
    url = "https://example.test/operation-envelope"
    headers = {"Content-Type": "text/html; charset=utf-8"}
    history = []
    body = ("<html><head><title>Operation Envelope Fixture</title></head><body><article>"
            "<h1>事实型网页素材</h1><p>这是一段确定性事实内容，只用于验证采集、整理、发布与关系整理的审计索引。</p>"
            "<p>它不包含总结、观点提炼或用户立场，并保留来源事实边界。</p></article></body></html>").encode()


class AdapterBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="guanlan-operation-adapters.", dir="/private/tmp")
        self.base = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_A01_transcript_adapter_records_completed_canonical_result(self):
        module = load_script("media_transcript_pipeline_adapter_test", "transcript-provider-bridge/media_transcript_pipeline.py")
        asset_root = self.base / "asset-library"; run_dir = self.base / "run"
        source = self.base / "source-material-v3.json"; manifest = self.base / "reference-manifest.json"
        write_json(source, {"material_id": MATERIAL, "revision_id": REVISION}); write_json(manifest, {})

        def fake_run(command, allowed={0}):
            name = Path(command[1]).name if len(command) > 1 else command[0]
            if command[0] == "ffprobe": return SimpleNamespace(returncode=0, stdout="10.0", stderr="")
            def target(flag): return Path(command[command.index(flag) + 1])
            if name == "funasr_chunked_provider.py":
                write_json(target("--output"), {"status": "completed", "segments": [{"text": "测试转录", "start_time": 0, "end_time": 10}]})
            elif name == "media_transcript_hygiene.py":
                write_json(target("--output-json"), {"text": "测试转录。"}); target("--output-text").write_text("测试转录。\n"); target("--output-md").write_text("测试转录。\n")
            elif name == "media_transcript_quality.py":
                write_json(target("--output"), {"quality_status": "ready_for_整理", "warnings": [], "missing_ranges": []})
            elif name == "add_transcript_revision.py":
                write_json(target("--output-summary"), {"status": "created", "material_id": MATERIAL, "revision_id": REVISION,
                                                        "source_material": str(source), "manifest": str(manifest)})
            elif name == "capture_inbox_completion.py":
                write_json(target("--result"), {"status": "capture_completed", "projection_written": True, "path": str(self.base / "00 收件箱/test.md")})
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        argv = ["media_transcript_pipeline.py", "--config", str(self.base / "config.json"), "--media", str(self.base / "media.wav"),
                "--source-material", str(source), "--manifest", str(manifest), "--asset-root", str(asset_root),
                "--material-dir", str(self.base / "material"), "--project-root", str(ROOT), "--inbox", str(self.base / "00 收件箱"),
                "--inbox-output", str(self.base / "00 收件箱/test.md"), "--run-dir", str(run_dir),
                "--created-at", "2026-09-21T00:00:00Z", "--output", str(self.base / "transcript-result.json"), "--scope", "test"]
        with mock.patch.object(module, "run", side_effect=fake_run), mock.patch.object(sys, "argv", argv):
            self.assertEqual(module.main(), 0)
        result = json.loads((self.base / "transcript-result.json").read_text())
        envelope = get_operation(asset_root / "operations", result["operation_id"])
        self.assertEqual((envelope["operation_type"], envelope["status"]), ("transcript", "completed"))
        self.assertIn(f"guanlan://material/{MATERIAL}/revision/{REVISION}", envelope["output_refs"])

    def test_A02_source_reconciliation_adapter_records_receipt(self):
        module = load_script("source_reconciliation_adapter_test", "source-material-generator/reconcile_source_readiness.py")
        asset_root = self.base / "asset-library"; material_dir = self.base / "material"
        selected = material_dir / "revisions" / REVISION / "source-material-v3.json"
        write_json(selected, {"material_id": MATERIAL, "revision_id": REVISION})
        receipt_id = "receipt_sha256_" + "c" * 64
        outcome = {"status": "reconciled", "material_id": MATERIAL, "revision_id": REVISION, "receipt_id": receipt_id}
        argv = ["reconcile_source_readiness.py", "--project-root", str(ROOT), "--asset-root", str(asset_root),
                "--material-dir", str(material_dir), "--revision-id", REVISION, "--inbox", str(self.base / "00 收件箱"),
                "--output", str(self.base / "projection.md"), "--receipt-output", str(self.base / "receipt.json"),
                "--validation-output", str(self.base / "validation.json"), "--result", str(self.base / "result.json"),
                "--created-at", "2026-09-21T00:00:00Z", "--scope", "test"]
        with mock.patch.object(module, "reconcile", return_value=outcome), mock.patch.object(sys, "argv", argv):
            self.assertEqual(module.main(), 0)
        result = json.loads((self.base / "result.json").read_text())
        envelope = get_operation(asset_root / "operations", result["operation_id"])
        self.assertEqual(envelope["status"], "completed")
        self.assertEqual(envelope["receipt_refs"], [f"guanlan://receipt/{receipt_id}"])

    def test_A03_capture_organize_publish_relation_isolated_chain(self):
        asset_root = self.base / "asset-library"; material_dir = asset_root / "materials" / "fixture"
        inbox = self.base / "00 收件箱"; inbox.mkdir(parents=True)
        projection = inbox / "2026-09-21_事实型网页素材.md"
        request = GenericWebCaptureRequest(capture_request_id="capture_operation_fixture", url=FakeResponse.url,
                                           requested_at="2026-09-21T00:00:00Z", timeout_seconds=2,
                                           language_hint="zh-CN", allow_private_test=True)
        captured, code = capture(request=request, asset_root=asset_root, material_dir=material_dir,
                                 inbox=inbox, projection=projection, scope="test", transport=lambda _: FakeResponse())
        self.assertEqual(code, 0); self.assertTrue(captured["inbox_projection_written"])
        self.assertEqual(get_operation(asset_root / "operations", captured["operation_id"])["status"], "completed")

        revision_dir = Path(captured["source_material"]).parent
        source = json.loads((revision_dir / "source-material-v3.json").read_text())
        manifest = json.loads((revision_dir / "reference-manifest.json").read_text())
        readable_entry = next(item for item in manifest["entries"] if item["role"] == "readable_source")
        readable = asset_root / readable_entry["storage_relative_path"]
        validation = revision_dir / "source-asset-validation.json"
        write_json(validation, {"protocol": "source-asset-validation-v1", "status": "passed", "material_id": source["material_id"],
                                "revision_id": source["revision_id"], "content_hash": source["content"]["readable"]["content_hash"]})

        bundle_output = self.base / "candidate-bundle.json"
        organize = subprocess.run([sys.executable, str(ROOT / "knowledge-ingestion-manager/organize_workflow.py"),
                                  "--source-material", str(revision_dir / "source-material-v3.json"), "--source-validation", str(validation),
                                  "--readable-source", str(readable), "--asset-root", str(asset_root), "--output", str(bundle_output)],
                                 cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(organize.returncode, 0, organize.stderr)
        bundle = json.loads(bundle_output.read_text()); self.assertEqual(bundle["workflow_state"], "awaiting_user_confirmation")
        self.assertEqual(get_operation(asset_root / "operations", bundle["operation_id"])["status"], "completed")

        runtime = self.base / "runtime"
        try:
            canonical_revision = runtime / "asset-library/materials/fixture/revisions" / source["revision_id"]
            canonical_revision.mkdir(parents=True)
            shutil.copy2(revision_dir / "source-material-v3.json", canonical_revision / "source-material-v3.json")
            shutil.copy2(revision_dir / "reference-manifest.json", canonical_revision / "reference-manifest.json")
            approval_ref = "guanlan://report/approval_" + "d" * 64
            validation_ref = "guanlan://report/validation_" + "e" * 64
            source_ref = f"guanlan://material/{source['material_id']}/revision/{source['revision_id']}"
            source_projection = canonical_revision / "source-asset-projection.md"
            source_projection.write_text(
                "---\n" + "\n".join(["type: source_asset", "asset_class: source", "graph_group: 10_source", "status: confirmed",
                    f"material_id: {source['material_id']}", f"revision_id: {source['revision_id']}",
                    f"content_hash: {source['content']['readable']['content_hash']}", f"source_reference: {source_ref}",
                    f"manifest_reference: {source['asset_manifest_reference']}", f"validation_reference: {validation_ref}",
                    f"approval_reference: {approval_ref}"]) + "\n---\n\n# 事实型网页素材\n\n## 完整可读原文\n\n" + readable.read_text(), encoding="utf-8")
            write_json(canonical_revision / "source-asset-validation.json", json.loads(validation.read_text()))
            write_json(canonical_revision / "source-asset-approval.json", {"confirmed": True, "confirmed_at": "2026-09-21T00:01:00Z",
                                                                            "reviewer": "user", "material_id": source["material_id"], "revision_id": source["revision_id"]})
            target = runtime / "vault/10 原始资料"; target.mkdir(parents=True)
            record = runtime / "source-ingestion-record.json"; publish_result = runtime / "bundle-publish-result.json"
            candidate_id = bundle["source_candidate"]["candidate_id"]
            rel = lambda value: os.path.relpath(value, self.base)
            plan = {"protocol": "candidate-bundle-publish-plan-v1", "bundle_id": bundle["bundle_id"],
                    "approval": {"confirmed": True, "reviewer": "user", "bindings": {candidate_id: prepare_binding(
                        candidate=bundle["source_candidate"], source=source, target_folder="10 原始资料",
                        filename="2026-09-21_事实型网页素材.md", bundle=bundle,
                        projection_hash=binding_sha(source_projection.read_bytes()),
                        quality=json.loads(validation.read_text()))}}, "selected_candidate_ids": [candidate_id],
                    "components": {candidate_id: {"asset_type": "source_asset", "inputs": {
                        "source_material": rel(canonical_revision / "source-material-v3.json"),
                        "manifest": rel(canonical_revision / "reference-manifest.json"), "projection": rel(source_projection),
                        "validation": rel(canonical_revision / "source-asset-validation.json"),
                        "confirmation": rel(canonical_revision / "source-asset-approval.json"), "vault": rel(target),
                        "filename": "2026-09-21_事实型网页素材.md", "record": rel(record)}}}}
            plan_path = runtime / "publish-plan.json"; write_json(plan_path, plan)
            publish = subprocess.run([sys.executable, str(ROOT / "knowledge-ingestion-manager/bundle_publish.py"),
                                      "--bundle", str(bundle_output), "--publish-plan", str(plan_path), "--scope", "test",
                                      "--operation-root", str(asset_root / "operations"), "--output", str(publish_result)],
                                     cwd=self.base, text=True, capture_output=True)
            self.assertEqual(publish.returncode, 0, publish.stderr)
            published = json.loads(publish_result.read_text()); self.assertEqual(published["status"], "published")
            publish_record = get_operation(asset_root / "operations", published["operation_id"])
            self.assertEqual(publish_record["status"], "completed"); self.assertIn(source_ref, publish_record["output_refs"])
            self.assertTrue((target / "2026-09-21_事实型网页素材.md").is_file())

            vault = runtime / "vault"
            for folder in ("20 学习笔记", "30 情报简报", "40 方法库", "50 输出成果"):
                (vault / folder).mkdir(parents=True)
            relation_root = asset_root / "relations"; relation_root.mkdir(parents=True)
            write_json(relation_root / "relation-registry-v1.json", {"protocol": "relation-registry-v1", "schema_version": "1.0.0", "registry_id": "fixture", "relations": [], "updated_at": ""})
            relation_output = self.base / "relation-run.json"
            relation = subprocess.run([sys.executable, str(ROOT / "knowledge-relation-manager/relation_curation.py"),
                                       "--vault", str(vault), "--asset-root", str(asset_root), "--output", str(relation_output)],
                                      cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(relation.returncode, 0, relation.stderr)
            relation_result = json.loads(relation_output.read_text())
            self.assertEqual(get_operation(asset_root / "operations", relation_result["operation_id"])["status"], "completed")

            bundle_ref = f"guanlan://candidate-bundle/{bundle['bundle_id']}"
            self.assertEqual(len(find_by_reference(asset_root / "operations", source_ref)["operations"]), 3)
            self.assertEqual(len(find_by_reference(asset_root / "operations", bundle_ref)["operations"]), 2)
            self.assertEqual({json.loads(path.read_text())["operation_type"] for path in operation_files(asset_root / "operations")},
                             {"capture", "organize", "publish", "relation_curation"})
        finally:
            shutil.rmtree(runtime, ignore_errors=True)

    def test_A04_canonical_capture_survives_operation_index_failure(self):
        asset_root = self.base / "asset-library"; asset_root.mkdir(parents=True)
        (asset_root / "operations").write_text("blocked directory", encoding="utf-8")
        material_dir = asset_root / "materials/fixture"; inbox = self.base / "00 收件箱"; inbox.mkdir()
        request = GenericWebCaptureRequest(capture_request_id="capture_index_failure", url=FakeResponse.url,
                                           requested_at="2026-09-21T00:00:00Z", timeout_seconds=2,
                                           language_hint=None, allow_private_test=True)
        result, code = capture(request=request, asset_root=asset_root, material_dir=material_dir,
                               inbox=inbox, projection=inbox / "fixture.md", scope="test", transport=lambda _: FakeResponse())
        self.assertEqual(code, 0); self.assertTrue(Path(result["source_material"]).is_file())
        self.assertTrue(result["inbox_projection_written"])
        self.assertTrue(any("operation_index_write_failed" in warning for warning in result["warnings"]))

    def test_A05_source_only_capture_is_partial_in_real_adapter(self):
        asset_root = self.base / "asset-library"; material_dir = asset_root / "materials/fixture"
        request = GenericWebCaptureRequest(capture_request_id="capture_source_only", url=FakeResponse.url,
                                           requested_at="2026-09-21T00:00:00Z", timeout_seconds=2,
                                           language_hint=None, allow_private_test=True)
        result, code = capture(request=request, asset_root=asset_root, material_dir=material_dir,
                               scope="test", transport=lambda _: FakeResponse())
        self.assertEqual(code, 0)
        self.assertEqual(get_operation(asset_root / "operations", result["operation_id"])["status"], "partial")

    def test_A06_transcript_unhandled_failure_is_persisted(self):
        module = load_script("media_transcript_pipeline_failure_test", "transcript-provider-bridge/media_transcript_pipeline.py")
        asset_root = self.base / "asset-library"; source = self.base / "source.json"; manifest = self.base / "manifest.json"
        write_json(source, {"material_id": MATERIAL, "revision_id": REVISION}); write_json(manifest, {})
        argv = ["media_transcript_pipeline.py", "--config", "fixture", "--media", "fixture.wav",
                "--source-material", str(source), "--manifest", str(manifest), "--asset-root", str(asset_root),
                "--material-dir", str(self.base / "material"), "--project-root", str(ROOT), "--inbox", str(self.base / "00 收件箱"),
                "--inbox-output", str(self.base / "inbox.md"), "--run-dir", str(self.base / "run"),
                "--created-at", "2026-09-21T00:00:00Z", "--output", str(self.base / "result.json"), "--scope", "test"]
        with mock.patch.object(module, "run", side_effect=RuntimeError("provider process interrupted")), mock.patch.object(sys, "argv", argv):
            with self.assertRaises(RuntimeError): module.main()
        records = [json.loads(path.read_text()) for path in operation_files(asset_root / "operations")]
        self.assertEqual(len(records), 1); self.assertEqual(records[0]["status"], "failed")
        self.assertEqual(records[0]["failure_class"], "transcript_pipeline_failed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
