#!/usr/bin/env python3
"""Immutable H1 approval-object digest; prepares evidence but never signs approval.

Only the human-approved approval record may carry ``confirmed=True``.  The
publisher recomputes this object from current inputs immediately before write.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from publisher_core import TARGETS, canonical, strip_frontmatter


PROTOCOL = "publisher-approval-binding-v1"


def sha(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def candidate_view(candidate: dict) -> dict:
    content = candidate.get("content", {})
    if candidate.get("asset_type") == "source_asset":
        content = {"readable_reference": candidate.get("readable_reference"), "content_hash": candidate.get("content_hash")}
    else:
        content = {"title": content.get("title"), "body_hash": sha((strip_frontmatter(content.get("markdown", "")).strip() + "\n").encode("utf-8"))}
    return {
        "candidate_id": candidate.get("candidate_id"), "asset_type": candidate.get("asset_type"),
        "status": candidate.get("status"), "source": {key: candidate.get("source", {}).get(key) for key in ("material_id", "revision_id")},
        "content": content, "provenance": sorted(candidate.get("provenance", {}).get("stable_references", [])),
        "admission": candidate.get("admission", {}),
    }


def bundle_view(bundle: dict) -> dict:
    candidates = [bundle["source_candidate"], *bundle.get("derivative_candidates", [])]
    return {
        "bundle_id": bundle["bundle_id"],
        "source": {key: bundle.get("source", {}).get(key) for key in ("material_id", "revision_id")},
        "candidates": sorted((candidate_view(item) for item in candidates), key=lambda item: item["candidate_id"]),
    }


def snapshot(*, candidate: dict, source: dict, target_folder: str, filename: str,
             body: str | None = None, title: str | None = None, quality: dict | None = None,
             bundle: dict | None = None, projection_hash: str | None = None) -> dict:
    asset_type = candidate["asset_type"]
    expected_folder = "10 原始资料" if asset_type == "source_asset" else TARGETS[asset_type]
    if target_folder != expected_folder or Path(filename).name != filename or not filename.endswith(".md"):
        raise ValueError("approval_binding_target_mismatch")
    if candidate.get("source", {}).get("material_id") != source.get("material_id") or candidate.get("source", {}).get("revision_id") != source.get("revision_id"):
        raise ValueError("approval_binding_source_mismatch")
    view = candidate_view(candidate)
    if body is not None:
        published_hash = sha((strip_frontmatter(body).strip() + "\n").encode("utf-8"))
        if view["content"].get("body_hash") != published_hash:
            raise ValueError("approval_binding_candidate_body_mismatch")
        view["content"]["published_body_hash"] = published_hash
    if title is not None:
        if view["content"].get("title") != title:
            raise ValueError("approval_binding_candidate_title_mismatch")
    if quality is not None:
        view["quality"] = {key: quality.get(key) for key in ("protocol", "status", "candidate_id", "asset_type", "source_traceability", "source_copy_check", "title_consistency") if key in quality}
    view["target"] = {"folder": target_folder, "filename": filename}
    if asset_type == "source_asset":
        if not projection_hash: raise ValueError("approval_binding_source_projection_missing")
        view["content"]["projection_hash"] = projection_hash
    view["bundle"] = bundle_view(bundle) if bundle is not None else None
    return view


def prepare(**kwargs) -> dict:
    view = snapshot(**kwargs)
    return {"protocol": PROTOCOL, "schema_version": "1.0.0", "digest": sha(canonical(view)), "snapshot": view}


def verify(approval: dict, **kwargs) -> str:
    binding = approval.get("approval_binding")
    if not isinstance(binding, dict) or binding.get("protocol") != PROTOCOL:
        raise ValueError("approval_binding_missing: explicit reapproval required")
    expected = prepare(**kwargs)
    if binding != expected:
        raise ValueError("approval_binding_mismatch: candidate or publisher inputs changed; explicit reapproval required")
    return expected["digest"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare an unapproved H1 candidate snapshot")
    parser.add_argument("--candidate", required=True); parser.add_argument("--source-material", required=True)
    parser.add_argument("--target-folder", required=True); parser.add_argument("--filename", required=True)
    parser.add_argument("--body"); parser.add_argument("--title"); parser.add_argument("--quality"); parser.add_argument("--bundle")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    load = lambda path: json.loads(Path(path).read_text(encoding="utf-8"))
    result = prepare(candidate=load(args.candidate), source=load(args.source_material), target_folder=args.target_folder,
                     filename=args.filename, body=Path(args.body).read_text(encoding="utf-8") if args.body else None,
                     title=args.title, quality=load(args.quality) if args.quality else None,
                     bundle=load(args.bundle) if args.bundle else None)
    result["approval_status"] = "awaiting_user_confirmation"
    Path(args.output).write_bytes(canonical(result))
    print(json.dumps({"digest": result["digest"], "approval_status": result["approval_status"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
