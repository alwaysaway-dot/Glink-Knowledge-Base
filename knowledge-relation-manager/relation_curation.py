#!/usr/bin/env python3
"""Full-vault relation curation with bounded retrieval and conservative judgment."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import tempfile
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from relation_apply import execute, rollback
from relation_common import (
    FORWARD_RELATIONS,
    atomic_json,
    candidate_id,
    canonical_pair,
    current_revision,
    relation_exists,
    scan_vault,
    sha256_bytes,
)
from relation_discovery import make_candidate
from relation_governance import audit_registry_markdown, reconcile_observations
from relation_registry import validate as validate_registry

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from operation_envelope import OperationRecorder


APPROVED_SEMANTIC_TYPES = {"extends", "supports", "contrasts_with", "applies", "updates"}
GENERIC_TERMS = {
    "来源", "材料", "内容", "问题", "方法", "知识", "结构", "观点", "作者", "系统", "进行", "一个", "一种", "可以",
    "需要", "不是", "没有", "这个", "这些", "以及", "通过", "认为", "分析", "理解", "说明", "相关", "核心", "主要",
    "source", "asset", "knowledge", "learning", "video", "material", "content", "relation",
}
SIGNALS = {
    "extends": re.compile(r"在.{0,30}(?:基础上|框架上).{0,30}(?:进一步|扩展|发展|延伸)|进一步(?:扩展|发展|推进|细化)|延伸了|补充了"),
    "supports": re.compile(r"(?:证据|案例|数据|事实|实验|观察).{0,40}(?:支持|证明|印证|佐证)|(?:支持|证明|印证|佐证).{0,40}(?:判断|主张|结论|机制)"),
    "contrasts_with": re.compile(r"(?:不同于|与.{0,24}相反|形成对照|相较之下|两者差异|冲突在于|另一种解释)"),
    "applies": re.compile(r"(?:实际|具体|本案例|本方案|本简报).{0,30}(?:应用|采用|使用).{0,30}(?:框架|方法|流程|原则)|将.{0,30}(?:框架|方法).{0,30}(?:应用|用于)"),
    "updates": re.compile(r"(?:截至|最新|本期|本周|本月|今日|当前).{0,40}(?:更新|变化|进展|状态)|对.{0,30}(?:旧判断|此前状态|原有情报).{0,30}(?:更新|修正)"),
}
CLAIM_CUE = re.compile(r"主张|判断|结论|认为|机制|核心观点")
EVIDENCE_CUE = re.compile(r"证据|案例|数据|事实|实验|观察|时间证据")
DATE_RE = re.compile(r"20\d{2}[-年/.]\d{1,2}(?:[-月/.]\d{1,2})?")
SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?；;])|\n+")


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def file_hash(path: Path):
    return "sha256:" + sha256_bytes(path.read_bytes()) if path.exists() else "missing"


def semantic_text(asset):
    excluded = re.compile(r"^(来源|来源与引用|稳定来源|证据入口|质量|资产边界|关联知识|派生知识|来源资料)")
    sections = [f"{heading}\n{text}" for heading, text in asset.get("sections", {}).items() if not excluded.search(heading)]
    return (asset["title"] + "\n" + "\n".join(sections)).strip()


def terms(text: str, limit: int = 220):
    counts = Counter()
    for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}|[\u4e00-\u9fff]{2,18}", text.lower()):
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            for size in (2, 3, 4):
                for index in range(max(0, len(token) - size + 1)):
                    part = token[index:index + size]
                    if part not in GENERIC_TERMS:
                        counts[part] += 1
        elif token not in GENERIC_TERMS:
            counts[token] += 1
    return [item for item, _ in counts.most_common(limit)]


def fingerprint(asset):
    text = semantic_text(asset)
    signals = {name: bool(pattern.search(text)) for name, pattern in SIGNALS.items()}
    return {
        "asset_id": asset["asset_id"], "revision": asset["revision"], "asset_class": asset["asset_class"],
        "title": asset["title"], "path": asset["relative_path"], "terms": terms(text), "anchors": semantic_anchors(asset),
        "source_identity": str(asset["frontmatter"].get("source_asset") or asset["frontmatter"].get("material_id") or ""),
        "time_sensitive": asset["asset_class"] == "intelligence" or bool(DATE_RE.search(text)),
        "signals": signals, "semantic_hash": "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def semantic_anchors(asset):
    """Return explicit named concepts, never generic character n-grams."""
    text = semantic_text(asset)
    values = set()
    ignored = {"ai结构化", "ai_candidate", "可复用的理解框架", "可复用理解框架", "来源主张与待核验边界"}
    patterns = (r"\*\*([^*\n]{2,40})\*\*", r"`([^`\n]{2,40})`", r"[“\"]([^”\"\n]{2,32})[”\"]")
    for pattern in patterns:
        for value in re.findall(pattern, text):
            normalized = re.sub(r"\s+", "", value).strip("：:，,。；;（）()《》")
            if 2 <= len(normalized) <= 32 and normalized.lower() not in GENERIC_TERMS and normalized.lower() not in ignored:
                values.add(normalized.lower())
    generic_headings = re.compile(r"来源|引用|边界|质量|信息|认知核|论证|内容|核心问题|核心概念|实践价值|关联知识")
    for heading in asset.get("sections", {}):
        normalized = re.sub(r"｜.*$|\s+", "", heading).strip("#：:，,。；;")
        if 3 <= len(normalized) <= 24 and not generic_headings.search(normalized) and normalized.lower() not in ignored:
            values.add(normalized.lower())
    return sorted(values)


def build_fingerprints(assets):
    return {item["asset_id"]: fingerprint(item) for item in assets if item["eligible"]}


def retrieve_pairs(fingerprints, top_k=12):
    started = time.perf_counter()
    index = defaultdict(list)
    for asset_id, fp in fingerprints.items():
        for term in set(fp["terms"]):
            index[term].append(asset_id)
    count = len(fingerprints)
    posting_limit = max(12, int(math.sqrt(max(1, count)) * 4))
    pair_scores = Counter()
    pair_terms = defaultdict(set)
    for term, postings in index.items():
        if len(postings) < 2 or len(postings) > posting_limit:
            continue
        weight = 1.0 + math.log((count + 1) / len(postings))
        ordered = sorted(postings)
        for left_index, left in enumerate(ordered):
            for right in ordered[left_index + 1:]:
                pair = canonical_pair(left, right)
                pair_scores[pair] += weight
                if len(pair_terms[pair]) < 12:
                    pair_terms[pair].add(term)
    selected = set()
    by_asset = defaultdict(list)
    for pair, score in pair_scores.items():
        by_asset[pair[0]].append((score, pair))
        by_asset[pair[1]].append((score, pair))
    for asset_id in fingerprints:
        for _, pair in sorted(by_asset[asset_id], key=lambda value: (-value[0], value[1]))[:top_k]:
            selected.add(pair)
    return [
        {"asset_a": pair[0], "asset_b": pair[1], "retrieval_score": round(pair_scores[pair], 3), "shared_terms": sorted(pair_terms[pair], key=lambda value: (-len(value), value))}
        for pair in sorted(selected)
    ], {"seconds": round(time.perf_counter() - started, 6), "posting_limit": posting_limit, "indexed_terms": len(index)}


def current_source_binding(target, source):
    prefix = f"guanlan://material/{source['asset_id']}/revision/"
    values = [str(value) for key, value in target["frontmatter"].items() if key.startswith("governance_reference") or key in {"source_reference", "manifest_reference"}]
    current = f"{prefix}{source['revision']}"
    return current in values or any(value.startswith(current) for value in values)


def structural_candidates(assets, registry, created_at):
    sources = {item["asset_id"]: item for item in assets if item["eligible"] and item["asset_class"] == "source"}
    output = []
    for target in assets:
        if not target["eligible"] or target["asset_class"] == "source":
            continue
        source = sources.get(str(target["frontmatter"].get("source_asset", "")))
        if not source:
            continue
        derivation_revision = str(target["frontmatter"].get("source_revision", ""))
        source_reference = str(target["frontmatter"].get("source_reference", ""))
        reference_match = source_reference.endswith(f"/{derivation_revision}") and source["asset_id"] in source_reference
        exact = derivation_revision == source["revision"]
        current_bound = exact or current_source_binding(target, source)
        if not derivation_revision or not reference_match or not current_bound:
            continue
        if relation_exists(registry, source["asset_id"], target["asset_id"], "source_of", "derived_from"):
            continue
        evidence = [
            {"kind": "stable_identity_match", "field": "source_asset", "value": source["asset_id"]},
            {"kind": "stable_reference_match", "field": "source_reference", "value": source_reference},
        ]
        if exact:
            evidence.append({"kind": "revision_match", "value": source["revision"]})
        else:
            evidence.extend([
                {"kind": "derivation_revision_match", "value": derivation_revision},
                {"kind": "current_source_revision_binding", "value": source["revision"]},
            ])
        candidate = make_candidate(
            source, target, "source_of", "strong", "high",
            "派生资产明确记录同一 Source material identity、派生时 revision 与稳定引用；当前正式 Source revision 也由治理引用绑定。该链接让读者可在事实原文与经确认知识加工结果之间往返核验。",
            evidence, "frontmatter.material_id + revision_id", "frontmatter.source_asset + source_revision + stable references",
        )
        candidate["created_at"] = created_at
        output.append(candidate)
    return output


def sentences(asset):
    return [part.strip() for part in SENTENCE_SPLIT.split(semantic_text(asset)) if len(part.strip()) >= 12]


def excerpt(asset, shared_terms, cue=None):
    ranked = []
    for sentence in sentences(asset):
        shared_count = sum(term in sentence.lower() for term in shared_terms)
        cue_hit = 1 if cue and cue.search(sentence) else 0
        if shared_count or cue_hit:
            ranked.append((cue_hit, shared_count, min(len(sentence), 240), sentence[:240]))
    return sorted(ranked, reverse=True)[0][3] if ranked else ""


def orient(left, right, relation_type):
    if relation_type == "applies":
        preferred = {"method", "creation", "intelligence"}
        if right["asset_class"] in preferred and left["asset_class"] not in preferred:
            return right, left
    if relation_type == "updates":
        if right["asset_class"] == "intelligence" and left["asset_class"] != "intelligence":
            return right, left
        left_dates, right_dates = DATE_RE.findall(semantic_text(left)), DATE_RE.findall(semantic_text(right))
        if right_dates and (not left_dates or max(right_dates) > max(left_dates)):
            return right, left
    if relation_type == "supports":
        if EVIDENCE_CUE.search(semantic_text(right)) and not EVIDENCE_CUE.search(semantic_text(left)):
            return right, left
    if relation_type == "extends":
        if SIGNALS["extends"].search(semantic_text(right)) and not SIGNALS["extends"].search(semantic_text(left)):
            return right, left
    return left, right


def deep_judge(left, right, retrieval, registry, created_at):
    # Automatic semantic Strong is intentionally limited to formal derived
    # assets. Source prose can contain relation-like words without asserting a
    # durable relation; provenance is handled separately by source_of.
    if left["asset_class"] == "source" or right["asset_class"] == "source":
        return "weak", None, "source_semantics_require_explicit_governed_signal"
    left_anchors, right_anchors = set(semantic_anchors(left)), set(semantic_anchors(right))
    shared = sorted(left_anchors & right_anchors, key=lambda value: (-len(value), value))[:8]
    left_text, right_text = semantic_text(left), semantic_text(right)
    explicit = []
    for relation_type, pattern in SIGNALS.items():
        if pattern.search(left_text) or pattern.search(right_text):
            explicit.append(relation_type)
    if "supports" in explicit and not ((EVIDENCE_CUE.search(left_text) and CLAIM_CUE.search(right_text)) or (EVIDENCE_CUE.search(right_text) and CLAIM_CUE.search(left_text))):
        explicit.remove("supports")
    if "updates" in explicit and not (left["asset_class"] == "intelligence" or right["asset_class"] == "intelligence"):
        explicit.remove("updates")
    if "applies" in explicit and not ({left["asset_class"], right["asset_class"]} & {"method", "creation", "intelligence"}):
        explicit.remove("applies")
    priority = ["updates", "applies", "contrasts_with", "extends", "supports"]
    relation_type = next((item for item in priority if item in explicit), "")
    if relation_type and shared:
        source, target = orient(left, right, relation_type)
        source_excerpt = excerpt(source, shared, SIGNALS[relation_type] if relation_type in SIGNALS else None)
        target_excerpt = excerpt(target, shared, CLAIM_CUE)
        shared_in_source = [value for value in shared if value in source_excerpt.lower()]
        shared_in_target = [value for value in shared if value in target_excerpt.lower()]
        pair_specific = set(shared_in_source) & set(shared_in_target)
        if source_excerpt and target_excerpt and pair_specific:
            why = {
                "extends": "扩展关系可让读者从基础论证继续到明确增加的机制或适用范围。",
                "supports": "支持关系可让读者从关键判断跳到直接证据、案例或论据。",
                "contrasts_with": "对照关系可让读者比较同一问题下不同假设、解释或结论。",
                "applies": "应用关系可让读者从框架或方法跳到其已发生的具体实践。",
                "updates": "更新关系可让读者从旧时效判断跳到新的事实或状态。",
            }[relation_type]
            evidence = [
                {"kind": "shared_semantic_object", "value": sorted(pair_specific)[:5]},
                {"kind": "source_excerpt", "path": source["relative_path"], "value": source_excerpt},
                {"kind": "target_excerpt", "path": target["relative_path"], "value": target_excerpt},
                {"kind": "link_usefulness", "value": why},
            ]
            candidate = make_candidate(source, target, relation_type, "strong", "high", f"共同语义对象：{'、'.join(sorted(pair_specific)[:5])}。{why}", evidence, "pair-specific excerpt", "pair-specific excerpt")
            candidate["created_at"] = created_at
            if relation_exists(registry, candidate["source_asset_id"], candidate["target_asset_id"], relation_type, candidate["reciprocal_relation"]):
                return "weak", None, "duplicate_existing_relation"
            return "strong", candidate, "explicit_pair_semantics"
    if len(shared) >= 2 and retrieval["retrieval_score"] >= 2.0:
        source_excerpt, target_excerpt = excerpt(left, shared), excerpt(right, shared)
        if source_excerpt and target_excerpt:
            candidate = make_candidate(
                left, right, "extends", "medium", "medium",
                f"双方围绕 {'、'.join(shared[:5])} 存在可复核交集，但当前无法唯一确定是扩展、支持还是对照；暂存观察，不投影正式关系。",
                [{"kind": "shared_semantic_object", "value": shared[:5]}, {"kind": "source_excerpt", "value": source_excerpt}, {"kind": "target_excerpt", "value": target_excerpt}],
                "candidate retrieval excerpt", "candidate retrieval excerpt",
            )
            candidate["created_at"] = created_at
            return "medium", candidate, "type_or_direction_uncertain"
    return "weak", None, "same_topic_keyword_or_entity_only"


def anti_overlink(strong, limit=6):
    structural = [item for item in strong if item["relation_type"] == "source_of"]
    semantic = [item for item in strong if item["relation_type"] != "source_of"]
    counts = Counter()
    kept, demoted = [], []
    for item in semantic:
        endpoints = (item["source_asset_id"], item["target_asset_id"])
        if any(counts[value] >= limit for value in endpoints):
            item["relation_strength"] = "medium"; item["confidence"] = "medium"
            item["rationale"] += " 因单轮 anti-overlinking 上限降入观察池。"
            demoted.append(item)
        else:
            kept.append(item)
            for value in endpoints:
                counts[value] += 1
    return structural + kept, demoted


def discover(assets, registry, created_at, top_k=12):
    eligible = [item for item in assets if item["eligible"]]
    fingerprints = build_fingerprints(eligible)
    retrieved, retrieval_stats = retrieve_pairs(fingerprints, top_k=top_k)
    by_id = {item["asset_id"]: item for item in eligible}
    structural = structural_candidates(assets, registry, created_at)
    structural_pairs = {canonical_pair(item["source_asset_id"], item["target_asset_id"]) for item in structural}
    strong, medium, weak = list(structural), [], []
    for item in retrieved:
        pair = canonical_pair(item["asset_a"], item["asset_b"])
        if pair in structural_pairs:
            continue
        classification, candidate, reason = deep_judge(by_id[item["asset_a"]], by_id[item["asset_b"]], item, registry, created_at)
        if classification == "strong": strong.append(candidate)
        elif classification == "medium": medium.append(candidate)
        else: weak.append({**item, "classification": "weak", "reason": reason})
    strong, demoted = anti_overlink(strong)
    medium.extend(demoted)
    return {
        "fingerprints": fingerprints, "retrieved_pairs": retrieved, "strong_candidates": strong,
        "medium_candidates": medium, "weak_candidates": weak,
        "retrieval_stats": retrieval_stats,
        "excluded_assets": [{"path": item["relative_path"], "reason": item["exclusion_reason"]} for item in assets if not item["eligible"]],
    }


def graph_metrics(registry, eligible_ids):
    edges = []
    for item in registry.get("relations", []):
        if item.get("approval_status") not in {"approved", "executed", "auto_executed"}:
            continue
        pair = (item.get("source_asset_id"), item.get("target_asset_id"))
        if pair[0] in eligible_ids and pair[1] in eligible_ids:
            edges.append(pair)
    adjacency = {value: set() for value in eligible_ids}
    for left, right in edges:
        if left == right: continue
        adjacency[left].add(right); adjacency[right].add(left)
    components, visited = 0, set()
    for node in adjacency:
        if node in visited: continue
        components += 1; stack = [node]
        while stack:
            current = stack.pop()
            if current in visited: continue
            visited.add(current); stack.extend(adjacency[current] - visited)
    degrees = [len(value) for value in adjacency.values()]
    average = round(sum(degrees) / len(degrees), 3) if degrees else 0
    return {"nodes": len(adjacency), "relations": len(edges), "isolated_nodes": sum(value == 0 for value in degrees), "connected_components": components, "average_semantic_degree": average, "max_degree": max(degrees, default=0), "abnormal_hub": max(degrees, default=0) >= max(6, len(adjacency) * 0.6)}


def rebase_candidate(candidate, assets):
    endpoint = {item["asset_id"]: item for item in assets if item["eligible"]}
    source, target = endpoint[candidate["source_asset_id"]], endpoint[candidate["target_asset_id"]]
    candidate = dict(candidate)
    candidate["source_revision"], candidate["target_revision"] = current_revision(source), current_revision(target)
    candidate["source_snapshot_hash"], candidate["target_snapshot_hash"] = source["file_hash"], target["file_hash"]
    candidate["candidate_id"] = candidate_id(source["asset_id"], candidate["source_revision"], target["asset_id"], candidate["target_revision"], candidate["relation_type"])
    return candidate, source, target


def rollback_applied(receipts):
    results = []
    with tempfile.TemporaryDirectory(prefix="guanlan-relation-rollback.") as temp:
        for receipt_path in reversed(receipts):
            receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
            confirmation = Path(temp) / (receipt["candidate_id"] + ".json")
            output = Path(temp) / (receipt["candidate_id"] + ".result.json")
            atomic_json(confirmation, {"confirmed": True, "candidate_id": receipt["candidate_id"]})
            results.append(rollback(receipt_path, confirmation, output))
    return results


def curate(vault: Path, asset_root: Path, output: Path, execute_writes=False, top_k=12):
    created_at = utc_now(); stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    relation_root = asset_root / "relations"
    registry_path = relation_root / "relation-registry-v1.json"
    observation_path = relation_root / "relation-observation-pool-v1.json"
    receipt_root = relation_root / "receipts"
    rollback_root = asset_root / "rollback" / "relation-curation"
    run_root = relation_root / "runs"
    graph_path = vault / ".obsidian" / "graph.json"
    registry_before_bytes = registry_path.read_bytes(); registry = json.loads(registry_before_bytes)
    validate_registry(registry)
    pool_before_bytes = observation_path.read_bytes() if observation_path.exists() else b""
    assets_before = scan_vault(str(vault)); eligible = [item for item in assets_before if item["eligible"]]
    eligible_ids = {item["asset_id"] for item in eligible}
    before_metrics = graph_metrics(registry, eligible_ids)
    discovery = discover(assets_before, registry, created_at, top_k=top_k)
    run_id = "relation_run_sha256_" + sha256_bytes((created_at + "|" + file_hash(registry_path)).encode("utf-8"))
    run_rollback_root = rollback_root / run_id
    pool_backup_path = run_rollback_root / "observation-pool.before.json"
    if execute_writes:
        run_rollback_root.mkdir(parents=True, exist_ok=False)
        if pool_before_bytes:
            from relation_common import atomic_write
            atomic_write(pool_backup_path, pool_before_bytes)
    preflight = {
        "registry_hash": file_hash(registry_path), "graph_config_hash": file_hash(graph_path),
        "eligible_markdown_hashes": {item["relative_path"]: item["file_hash"] for item in eligible},
    }
    receipts, applied = [], []
    pool_after_hash = file_hash(observation_path)
    try:
        if execute_writes:
            for candidate in discovery["strong_candidates"]:
                current_registry = json.loads(registry_path.read_text(encoding="utf-8"))
                if relation_exists(current_registry, candidate["source_asset_id"], candidate["target_asset_id"], candidate["relation_type"], candidate["reciprocal_relation"]):
                    continue
                candidate, source, target = rebase_candidate(candidate, scan_vault(str(vault)))
                receipt_path = receipt_root / f"{stamp}_{candidate['candidate_id']}.json"
                receipt = execute(candidate, source, target, registry_path, None, rollback_root, receipt_path, auto=True)
                receipts.append(str(receipt_path)); applied.append({"candidate": candidate, "receipt": receipt})
            reconcile_observations(observation_path, discovery["medium_candidates"], discovery["strong_candidates"], created_at)
            pool_after_hash = file_hash(observation_path)
        registry_after = json.loads(registry_path.read_text(encoding="utf-8"))
        validate_registry(registry_after)
        assets_after, checks, exceptions, repairs = audit_registry_markdown(vault, registry_after, receipt_root)
        post_eligible = [item for item in assets_after if item["eligible"]]
        after_metrics = graph_metrics(registry_after, {item["asset_id"] for item in post_eligible})
        result = {
            "protocol": "relation-curation-run-v1", "schema_version": "1.0.0", "run_id": run_id,
            "created_at": created_at, "mode": "execute" if execute_writes else "dry_run", "model_identity": "model_identity_unverifiable",
            "scan_scope": list(("10 原始资料", "20 学习笔记", "30 情报简报", "40 方法库", "50 输出成果")),
            "excluded_scope": ["00 收件箱", "90 系统", ".obsidian", "templates", "rollback", "cache", "fixtures", "temporary outputs"],
            "preflight": preflight,
            "summary": {
                "markdown_scanned": len(assets_before), "eligible_markdown": len(eligible), "fingerprints": len(discovery["fingerprints"]),
                "candidate_pairs": len(discovery["retrieved_pairs"]), "deep_judged_pairs": len(discovery["retrieved_pairs"]),
                "strong": len(discovery["strong_candidates"]), "medium": len(discovery["medium_candidates"]), "weak": len(discovery["weak_candidates"]),
                "relations_applied": len(applied), "existing_relations_before": before_metrics["relations"],
                "broken_relations": sum(item["status"] not in {"healthy", "verified"} for item in checks),
            },
            "strong_candidates": discovery["strong_candidates"], "medium_candidates": discovery["medium_candidates"],
            "weak_statistics": Counter(item["reason"] for item in discovery["weak_candidates"]),
            "excluded_assets": discovery["excluded_assets"], "applied": applied,
            "integrity": {"checks": checks, "exceptions": exceptions, "repair_candidates": repairs},
            "graph_before": before_metrics, "graph_after": after_metrics,
            "performance": {"candidate_retrieval": discovery["retrieval_stats"], "algorithm": "bounded_inverted_index_top_k_then_deep_judgment", "full_n_squared_deep_judgment": False},
            "rollback": {"supported": True, "receipt_paths": receipts, "registry_pre_hash": preflight["registry_hash"], "observation_pool_path": str(observation_path), "observation_pool_backup": str(pool_backup_path) if pool_before_bytes else "", "observation_pool_pre_hash": "sha256:" + sha256_bytes(pool_before_bytes) if pool_before_bytes else "missing", "observation_pool_post_hash": pool_after_hash},
        }
        # Counter is not JSON serializable as a distinct type on all runtimes.
        result["weak_statistics"] = dict(result["weak_statistics"])
        if execute_writes:
            run_root.mkdir(parents=True, exist_ok=True)
            persistent = run_root / f"{run_id}.json"
            atomic_json(persistent, result)
            result["persistent_run_record"] = str(persistent)
            atomic_json(persistent, result)
        atomic_json(output, result)
        return result
    except Exception:
        if receipts:
            rollback_applied(receipts)
        if pool_before_bytes:
            from relation_common import atomic_write
            atomic_write(observation_path, pool_before_bytes)
        raise


def rollback_run(run_record: Path, confirmation: Path, output: Path):
    run = json.loads(run_record.read_text(encoding="utf-8")); approval = json.loads(confirmation.read_text(encoding="utf-8"))
    if not approval.get("confirmed") or approval.get("run_id") != run.get("run_id"):
        raise ValueError("matching relation run rollback confirmation is required")
    rollback_info = run.get("rollback", {})
    pool_path = Path(rollback_info.get("observation_pool_path", ""))
    pool_backup = Path(rollback_info.get("observation_pool_backup", ""))
    expected_pool_hash = rollback_info.get("observation_pool_post_hash")
    if pool_path.is_file() and expected_pool_hash and file_hash(pool_path) != expected_pool_hash:
        raise ValueError("observation pool rollback hash guard failed")
    receipts = rollback_info.get("receipt_paths", [])
    results = rollback_applied(receipts)
    if pool_backup.is_file():
        from relation_common import atomic_write
        atomic_write(pool_path, pool_backup.read_bytes())
    result = {"status": "rolled_back", "run_id": run["run_id"], "relations_rolled_back": len(results), "permanent_deletion": False}
    atomic_json(output, result); return result


def main():
    parser = argparse.ArgumentParser(description="User command: 整理关系图谱")
    parser.add_argument("--command", choices=("curate", "rollback"), default="curate")
    parser.add_argument("--vault"); parser.add_argument("--asset-root"); parser.add_argument("--output", required=True)
    parser.add_argument("--execute", action="store_true"); parser.add_argument("--top-k", type=int, default=12)
    parser.add_argument("--run-record"); parser.add_argument("--rollback-confirmation")
    args = parser.parse_args()
    operation = None
    try:
        if args.command == "rollback":
            if not args.run_record or not args.rollback_confirmation: raise ValueError("rollback requires run-record and rollback-confirmation")
            result = rollback_run(Path(args.run_record), Path(args.rollback_confirmation), Path(args.output))
        else:
            if not args.vault or not args.asset_root: raise ValueError("curate requires vault and asset-root")
            operation = OperationRecorder(Path(args.asset_root).resolve() / "operations", "relation_curation",
                                          input_refs=["guanlan://relation-registry/v1"])
            result = curate(Path(args.vault).resolve(), Path(args.asset_root).resolve(), Path(args.output), args.execute, max(1, args.top_k))
            run_ref = f"guanlan://relation-run/{result['run_id']}"
            receipt_refs = []
            for receipt_path in result.get("rollback", {}).get("receipt_paths", []):
                try:
                    receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
                    receipt_id = receipt.get("receipt_id") or receipt.get("candidate_id")
                    if receipt_id: receipt_refs.append(f"guanlan://receipt/{receipt_id}")
                except (OSError, json.JSONDecodeError): pass
            warning = operation.finish("completed", output_refs=[run_ref, "guanlan://relation-registry/v1"],
                                       receipt_refs=receipt_refs,
                                       change_refs=["guanlan://relation-registry/v1"] if args.execute else [])
            result["operation_id"] = operation.operation_id
            if warning: result["operation_index_warning"] = warning
            atomic_json(Path(args.output), result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        if operation is not None: operation.finish("failed", failure_class="relation_curation_failed", failure_detail=str(error))
        raise SystemExit(f"ERROR: {error}") from error


if __name__ == "__main__":
    main()
