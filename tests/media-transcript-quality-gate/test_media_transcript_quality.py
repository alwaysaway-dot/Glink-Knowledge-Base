#!/usr/bin/env python3
"""T01-T24 regression for bounded media ASR and usable-transcript completion."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
import wave
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).with_name("fixtures")
sys.path.insert(0, str(PROJECT / "transcript-provider-bridge"))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GATE = load_module("media_gate_tests", PROJECT / "transcript-quality-gate" / "media_transcript_quality.py")
HYGIENE = load_module("media_hygiene_tests", PROJECT / "transcript-intelligence" / "media_transcript_hygiene.py")
CHUNKED = load_module("chunked_provider_tests", PROJECT / "transcript-provider-bridge" / "funasr_chunked_provider.py")
FOUNDATION = load_module("foundation_media_gate_tests", PROJECT / "knowledge-foundation-stability" / "foundation_stability.py")
COMPLETION = load_module("completion_media_gate_tests", PROJECT / "source-material-generator" / "capture_inbox_completion.py")


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode() + b"\n"


def positive_transcript(duration: float = 60, count: int = 6) -> dict:
    unit = duration / count
    base = "本段记录来源中的事实陈述，并保留原始含义。内容围绕经济结构、产业变化与风险条件展开。"
    segments = []
    for index in range(count):
        segments.append({"segment_id": f"transcript-{index + 1:04d}", "start_time": index * unit,
                         "end_time": (index + 1) * unit, "text": base + f"这是第{index + 1}段。"})
    return {"protocol": "transcript-provider-v1", "provider": "fixture", "model": "fixture",
            "language": "zh-CN", "status": "completed", "text": "".join(x["text"] for x in segments),
            "segments": segments, "missing_ranges": []}


def put_object(root: Path, value: bytes, role: str, media_type: str, report: bool = False) -> dict:
    hexdigest = hashlib.sha256(value).hexdigest()
    relative = Path("objects/sha256") / hexdigest[:2] / hexdigest
    target = root / relative; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(value)
    kind = "report" if report else "asset"
    return {"asset_id": "asset_sha256_" + hexdigest, "content_hash": "sha256:" + hexdigest,
            "media_type": media_type, "reference": f"guanlan://{kind}/asset_sha256_{hexdigest}",
            "role": role, "size_bytes": len(value), "storage_relative_path": relative.as_posix()}


class MediaTranscriptQualityContract(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="guanlan-media-gate-", dir="/private/tmp"))

    def tearDown(self):
        shutil.rmtree(self.root)

    def readable(self, transcript: dict) -> str:
        return HYGIENE.build(transcript, 220, 420)["readable_text"]

    def evaluate(self, transcript: dict, duration: float) -> dict:
        return GATE.evaluate(transcript, self.readable(transcript), duration)

    def write_silence(self, duration: int) -> Path:
        path = self.root / "audio.wav"
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1); handle.setsampwidth(2); handle.setframerate(16000)
            block = b"\0\0" * 16000
            for _ in range(duration): handle.writeframesraw(block)
        return path

    def fake_provider(self, behavior: str) -> Path:
        path = self.root / f"fake-{behavior}.py"
        body = '''
import argparse,json,time,wave
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument("--config");p.add_argument("--audio");p.add_argument("--output");a=p.parse_args()
name=Path(a.audio).name
BEHAVIOR
with wave.open(a.audio,"rb") as w: duration=w.getnframes()/w.getframerate()
value={"protocol":"transcript-provider-v1","status":"completed","provider":"funasr","model":"paraformer-zh","text":"这是可验证的分段事实文本。","segments":[{"segment_id":"local-1","start_time":0,"end_time":duration,"text":"这是可验证的分段事实文本。"}]}
Path(a.output).write_text(json.dumps(value,ensure_ascii=False))
'''.replace("BEHAVIOR", behavior)
        path.write_text(textwrap.dedent(body), encoding="utf-8")
        return path

    def config(self) -> Path:
        path = self.root / "config.json"
        path.write_text(json.dumps({"provider": "funasr", "model": "paraformer-zh", "python_path": sys.executable,
                                    "enabled": True, "network_access": False, "device": "cpu"}))
        return path

    def run_chunked(self, script: Path, duration: int = 31, timeout: int = 8, retries: int = 1):
        output = self.root / "result.json"
        completed = subprocess.run([sys.executable, str(PROJECT / "transcript-provider-bridge/funasr_chunked_provider.py"),
            "--config", str(self.config()), "--audio", str(self.write_silence(duration)), "--output", str(output),
            "--work-dir", str(self.root / "work"), "--chunk-seconds", "15", "--segment-timeout-seconds", str(timeout),
            "--max-retries", str(retries), "--provider-script", str(script)], capture_output=True, text=True)
        value = json.loads(output.read_text()) if output.exists() else None
        return completed, value

    def completion_fixture(self, with_report: bool, tamper_report: bool = False):
        asset_root = self.root / "asset-library"; inbox = self.root / "00 收件箱"; inbox.mkdir(parents=True)
        transcript = positive_transcript(60, 6); raw = put_object(asset_root, canonical(transcript), "raw_transcript", "application/json")
        readable_bytes = self.readable(transcript).encode(); readable = put_object(asset_root, readable_bytes, "readable_transcript", "text/plain")
        media = put_object(asset_root, b"media", "source_media", "video/mp4")
        entries = [raw, readable, media]; history = []
        if with_report:
            report = self.evaluate(transcript, 60)
            report["transcript_content_hash"] = "sha256:" + ("0" * 64) if tamper_report else raw["content_hash"]
            report["readable_content_hash"] = readable["content_hash"]
            report_entry = put_object(asset_root, canonical(report), "transcript_quality_report", "application/json", True)
            entries.append(report_entry); history.append({"processor": "fixture", "report_reference": report_entry["reference"]})
        source_url = "https://example.test/video/quality"
        material_id = FOUNDATION.material_id_from_source_key(FOUNDATION.source_key("video", "quality", source_url))
        source = {"protocol": "source-material-v3", "schema_version": "3.0.0", "material_id": material_id,
            "revision_id": "revision_sha256_" + "0" * 64,
            "source": {"platform": "video", "source_id": "quality", "source_url": source_url, "title": "质量测试", "author": "fixture", "captured_at": "2026-09-08T00:00:00Z", "published_at": ""},
            "content": {"raw": {"storage": "reference", "reference": raw["reference"], "content_hash": raw["content_hash"], "media_type": "application/json"},
                        "readable": {"storage": "reference", "reference": readable["reference"], "content_hash": readable["content_hash"], "media_type": "text/plain", "operations": ["no_summary"]}},
            "evidence": [{"evidence_id": "transcript-1", "kind": "transcript", "reference": raw["reference"], "content_hash": raw["content_hash"], "start_time": 0, "end_time": 60, "uncertainty": ""},
                         {"evidence_id": "media-1", "kind": "source_media", "reference": media["reference"], "content_hash": media["content_hash"], "start_time": 0, "end_time": 60, "uncertainty": ""}],
            "quality": {"capture_status": "complete", "content_fidelity": "full", "transcript_quality": "readable", "review_required": True, "uncertainties": []},
            "lifecycle": {"status": "captured", "review_status": "pending", "created_at": "2026-09-08T00:00:00Z", "updated_at": "2026-09-08T00:00:00Z", "processing_history": history},
            "asset_manifest_reference": "guanlan://manifest/placeholder/revision", "understanding_sidecar_reference": ""}
        source["revision_id"] = FOUNDATION.revision_id(source); source["asset_manifest_reference"] = f"guanlan://manifest/{material_id}/{source['revision_id']}"
        manifest = {"protocol": "reference-manifest-v1", "schema_version": "1.0.0", "material_id": material_id, "revision_id": source["revision_id"], "entries": entries}
        sp = self.root / "source.json"; mp = self.root / "manifest.json"; sp.write_bytes(canonical(source)); mp.write_bytes(canonical(manifest))
        return asset_root, inbox, sp, mp

    def test_T01_default_chunk_is_bounded(self):
        self.assertIn('default=60', (PROJECT / "transcript-provider-bridge/funasr_chunked_provider.py").read_text())

    def test_T02_chunk_above_bound_is_rejected(self):
        run = subprocess.run([sys.executable, str(PROJECT / "transcript-provider-bridge/funasr_chunked_provider.py"), "--config", "x", "--audio", "x", "--output", "x", "--work-dir", "x", "--chunk-seconds", "121"], capture_output=True, text=True)
        self.assertNotEqual(run.returncode, 0)

    def test_T03_d1_old_giant_segment_fails(self):
        value = json.loads((FIXTURES / "synthetic-repetitive-transcript.json").read_text()); result = GATE.evaluate(value, value["text"], 301.906)
        self.assertIn("giant_single_segment", result["transcript_structural_qa"]["failures"]); self.assertFalse(result["ready_for_sorting"])

    def test_T04_d2_placeholder_fails(self):
        value = json.loads((FIXTURES / "synthetic-placeholder-transcript.json").read_text()); result = GATE.evaluate(value, value["text"], 1071.535)
        self.assertIn("placeholder_text", result["transcript_structural_qa"]["failures"]); self.assertFalse(result["ready_for_sorting"])

    def test_T05_short_usable_passes(self): self.assertTrue(self.evaluate(positive_transcript(60, 6), 60)["ready_for_sorting"])
    def test_T06_long_dynamic_segments_pass(self): self.assertTrue(self.evaluate(positive_transcript(725, 25), 725)["ready_for_sorting"])

    def test_T07_partial_missing_range_is_not_ready(self):
        value = positive_transcript(); value["status"] = "partial"; value["missing_ranges"] = [{"start_time": 30, "end_time": 40, "reason": "timeout"}]
        self.assertEqual(self.evaluate(value, 60)["quality_status"], "transcript_partial")

    def test_T08_provider_failure_is_not_ready(self):
        value = positive_transcript(); value["status"] = "failed"; self.assertFalse(self.evaluate(value, 60)["ready_for_sorting"])

    def test_T09_missing_timestamps_fail(self):
        value = positive_transcript(); value["segments"] = []; self.assertIn("transcript_empty", GATE.evaluate(value, value["text"], 60)["transcript_structural_qa"]["failures"])

    def test_T10_timestamp_coverage_is_measured(self): self.assertEqual(self.evaluate(positive_transcript(), 60)["transcript_structural_qa"]["metrics"]["timestamp_coverage_ratio"], 1.0)

    def test_T11_raw_and_readable_are_distinct_layers(self): self.assertFalse(HYGIENE.build(positive_transcript(), 220, 420)["raw_and_readable_byte_identical"])
    def test_T12_hygiene_declares_no_summary(self): self.assertIn("no_summary", HYGIENE.build(positive_transcript(), 220, 420)["operations"])

    def test_T13_hygiene_removes_exact_adjacent_phrase(self):
        value = positive_transcript(); value["segments"][0]["text"] = "经济转型经济转型带来变化"; result = self.readable(value)
        self.assertNotIn("经济转型经济转型", result)

    def test_T14_low_density_fails(self): self.assertIn("content_density_too_low", GATE.evaluate(positive_transcript(600, 10), "短文。", 600)["transcript_content_quality"]["failures"])

    def test_T15_repetition_pollution_fails(self):
        value = positive_transcript(); text = "产业转型" * 100
        self.assertIn("mechanical_repetition_pollution", GATE.evaluate(value, text, 60)["transcript_content_quality"]["failures"])

    def test_T16_unpunctuated_long_text_fails(self):
        value = positive_transcript(); text = "这是一段没有任何标点并且持续重复结构但内容字符不断变化" * 60
        self.assertIn("punctuation_absent_in_long_text", GATE.evaluate(value, text, 60)["transcript_content_quality"]["failures"])

    def test_T17_abnormal_characters_fail(self):
        value = positive_transcript(); text = "有效文本。" * 50 + "\ufffd" * 30
        self.assertIn("abnormal_character_ratio", GATE.evaluate(value, text, 60)["transcript_content_quality"]["failures"])

    def test_T18_segment_timeout_is_bounded(self):
        run, value = self.run_chunked(self.fake_provider("time.sleep(10)"), duration=1, timeout=5, retries=0)
        self.assertNotEqual(run.returncode, 0); self.assertEqual(value["chunking"]["chunks"][0]["failure_reason"], "segment_timeout")

    def test_T19_retry_recovers_segment(self):
        run, value = self.run_chunked(self.fake_provider('''\nif "attempt-0" in a.output: raise SystemExit(2)\n'''), duration=1, retries=1)
        self.assertEqual(run.returncode, 0); self.assertEqual(value["chunking"]["chunks"][0]["asr_status"], "completed_after_retry")

    def test_T20_segment_failure_is_isolated(self):
        run, value = self.run_chunked(self.fake_provider('''\nif name == "chunk-001.wav": raise SystemExit(2)\n'''), duration=31, retries=0)
        self.assertEqual(run.returncode, 0); self.assertEqual(value["status"], "partial"); self.assertEqual(len(value["missing_ranges"]), 1); self.assertTrue(value["text"])

    def test_T21_successful_segment_cache_is_reused(self):
        script = self.fake_provider(""); first, _ = self.run_chunked(script, duration=1); second, value = self.run_chunked(script, duration=1)
        self.assertEqual((first.returncode, second.returncode), (0, 0)); self.assertEqual(value["chunking"]["chunks"][0]["asr_status"], "completed_cached")

    def test_T22_media_without_quality_report_is_partial(self):
        root, inbox, sp, mp = self.completion_fixture(False)
        result, code = COMPLETION.complete_capture(source_path=sp, manifest_path=mp, asset_root=root, inbox=inbox, requested_output=inbox / "x.md", project_root=PROJECT, scope="test")
        self.assertEqual((code, result["status"]), (0, "capture_partial"))

    def test_T23_media_with_bound_quality_report_completes(self):
        root, inbox, sp, mp = self.completion_fixture(True)
        result, code = COMPLETION.complete_capture(source_path=sp, manifest_path=mp, asset_root=root, inbox=inbox, requested_output=inbox / "x.md", project_root=PROJECT, scope="test")
        self.assertEqual((code, result["status"]), (0, "capture_completed"))

    def test_T24_tampered_quality_binding_blocks(self):
        root, inbox, sp, mp = self.completion_fixture(True, True)
        result, code = COMPLETION.complete_capture(source_path=sp, manifest_path=mp, asset_root=root, inbox=inbox, requested_output=inbox / "x.md", project_root=PROJECT, scope="test")
        self.assertNotEqual(code, 0); self.assertEqual(result["status"], "capture_blocked")


if __name__ == "__main__": unittest.main(verbosity=2)
