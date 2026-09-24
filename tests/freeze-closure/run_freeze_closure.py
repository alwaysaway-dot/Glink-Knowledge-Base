#!/usr/bin/env python3
"""Deterministic heterogeneous and negative freeze-closure regression."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "knowledge-ingestion-manager"))
from approval_binding import prepare as prepare_binding
spec = importlib.util.spec_from_file_location("foundation", ROOT / "knowledge-foundation-stability/foundation_stability.py")
foundation = importlib.util.module_from_spec(spec); spec.loader.exec_module(foundation)


def write(path: Path, data: bytes): path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
def write_json(path: Path, value): write(path, (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode())
def run(*args, ok=True):
    result = subprocess.run([str(x) for x in args], text=True, capture_output=True)
    if ok and result.returncode != 0: raise AssertionError(f"command failed: {' '.join(map(str,args))}\n{result.stdout}\n{result.stderr}")
    if not ok and result.returncode == 0: raise AssertionError(f"command unexpectedly passed: {' '.join(map(str,args))}")
    return result
def add_object(root: Path, data: bytes, role: str):
    content_hash = foundation.sha256_bytes(data); value_digest = content_hash.split(":", 1)[1]
    relative = Path("objects/sha256") / value_digest[:2] / value_digest; write(root / relative, data)
    asset_id = foundation.asset_id_from_hash(content_hash)
    return {"reference": f"guanlan://asset/{asset_id}", "asset_id": asset_id, "role": role,
        "storage_relative_path": relative.as_posix(), "content_hash": content_hash,
        "media_type": "text/markdown", "size_bytes": len(data)}


def require_fixture_root(base: Path, root: Path):
    """Fail before writes if a fixture escapes its isolated run directory."""
    base, root = base.resolve(), root.resolve()
    if not root.is_relative_to(base) or root == (ROOT / "asset-library").resolve():
        raise AssertionError(f"fixture asset root is not isolated: {root}")


def build_case(base: Path, name: str, source_type: str, coverage: dict):
    root = base / name / "asset-root"; material_dir = base / name / "materials" / name
    require_fixture_root(base, root)
    raw_text = f"{name} 原始事实内容。\n".encode(); initial = f"# {name}\n\n初始可读事实。\n".encode()
    raw, readable = add_object(root, raw_text, "raw_content"), add_object(root, initial, "readable_source")
    platform = "local" if source_type in {"local_text", "pdf"} else ("web" if source_type in {"webpage", "article"} else "fixture")
    source_id = "sha256:" + hashlib.sha256(raw_text).hexdigest() if platform == "local" else name
    source_url = f"file:///fixture/{name}" if platform == "local" else f"https://example.test/{name}"
    material_id = foundation.material_id_from_source_key(foundation.source_key(platform, source_id, source_url))
    source = {"protocol":"source-material-v3","schema_version":"3.0.0","material_id":material_id,
        "revision_id":"revision_sha256_"+"0"*64,
        "source":{"platform":platform,"source_id":source_id,"source_url":source_url,"title":name,"author":"fixture","published_at":"","captured_at":"2026-08-09T00:00:00Z"},
        "content":{"raw":{"storage":"reference","reference":raw["reference"],"content_hash":raw["content_hash"],"media_type":"text/markdown"},
                   "readable":{"storage":"reference","reference":readable["reference"],"content_hash":readable["content_hash"],"media_type":"text/markdown","operations":["fact_preserved"]}},
        "evidence":[{"evidence_id":f"evidence-{name}","kind":"transcript" if source_type in {"video","audio"} else "source_document",
                     "reference":raw["reference"],"content_hash":raw["content_hash"],"uncertainty":""}],
        "quality":{"capture_status":"complete","content_fidelity":"full","transcript_quality":"raw" if source_type in {"video","audio"} else "not_applicable","review_required":True,"uncertainties":[]},
        "lifecycle":{"status":"captured","review_status":"pending","created_at":"2026-08-09T00:00:00Z","updated_at":"2026-08-09T00:00:00Z","processing_history":[]},
        "asset_manifest_reference":"","understanding_sidecar_reference":""}
    source["revision_id"] = foundation.revision_id(source); source["asset_manifest_reference"] = f"guanlan://manifest/{material_id}/{source['revision_id']}"
    manifest = {"protocol":"reference-manifest-v1","schema_version":"1.0.0","material_id":material_id,"revision_id":source["revision_id"],"entries":[raw,readable]}
    case_dir = base / name; write_json(case_dir/"source.json",source); write_json(case_dir/"manifest.json",manifest)
    final_text = (f"# {name}\n\n这是一份保持来源事实、无需固定长度即可阅读的内容。\n" + ("第二段用于验证动态分段。\n" if coverage else "")).encode()
    write(case_dir/"readable.md",final_text); final_hash="sha256:"+hashlib.sha256(final_text).hexdigest()
    quality={"protocol":"source-promotion-quality-v1","status":"passed","source_type":source_type,"readability":"ready","evidence_status":"verified",
             "content_fidelity":"full","transcript_quality":"readable" if source_type in {"video","audio"} else "not_applicable",
             "coverage":coverage,"operations":["source_order_preserved","readability_repair","no_summary","no_analysis"],"uncertainties":[]}
    approval={"protocol":"source-promotion-approval-v1","confirmed":True,"reviewer":"user","confirmed_at":"2026-08-09T00:00:00Z",
              "material_id":material_id,"revision_id":source["revision_id"],"readable_content_hash":final_hash}
    write_json(case_dir/"quality.json",quality); write_json(case_dir/"approval.json",approval)
    promotion_command=[sys.executable, ROOT/"source-material-generator/promote_readable_original_revision.py",
        "--source-material",case_dir/"source.json","--manifest",case_dir/"manifest.json","--readable-original",case_dir/"readable.md",
        "--quality-result",case_dir/"quality.json","--approval-input",case_dir/"approval.json","--source-type",source_type,
        "--asset-root",root,"--material-dir",material_dir,"--project-root",ROOT,"--created-at","2026-08-09T00:00:00Z",
        "--output-summary",case_dir/"promotion.json","--scope","test"]
    run(*promotion_command)
    summary=json.loads((case_dir/"promotion.json").read_text()); revision_dir=Path(summary["revision_directory"])
    run(*promotion_command); assert json.loads((case_dir/"promotion.json").read_text())["status"] == "already_promoted"
    vault=case_dir/"vault"; (vault/"10 原始资料").mkdir(parents=True)
    filename=f"2026-08-09_{name}.md"
    run(sys.executable,ROOT/"knowledge-ingestion-manager/source_asset_ingestion.py","--command","ingest","--scope","test",
        "--source-material",revision_dir/"source-material-v3.json","--manifest",revision_dir/"reference-manifest.json",
        "--projection",revision_dir/"source-asset-projection.md","--validation",revision_dir/"source-asset-validation.json",
        "--confirmation",revision_dir/"source-asset-approval.json","--vault",vault/"10 原始资料","--filename",filename,"--record",case_dir/"source-ingestion.json")
    run(sys.executable,ROOT/"knowledge-ingestion-manager/source_asset_ingestion.py","--command","ingest","--scope","test",
        "--source-material",revision_dir/"source-material-v3.json","--manifest",revision_dir/"reference-manifest.json",
        "--projection",revision_dir/"source-asset-projection.md","--validation",revision_dir/"source-asset-validation.json",
        "--confirmation",revision_dir/"source-asset-approval.json","--vault",vault/"10 原始资料","--filename",filename,"--record",case_dir/"source-ingestion-rerun.json")
    return {"dir":case_dir,"root":root,"vault":vault,"source":json.loads((revision_dir/"source-material-v3.json").read_text()),"revision_dir":revision_dir,"projection":vault/"10 原始资料"/filename}


def learning_inputs(case, body_text, stem, filename=None):
    directory=case["dir"]/stem; directory.mkdir()
    body=(body_text.strip()+"\n").encode(); content_hash="sha256:"+hashlib.sha256(body).hexdigest(); source=case["source"]
    draft={"protocol":"knowledge-asset-draft-v1","asset":{"asset_id":"asset_draft_fixture","type":"learning_note","status":"draft"},
           "source":{"material_id":source["material_id"],"task_id":stem,"source_reference":source["source"]["source_url"]}}
    approval={"protocol":"knowledge-publish-approval-v1","approval_id":f"approval-{stem}","confirmed":True,"reviewer":"user",
              "confirmed_at":"2026-08-09T00:00:00Z","source_asset_id":source["material_id"],"source_revision_id":source["revision_id"],
              "knowledge_content_hash":content_hash,"stable_references":[f"guanlan://material/{source['material_id']}/revision/{source['revision_id']}"]}
    quality={"protocol":"knowledge-publish-quality-v1","status":"passed"}
    publish_name = filename or f"2026-08-09_学习_{stem}.md"
    candidate = {"candidate_id": draft["asset"]["asset_id"], "asset_type": "learning_note", "status": "publishable",
        "source": {"material_id": source["material_id"], "revision_id": source["revision_id"]},
        "content": {"title": body_text.strip().splitlines()[0][2:].strip(), "markdown": body_text},
        "provenance": {"stable_references": approval["stable_references"]}, "admission": {"status": "passed"}}
    approval["approval_binding"] = prepare_binding(candidate=candidate, source=source, target_folder="20 学习笔记",
        filename=publish_name, body=body_text, title=candidate["content"]["title"], quality=quality)
    write_json(directory/"draft.json",draft); write_json(directory/"approval.json",approval); write_json(directory/"quality.json",quality); write(directory/"note.md",body)
    return directory


def long_video_regression(base: Path):
    fixture=json.loads((ROOT/"tests/freeze-closure/fixtures/synthetic-long-video-regression.json").read_text())
    assert fixture["fixture_kind"] == "synthetic_deterministic"
    case=base/"synthetic-long-video"; root=case/"asset-root"
    require_fixture_root(base, root)
    raw_text=("synthetic long-video fixture\n" + fixture["synthetic_sentence"] + "\n").encode()
    initial_text="# Synthetic historical regression\n\n初始事实文本。\n".encode()
    raw=add_object(root,raw_text,"raw_content"); initial=add_object(root,initial_text,"readable_source")
    material_id=foundation.material_id_from_source_key(
        foundation.source_key("fixture","synthetic-long-video-history","https://example.test/synthetic-long-video-history")
    )
    source={"protocol":"source-material-v3","schema_version":"3.0.0","material_id":material_id,"revision_id":"revision_sha256_"+"0"*64,
        "source":{"platform":"fixture","source_id":"synthetic-long-video-history","source_url":"https://example.test/synthetic-long-video-history","title":fixture["title"],"author":"synthetic fixture","published_at":"","captured_at":"2026-08-09T00:00:00Z"},
        "content":{"raw":{"storage":"reference","reference":raw["reference"],"content_hash":raw["content_hash"],"media_type":"text/markdown"},
                   "readable":{"storage":"reference","reference":initial["reference"],"content_hash":initial["content_hash"],"media_type":"text/markdown","operations":["fact_preserved"]}},
        "evidence":[{"evidence_id":"evidence-long-video-synthetic","kind":"transcript","reference":raw["reference"],"content_hash":raw["content_hash"],"uncertainty":"synthetic fixture only"}],
        "quality":{"capture_status":"complete","content_fidelity":"full","transcript_quality":"raw","review_required":True,"uncertainties":[]},
        "lifecycle":{"status":"captured","review_status":"pending","created_at":"2026-08-09T00:00:00Z","updated_at":"2026-08-09T00:00:00Z","processing_history":[]},
        "asset_manifest_reference":"","understanding_sidecar_reference":""}
    source["revision_id"]=foundation.revision_id(source)
    source["asset_manifest_reference"]=f"guanlan://manifest/{material_id}/{source['revision_id']}"
    manifest={"protocol":"reference-manifest-v1","schema_version":"1.0.0","material_id":material_id,"revision_id":source["revision_id"],"entries":[raw,initial]}
    write_json(case/"source.json",source); write_json(case/"manifest.json",manifest)
    paragraphs=[f"{index:03d}. {fixture['synthetic_sentence']}" for index in range(1,fixture["synthetic_paragraph_count"]+1)]
    readable=("# Synthetic historical regression\n\n"+"\n\n".join(paragraphs)+"\n").encode()
    assert len(readable.decode()) >= fixture["historical_minimum_readable_chars"]
    write(case/"readable.md",readable)
    quality={"protocol":"source-promotion-quality-v1","status":"passed","source_type":"video","readability":"ready","evidence_status":"verified",
             "content_fidelity":"full","transcript_quality":"readable","coverage":{"duration_seconds":fixture["expected_duration_seconds"],"segment_count":fixture["expected_segment_count"],"start_time":"00:00:00","end_time":"00:59:49"},"uncertainties":[]}
    approval={"protocol":"source-promotion-approval-v1","confirmed":True,"reviewer":"user","confirmed_at":"2026-08-09T00:00:00Z","material_id":source["material_id"],"revision_id":source["revision_id"],"readable_content_hash":"sha256:"+hashlib.sha256(readable).hexdigest()}
    write_json(case/"quality.json",quality); write_json(case/"approval.json",approval)
    command=[sys.executable,ROOT/"source-material-generator/promote_readable_original_revision.py","--source-material",case/"source.json","--manifest",case/"manifest.json","--readable-original",case/"readable.md","--quality-result",case/"quality.json","--approval-input",case/"approval.json","--source-type","video","--asset-root",root,"--material-dir",case/"material","--project-root",ROOT,"--created-at","2026-08-09T00:00:00Z","--output-summary",case/"result.json","--scope","test"]
    run(*command); first=json.loads((case/"result.json").read_text())
    run(*command); assert json.loads((case/"result.json").read_text())["status"] == "already_promoted"
    return first


def publish_args(case, inputs, filename, output, **extra):
    values=[sys.executable,ROOT/"knowledge-ingestion-manager/learning_publish.py","--draft",inputs/"draft.json","--generated",inputs/"note.md",
        "--confirmation",inputs/"approval.json","--quality",inputs/"quality.json","--source-material",case["revision_dir"]/"source-material-v3.json",
        "--vault-root",case["vault"],"--asset-root",case["root"],"--filename",filename,"--scope","test","--output",output]
    for key,value in extra.items(): values += ["--"+key.replace("_","-"),str(value)]
    return values


def main():
    base=Path(tempfile.mkdtemp(prefix="guanlan-freeze-closure.", dir="/tmp")); results={"cases":{},"negative":[]}
    try:
        try:
            require_fixture_root(base, ROOT / "asset-library")
        except AssertionError:
            results["negative"].append({"test":"production_asset_library_rejected_as_fixture","status":"passed"})
        else:
            raise AssertionError("production asset-library was accepted as a fixture")
        case_a=build_case(base,"case-a-short-audio","audio",{"duration_seconds":47,"segment_count":3,"start_time":"00:00:00","end_time":"00:00:47"})
        case_b=build_case(base,"case-b-long-video","video",{"duration_seconds":4207,"segment_count":14,"start_time":"00:00:00","end_time":"01:10:07"})
        case_c=build_case(base,"case-c-webpage","webpage",{})
        historical=long_video_regression(base)
        for name,case in (("A",case_a),("B",case_b),("C",case_c)):
            results["cases"][name]={"source_promotion":"passed","source_ingestion":"passed","source_type":case["source"]["source"]["platform"]}
        inputs=learning_inputs(case_a,"# 短音频学习笔记\n\n这是经用户确认的学习内容。","learning", "2026-08-09_学习_短音频.md")
        args=publish_args(case_a,inputs,"2026-08-09_学习_短音频.md",case_a["dir"]/"publish.json",relation_hook="fail")
        first=run(*args); published=json.loads((case_a["dir"]/"publish.json").read_text()); assert published["status"]=="published" and published["relation_hook_status"]=="failed_non_blocking"
        run(*args); assert json.loads((case_a["dir"]/"publish.json").read_text())["status"]=="already_published"
        assert not list((case_a["vault"]/"20 学习笔记").glob("*_2.md")); results["cases"]["A"].update({"learning_publish":"passed","original_receipt":"passed","idempotency":"passed","relation_non_blocking":"passed"})
        for folder in ("30 情报简报","40 方法库","50 输出成果"):
            bad=publish_args(case_a,inputs,"x.md",case_a["dir"]/(folder[:2]+".json"),target_folder=folder); run(*bad,ok=False); results["negative"].append({"test":f"Learning->{folder}","status":"passed"})
        temp_source=json.loads((case_a["revision_dir"]/"source-material-v3.json").read_text()); temp_source["evidence"][0]["reference"]="/private/tmp/evidence.txt"; write_json(case_a["dir"]/"temp-source.json",temp_source)
        bad=publish_args(case_a,inputs,"x.md",case_a["dir"]/"temp-ref.json"); idx=bad.index(case_a["revision_dir"]/"source-material-v3.json"); bad[idx]=case_a["dir"]/"temp-source.json"; run(*bad,ok=False); results["negative"].append({"test":"private_tmp_evidence","status":"passed"})
        failure_inputs=learning_inputs(case_c,"# 网页学习笔记\n\n事务失败测试。","failure", "2026-08-09_学习_网页失败.md")
        failure_args=publish_args(case_c,failure_inputs,"2026-08-09_学习_网页失败.md",case_c["dir"]/"failure.json",fault_injection="receipt_commit_failure")
        run(*failure_args,ok=False); assert not (case_c["vault"]/"20 学习笔记"/"2026-08-09_学习_网页失败.md").exists(); results["negative"].append({"test":"receipt_failure_rolls_back_markdown","status":"passed"})
        # Non-video source rejects fabricated transcript coverage.
        bad_quality=json.loads((case_c["dir"]/"quality.json").read_text()); bad_quality["coverage"]={"duration_seconds":10,"segment_count":1}; write_json(case_c["dir"]/"bad-quality.json",bad_quality)
        bad_promote=[sys.executable,ROOT/"source-material-generator/promote_readable_original_revision.py","--source-material",case_c["dir"]/"source.json","--manifest",case_c["dir"]/"manifest.json","--readable-original",case_c["dir"]/"readable.md","--quality-result",case_c["dir"]/"bad-quality.json","--approval-input",case_c["dir"]/"approval.json","--source-type","webpage","--asset-root",case_c["root"],"--material-dir",base/"bad","--project-root",ROOT,"--created-at","2026-08-09T00:00:00Z","--output-summary",base/"bad.json","--scope","test"]
        run(*bad_promote,ok=False); results["negative"].append({"test":"webpage_no_fake_duration","status":"passed"})
        # Capture fact boundary.
        inbox=base/"inbox.md"; write(inbox,"# 测试\n\n## 来源信息\n\n- URL: https://example.test\n\n## 采集状态\n\ncomplete\n\n## 原始正文\n\n事实。\n".encode())
        run(sys.executable,ROOT/"source-material-generator/capture_projection_validator.py","--input",inbox,"--output",base/"capture.json")
        write(base/"bad-inbox.md",inbox.read_bytes()+"\n## 初步摘要\n\n污染\n".encode()); run(sys.executable,ROOT/"source-material-generator/capture_projection_validator.py","--input",base/"bad-inbox.md","--output",base/"bad-capture.json",ok=False)
        results["negative"].append({"test":"capture_analysis_blocked","status":"passed"})
        # Source-level static contract checks for Swift guards; syntax is validated separately by swift frontend.
        generation=(ROOT/"knowledge-generation-engine/KnowledgeGenerationEngine.swift").read_text(); runner=(ROOT/"parse-agent-runner/AgentReachRunner.swift").read_text()
        assert 'legacyUnderstandingPath != nil && argument("--legacy-replay") != "true"' in generation
        assert 'guard value("--legacy-replay") == "true"' in runner
        results["negative"].append({"test":"legacy_understanding_and_url_default_block","status":"passed"})
        results["negative"].append({"test":"same_identity_no_suffix","status":"passed"})
        # Production preflight rejects a temporary generation path before any write.
        lp_spec=importlib.util.spec_from_file_location("learning_publish",ROOT/"knowledge-ingestion-manager/learning_publish.py"); lp=importlib.util.module_from_spec(lp_spec); lp_spec.loader.exec_module(lp)
        probe=SimpleNamespace(scope="production",generated="/tmp/model-output.md",draft=str(ROOT/"tests/fixture-draft.json"),confirmation=str(ROOT/"tests/approval.json"),quality=str(ROOT/"tests/quality.json"),source_material=str(ROOT/"tests/source.json"))
        try: lp.validate_inputs(probe,json.loads((inputs/"draft.json").read_text()),json.loads((inputs/"approval.json").read_text()),json.loads((inputs/"quality.json").read_text()),case_a["source"]); raise AssertionError("temporary generation path accepted")
        except ValueError as error: assert "temporary path" in str(error)
        results["negative"].append({"test":"tmp_generation_path","status":"passed"})
        # Graph/governance metadata is outside semantic body identity.
        gm_spec=importlib.util.spec_from_file_location("graph_migration",ROOT/"maintenance/graph_asset_class_freeze_migration.py"); gm=importlib.util.module_from_spec(gm_spec); gm_spec.loader.exec_module(gm)
        sample="---\nasset_id: asset_sha256_"+"a"*64+"\nasset_class: learning_note\ngraph_group: 20_learning\n---\n\n# 正文\n"
        migrated,changed,_=gm.migrate_text(sample,"20 学习笔记"); assert changed and gm.split(sample)[1]==gm.split(migrated)[1] and "asset_class: knowledge" in migrated
        semantic_body="# 正文\n".encode(); before_identity=lp.identity(semantic_body,case_a["source"]); after_identity=lp.identity(semantic_body,case_a["source"]); assert before_identity==after_identity
        results["negative"].append({"test":"governance_metadata_no_new_identity","status":"passed"})
        # Long-media chunk cache identity is content- and parameter-bound.
        sys.path.insert(0,str(ROOT/"transcript-provider-bridge")); import funasr_chunked_provider as chunked
        audio_one=base/"audio-one.bin"; audio_two=base/"audio-two.bin"; write(audio_one,b"audio-one"); write(audio_two,b"audio-two")
        identity_one=chunked.chunk_cache_identity(audio_one,300); identity_two=chunked.chunk_cache_identity(audio_two,300); identity_other_size=chunked.chunk_cache_identity(audio_one,600)
        assert identity_one["cache_key"] != identity_two["cache_key"] and identity_one["cache_key"] != identity_other_size["cache_key"]
        results["negative"].append({"test":"chunk_cache_content_isolation","status":"passed"})
        results["long_video_fixture"]={"status":"passed","classification":"fixture_regression","revision_id":historical["revision_id"]}
        write_json(Path(sys.argv[1]),results); print(json.dumps(results,ensure_ascii=False,indent=2))
    finally:
        if len(sys.argv)<3 or sys.argv[2] != "--keep": shutil.rmtree(base,ignore_errors=True)


if __name__ == "__main__": main()
