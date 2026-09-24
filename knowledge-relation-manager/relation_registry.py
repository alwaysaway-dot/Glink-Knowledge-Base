#!/usr/bin/env python3
"""Validate the independent Relation Registry without reading Markdown links."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from relation_common import ASSET_ID_RE, MATERIAL_ID_RE, REVISION_ID_RE, SNAPSHOT_RE, canonical_pair


APPROVAL_STATES = {"approved", "executed", "auto_executed", "rejected", "revoked"}


def valid_endpoint(value):
    return bool(ASSET_ID_RE.fullmatch(value) or MATERIAL_ID_RE.fullmatch(value))


def valid_revision(value):
    return bool(REVISION_ID_RE.fullmatch(value) or SNAPSHOT_RE.fullmatch(value))


def validate(registry):
    if registry.get("protocol") != "relation-registry-v1" or registry.get("schema_version") != "1.0.0":
        raise ValueError("relation-registry-v1 schema 1.0.0 is required")
    if not isinstance(registry.get("relations"), list):
        raise ValueError("relations must be an array")
    seen_ids, seen_active_facts = set(), set()
    for item in registry["relations"]:
        if item.get("relation_id") in seen_ids:
            raise ValueError("duplicate relation_id")
        seen_ids.add(item.get("relation_id"))
        if not valid_endpoint(str(item.get("source_asset_id", ""))) or not valid_endpoint(str(item.get("target_asset_id", ""))):
            raise ValueError("invalid endpoint identity")
        if item.get("source_asset_id") == item.get("target_asset_id"):
            raise ValueError("self relation is forbidden")
        if not valid_revision(str(item.get("source_revision", ""))) or not valid_revision(str(item.get("target_revision", ""))):
            raise ValueError("invalid endpoint revision")
        if item.get("approval_status") not in APPROVAL_STATES:
            raise ValueError("invalid approval_status")
        fact = (canonical_pair(item["source_asset_id"], item["target_asset_id"]), frozenset((item.get("relation_type"), item.get("reciprocal_relation"))))
        if item.get("approval_status") in {"approved", "executed", "auto_executed"}:
            if fact in seen_active_facts:
                raise ValueError("duplicate active relation fact")
            seen_active_facts.add(fact)
    return {"status": "valid", "relation_count": len(registry["relations"]), "identity_source": "asset_id_and_revision", "markdown_is_authority": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", required=True)
    args = parser.parse_args()
    try:
        result = validate(json.loads(Path(args.registry).read_text(encoding="utf-8")))
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"ERROR: {error}") from error


if __name__ == "__main__":
    main()
