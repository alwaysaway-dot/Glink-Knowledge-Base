#!/usr/bin/env python3
"""Regression matrix for full-vault Relation Graph Curation."""

from __future__ import annotations

import json
import sys
import tempfile
import tracemalloc
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "knowledge-relation-manager"))

import relation_common
import relation_curation
import relation_registry
from relation_apply import auto_apply_gate, execute, has_conflicting_relation
from relation_governance import audit_registry_markdown, normalize_nonsemantic_projection


def ident(prefix, char): return prefix + char * 64


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text, encoding="utf-8")


def fm(asset_type, status, identity, revision, graph_group, extra=""):
    key = "material_id" if asset_type == "source_asset" else "asset_id"
    return f"---\ntype: {asset_type}\nstatus: {status}\n{key}: {identity}\nrevision_id: {revision}\nasset_class: {'source' if asset_type == 'source_asset' else 'knowledge'}\ngraph_group: {graph_group}\n{extra}---\n"


def registry():
    return {"protocol": "relation-registry-v1", "schema_version": "1.0.0", "registry_id": "test", "relations": [], "updated_at": ""}


def candidate_asset(char, asset_class, text, title=None):
    return {
        "asset_id": ident("asset_sha256_", char), "revision": ident("revision_sha256_", char),
        "file_hash": "sha256:" + char * 64, "asset_class": asset_class, "title": title or char,
        "relative_path": f"20 学习笔记/{char}.md", "absolute_path": f"/tmp/{char}.md", "frontmatter": {},
        "sections": {"正文": text}, "body": text, "eligible": True, "exclusion_reason": "",
    }


