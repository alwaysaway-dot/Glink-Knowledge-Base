#!/usr/bin/env python3
"""Deterministic regression for Learning Note Generation v2 boundaries."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run(command, ok=True):
    result = subprocess.run([str(item) for item in command], text=True, capture_output=True)
    if ok and result.returncode:
        raise AssertionError(f"command failed: {' '.join(map(str, command))}\n{result.stdout}\n{result.stderr}")
    if not ok and not result.returncode:
        raise AssertionError(f"command unexpectedly succeeded: {' '.join(map(str, command))}")
    return result


def fixture(base: Path, *, title="中文来源", author="作者", source_text="材料讨论债务、产业与转型条件。", language="zh-CN"):
    material = "material_sha256_" + "a" * 64
    revision = "revision_sha256_" + "b" * 64
    source = {
        "protocol": "source-material-v3", "schema_version": "3.0.0", "material_id": material, "revision_id": revision,
        "source": {"source_url": "https://example.test/source", "title": title, "author": author, "platform": "fixture", "language": language},
        "content": {"readable": {"reference": "guanlan://asset/asset_sha256_" + "c" * 64}},
        "quality": {"capture_status": "complete", "transcript_quality": "readable", "review_required": True,
                    "uncertainties": ["ASR transcript is unreviewed and may contain recognition errors."]},
        "lifecycle": {"review_status": "pending"},
        "asset_manifest_reference": f"guanlan://manifest/{material}/{revision}",
    }
    validation = {"status": "passed", "manifest_status": "valid", "material_id": material, "revision_id": revision}
    draft = {"protocol": "knowledge-asset-draft-v1", "asset": {"asset_id": "candidate_test", "type": "learning_note", "status": "draft"},
             "source": {"material_id": material, "task_id": "task", "source_reference": source["source"]["source_url"]},
             "content": {"title": "待生成知识标题", "references": []}, "review": {"need_confirmation": True, "confirmed": False}}
    plan = {"protocol": "knowledge-generation-v1", "input": {"asset_draft_id": "candidate_test", "material_id": material,
             "source_reference": source["source"]["source_url"]}, "generation": {"asset_type": "learning_note", "template": "learning_note", "requirements": []},
            "output": {"draft_reference": "guanlan://candidate/candidate_test", "need_confirmation": True}}
    paths = {name: base / name for name in ("source.json", "validation.json", "draft.json", "plan.json", "readable.md")}
    write_json(paths["source.json"], source); write_json(paths["validation.json"], validation)
    write_json(paths["draft.json"], draft); write_json(paths["plan.json"], plan)
    paths["readable.md"].write_text(source_text + "\n", encoding="utf-8")
    return paths


def engine_case(engine: Path, base: Path, markdown: str, *, title="中文来源", author="作者", source_text="材料讨论债务、产业与转型条件。", language="zh-CN", extras=()):
    base.mkdir(parents=True, exist_ok=True)
    paths = fixture(base, title=title, author=author, source_text=source_text, language=language)
    llm = base / "llm.md"; llm.write_text(markdown, encoding="utf-8")
    command = [engine, "--draft", paths["draft.json"], "--plan", paths["plan.json"], "--source-material", paths["source.json"],
               "--source-validation", paths["validation.json"], "--readable-source", paths["readable.md"], "--candidate-generation", "true",
               "--provider", "file", "--model", "fixture", "--prompt-version", "learning-note-generation-v2",
               "--prompt-file", ROOT / "core/prompt/learning-note-generation-v2.md", "--llm-output", llm,
               "--output", base / "output.md", "--quality", base / "quality.json", "--metadata", base / "metadata.json", "--record", base / "record.json"]
    run(command + list(extras))
    return json.loads((base / "quality.json").read_text(encoding="utf-8"))["generation-quality-check"]


GOOD = """# 债务约束下的产业转型机制

