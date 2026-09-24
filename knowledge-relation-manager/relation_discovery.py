#!/usr/bin/env python3
"""Read-only relation candidate discovery for formal Vault assets."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from relation_common import (
    FORWARD_RELATIONS,
    atomic_json,
    candidate_id,
    canonical_pair,
    relation_exists,
    scan_vault,
)


ROLE_PATTERNS = {
    "core_questions": re.compile(r"核心问题|解决什么问题|问题"),
    "core_concepts": re.compile(r"核心概念|关键概念|概念"),
    "argument": re.compile(r"论证|内容脉络|关键知识点|核心观点"),
    "method": re.compile(r"方法|操作步骤|适用场景|流程"),
    "conclusion": re.compile(r"结论|值得长期保存|下一步|实践价值"),
    "limitations": re.compile(r"限定|边界|注意事项|不确定|风险"),
}
STOP = {
    "一个", "一种", "可以", "应该", "需要", "如果", "这个", "这些", "以及", "进行", "使用", "内容", "资产", "用户",
    "知识", "系统", "来源", "视频", "材料", "作者", "时间", "证据", "问题", "方法", "通过", "不是", "没有", "已经",
}


def role_text(asset, pattern):
    return "\n".join(value for heading, value in asset["sections"].items() if pattern.search(heading))


def semantic_terms(text):
    words = set(re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}|[\u4e00-\u9fff]{2,8}", text.lower()))
    return {word for word in words if word not in STOP and len(word) <= 12}


def overlap_score(left, right):
    if not left or not right:
        return 0.0, []
    common = left & right
    score = len(common) / max(1, min(len(left), len(right)))
    return score, sorted(common, key=lambda item: (-len(item), item))[:8]


def make_candidate(source, target, relation_type, strength, confidence, rationale, evidence, source_anchor, target_anchor):
    reciprocal = FORWARD_RELATIONS[relation_type]
    directionality = "symmetric" if relation_type in {"contrasts_with", "related"} else "directed"
    return {
        "protocol": "relation-candidate-v1",
        "schema_version": "1.0.0",
        "candidate_id": candidate_id(source["asset_id"], source["revision"], target["asset_id"], target["revision"], relation_type),
        "source_asset_id": source["asset_id"],
        "source_revision": source["revision"],
        "source_snapshot_hash": source["file_hash"],
        "target_asset_id": target["asset_id"],
        "target_revision": target["revision"],
        "target_snapshot_hash": target["file_hash"],
        "relation_type": relation_type,
        "relation_strength": strength,
        "confidence": confidence,
        "rationale": rationale,
        "evidence": evidence,
        "source_anchor": source_anchor,
        "target_anchor": target_anchor,
        "directionality": directionality,
        "reciprocal_relation": reciprocal,
        "decision_status": "suggested",
        "created_at": "",
        "source_display": {"title": source["title"], "path": source["relative_path"], "asset_class": source["asset_class"]},
        "target_display": {"title": target["title"], "path": target["relative_path"], "asset_class": target["asset_class"]},
    }


def structural_candidates(assets, registry):
    sources = [item for item in assets if item["eligible"] and item["asset_class"] == "source"]
    derived = [item for item in assets if item["eligible"] and item["asset_class"] != "source"]
    output = []
    for source in sources:
        for target in derived:
            fm = target["frontmatter"]
            material_match = str(fm.get("source_asset", "")) == source["asset_id"]
            revision_match = str(fm.get("source_revision", "")) == source["revision"]
            reference_match = str(fm.get("source_reference", "")).endswith(f"/{source['revision']}")
            if not material_match or not revision_match or not reference_match:
                continue
            if relation_exists(registry, source["asset_id"], target["asset_id"], "source_of", "derived_from"):
                continue
            output.append(
                make_candidate(
                    source,
                    target,
                    "source_of",
                    "strong",
                    "high",
                    "Learning Asset 明确记录同一 material_id、source revision 与稳定 source_reference；从学习笔记跳回原始资料可核对完整上下文，从原始资料跳向学习笔记可查看经确认的知识加工结果。",
                    [
                        {"kind": "stable_identity_match", "field": "source_asset", "value": source["asset_id"]},
                        {"kind": "revision_match", "field": "source_revision", "value": source["revision"]},
                        {"kind": "stable_reference_match", "field": "source_reference", "value": fm.get("source_reference")},
                    ],
                    "frontmatter.material_id + frontmatter.revision_id",
                    "frontmatter.source_asset + frontmatter.source_revision + frontmatter.source_reference",
                )
            )
    return output


def semantic_candidate(left, right):
    if left["asset_class"] == "source" or right["asset_class"] == "source":
        return None, {"reason": "no_verified_derivation_or_cross_asset_semantics"}
    dimensions = []
    evidence = []
    for role, pattern in ROLE_PATTERNS.items():
        left_terms = semantic_terms(role_text(left, pattern))
        right_terms = semantic_terms(role_text(right, pattern))
        score, common = overlap_score(left_terms, right_terms)
        if score >= 0.16 and len(common) >= 2:
            dimensions.append((role, score))
            evidence.append({"kind": "semantic_dimension", "dimension": role, "overlap": common, "score": round(score, 3)})
    if len(dimensions) < 3:
        return None, {"reason": "fewer_than_three_semantic_dimensions", "matched_dimensions": len(dimensions)}

    has_method = any(role == "method" for role, _ in dimensions)
    if left["asset_class"] == "method" and has_method:
        relation_type = "method_for"
    elif right["asset_class"] == "method" and has_method:
        left, right = right, left
        relation_type = "method_for"
    else:
        relation_type = "explains"
    average = sum(score for _, score in dimensions) / len(dimensions)
    strength = "strong" if len(dimensions) >= 4 and average >= 0.30 else "medium"
    confidence = "high" if strength == "strong" else "medium"
    candidate = make_candidate(
        left,
        right,
        relation_type,
        strength,
        confidence,
        f"两项正式资产在 {len(dimensions)} 个结构化语义维度存在可复核交集；阅读其中一项时，另一项可补充问题定义、方法或限定条件，而非只重复标题或标签。",
        evidence,
        "structured semantic sections",
        "structured semantic sections",
    )
    return candidate, None


def discover(assets, registry, created_at):
    eligible = [item for item in assets if item["eligible"]]
    strong = structural_candidates(assets, registry)
    medium = []
    filtered = []
    seen_pairs = {canonical_pair(item["source_asset_id"], item["target_asset_id"]) for item in strong}
    for index, left in enumerate(eligible):
        for right in eligible[index + 1 :]:
            pair = canonical_pair(left["asset_id"], right["asset_id"])
            if pair in seen_pairs:
                continue
            candidate, rejection = semantic_candidate(left, right)
            if candidate is None:
                filtered.append({
                    "source_asset_id": left["asset_id"], "target_asset_id": right["asset_id"],
                    "source_title": left["title"], "target_title": right["title"],
                    "classification": "weak", **rejection,
                })
                continue
            if relation_exists(registry, candidate["source_asset_id"], candidate["target_asset_id"], candidate["relation_type"], candidate["reciprocal_relation"]):
                filtered.append({"classification": "duplicate_existing_relation", "candidate_id": candidate["candidate_id"]})
                continue
            if candidate["candidate_id"] in {item["candidate_id"] for item in strong + medium}:
                filtered.append({"classification": "duplicate_candidate", "candidate_id": candidate["candidate_id"]})
                continue
            candidate["created_at"] = created_at
            (strong if candidate["relation_strength"] == "strong" else medium).append(candidate)
            seen_pairs.add(pair)
    for item in strong:
        item["created_at"] = created_at
    exclusions = [
        {
            "path": item["relative_path"], "title": item["title"], "asset_class": item["asset_class"],
            "reason": item["exclusion_reason"],
        }
        for item in assets if not item["eligible"]
    ]
    return strong, medium, filtered, exclusions


def render_review(result):
    lines = [
        "# Relation Discovery Review", "", "状态：`dry_run`；未修改 Vault，未写入双链。", "",
        "## A. Strong Candidates", "",
    ]
    if not result["strong_candidates"]:
        lines.append("`no_strong_relation_found`")
    for item in result["strong_candidates"]:
        lines.extend([
            f"### {item['source_display']['title']} → {item['target_display']['title']}", "",
            f"- Candidate：`{item['candidate_id']}`",
            f"- 关系：`{item['relation_type']}`；反向：`{item['reciprocal_relation']}`",
            f"- 强度 / 置信度：`{item['relation_strength']}` / `{item['confidence']}`",
            f"- 理由：{item['rationale']}",
            f"- 证据：`{json.dumps(item['evidence'], ensure_ascii=False)}`",
            f"- Source anchor：`{item['source_anchor']}`",
            f"- Target anchor：`{item['target_anchor']}`", "",
        ])
    lines.extend(["## B. Medium Candidates", ""])
    if not result["medium_candidates"]:
        lines.append("无。")
    for item in result["medium_candidates"]:
        lines.extend([
            f"### {item['source_display']['title']} → {item['target_display']['title']}", "",
            f"- 关系 / 反向：`{item['relation_type']}` / `{item['reciprocal_relation']}`",
            f"- 理由：{item['rationale']}", f"- 证据：`{json.dumps(item['evidence'], ensure_ascii=False)}`", "",
        ])
    lines.extend(["## C. Rejected / Weak", ""])
    lines.append(f"- Weak pair：{len(result['filtered_candidates'])} 组；均未进入可审批候选。")
    lines.append(f"- 排除资产：{len(result['excluded_assets'])} 项。")
    for item in result["excluded_assets"]:
        lines.append(f"- `{item['path']}`：`{item['reason']}`")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault", required=True)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--review", required=True)
    parser.add_argument("--created-at", default="")
    args = parser.parse_args()
    created_at = args.created_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    registry = json.loads(Path(args.registry).read_text(encoding="utf-8"))
    if registry.get("protocol") != "relation-registry-v1":
        raise SystemExit("ERROR: relation-registry-v1 is required")
    assets = scan_vault(args.vault)
    strong, medium, filtered, excluded = discover(assets, registry, created_at)
    result = {
        "protocol": "relation-discovery-run-v1", "schema_version": "1.0.0", "dry_run": True,
        "created_at": created_at,
        "scan_scope": list(("10 原始资料", "20 学习笔记", "30 情报简报", "40 方法库", "50 输出成果")),
        "excluded_scope": ["00 收件箱", "/tmp", "draft", "waiting_user_confirmation", "AI_candidate", "cleanup_candidate"],
        "summary": {
            "scanned_assets": len(assets), "eligible_assets": sum(item["eligible"] for item in assets),
            "excluded_assets": len(excluded), "strong_candidates": len(strong),
            "medium_candidates": len(medium), "filtered_or_weak_pairs": len(filtered),
            "markdown_files_modified": 0, "links_written": 0,
        },
        "strong_candidates": strong, "medium_candidates": medium,
        "filtered_candidates": filtered, "excluded_assets": excluded,
    }
    atomic_json(Path(args.output), result)
    Path(args.review).write_text(render_review(result), encoding="utf-8")


if __name__ == "__main__":
    main()