class RelationCurationTests(unittest.TestCase):
    def vault_fixture(self, root):
        vault = Path(root) / "vault"
        for name in list(relation_common.SCAN_DIRECTORIES) + ["00 收件箱", "90 系统"]:
            (vault / name).mkdir(parents=True, exist_ok=True)
        material, old_revision, current_revision = ident("material_sha256_", "a"), ident("revision_sha256_", "b"), ident("revision_sha256_", "c")
        knowledge, knowledge_revision = ident("asset_sha256_", "d"), ident("revision_sha256_", "e")
        write(vault / "10 原始资料/source.md", fm("source_asset", "confirmed", material, current_revision, "10_source") + "# Source\n\n事实。\n")
        extra = f"source_asset: {material}\nsource_revision: {old_revision}\nsource_reference: guanlan://material/{material}/revision/{old_revision}\ngovernance_reference_2: guanlan://material/{material}/revision/{current_revision}\n"
        write(vault / "20 学习笔记/learning.md", fm("learning_note", "published", knowledge, knowledge_revision, "20_learning", extra) + "# Learning\n\n## 核心主张\n\n结构化知识。\n")
        for folder, char, asset_type, group in (("30 情报简报", "f", "intelligence_brief", "30_brief"), ("40 方法库", "1", "method_asset", "40_method"), ("50 输出成果", "2", "creation_asset", "50_creation")):
            write(vault / folder / f"{char}.md", fm(asset_type, "published", ident("asset_sha256_", char), ident("revision_sha256_", char), group) + f"# {folder}\n")
        write(vault / "00 收件箱/pending.md", fm("source_asset", "waiting_user_confirmation", ident("material_sha256_", "3"), ident("revision_sha256_", "3"), "00_inbox") + "# pending\n")
        write(vault / "90 系统/system.md", "# system\n")
        return vault, material, knowledge

    def test_T01_T03_scope_excludes_00_90_and_includes_formal_directories(self):
        with tempfile.TemporaryDirectory() as temp:
            vault, _, _ = self.vault_fixture(temp); assets = relation_common.scan_vault(str(vault))
            self.assertEqual({a["asset_class"] for a in assets if a["eligible"]}, {"source", "knowledge", "intelligence", "method", "creation"})
            self.assertFalse(any(a["relative_path"].startswith(("00 ", "90 ")) for a in assets))

    def test_T04_T05_provenance_dedup_and_revision_reconciliation(self):
        with tempfile.TemporaryDirectory() as temp:
            vault, material, knowledge = self.vault_fixture(temp); assets = relation_common.scan_vault(str(vault))
            found = relation_curation.structural_candidates(assets, registry(), "2026-09-16T00:00:00Z")
            self.assertEqual(len(found), 1); self.assertEqual(found[0]["source_asset_id"], material); self.assertEqual(found[0]["target_asset_id"], knowledge)
            reg = registry(); reg["relations"].append({"relation_id": "r", "source_asset_id": material, "source_revision": found[0]["source_revision"], "target_asset_id": knowledge, "target_revision": found[0]["target_revision"], "relation_type": "source_of", "reciprocal_relation": "derived_from", "approval_status": "executed"})
            self.assertEqual(relation_curation.structural_candidates(assets, reg, "2026-09-16T00:00:00Z"), [])

    def judge(self, relation_type, source_class="knowledge", target_class="knowledge"):
        anchor = {"extends": "债务传导框架", "supports": "风险纪律", "contrasts_with": "增长模型", "applies": "风险检查法", "updates": "市场状态"}[relation_type]
        source_sentence = {
            "extends": f"在 **{anchor}** 基础上进一步扩展适用条件。",
            "supports": f"案例证据直接支持 **{anchor}** 的核心判断。",
            "contrasts_with": f"与 **{anchor}** 的旧解释相反，本资产给出不同结论。",
            "applies": f"本方案实际应用 **{anchor}** 方法完成检查。",
            "updates": f"截至2026-09，更新 **{anchor}** 的当前状态。",
        }[relation_type]
        target_sentence = f"核心主张：**{anchor}** 用于解释同一明确问题。"
        left, right = candidate_asset("a", source_class, source_sentence), candidate_asset("b", target_class, target_sentence)
        retrieval = {"shared_terms": [anchor], "retrieval_score": 9.0}
        return relation_curation.deep_judge(left, right, retrieval, registry(), "2026-09-16T00:00:00Z")

    def test_T06_T08_same_topic_keyword_entity_are_weak(self):
        left = candidate_asset("a", "knowledge", "同主题 人工智能 张三")
        right = candidate_asset("b", "knowledge", "同主题 人工智能 张三")
        result = relation_curation.deep_judge(left, right, {"shared_terms": ["人工智能", "张三"], "retrieval_score": 8}, registry(), "now")
        self.assertEqual(result[0], "weak")

    def test_T09_T13_explicit_relation_types_are_strong(self):
        for relation_type, classes in (("extends", ("knowledge", "knowledge")), ("supports", ("knowledge", "knowledge")), ("contrasts_with", ("knowledge", "knowledge")), ("applies", ("creation", "knowledge")), ("updates", ("intelligence", "intelligence"))):
            with self.subTest(relation_type=relation_type):
                status, candidate, _ = self.judge(relation_type, *classes)
                self.assertEqual(status, "strong"); self.assertEqual(candidate["relation_type"], relation_type)

    def test_T14_T16_direction_symmetry_and_single_canonical_record(self):
        _, applies, _ = self.judge("applies", "creation", "knowledge")
        self.assertEqual(applies["reciprocal_relation"], "applied_by"); self.assertEqual(applies["directionality"], "directed")
        _, contrast, _ = self.judge("contrasts_with")
        self.assertEqual(contrast["reciprocal_relation"], "contrasts_with"); self.assertEqual(contrast["directionality"], "symmetric")
        reg = registry(); reg["relations"].append({"relation_id": "r1", "source_asset_id": contrast["source_asset_id"], "source_revision": contrast["source_revision"], "target_asset_id": contrast["target_asset_id"], "target_revision": contrast["target_revision"], "relation_type": "contrasts_with", "reciprocal_relation": "contrasts_with", "approval_status": "executed"})
        self.assertEqual(relation_registry.validate(reg)["relation_count"], 1)

    def test_T17_T23_projection_is_reversible_nonsemantic_and_identity_stable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); vault, _, _ = self.vault_fixture(temp); assets = relation_common.scan_vault(str(vault)); reg = registry(); reg_path = root / "registry.json"; relation_common.atomic_json(reg_path, reg)
            candidate = relation_curation.structural_candidates(assets, reg, "2026-09-16T00:00:00Z")[0]
            source = next(a for a in assets if a["asset_id"] == candidate["source_asset_id"]); target = next(a for a in assets if a["asset_id"] == candidate["target_asset_id"])
            source_before, target_before = Path(source["absolute_path"]).read_text(), Path(target["absolute_path"]).read_text(); source_id, target_id = source["asset_id"], target["asset_id"]
            receipt = execute(candidate, source, target, reg_path, None, root / "rollback", root / "receipt.json", auto=True)
            self.assertIn("[[learning]]", Path(source["absolute_path"]).read_text()); self.assertIn("[[source]]", Path(target["absolute_path"]).read_text())
            self.assertEqual(normalize_nonsemantic_projection(Path(source["absolute_path"]).read_text(), candidate["candidate_id"]), normalize_nonsemantic_projection(source_before, candidate["candidate_id"]))
            after = relation_common.scan_vault(str(vault)); self.assertEqual(source_id, next(a for a in after if a["asset_class"] == "source")["asset_id"]); self.assertEqual(target_id, next(a for a in after if a["asset_class"] == "knowledge")["asset_id"])
            self.assertEqual(len(json.loads(reg_path.read_text())["relations"]), 1); self.assertTrue(receipt["backup_directory"])

    def test_T18_T19_medium_and_weak_do_not_project(self):
        left = candidate_asset("a", "knowledge", "**框架甲** 与 **框架乙** 的说明")
        right = candidate_asset("b", "knowledge", "**框架甲** 与 **框架乙** 的另一说明")
        status, candidate, _ = relation_curation.deep_judge(left, right, {"shared_terms": ["框架甲", "框架乙"], "retrieval_score": 5}, registry(), "now")
        self.assertEqual(status, "medium"); self.assertEqual(candidate["decision_status"], "suggested")
        self.assertEqual(self.judge("extends")[1]["decision_status"], "suggested")

    def test_T20_repeat_run_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); vault, _, _ = self.vault_fixture(temp); asset_root = root / "assets"; relation_root = asset_root / "relations"; relation_root.mkdir(parents=True)
            relation_common.atomic_json(relation_root / "relation-registry-v1.json", registry()); relation_common.atomic_json(relation_root / "relation-observation-pool-v1.json", {"protocol": "relation-observation-pool-v1", "schema_version": "1.0.0", "observations": [], "updated_at": ""})
            first = relation_curation.curate(vault, asset_root, root / "first.json", True); second = relation_curation.curate(vault, asset_root, root / "second.json", True)
            self.assertEqual(first["summary"]["relations_applied"], 1); self.assertEqual(second["summary"]["relations_applied"], 0); self.assertEqual(len(json.loads((relation_root / "relation-registry-v1.json").read_text())["relations"]), 1)
            confirmation = root / "rollback-confirmation.json"; relation_common.atomic_json(confirmation, {"confirmed": True, "run_id": first["run_id"]})
            rolled_back = relation_curation.rollback_run(Path(first["persistent_run_record"]), confirmation, root / "rollback-result.json")
            self.assertEqual(rolled_back["relations_rolled_back"], 1); self.assertEqual(json.loads((relation_root / "relation-registry-v1.json").read_text())["relations"], [])

    def test_T24_T27_broken_self_duplicate_conflict_detection(self):
        bad = registry(); eid = ident("asset_sha256_", "a"); rev = ident("revision_sha256_", "b")
        bad["relations"].append({"relation_id": "r", "source_asset_id": eid, "source_revision": rev, "target_asset_id": eid, "target_revision": rev, "relation_type": "extends", "reciprocal_relation": "extended_by", "approval_status": "executed"})
        with self.assertRaisesRegex(ValueError, "self relation"): relation_registry.validate(bad)
        _, candidate, _ = self.judge("extends"); reg = registry(); reg["relations"].append({"relation_id": "r", "source_asset_id": candidate["source_asset_id"], "source_revision": candidate["source_revision"], "target_asset_id": candidate["target_asset_id"], "target_revision": candidate["target_revision"], "relation_type": "supports", "reciprocal_relation": "supported_by", "approval_status": "executed"})
        self.assertTrue(has_conflicting_relation(reg, candidate))

    def test_T28_T30_hub_overlink_and_same_domain_protection(self):
        ids = {ident("asset_sha256_", char) for char in "abcdefg"}; reg = registry(); center = sorted(ids)[0]
        for index, target in enumerate(sorted(ids - {center})):
            reg["relations"].append({"relation_id": f"r{index}", "source_asset_id": center, "target_asset_id": target, "approval_status": "executed"})
        self.assertTrue(relation_curation.graph_metrics(reg, ids)["abnormal_hub"])
        left = candidate_asset("a", "knowledge", "政治经济 债务 资本", "宏观经济转型")
        right = candidate_asset("b", "knowledge", "政治经济 债务 资本", "资本积累与制度动员")
        self.assertNotEqual(relation_curation.deep_judge(left, right, {"shared_terms": ["政治经济", "债务", "资本"], "retrieval_score": 9}, registry(), "now")[0], "strong")
        candidates = [dict(self.judge("extends")[1], source_asset_id=center, target_asset_id=value) for value in sorted(ids - {center})]
        kept, demoted = relation_curation.anti_overlink(candidates, limit=3); self.assertEqual(len(kept), 3); self.assertEqual(len(demoted), 3)

    def test_T31_T33_bounded_retrieval_scale(self):
        for count in (10, 50, 100, 500, 1000):
            fps = {}
            for index in range(count):
                asset_id = ident("asset_sha256_", format(index % 16, "x")) + str(index)  # synthetic key need not validate
                fps[asset_id] = {"terms": [f"group-{index // 10}", f"unique-{index}"]}
            tracemalloc.start(); pairs, stats = relation_curation.retrieve_pairs(fps, top_k=8); _, peak = tracemalloc.get_traced_memory(); tracemalloc.stop()
            self.assertLessEqual(len(pairs), count * 8); self.assertLess(peak, 80 * 1024 * 1024); self.assertGreaterEqual(stats["seconds"], 0)

    def test_T34_T35_graph_metadata_unchanged_and_registry_canonical(self):
        with tempfile.TemporaryDirectory() as temp:
            vault, _, _ = self.vault_fixture(temp); before = {a["relative_path"]: a["frontmatter"].get("graph_group") for a in relation_common.scan_vault(str(vault))}
            after = {a["relative_path"]: a["frontmatter"].get("graph_group") for a in relation_common.scan_vault(str(vault))}
            self.assertEqual(before, after); self.assertFalse(relation_registry.validate(registry())["markdown_is_authority"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
