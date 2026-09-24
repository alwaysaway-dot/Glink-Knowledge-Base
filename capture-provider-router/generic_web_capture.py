#!/usr/bin/env python3
"""Capture one public static HTML page into Source Material v3 and an optional 00 projection."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from providers.generic_web_contract import GenericWebCaptureRequest, GenericWebPayload
from providers.scrapling_static_adapter import fetch_static, provider_version


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from operation_envelope import OperationRecorder


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


FOUNDATION = load_module("foundation_generic_web", ROOT / "knowledge-foundation-stability/foundation_stability.py")
COMPLETION = load_module("completion_generic_web", ROOT / "source-material-generator/capture_inbox_completion.py")


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    try:
        with temporary.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def put_object(asset_root: Path, data: bytes, role: str, media_type: str) -> dict:
    content_hash = FOUNDATION.sha256_bytes(data)
    digest = content_hash.split(":", 1)[1]
    relative = Path("objects/sha256") / digest[:2] / digest
    target = asset_root / relative
    if target.exists() and FOUNDATION.sha256_file(target) != content_hash:
        raise ValueError("content-addressed object collision")
    if not target.exists():
        atomic_write(target, data)
    asset_id = FOUNDATION.asset_id_from_hash(content_hash)
    return {
        "reference": f"guanlan://asset/{asset_id}",
        "asset_id": asset_id,
        "role": role,
        "storage_relative_path": relative.as_posix(),
        "content_hash": content_hash,
        "media_type": media_type,
        "size_bytes": len(data),
    }


def validate_targets(
    asset_root: Path, material_dir: Path, inbox: Path | None,
    projection: Path | None, scope: str,
) -> None:
    """Reject unsafe or incomplete destinations before any fetch or filesystem write."""
    if scope not in {"production", "test"}:
        raise ValueError("invalid capture scope")
    if (inbox is None) != (projection is None):
        raise ValueError("inbox and projection must be supplied together")
    asset_root = asset_root.resolve()
    material_dir = material_dir.resolve()
    if scope == "production":
        configured = os.environ.get("GUANLAN_ASSET_ROOT", "")
        if configured and not Path(configured).is_absolute():
            raise ValueError("GUANLAN_ASSET_ROOT must be absolute")
        expected_root = Path(configured).resolve() if configured else (ROOT / "asset-library").resolve()
        if asset_root != expected_root:
            raise ValueError("production asset root must match GUANLAN_ASSET_ROOT or this checkout's asset-library")
        if material_dir.parent != asset_root / "materials":
            raise ValueError("production material directory must be a direct child of asset-library/materials")
        if inbox is None or projection is None:
            raise ValueError("production capture requires a 00 inbox projection")
    elif not all(str(path).startswith(("/tmp/", "/private/tmp/")) for path in (asset_root, material_dir)):
        raise ValueError("test asset and material roots must be under /tmp")
    if inbox is not None and projection is not None:
        COMPLETION.validate_destination(inbox, projection, scope)


def build_source(
    request: GenericWebCaptureRequest,
    payload: GenericWebPayload,
    asset_root: Path,
    material_dir: Path,
) -> tuple[dict, dict, Path, Path, dict]:
    if not payload.succeeded or payload.raw_html is None or payload.readable_text is None or not payload.final_url:
        raise ValueError("successful provider payload with raw/readable content is required")
    raw = put_object(asset_root, payload.raw_html, "raw_html", payload.response_headers_subset.get("content-type", "text/html"))
    readable_bytes = (payload.readable_text.strip() + "\n").encode("utf-8")
    readable = put_object(asset_root, readable_bytes, "readable_source", "text/plain; charset=utf-8")
    source_key = FOUNDATION.source_key("webpage", "unknown", payload.final_url)
    material_id = FOUNDATION.material_id_from_source_key(source_key)
    captured_at = now()
    source = {
        "protocol": "source-material-v3",
        "schema_version": "3.0.0",
        "material_id": material_id,
        "revision_id": "revision_sha256_" + "0" * 64,
        "source": {
            "platform": "webpage",
            "source_id": "unknown",
            "source_url": payload.final_url,
            "title": payload.title or "unknown",
            "author": payload.author or "unknown",
            "published_at": payload.published_at or "",
            "captured_at": captured_at,
        },
        "content": {
            "raw": {"storage": "reference", "reference": raw["reference"], "content_hash": raw["content_hash"], "media_type": raw["media_type"]},
            "readable": {"storage": "reference", "reference": readable["reference"], "content_hash": readable["content_hash"], "media_type": readable["media_type"], "operations": ["static_html_parse", "boilerplate_removed", "whitespace_normalized", "no_summary", "no_ai_rewrite"]},
        },
        "evidence": [
            {"evidence_id": "evidence_raw_html_" + raw["content_hash"].split(":", 1)[1][:16], "kind": "raw_html", "reference": raw["reference"], "content_hash": raw["content_hash"], "uncertainty": ""},
            {"evidence_id": "evidence_readable_" + readable["content_hash"].split(":", 1)[1][:16], "kind": "readable_source", "reference": readable["reference"], "content_hash": readable["content_hash"], "uncertainty": "deterministic parser extraction; raw HTML retained"},
        ],
        "quality": {
            "capture_status": "complete",
            "content_fidelity": "full",
            "transcript_quality": "not_applicable",
            "review_required": True,
            "uncertainties": list(payload.warnings),
        },
        "lifecycle": {
            "status": "captured",
            "review_status": "pending",
            "created_at": captured_at,
            "updated_at": captured_at,
            "processing_history": [{
                "processor": "generic_web_static",
                "version": provider_version(),
                "capture_request_id": request.capture_request_id,
                "requested_url": request.url,
                "final_url": payload.final_url,
                "http_status": payload.http_status,
                "redirect_count": payload.redirect_count,
                "extraction_method": payload.extraction_method,
                "robots_evaluation": "not_implemented_single_url_capture",
            }],
        },
        "asset_manifest_reference": "",
        "understanding_sidecar_reference": "",
    }
    source["revision_id"] = FOUNDATION.revision_id(source)
    source["asset_manifest_reference"] = f"guanlan://manifest/{material_id}/{source['revision_id']}"
    manifest = {
        "protocol": "reference-manifest-v1",
        "schema_version": "1.0.0",
        "material_id": material_id,
        "revision_id": source["revision_id"],
        "entries": [raw, readable],
    }
    revision_dir = material_dir / "revisions" / source["revision_id"]
    source_path = revision_dir / "source-material-v3.json"
    manifest_path = revision_dir / "reference-manifest.json"
    desired_source, desired_manifest = canonical(source), canonical(manifest)
    if source_path.exists() or manifest_path.exists():
        if not source_path.exists() or not manifest_path.exists() or manifest_path.read_bytes() != desired_manifest:
            raise ValueError("existing revision conflicts with deterministic capture result")
        existing_source = json.loads(source_path.read_text(encoding="utf-8"))
        if existing_source.get("material_id") != material_id or existing_source.get("revision_id") != source["revision_id"]:
            raise ValueError("existing Source identity conflicts with deterministic capture result")
        source = existing_source
        action = "already_captured"
    else:
        atomic_write(source_path, desired_source)
        atomic_write(manifest_path, desired_manifest)
        action = "captured"
    atomic_write(material_dir / "CURRENT_REVISION", (source["revision_id"] + "\n").encode())
    result = {
        "protocol": "generic-web-provider-result-v1",
        "schema_version": "1.0.0",
        "capture_request_id": request.capture_request_id,
        "provider_id": "scrapling_static",
        "provider_version": provider_version(),
        "requested_url": request.url,
        "final_url": payload.final_url,
        "requested_at": request.requested_at,
        "retrieved_at": captured_at,
        "http_status": payload.http_status,
        "content_type": payload.response_headers_subset.get("content-type"),
        "response_headers_subset": payload.response_headers_subset,
        "title": payload.title,
        "author": payload.author,
        "published_at": payload.published_at,
        "raw_html_ref": raw["reference"],
        "readable_text_ref": readable["reference"],
        "extraction_method": payload.extraction_method,
        "warnings": list(payload.warnings),
        "failure_class": None,
        "provider_metadata": {"redirect_count": payload.redirect_count, "language_hint": request.language_hint, "robots_evaluation": "not_implemented_single_url_capture"},
        "source_material": str(source_path),
        "manifest": str(manifest_path),
        "material_id": material_id,
        "revision_id": source["revision_id"],
        "capture_action": action,
    }
    return source, manifest, source_path, manifest_path, result


def capture(
    *, request: GenericWebCaptureRequest, asset_root: Path, material_dir: Path,
    inbox: Path | None = None, projection: Path | None = None, scope: str = "production",
    transport=None,
) -> tuple[dict, int]:
    validate_targets(asset_root, material_dir, inbox, projection, scope)
    if scope == "production" and request.allow_private_test:
        raise ValueError("production capture cannot bypass public-target checks")
    operation = OperationRecorder(Path(asset_root) / "operations", "capture")
    payload = fetch_static(request, transport=transport)
    if not payload.succeeded:
        result = {
            "protocol": "generic-web-provider-result-v1", "schema_version": "1.0.0",
            "capture_request_id": request.capture_request_id, "provider_id": "scrapling_static",
            "provider_version": provider_version(), "requested_url": request.url,
            "final_url": payload.final_url, "http_status": payload.http_status,
            "response_headers_subset": payload.response_headers_subset,
            "warnings": list(payload.warnings), "failure_class": payload.failure_class,
            "failure_detail": payload.failure_detail, "handoff_kind": payload.handoff_kind,
            "source_material_written": False, "inbox_projection_written": False,
            "operation_id": operation.operation_id,
        }
        blocked = {"invalid_url", "authentication_required", "challenge_page", "javascript_required", "unsupported_content_type"}
        warning = operation.finish(
            "blocked" if payload.failure_class in blocked else "failed",
            failure_class=payload.failure_class, failure_detail=payload.failure_detail,
        )
        if warning: result.setdefault("warnings", []).append(warning)
        return result, 2
    try:
        source, manifest, source_path, manifest_path, result = build_source(request, payload, asset_root, material_dir)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        operation.finish("failed", failure_class="capture_commit_failed", failure_detail=str(error))
        raise
    if inbox is not None and projection is not None:
        try:
            completion, code = COMPLETION.complete_capture(
                source_path=source_path, manifest_path=manifest_path, asset_root=asset_root,
                inbox=inbox, requested_output=projection, project_root=ROOT, scope=scope,
            )
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
            operation.finish("partial", output_refs=[source["asset_manifest_reference"]],
                             failure_class="inbox_projection_failed", failure_detail=str(error))
            raise
        result["inbox_completion"] = completion
        result["inbox_projection_written"] = bool(completion.get("projection_written") or completion.get("status") == "already_projected")
        if code:
            result["failure_class"] = "provider_error"
            result["failure_detail"] = "Source created but inbox projection failed"
            result["operation_id"] = operation.operation_id
            warning = operation.finish(
                "partial", output_refs=[source["asset_manifest_reference"]],
                failure_class="inbox_projection_failed", failure_detail=result["failure_detail"],
            )
            if warning: result.setdefault("warnings", []).append(warning)
            return result, code
    else:
        result["inbox_projection_written"] = False
    result["operation_id"] = operation.operation_id
    output_refs = [source["asset_manifest_reference"], f"guanlan://material/{source['material_id']}/revision/{source['revision_id']}"]
    warning = operation.finish(
        "completed" if result.get("inbox_projection_written") else "partial",
        output_refs=output_refs,
        change_refs=output_refs if result.get("capture_action") == "captured" else [],
        warnings=result.get("warnings", []),
        failure_class=None if result.get("inbox_projection_written") else "inbox_projection_absent",
    )
    if warning: result.setdefault("warnings", []).append(warning)
    return result, 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture-request-id", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--requested-at", required=True)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--language-hint")
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--material-dir", type=Path, required=True)
    parser.add_argument("--inbox", type=Path)
    parser.add_argument("--projection", type=Path)
    parser.add_argument("--scope", choices=("production", "test"), default="production")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if (args.inbox is None) != (args.projection is None):
        parser.error("--inbox and --projection must be supplied together")
    if args.scope == "production" and (args.inbox is None or args.projection is None):
        parser.error("production capture requires --inbox and --projection")
    request = GenericWebCaptureRequest(
        capture_request_id=args.capture_request_id, url=args.url, requested_at=args.requested_at,
        timeout_seconds=args.timeout, language_hint=args.language_hint,
        allow_private_test=args.scope == "test",
    )
    result, code = capture(
        request=request, asset_root=args.asset_root, material_dir=args.material_dir,
        inbox=args.inbox, projection=args.projection, scope=args.scope,
    )
    atomic_write(args.output, canonical(result))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