> 标注“AI结构化”的章节是观澜基于来源论证所做的结构抽象（AI_candidate），并非来源逐条明确提出。

## 认知核｜AI结构化

来源主张，产业变化的核心不是名称替换，而是债务承接方式与产业能力共同变化。

## 机制链｜AI结构化

债务约束构成前提，产业承接能力决定转型路径；二者的关系解释了不同结果。

## 可复用观察框架｜AI结构化

可复用的分析框架是同时检查融资来源、产业承接者和约束条件。

## 来源边界

这是对材料结构的抽象，不是外部事实补充；来源未提供统计数据，因果判断仍待核验。

## 来源与引用

- 原始来源：https://example.test/source
"""


def main():
    base = Path(tempfile.mkdtemp(prefix="guanlan-learning-v2.", dir="/tmp"))
    tests = []
    try:
        engine = base / "engine"
        run(["swiftc", "-parse-as-library", ROOT / "knowledge-generation-engine/KnowledgeGenerationEngine.swift", "-o", engine])

        good = engine_case(engine, base / "good", GOOD)
        assert good["source_language"] == "zh-CN" and good["output_language"] == "zh-CN"
        assert good["translation_required"] is False and "未提供中文翻译" not in good["missing_information"]
        assert "external_verification_not_requested" in good["intentional_scope_boundaries"]
        assert not any("外部背景" in item for item in good["missing_information"])
        assert good["authority_boundary"] == "passed"
        assert good["ai_candidate_sections"] == ["认知核｜AI结构化", "机制链｜AI结构化", "可复用观察框架｜AI结构化"]
        assert good["source_claim_labeling"] == "passed" and good["user_confirmed_view"] == "not_present"
        assert good["semantic_redundancy"] == "low"
        tests += ["T01", "T02", "T04", "T13", "T15", "T17", "T18", "T19", "T20", "T21", "T22", "T23"]

        unlabeled = engine_case(engine, base / "unlabeled-authority", GOOD.replace("## 可复用观察框架｜AI结构化", "## 可复用观察框架"))
        assert unlabeled["authority_boundary"] == "failed" and "authority_boundary_missing_or_invalid" in unlabeled["blocking_reasons"]
        tests.append("T26_ai_framework_requires_candidate_label")

        source_mislabeled = engine_case(engine, base / "source-mislabeled", GOOD.replace("## 来源边界", "## 来源主张与待核验边界｜AI结构化"))
        assert source_mislabeled["source_claim_labeling"] == "misclassified_as_ai_candidate" and source_mislabeled["publishable"] is False
        tests.append("T27_source_claim_not_ai_labeled")

        invented_user = engine_case(engine, base / "invented-user", GOOD.replace("## 来源与引用", "## User Confirmed View\n\n用户已确认上述框架。\n\n## 来源与引用"))
        assert invented_user["user_confirmed_view"] == "unverified" and invented_user["publishable"] is False
        tests.append("T28_user_confirmed_requires_explicit_input")

        grounded_user = engine_case(engine, base / "grounded-user", GOOD.replace("## 来源与引用", "## User Confirmed View\n\n用户已确认上述框架。\n\n## 来源与引用"), extras=("--user-confirmed-view", "true"))
        assert grounded_user["user_confirmed_view"] == "grounded" and grounded_user["authority_boundary"] == "passed"
        tests.append("T29_explicit_user_confirmation_allowed")

        translated = engine_case(engine, base / "translated", GOOD, source_text="The source describes debt and industrial transition.", language="en",
                                 extras=("--output-language", "zh-CN", "--translation-policy", "required"))
        assert translated["translation_required"] is True
        tests.append("T03")

        missing = engine_case(engine, base / "missing", GOOD, title="unknown", author="unknown")
        assert "来源标题未知" in missing["missing_information"] and "来源作者未知" in missing["missing_information"]
        tests.append("T05")

        repeated_block = "来源主张，债务约束与产业结构形成机制关系。该结构可以作为可复用分析框架，但具体因果仍待核验。" * 8
        repeated = f"# 重复草稿\n\n## 第一部分\n\n{repeated_block}\n\n## 第二部分\n\n{repeated_block}\n\n## 来源边界\n\n来源认为上述关系成立，相关事实仍待核验。\n"
        repeated_quality = engine_case(engine, base / "repeated", repeated)
        assert repeated_quality["semantic_redundancy"] == "high" and repeated_quality["publishable"] is False
        tests.append("T12")

        recap = "# 来源缩写\n\n## 内容\n\n来源认为材料讨论债务与产业。\n\n## 来源边界\n\n材料未提供数据，仍待核验。\n"
        recap_quality = engine_case(engine, base / "recap", recap)
        assert recap_quality["cognitive_delta"] == "insufficient_cognitive_delta" and recap_quality["publishable"] is False
        tests.append("T14")

        unsupported = GOOD.replace("因果判断仍待核验", "因果判断仍待核验；材料还证明增长达到37%")
        unsupported_quality = engine_case(engine, base / "unsupported", unsupported)
        assert unsupported_quality["grounding_status"] == "failed" and "37%" in unsupported_quality["unsupported_factual_expansions"]
        tests.append("T16")

        candidate_dir = base / "candidate"
        candidate_paths = fixture(candidate_dir, title="#原始 #标签", source_text="材料讨论债务、产业与转型条件。")
        llm = candidate_dir / "candidate-llm.md"; llm.write_text(GOOD, encoding="utf-8")
        candidate_path = candidate_dir / "candidate.json"
        run([sys.executable, ROOT / "knowledge-ingestion-manager/learning_candidate_generation.py",
             "--source-material", candidate_paths["source.json"], "--source-validation", candidate_paths["validation.json"],
             "--readable-source", candidate_paths["readable.md"], "--operation-dir", candidate_dir / "operation",
             "--provider", "file", "--model", "fixture", "--llm-output", llm, "--output", candidate_path])
        candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
        assert candidate["content"]["title"] == "债务约束下的产业转型机制"
        assert candidate["content"]["generated_title"] == candidate["content"]["title"]
        assert candidate["source"]["original_title"] == "#原始 #标签" and candidate["content"]["title"] != candidate["source"]["original_title"]
        assert candidate["status"] == "publishable"
        tests += ["T06", "T07", "T08", "T09", "T10"]

        unknown_dir = base / "candidate-unknown-source-title"
        unknown_paths = fixture(unknown_dir, title="unknown", author="unknown", source_text="材料讨论债务、产业与转型条件。")
        unknown_llm = unknown_dir / "candidate-llm.md"; unknown_llm.write_text(GOOD, encoding="utf-8")
        unknown_candidate_path = unknown_dir / "candidate.json"
        run([sys.executable, ROOT / "knowledge-ingestion-manager/learning_candidate_generation.py",
             "--source-material", unknown_paths["source.json"], "--source-validation", unknown_paths["validation.json"],
             "--readable-source", unknown_paths["readable.md"], "--operation-dir", unknown_dir / "operation",
             "--provider", "file", "--model", "fixture", "--llm-output", unknown_llm, "--output", unknown_candidate_path])
        unknown_candidate = json.loads(unknown_candidate_path.read_text(encoding="utf-8"))
        assert unknown_candidate["source"]["original_title"] == "unknown"
        assert unknown_candidate["content"]["title"] != "unknown" and unknown_candidate["status"] == "publishable"
        tests.append("T11")

        assert good["publishable"] is True and good["generated_title"] == "债务约束下的产业转型机制"
        tests += ["T24_fixture_boundary", "T25_fixture_boundary", "T30_authority_label_no_redundancy"]
        print(json.dumps({"status": "passed", "tests": tests, "count": len(tests)}, ensure_ascii=False, indent=2))
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    main()
