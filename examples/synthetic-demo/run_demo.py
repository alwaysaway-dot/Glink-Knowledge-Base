#!/usr/bin/env python3
"""Fixture-based local workflow demo. No real capture or model/API call."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests/freeze-closure"))
sys.path.insert(0, str(ROOT / "knowledge-relation-manager"))
sys.path.insert(0, str(ROOT / "knowledge-ingestion-manager"))
from run_freeze_closure import build_case, learning_inputs  # noqa: E402
from approval_binding import prepare as prepare_binding  # noqa: E402
from relation_common import atomic_json, scan_vault  # noqa: E402
from relation_curation import structural_candidates  # noqa: E402
from relation_apply import execute  # noqa: E402
from relation_registry import validate  # noqa: E402


def run(*args: object) -> None:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run([str(arg) for arg in args], capture_output=True, text=True, env=env)
    if result.returncode:
        raise RuntimeError(f"demo stage failed ({result.returncode}): {result.stderr.strip()}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    base = args.output_root.resolve()
    if not str(base).startswith(("/tmp/", "/private/tmp/")) or base.exists():
        raise SystemExit("demo output must be a new isolated /tmp directory")
    base.mkdir(parents=True)

    # The fixture helper creates source evidence, a promoted revision and 10 Source.
    # It never fetches a real URL or calls a model; its test approvals are synthetic.
    case = build_case(base, "synthetic-web-article", "webpage", {})
    inbox = case["vault"] / "00 收件箱"
    inbox.mkdir()
    run(sys.executable, ROOT / "source-material-generator/capture_inbox_completion.py",
        "--source-material", case["dir"] / "source.json",
        "--manifest", case["dir"] / "manifest.json",
        "--asset-root", case["root"], "--inbox", inbox,
        "--output", inbox / "2026-08-09_采集_合成网页.md",
        "--project-root", ROOT, "--result", case["dir"] / "capture-result.json",
        "--scope", "test")

    body = ("# 合成网页的学习候选\n\n## 来源主张\n\n人工构造的来源称：先记录事实，再做解释。\n\n"
            "## 可复用框架｜AI结构化\n\n这是基于合成来源整理的 AI_candidate，"
            "并非来源逐条明确提出：保留证据、标注不确定性、等待人工判断。\n")
    inputs = learning_inputs(case, body, "synthetic-learning", "2026-08-09_学习_合成来源.md")
    bundle_path = case["dir"] / "candidate-bundle.json"
    run(sys.executable, ROOT / "knowledge-ingestion-manager/organize_workflow.py",
        "--source-material", case["revision_dir"] / "source-material-v3.json",
        "--source-validation", case["revision_dir"] / "source-asset-validation.json",
        "--readable-source", case["dir"] / "readable.md",
        "--asset-root", case["root"], "--learning-provider", "file",
        "--learning-llm-output", inputs / "note.md", "--output", bundle_path)
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    if bundle["workflow_state"] != "awaiting_user_confirmation" or not any(
        item["asset_type"] == "learning_note" and item["status"] == "publishable"
        for item in bundle["derivative_candidates"]
    ):
        raise AssertionError("synthetic Candidate Bundle is not reviewable")
    candidate = dict(next(item for item in bundle["derivative_candidates"] if item["asset_type"] == "learning_note"))
    # The organizer's run-local file pointers are not provenance. The reviewable
    # candidate retains stable source refs and has no /tmp fields at publish time.
    candidate.pop("publish_inputs", None)
    if "generation" in candidate:
        candidate["generation"] = dict(candidate["generation"])
        candidate["generation"].pop("record_path", None)
    bundle["derivative_candidates"] = [
        candidate if item["asset_type"] == "learning_note" else item
        for item in bundle["derivative_candidates"]
    ]
    atomic_json(bundle_path, bundle)
    candidate_path = case["dir"] / "learning-candidate.json"
    atomic_json(candidate_path, candidate)
    draft_path = inputs / "draft.json"
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    draft["asset"]["asset_id"] = candidate["candidate_id"]
    atomic_json(draft_path, draft)
    quality = json.loads((inputs / "quality.json").read_text(encoding="utf-8"))
    approval_path = inputs / "approval.json"
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    approval["approval_binding"] = prepare_binding(
        candidate=candidate, source=case["source"], target_folder="20 学习笔记",
        filename="2026-08-09_学习_合成来源.md", body=body,
        title=candidate["content"]["title"], quality=quality)
    atomic_json(approval_path, approval)
    publish_result = case["dir"] / "learning-publish.json"
    run(sys.executable, ROOT / "knowledge-ingestion-manager/learning_publish.py",
        "--draft", draft_path, "--generated", inputs / "note.md", "--candidate", candidate_path,
        "--confirmation", approval_path, "--quality", inputs / "quality.json",
        "--source-material", case["revision_dir"] / "source-material-v3.json",
        "--vault-root", case["vault"], "--asset-root", case["root"],
        "--filename", "2026-08-09_学习_合成来源.md", "--scope", "test",
        "--relation-hook", "skip", "--output", publish_result)

    registry_path = case["dir"] / "relation-registry.json"
    registry = {"protocol": "relation-registry-v1", "schema_version": "1.0.0",
                "registry_id": "synthetic-demo", "relations": [], "updated_at": ""}
    atomic_json(registry_path, registry)
    assets = scan_vault(str(case["vault"]))
    candidates = structural_candidates(assets, registry, "2026-08-09T00:00:00Z")
    if len(candidates) != 1:
        raise AssertionError(f"expected one structural relation, got {len(candidates)}")
    candidate = candidates[0]
    source = next(item for item in assets if item["asset_id"] == candidate["source_asset_id"])
    target = next(item for item in assets if item["asset_id"] == candidate["target_asset_id"])
    execute(candidate, source, target, registry_path, None,
            case["dir"] / "relation-rollback", case["dir"] / "relation-receipt.json", auto=True)
    relation_check = validate(json.loads(registry_path.read_text(encoding="utf-8")))
    receipt_dir = case["root"] / "governance" / "knowledge-publish" / "original-receipts"
    receipts = list(receipt_dir.glob("*.json"))
    if len(receipts) != 1 or relation_check["relation_count"] != 1:
        raise AssertionError("publish receipt or relation registry missing")
    summary = {
        "demo_kind": "fixture_based_synthetic_demo",
        "real_capture": False, "real_model_generation": False,
        "approval": "synthetic_test_approval_only",
        "inbox_projection": str(inbox / "2026-08-09_采集_合成网页.md"),
        "source_asset": str(case["projection"]),
        "learning_asset": str(case["vault"] / "20 学习笔记" / "2026-08-09_学习_合成来源.md"),
        "source_evidence": str(case["dir"] / "manifest.json"),
        "candidate_bundle": str(bundle_path),
        "candidate_input": str(inputs / "draft.json"),
        "publish_receipt": str(receipts[0]),
        "relation_registry": str(registry_path),
        "relation_receipt": str(case["dir"] / "relation-receipt.json"),
    }
    atomic_json(base / "demo-summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
