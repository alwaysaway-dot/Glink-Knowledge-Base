#!/usr/bin/env python3
"""Regression for user-level organize, multi-asset gates and publisher routing."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "knowledge-ingestion-manager"))
from approval_binding import prepare as prepare_binding


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text, encoding="utf-8")


def write_json(path: Path, value):
    write(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def run(*args, ok=True):
    result = subprocess.run([str(arg) for arg in args], text=True, capture_output=True)
    if ok and result.returncode:
        raise AssertionError(f"failed: {' '.join(map(str,args))}\n{result.stdout}\n{result.stderr}")
    if not ok and not result.returncode:
        raise AssertionError(f"unexpected success: {' '.join(map(str,args))}")
    return result


def content_hash(text: str): return "sha256:" + hashlib.sha256((text.strip() + "\n").encode()).hexdigest()


def source_fixture(base: Path):
    root = base / "asset-library"; material = "material_sha256_" + "a" * 64; revision = "revision_sha256_" + "b" * 64
    source = {
        "protocol": "source-material-v3", "schema_version": "3.0.0", "material_id": material, "revision_id": revision,
        "source": {"source_url": "https://example.test/economy", "title": "经济转型教程"},
        "content": {"readable": {"reference": "guanlan://asset/asset_sha256_" + "c" * 64}},
        "quality": {"capture_status": "complete", "transcript_quality": "readable", "review_required": True},
        "lifecycle": {"review_status": "pending"}, "asset_manifest_reference": f"guanlan://manifest/{material}/{revision}",
    }
    validation = {"protocol": "source-asset-validation-v1", "status": "passed", "material_id": material, "revision_id": revision}
    source_path = base / "source.json"; validation_path = base / "validation.json"; readable = base / "readable.md"
    write_json(source_path, source); write_json(validation_path, validation); write(readable, "# 经济转型教程\n\n来源事实：债务、产业与转型条件。\n")
    return root, source, source_path, validation_path, readable


def derivative(source, asset_type, markdown, admission):
    return {
        "protocol": "derivative-candidate-v1", "schema_version": "1.0.0",
        "candidate_id": "candidate_" + asset_type, "asset_type": asset_type, "status": "publishable",
        "source": {"material_id": source["material_id"], "revision_id": source["revision_id"]},
        "content": {"title": asset_type, "markdown": markdown},
        "provenance": {"stable_references": [f"guanlan://material/{source['material_id']}/revision/{source['revision_id']}"]},
        "admission": admission,
    }


def derivative_publish(base, root, source_path, source, candidate, target):
    asset_type = candidate["asset_type"]; directory = base / asset_type; candidate_path = directory / "candidate.json"; write_json(candidate_path, candidate)
    body_hash = content_hash(candidate["content"]["markdown"])
    confirmation = {"protocol": "derivative-publish-approval-v1", "approval_id": "approval-" + asset_type, "confirmed": True, "reviewer": "user", "confirmed_at": "2026-09-15T00:00:00Z", "candidate_id": candidate["candidate_id"], "asset_type": asset_type, "content_hash": body_hash, "stable_references": candidate["provenance"]["stable_references"]}
    quality = {"protocol": "derivative-publish-quality-v1", "status": "passed", "candidate_id": candidate["candidate_id"], "asset_type": asset_type}
    confirmation["approval_binding"] = prepare_binding(candidate=candidate, source=source, target_folder=target,
        filename=f"2026-09-15_{asset_type}.md", body=candidate["content"]["markdown"],
        title=candidate["content"]["title"], quality=quality)
    confirmation_path = directory / "approval.json"; quality_path = directory / "quality.json"; output = directory / "output.json"
    write_json(confirmation_path, confirmation); write_json(quality_path, quality)
    vault = base / "vault"; (vault / target).mkdir(parents=True, exist_ok=True)
    args = [sys.executable, ROOT / "knowledge-ingestion-manager/derivative_publish.py", "--candidate", candidate_path, "--confirmation", confirmation_path, "--quality", quality_path, "--source-material", source_path, "--vault-root", vault, "--asset-root", root, "--filename", f"2026-09-15_{asset_type}.md", "--target-folder", target, "--scope", "test", "--output", output]
    run(*args); first = json.loads(output.read_text()); assert first["status"] in {"published", "already_published"}
    run(*args); assert json.loads(output.read_text())["status"] == "already_published"
    assert not list((vault / target).glob("*_2.md"))
    wrong = list(args); wrong[wrong.index("--target-folder") + 1] = "20 学习笔记"; wrong[wrong.index("--output") + 1] = directory / "wrong.json"; run(*wrong, ok=False)
    return args, vault


def main():
    base = Path(tempfile.mkdtemp(prefix="guanlan-multi-asset.", dir="/tmp")); results = {"tests": []}
    try:
        root, source, source_path, validation_path, readable = source_fixture(base)
        llm = base / "learning.md"; write(llm, "# 债务约束下的产业转型机制\n\n> 标注“AI结构化”的章节是观澜基于来源论证所做的结构抽象（AI_candidate），并非来源逐条明确提出。\n\n## 认知核｜AI结构化\n\n来源主张，经济转型不是产业名单的轮换，而是债务承接方式与产业结构共同变化。\n\n## 机制链｜AI结构化\n\n债务约束构成前提，产业承接能力决定转型路径；两者的关系解释了为什么相似增长目标可能导向不同结构。\n\n## 可复用观察框架｜AI结构化\n\n可复用的分析框架是同时检查融资来源、产业承接者与转型约束，而不是只观察产出增速。\n\n## 来源边界\n\n以上是对来源结构的抽象；材料未提供统计数据，相关因果判断仍待核验。\n\n## 来源与引用\n\n- 来源：经济转型教程。\n")
        method = derivative(source, "method_asset", "# 证据核查方法\n\n可复用的来源核查步骤。", {"status": "passed", "required_fields": ["purpose", "inputs", "preconditions", "steps", "outputs", "limitations", "applicability", "failure_conditions", "source_basis"], "ai_invented": False, "validation_status": "not_required"})
        signals = {"protocol": "derivative-signals-v1", "candidates": [method, {"asset_type": "intelligence_brief", "status": "needs_corroboration", "source": {"material_id": source["material_id"], "revision_id": source["revision_id"]}, "reason": "single source"}, {"asset_type": "creation_asset", "status": "not_applicable", "source": {"material_id": source["material_id"], "revision_id": source["revision_id"]}, "reason": "no audience/purpose/deliverable"}]}
        signals_path = base / "signals.json"; bundle_path = base / "bundle.json"; write_json(signals_path, signals)
        run(sys.executable, ROOT / "knowledge-ingestion-manager/organize_workflow.py", "--source-material", source_path, "--source-validation", validation_path, "--readable-source", readable, "--asset-root", root, "--derivative-signals", signals_path, "--learning-provider", "file", "--learning-llm-output", llm, "--output", bundle_path)
        bundle = json.loads(bundle_path.read_text()); statuses = {item["asset_type"]: item["status"] for item in bundle["derivative_candidates"]}
        assert bundle["workflow_state"] == "awaiting_user_confirmation" and bundle["vault_writes"] is False
        assert statuses["learning_note"] == "publishable" and statuses["method_asset"] == "publishable", bundle["derivative_candidates"]
        assert statuses["intelligence_brief"] == "needs_corroboration" and statuses["creation_asset"] == "not_applicable"
        assert not (base / "vault" / "10 原始资料").exists(); results["tests"].extend(["T01_capture_source_only", "T03_ready_source_organize", "T04_source_candidate", "T05_derivation_router", "T06_learning_candidate", "T09_single_source_intelligence_needs_corroboration", "T11_method_candidate", "T13_creation_not_applicable", "T15-T19_organize_no_vault_write", "T20_candidate_identities", "T21_stable_provenance"])
        intelligence = derivative(source, "intelligence_brief", "# 外部变化简报\n\n多来源变化及其影响。", {"status": "passed", "time_sensitive": True, "external_change": True, "independent_source_count": 2})
        creation = derivative(source, "creation_asset", "# 团队方案\n\n面向团队的交付方案。", {"status": "passed", "required_fields": ["audience", "purpose", "deliverable", "version"], "user_output_intent": True})
        derivative_publish(base, root, source_path, source, intelligence, "30 情报简报")
        derivative_publish(base, root, source_path, source, method, "40 方法库")
        derivative_publish(base, root, source_path, source, creation, "50 输出成果")
        results["tests"].extend(["T10_multi_source_intelligence_publishable", "T24_intelligence_to_30", "T25_method_to_40", "T26_creation_to_50", "T27-T29_nonpublishable_not_routed", "T31_wrong_target_rejected", "T32-T34_idempotent_no_suffix"])
        bad = dict(intelligence); bad["admission"] = dict(intelligence["admission"], independent_source_count=1); bad_path = base / "bad.json"; write_json(bad_path, bad)
        # Gate must reject a single-source claim even if caller marks it publishable.
        args, _ = derivative_publish(base, root, source_path, source, intelligence, "30 情报简报")
        blocked = list(args); blocked[blocked.index("--candidate") + 1] = bad_path; blocked[blocked.index("--output") + 1] = base / "bad-output.json"; run(*blocked, ok=False)
        results["tests"].extend(["T37_intelligence_not_fake_multisource", "T38_method_not_ai_invented", "T39_creation_requires_intent", "T40_legacy_path_covered_by_freeze_suite"])
        write_json(Path(sys.argv[1]), results); print(json.dumps(results, ensure_ascii=False, indent=2))
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    main()
