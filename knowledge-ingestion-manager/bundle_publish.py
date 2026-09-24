#!/usr/bin/env python3
"""Ordered, resumable dispatch for one user-approved Candidate Bundle.

This is intentionally a thin dispatcher, not a second ingestion framework.
Each component keeps its own transaction, identity and original receipt.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from publisher_core import TARGETS, atomic_json, has_temp, load_json
from approval_binding import prepare as prepare_binding, candidate_view, sha


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from operation_envelope import OperationRecorder
ORDER = ("source_asset", "learning_note", "intelligence_brief", "method_asset", "creation_asset")


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def preflight(bundle: dict, plan: dict):
    if bundle.get("protocol") != "candidate-bundle-v1" or bundle.get("workflow_state") != "awaiting_user_confirmation":
        raise ValueError("an awaiting_user_confirmation candidate-bundle-v1 is required")
    if plan.get("protocol") != "candidate-bundle-publish-plan-v1" or plan.get("bundle_id") != bundle.get("bundle_id"):
        raise ValueError("publish plan/bundle mismatch")
    if plan.get("approval", {}).get("confirmed") is not True or plan["approval"].get("reviewer") != "user":
        raise ValueError("one explicit user bundle approval is required")
    candidates = {bundle["source_candidate"]["candidate_id"]: bundle["source_candidate"]}
    candidates.update({item["candidate_id"]: item for item in bundle.get("derivative_candidates", [])})
    selected = plan.get("selected_candidate_ids", [])
    if not selected:
        selected = [item["candidate_id"] for item in candidates.values() if item.get("status") == "publishable"]
    prepared = []
    for candidate_id in selected:
        candidate = candidates.get(candidate_id)
        if not candidate:
            raise ValueError("selected candidate absent from bundle")
        if candidate.get("status") != "publishable":
            raise ValueError("selected candidate is not publishable")
        asset_type = candidate["asset_type"]
        component = plan.get("components", {}).get(candidate_id)
        if not component or component.get("asset_type") != asset_type:
            raise ValueError("publisher component missing or type mismatch")
        if asset_type != "source_asset" and component.get("target_folder") != TARGETS.get(asset_type):
            raise ValueError("component target does not match asset type")
        for value in component.get("inputs", {}).values():
            if isinstance(value, str) and (value.startswith("/tmp/") or value.startswith("/private/tmp/")):
                raise ValueError("temporary path is forbidden in publish plan")
        inputs = component["inputs"]
        source = load_json(Path(inputs["source_material"]), "source material")
        actual_candidate = candidate
        if asset_type != "source_asset":
            if asset_type == "learning_note" and not inputs.get("candidate"):
                raise ValueError("approval_binding_missing: Learning Candidate snapshot required")
            actual_candidate = load_json(Path(inputs["candidate"]), "candidate")
            if candidate_view(actual_candidate) != candidate_view(candidate):
                raise ValueError("approval_binding_mismatch: Bundle Candidate changed")
        target_folder = "10 原始资料" if asset_type == "source_asset" else component["target_folder"]
        kwargs = {"candidate": candidate, "source": source, "target_folder": target_folder,
                  "filename": inputs["filename"], "bundle": bundle}
        if asset_type == "source_asset":
            kwargs["projection_hash"] = sha(Path(inputs["projection"]).read_bytes())
            kwargs["quality"] = load_json(Path(inputs["validation"]), "Source validation")
        else:
            kwargs["quality"] = load_json(Path(inputs["quality"]), "publish quality")
            kwargs["body"] = Path(inputs["generated"]).read_text(encoding="utf-8") if asset_type == "learning_note" else candidate["content"]["markdown"]
            kwargs["title"] = candidate["content"]["title"]
        expected = prepare_binding(**kwargs)
        approved = plan["approval"].get("bindings", {}).get(candidate_id)
        if approved != expected:
            raise ValueError("approval_binding_mismatch: explicit approval of current Candidate Bundle required")
        if asset_type != "source_asset":
            confirmation = load_json(Path(inputs["confirmation"]), "component confirmation")
            if confirmation.get("approval_binding") != prepare_binding(**dict(kwargs, bundle=None)):
                raise ValueError("approval_binding_mismatch: component confirmation differs from H1 approval")
        prepared.append((asset_type, candidate_id, component))
    return sorted(prepared, key=lambda item: ORDER.index(item[0]))


def command_for(asset_type: str, component: dict, scope: str):
    inputs = component["inputs"]
    if asset_type == "source_asset":
        required = ("source_material", "manifest", "projection", "validation", "confirmation", "vault", "filename", "record")
        if not all(inputs.get(key) for key in required):
            raise ValueError("Source component inputs incomplete")
        return [sys.executable, str(ROOT / "knowledge-ingestion-manager" / "source_asset_ingestion.py"), "--command", "ingest", "--scope", scope,
                "--source-material", inputs["source_material"], "--manifest", inputs["manifest"], "--projection", inputs["projection"],
                "--validation", inputs["validation"], "--confirmation", inputs["confirmation"], "--vault", inputs["vault"],
                "--filename", inputs["filename"], "--record", inputs["record"]]
    if asset_type == "learning_note":
        required = ("draft", "generated", "confirmation", "quality", "source_material", "vault_root", "asset_root", "filename", "output")
        if not all(inputs.get(key) for key in required):
            raise ValueError("Learning component inputs incomplete")
        command = [sys.executable, str(ROOT / "knowledge-ingestion-manager" / "learning_publish.py"), "--draft", inputs["draft"], "--generated", inputs["generated"],
                "--confirmation", inputs["confirmation"], "--quality", inputs["quality"], "--source-material", inputs["source_material"],
                "--vault-root", inputs["vault_root"], "--asset-root", inputs["asset_root"], "--filename", inputs["filename"], "--scope", scope, "--output", inputs["output"]]
        if inputs.get("candidate"):
            command.extend(["--candidate", inputs["candidate"]])
        return command
    required = ("candidate", "confirmation", "quality", "source_material", "vault_root", "asset_root", "filename", "target_folder", "output")
    if not all(inputs.get(key) for key in required):
        raise ValueError(f"{asset_type} component inputs incomplete")
    return [sys.executable, str(ROOT / "knowledge-ingestion-manager" / "derivative_publish.py"), "--candidate", inputs["candidate"], "--confirmation", inputs["confirmation"],
            "--quality", inputs["quality"], "--source-material", inputs["source_material"], "--vault-root", inputs["vault_root"], "--asset-root", inputs["asset_root"],
            "--filename", inputs["filename"], "--target-folder", inputs["target_folder"], "--scope", scope, "--output", inputs["output"]]


def operation_root(bundle_path: Path, plan: dict, explicit: str | None) -> Path:
    if explicit: return Path(explicit).resolve()
    for component in plan.get("components", {}).values():
        root = component.get("inputs", {}).get("asset_root")
        if root: return Path(root).resolve() / "operations"
    for component in plan.get("components", {}).values():
        source = component.get("inputs", {}).get("source_material")
        if source:
            for parent in Path(source).resolve().parents:
                if parent.name == "asset-library": return parent / "operations"
    for parent in bundle_path.resolve().parents:
        if parent.name == "operations": return parent
    raise ValueError("operation root cannot be derived from publish inputs")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True); parser.add_argument("--publish-plan", required=True)
    parser.add_argument("--scope", choices=("production", "test"), default="production"); parser.add_argument("--output", required=True)
    parser.add_argument("--operation-root")
    args = parser.parse_args()
    operation = None
    try:
        bundle_path = Path(args.bundle)
        bundle = load_json(bundle_path, "candidate bundle"); plan = load_json(Path(args.publish_plan), "publish plan")
        bundle_ref = f"guanlan://candidate-bundle/{bundle['bundle_id']}"
        try:
            operation = OperationRecorder(operation_root(bundle_path, plan, args.operation_root), "publish", input_refs=[bundle_ref])
        except (OSError, ValueError) as index_error:
            operation = OperationRecorder.unavailable("publish", str(index_error))
        if has_temp(bundle) or has_temp(plan):
            raise ValueError("temporary references are forbidden")
        components = preflight(bundle, plan)
        results = []; source_failed = False
        for asset_type, candidate_id, component in components:
            if source_failed:
                results.append({"candidate_id": candidate_id, "asset_type": asset_type, "status": "pending_retry", "reason": "Source publication did not commit"})
                continue
            run = subprocess.run(command_for(asset_type, component, args.scope), text=True, capture_output=True)
            result = {"candidate_id": candidate_id, "asset_type": asset_type, "returncode": run.returncode, "stdout": run.stdout, "stderr": run.stderr}
            if run.returncode == 0:
                result["status"] = "published_or_already_published"
            else:
                result["status"] = "pending_retry"
                if asset_type == "source_asset": source_failed = True
            results.append(result)
        final_status = "published" if all(item.get("status") == "published_or_already_published" for item in results) else "publish_partial"
        output_refs, receipt_refs = [], []
        for component_type, _candidate_id, component in components:
            inputs = component.get("inputs", {})
            output_path = inputs.get("record") if component_type == "source_asset" else inputs.get("output")
            if not output_path or not Path(output_path).is_file(): continue
            try: published = json.loads(Path(output_path).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError): continue
            asset_id = published.get("asset_id") or published.get("knowledge_asset_id")
            source = published.get("source", {})
            receipt_path = published.get("receipt")
            if asset_id: output_refs.append(f"guanlan://asset/{asset_id}")
            if source.get("material_id") and source.get("revision_id"):
                output_refs.append(f"guanlan://material/{source['material_id']}/revision/{source['revision_id']}")
            if published.get("receipt_reference"):
                receipt_refs.append(published["receipt_reference"])
            if receipt_path and Path(receipt_path).is_file():
                try:
                    receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
                    if receipt.get("receipt_id"): receipt_refs.append(f"guanlan://receipt/{receipt['receipt_id']}")
                except (OSError, json.JSONDecodeError): pass
        status = "completed" if final_status == "published" else "partial"
        warning = operation.finish(status, output_refs=output_refs, receipt_refs=receipt_refs,
                                   change_refs=output_refs, failure_class=None if status == "completed" else "publish_partial")
        result = {"protocol": "candidate-bundle-publish-result-v1", "bundle_id": bundle["bundle_id"], "status": final_status,
                  "results": results, "updated_at": now(), "operation_id": operation.operation_id}
        if warning: result["operation_index_warning"] = warning
        atomic_json(Path(args.output), result); print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        if operation is not None: operation.finish("blocked", failure_class="publish_preflight_or_dispatch_failed", failure_detail=str(error))
        raise SystemExit(f"ERROR: {error}") from error


if __name__ == "__main__":
    main()
