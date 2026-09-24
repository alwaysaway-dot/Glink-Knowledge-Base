#!/usr/bin/env python3
"""T01-T15 regression contract for user-level Capture -> 00 completion."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FOUNDATION = load_module(
    "foundation_capture_completion_tests",
    PROJECT / "knowledge-foundation-stability" / "foundation_stability.py",
)
COMPLETION = load_module(
    "capture_inbox_completion_tests",
    PROJECT / "source-material-generator" / "capture_inbox_completion.py",
)


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def put_object(root: Path, value: bytes, role: str, media_type: str) -> dict:
    hexdigest = hashlib.sha256(value).hexdigest()
    relative = Path("objects") / "sha256" / hexdigest[:2] / hexdigest
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(value)
    return {
        "asset_id": "asset_sha256_" + hexdigest,
        "content_hash": "sha256:" + hexdigest,
        "media_type": media_type,
        "reference": "guanlan://asset/asset_sha256_" + hexdigest,
        "role": role,
        "size_bytes": len(value),
        "storage_relative_path": relative.as_posix(),
    }


class CaptureCompletionContract(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="guanlan-capture-contract-", dir="/private/tmp"))
        self.asset_root = self.root / "asset-library"
        self.inbox = self.root / "00 收件箱"
        self.inbox.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.root)

    def fixture(self, platform="webpage", transcript=True, partial=False, unknown_meta=False):
        raw_value = {
            "protocol": "transcript-provider-v1" if transcript else "capture-result-v1",
            "text": "第一段事实内容。第二段事实内容。" if transcript else "",
            "segments": [{
                "segment_id": "transcript-001", "start_time": 0.0, "end_time": 3.0,
                "start_timestamp": "00:00:00.000", "end_timestamp": "00:00:03.000",
                "text": "第一段事实内容。第二段事实内容。",
            }] if transcript else [],
        }
        raw = put_object(self.asset_root, canonical(raw_value), "raw_transcript" if transcript else "capture_metadata", "application/json")
        readable = put_object(self.asset_root, "第一段事实内容。\n\n第二段事实内容。\n".encode(), "readable_transcript", "text/plain; charset=utf-8")
        entries = [raw, readable]
        processing_history = []
        evidence = [{
            "evidence_id": "evidence-primary-001",
            "kind": "transcript" if transcript else "capture_metadata",
            "reference": raw["reference"],
            "content_hash": raw["content_hash"],
            "uncertainty": "",
            **({"start_time": 0.0, "end_time": 3.0} if transcript else {}),
        }]
        if platform in {"youtube", "douyin", "bilibili", "xiaohongshu", "video", "audio"}:
            media = put_object(self.asset_root, b"fixture-media", "source_media", "video/mp4")
            entries.append(media)
            evidence.append({
                "evidence_id": "evidence-media-001", "kind": "source_media",
                "reference": media["reference"], "content_hash": media["content_hash"],
                "start_time": 0.0, "end_time": 3.0, "uncertainty": "",
            })
            if transcript:
                quality_value = {
                    "protocol": "media-transcript-quality-v1", "schema_version": "1.0.0",
                    "transcript_content_hash": raw["content_hash"],
                    "readable_content_hash": readable["content_hash"],
                    "quality_status": "ready_for_整理", "ready_for_sorting": True,
                    "capture_completion_status": "capture_completed",
                }
                quality_entry = put_object(self.asset_root, canonical(quality_value), "transcript_quality_report", "application/json")
                quality_entry["reference"] = quality_entry["reference"].replace("guanlan://asset/", "guanlan://report/")
                entries.append(quality_entry)
                processing_history.append({"processor": "fixture", "report_reference": quality_entry["reference"]})
        source_id = "fixture-001"
        source_url = f"https://example.test/{platform}/fixture-001"
        if platform == "local":
            source_id = readable["content_hash"]
            source_url = ""
        material_id = FOUNDATION.material_id_from_source_key(
            FOUNDATION.source_key(platform, source_id, source_url)
        )
        source = {
            "protocol": "source-material-v3", "schema_version": "3.0.0",
            "material_id": material_id, "revision_id": "revision_sha256_" + "0" * 64,
            "source": {
                "platform": platform, "source_id": source_id, "source_url": source_url,
                "title": "unknown" if unknown_meta else "确定性测试素材",
                "author": "unknown" if unknown_meta else "测试作者",
                "captured_at": "2026-09-08T00:00:00Z", "published_at": "",
            },
            "content": {
                "raw": {"storage": "reference", "reference": raw["reference"], "content_hash": raw["content_hash"], "media_type": raw["media_type"]},
                "readable": {"storage": "reference", "reference": readable["reference"], "content_hash": readable["content_hash"], "media_type": readable["media_type"], "operations": []},
            },
            "evidence": evidence,
            "quality": {
                "capture_status": "partial" if partial else "complete",
                "content_fidelity": "partial" if partial else "full",
                "transcript_quality": "raw" if transcript else "not_applicable",
                "review_required": True,
                "uncertainties": ["Transcript 尚未取得"] if partial and not transcript else [],
            },
            "lifecycle": {
                "status": "partial" if partial else "captured", "review_status": "pending",
                "created_at": "2026-09-08T00:00:00Z", "updated_at": "2026-09-08T00:00:00Z",
                "processing_history": processing_history,
            },
            "asset_manifest_reference": "guanlan://manifest/placeholder/revision",
            "understanding_sidecar_reference": "",
        }
        source["revision_id"] = FOUNDATION.revision_id(source)
        source["asset_manifest_reference"] = f"guanlan://manifest/{material_id}/{source['revision_id']}"
        manifest = {
            "protocol": "reference-manifest-v1", "schema_version": "1.0.0",
            "material_id": material_id, "revision_id": source["revision_id"], "entries": entries,
        }
        revision_dir = self.root / "material" / "revisions" / source["revision_id"]
        revision_dir.mkdir(parents=True)
        source_path = revision_dir / "source-material-v3.json"
        manifest_path = revision_dir / "reference-manifest.json"
        source_path.write_bytes(canonical(source))
        manifest_path.write_bytes(canonical(manifest))
        return source, manifest, source_path, manifest_path

    def complete(self, source_path, manifest_path, name="2026-09-08_采集_测试素材.md", fault=""):
        return COMPLETION.complete_capture(
            source_path=source_path, manifest_path=manifest_path,
            asset_root=self.asset_root, inbox=self.inbox,
            requested_output=self.inbox / name, project_root=PROJECT,
            scope="test", fault=fault,
        )

    def test_T01_valid_source_requires_and_gets_projection(self):
        _, _, source_path, manifest_path = self.fixture()
        result, code = self.complete(source_path, manifest_path)
        self.assertEqual((code, result["status"]), (0, "capture_completed"))
        self.assertTrue(Path(result["path"]).is_file())

    def test_T02_projection_failure_is_not_capture_complete(self):
        _, _, source_path, manifest_path = self.fixture()
        result, code = self.complete(source_path, manifest_path, fault="projection_write_failure")
        self.assertNotEqual(code, 0)
        self.assertEqual(result["status"], "capture_incomplete_projection_pending")
        self.assertFalse(list(self.inbox.glob("*.md")))

    def test_T03_partial_video_still_gets_visible_projection(self):
        _, _, source_path, manifest_path = self.fixture("xiaohongshu", transcript=False, partial=True, unknown_meta=True)
        result, code = self.complete(source_path, manifest_path)
        self.assertEqual((code, result["status"]), (0, "capture_partial"))
        self.assertIn("Transcript 尚未取得", Path(result["path"]).read_text())

    def test_T04_provider_transcript_creates_immutable_new_revision(self):
        source, _, source_path, manifest_path = self.fixture("douyin", transcript=False, partial=True)
        material_dir = self.root / "material"
        (material_dir / "CURRENT_REVISION").write_text(source["revision_id"] + "\n")
        provider = {
            "protocol": "transcript-provider-v1", "status": "completed", "provider": "funasr",
            "model": "paraformer-zh", "language": "zh", "text": "新的事实字幕。",
            "timestamp": {"start_time": 0.0, "end_time": 4.0}, "warnings": [],
            "provider_metadata": {"bridge_version": "test", "network_access": False},
            "segments": [{"segment_id": "transcript-001", "start_time": 0.0, "end_time": 4.0,
                          "start_timestamp": "00:00:00.000", "end_timestamp": "00:00:04.000", "text": "新的事实字幕。"}],
        }
        provider_path = self.root / "provider.json"; provider_path.write_bytes(canonical(provider))
        readable_path = self.root / "provider-readable.txt"
        readable_path.write_text("新的事实字幕。\n", encoding="utf-8")
        quality = {
            "protocol": "media-transcript-quality-v1", "schema_version": "1.0.0",
            "transcript_content_hash": "sha256:" + hashlib.sha256(json.dumps(provider, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            "readable_content_hash": "sha256:" + hashlib.sha256(readable_path.read_bytes()).hexdigest(),
            "quality_status": "ready_for_整理", "ready_for_sorting": True,
            "capture_completion_status": "capture_completed",
        }
        quality_path = self.root / "provider-quality.json"; quality_path.write_bytes(canonical(quality))
        summary_path = self.root / "enrichment.json"
        old_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
        subprocess.run([
            sys.executable, str(PROJECT / "source-material-generator" / "add_transcript_revision.py"),
            "--source-material", str(source_path), "--manifest", str(manifest_path),
            "--provider-result", str(provider_path), "--asset-root", str(self.asset_root),
            "--readable-text", str(readable_path),
            "--quality-result", str(quality_path),
            "--material-dir", str(material_dir), "--project-root", str(PROJECT),
            "--created-at", "2026-09-08T01:00:00Z", "--output-summary", str(summary_path), "--scope", "test",
        ], check=True, capture_output=True, text=True)
        result = json.loads(summary_path.read_text())
        self.assertNotEqual(result["revision_id"], source["revision_id"])
        self.assertEqual(hashlib.sha256(source_path.read_bytes()).hexdigest(), old_hash)
        completion, code = self.complete(Path(result["source_material"]), Path(result["manifest"]))
        self.assertEqual((code, completion["status"]), (0, "capture_completed"))

    def test_T05_same_revision_is_idempotent_without_suffix(self):
        _, _, source_path, manifest_path = self.fixture()
        first, _ = self.complete(source_path, manifest_path)
        second, code = self.complete(source_path, manifest_path)
        self.assertEqual((code, second["status"]), (0, "already_projected"))
        self.assertEqual(len(list(self.inbox.glob("*.md"))), 1)
        self.assertNotIn("_2", Path(first["path"]).name)

    def test_T06_new_revision_updates_same_pending_projection(self):
        source, manifest, source_path, manifest_path = self.fixture()
        first, _ = self.complete(source_path, manifest_path)
        new_readable = put_object(self.asset_root, "新版事实内容。\n".encode(), "readable_transcript", "text/plain; charset=utf-8")
        source2 = copy.deepcopy(source)
        source2["content"]["readable"].update(reference=new_readable["reference"], content_hash=new_readable["content_hash"])
        source2["revision_id"] = FOUNDATION.revision_id(source2)
        source2["asset_manifest_reference"] = f"guanlan://manifest/{source2['material_id']}/{source2['revision_id']}"
        manifest2 = copy.deepcopy(manifest)
        manifest2["revision_id"] = source2["revision_id"]
        manifest2["entries"] = [item for item in manifest2["entries"] if item["role"] != "readable_transcript"] + [new_readable]
        rev = self.root / "material" / "revisions" / source2["revision_id"]; rev.mkdir()
        sp = rev / "source-material-v3.json"; mp = rev / "reference-manifest.json"
        sp.write_bytes(canonical(source2)); mp.write_bytes(canonical(manifest2))
        second, code = self.complete(sp, mp, name="different-requested-name.md")
        self.assertEqual((code, second["action"]), (0, "updated"))
        self.assertEqual(second["path"], first["path"])
        self.assertEqual(len(list(self.inbox.glob("*.md"))), 1)

    def test_T07_temporary_reference_blocks_projection(self):
        source, _, source_path, manifest_path = self.fixture()
        source["content"]["readable"]["reference"] = "/private/tmp/output.txt"
        source_path.write_bytes(canonical(source))
        result, code = self.complete(source_path, manifest_path)
        self.assertNotEqual(code, 0); self.assertEqual(result["status"], "capture_blocked")

    def test_T08_analysis_field_cannot_enter_fact_projection(self):
        source, _, source_path, manifest_path = self.fixture()
        source["summary"] = "不应出现的分析"
        source_path.write_bytes(canonical(source))
        result, code = self.complete(source_path, manifest_path)
        self.assertNotEqual(code, 0); self.assertEqual(result["status"], "capture_blocked")

    def test_T09_youtube_full_capture_contract(self):
        _, _, sp, mp = self.fixture("youtube", transcript=True)
        result, code = self.complete(sp, mp); self.assertEqual((code, result["status"]), (0, "capture_completed"))

    def test_T10_douyin_full_capture_contract(self):
        _, _, sp, mp = self.fixture("douyin", transcript=True)
        result, code = self.complete(sp, mp); self.assertEqual((code, result["status"]), (0, "capture_completed"))

    def test_T11_local_file_has_no_video_only_requirements(self):
        _, _, sp, mp = self.fixture("local", transcript=False)
        result, code = self.complete(sp, mp); self.assertEqual((code, result["status"]), (0, "capture_completed"))

    def test_T12_xiaohongshu_partial_capture_is_visible(self):
        _, _, sp, mp = self.fixture("xiaohongshu", transcript=False, partial=True)
        result, code = self.complete(sp, mp); self.assertEqual((code, result["status"]), (0, "capture_partial"))

    def test_T13_bilibili_router_remains_explicitly_blocked(self):
        output = self.root / "route.json"
        subprocess.run([sys.executable, str(PROJECT / "capture-provider-router" / "source_router.py"),
                        "--url", "https://www.bilibili.com/video/BV1SYNTH1234", "--output", str(output)], check=True)
        route = json.loads(output.read_text())
        self.assertEqual(route["status"], "blocked")
        self.assertTrue(route["blocked_reason"]); self.assertTrue(route["required_capability"])

    def test_T14_projection_failure_does_not_mutate_source(self):
        _, _, sp, mp = self.fixture()
        before = hashlib.sha256(sp.read_bytes()).hexdigest()
        self.inbox.chmod(0o500)
        try:
            result, code = self.complete(sp, mp)
        finally:
            self.inbox.chmod(0o700)
        self.assertNotEqual(code, 0)
        self.assertEqual(result["status"], "capture_incomplete_projection_pending")
        self.assertEqual(hashlib.sha256(sp.read_bytes()).hexdigest(), before)

    def test_T15_invalid_source_never_creates_projection(self):
        _, _, sp, mp = self.fixture()
        mp.unlink()
        result, code = self.complete(sp, mp)
        self.assertNotEqual(code, 0); self.assertEqual(result["status"], "capture_blocked")
        self.assertFalse(list(self.inbox.glob("*.md")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
