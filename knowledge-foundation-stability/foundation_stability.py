#!/usr/bin/env python3
"""Validate Guanlan v0.5 source-material identities and permanent references."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

HEX64 = r"[0-9a-f]{64}"
CONTENT_HASH_RE = re.compile(rf"^sha256:{HEX64}$")
ASSET_ID_RE = re.compile(rf"^asset_sha256_{HEX64}$")
MATERIAL_ID_RE = re.compile(rf"^material_sha256_{HEX64}$")
REVISION_ID_RE = re.compile(rf"^revision_sha256_{HEX64}$")
SIDECAR_ID_RE = re.compile(rf"^sidecar_sha256_{HEX64}$")
TEMP_PREFIXES = ("/tmp/", "/private/tmp/")
TRACKING_QUERY_KEYS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "si", "feature",
}


class ValidationFailure(Exception):
    pass


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def validate_content_hash(value: str) -> None:
    if not CONTENT_HASH_RE.fullmatch(value):
        raise ValidationFailure(f"invalid content_hash: {value}")


def asset_id_from_hash(content_hash: str) -> str:
    validate_content_hash(content_hash)
    return "asset_sha256_" + content_hash.split(":", 1)[1]


def canonical_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValidationFailure("source_url must be an absolute http(s) URL")
    query = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in TRACKING_QUERY_KEYS
    ]
    normalized = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
        fragment="",
        query=urlencode(sorted(query)),
    )
    return urlunparse(normalized)


def source_key(platform: str, source_id: str, source_url: str = "") -> str:
    normalized_platform = platform.strip().lower()
    normalized_id = source_id.strip()
    if not normalized_platform:
        raise ValidationFailure("platform is required")
    if normalized_platform == "local":
        validate_content_hash(normalized_id)
        return f"local:{normalized_id}"
    if normalized_id and normalized_id not in {"unknown", "none"}:
        return f"{normalized_platform}:{normalized_id}"
    normalized_url = canonical_url(source_url)
    return "url:" + sha256_bytes(normalized_url.encode("utf-8"))


def material_id_from_source_key(value: str) -> str:
    return "material_sha256_" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def revision_payload(record: dict) -> dict:
    source = record["source"]
    content = record["content"]
    quality = record["quality"]
    evidence = sorted(
        [
            {
                "evidence_id": item["evidence_id"],
                "kind": item["kind"],
                "content_hash": item["content_hash"],
                "start_time": item.get("start_time"),
                "end_time": item.get("end_time"),
                "uncertainty": item.get("uncertainty", ""),
            }
            for item in record["evidence"]
        ],
        key=lambda item: item["evidence_id"],
    )
    return {
        "schema_version": record["schema_version"],
        "material_id": record["material_id"],
        "source": {
            "platform": source["platform"],
            "source_id": source["source_id"],
            "source_url": source["source_url"],
            "title": source["title"],
            "author": source["author"],
            "published_at": source.get("published_at", ""),
        },
        "content": {
            "raw_content_hash": content["raw"]["content_hash"],
            "readable_content_hash": content["readable"]["content_hash"],
        },
        "evidence": evidence,
        "quality": {
            "capture_status": quality["capture_status"],
            "content_fidelity": quality["content_fidelity"],
            "transcript_quality": quality["transcript_quality"],
            "uncertainties": quality["uncertainties"],
        },
    }


def revision_id(record: dict) -> str:
    return "revision_sha256_" + hashlib.sha256(
        canonical_json(revision_payload(record))
    ).hexdigest()


def is_temp_reference(value: str) -> bool:
    return value.startswith(TEMP_PREFIXES) or value.startswith(
        ("file:///tmp/", "file:///private/tmp/")
    )


def validate_logical_reference(value: str, allowed_kinds: set[str] | None = None) -> None:
    if is_temp_reference(value):
        raise ValidationFailure(f"temporary reference is forbidden: {value}")
    parsed = urlparse(value)
    if parsed.scheme != "guanlan" or not parsed.netloc:
        raise ValidationFailure(f"reference must use guanlan:// URI: {value}")
    allowed = allowed_kinds or {"asset", "manifest", "report", "sidecar", "material"}
    if parsed.netloc not in allowed:
        raise ValidationFailure(f"unsupported reference kind: {parsed.netloc}")
    parts = [part for part in parsed.path.split("/") if part]
    if parsed.netloc in {"asset", "report"}:
        if len(parts) != 1 or not ASSET_ID_RE.fullmatch(parts[0]):
            raise ValidationFailure(f"invalid asset/report reference: {value}")
    elif parsed.netloc == "sidecar":
        if len(parts) != 1 or not SIDECAR_ID_RE.fullmatch(parts[0]):
            raise ValidationFailure(f"invalid sidecar reference: {value}")
    elif parsed.netloc == "manifest":
        if (
            len(parts) != 2
            or not MATERIAL_ID_RE.fullmatch(parts[0])
            or not REVISION_ID_RE.fullmatch(parts[1])
        ):
            raise ValidationFailure(f"invalid manifest reference: {value}")
    elif parsed.netloc == "material":
        if (
            len(parts) != 3
            or not MATERIAL_ID_RE.fullmatch(parts[0])
            or parts[1] != "revision"
            or not REVISION_ID_RE.fullmatch(parts[2])
        ):
            raise ValidationFailure(f"invalid material reference: {value}")


def require_keys(value: dict, keys: tuple[str, ...], context: str) -> None:
    missing = [key for key in keys if key not in value]
    if missing:
        raise ValidationFailure(f"{context} missing keys: {', '.join(missing)}")


def validate_content_block(block: dict, name: str) -> list[str]:
    require_keys(block, ("storage", "content_hash", "media_type"), f"content.{name}")
    validate_content_hash(block["content_hash"])
    if block["storage"] == "inline":
        if "text" not in block:
            raise ValidationFailure(f"content.{name}.text is required for inline storage")
        actual = sha256_bytes(block["text"].encode("utf-8"))
        if actual != block["content_hash"]:
            raise ValidationFailure(f"content.{name} inline content_hash mismatch")
        return []
    if block["storage"] == "reference":
        reference = block.get("reference", "")
        validate_logical_reference(reference, {"asset"})
        return [reference]
    raise ValidationFailure(f"content.{name}.storage must be inline or reference")


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValidationFailure(f"cannot read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise ValidationFailure(f"JSON root must be an object: {path}")
    return value


def validate_source_material(record: dict) -> list[str]:
    require_keys(
        record,
        (
            "protocol", "schema_version", "material_id", "revision_id", "source",
            "content", "evidence", "quality", "lifecycle",
            "asset_manifest_reference", "understanding_sidecar_reference",
        ),
        "source material",
    )
    if record["protocol"] != "source-material-v3":
        raise ValidationFailure("protocol must be source-material-v3")
    if record["schema_version"] != "3.0.0":
        raise ValidationFailure("schema_version must be 3.0.0")
    forbidden_keys = {
        "analysis", "summary", "key_points", "core_claims", "argument_chain",
        "argument_structure", "recommendation", "possible_value", "methodology",
    }

    def reject_understanding_fields(value: object, path: str = "$") -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in forbidden_keys:
                    raise ValidationFailure(
                        f"understanding/generation field is forbidden at {path}.{key}"
                    )
                reject_understanding_fields(item, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                reject_understanding_fields(item, f"{path}[{index}]")

    reject_understanding_fields(record)
    if not MATERIAL_ID_RE.fullmatch(record["material_id"]):
        raise ValidationFailure("invalid material_id")
    if not REVISION_ID_RE.fullmatch(record["revision_id"]):
        raise ValidationFailure("invalid revision_id")

    source = record["source"]
    require_keys(
        source,
        ("platform", "source_id", "source_url", "title", "author", "captured_at"),
        "source",
    )
    expected_material = material_id_from_source_key(
        source_key(source["platform"], source["source_id"], source["source_url"])
    )
    if record["material_id"] != expected_material:
        raise ValidationFailure("material_id does not match stable source identity")

    content = record["content"]
    require_keys(content, ("raw", "readable"), "content")
    references = []
    references.extend(validate_content_block(content["raw"], "raw"))
    references.extend(validate_content_block(content["readable"], "readable"))
    if "operations" not in content["readable"]:
        raise ValidationFailure("content.readable.operations is required")

    if not isinstance(record["evidence"], list):
        raise ValidationFailure("evidence must be an array")
    evidence_ids = set()
    for item in record["evidence"]:
        require_keys(
            item, ("evidence_id", "kind", "reference", "content_hash", "uncertainty"),
            "evidence item",
        )
        if item["evidence_id"] in evidence_ids:
            raise ValidationFailure(f"duplicate evidence_id: {item['evidence_id']}")
        evidence_ids.add(item["evidence_id"])
        validate_content_hash(item["content_hash"])
        validate_logical_reference(item["reference"], {"asset"})
        references.append(item["reference"])
        start, end = item.get("start_time"), item.get("end_time")
        if start is not None and end is not None and float(end) < float(start):
            raise ValidationFailure(f"invalid evidence time range: {item['evidence_id']}")

    quality = record["quality"]
    require_keys(
        quality,
        (
            "capture_status", "content_fidelity", "transcript_quality",
            "review_required", "uncertainties",
        ),
        "quality",
    )
    if quality["capture_status"] not in {"complete", "partial"}:
        raise ValidationFailure("quality.capture_status must be complete or partial")
    if quality["content_fidelity"] not in {"full", "partial"}:
        raise ValidationFailure("quality.content_fidelity must be full or partial")
    if quality["transcript_quality"] not in {
        "not_applicable", "raw", "readable", "partial"
    }:
        raise ValidationFailure("invalid quality.transcript_quality")
    if quality["review_required"] is not True:
        raise ValidationFailure("quality.review_required must be true")
    if not isinstance(quality["uncertainties"], list):
        raise ValidationFailure("quality.uncertainties must be an array")

    lifecycle = record["lifecycle"]
    require_keys(
        lifecycle,
        ("status", "review_status", "created_at", "updated_at", "processing_history"),
        "lifecycle",
    )
    if lifecycle["status"] not in {"captured", "partial", "reviewed", "archived"}:
        raise ValidationFailure("invalid lifecycle.status")
    if lifecycle["review_status"] not in {
        "pending", "reviewed", "convert_approved", "archived"
    }:
        raise ValidationFailure("invalid lifecycle.review_status")
    if not isinstance(lifecycle["processing_history"], list):
        raise ValidationFailure("lifecycle.processing_history must be an array")
    for history in lifecycle["processing_history"]:
        if not isinstance(history, dict):
            raise ValidationFailure("processing_history entries must be objects")
        report_reference = history.get("report_reference", "")
        if report_reference:
            validate_logical_reference(report_reference, {"report"})
            references.append(report_reference)

    validate_logical_reference(record["asset_manifest_reference"], {"manifest"})
    references.append(record["asset_manifest_reference"])
    sidecar_reference = record["understanding_sidecar_reference"]
    if sidecar_reference:
        validate_logical_reference(sidecar_reference, {"sidecar"})
        references.append(sidecar_reference)

    expected_revision = revision_id(record)
    if record["revision_id"] != expected_revision:
        raise ValidationFailure("revision_id does not match canonical revision payload")

    def scan_temp(value: object, path: str = "$") -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                scan_temp(item, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                scan_temp(item, f"{path}[{index}]")
        elif isinstance(value, str) and is_temp_reference(value):
            raise ValidationFailure(f"temporary path at {path}: {value}")

    scan_temp(record)
    return references


def validate_manifest(
    manifest: dict,
    asset_root: Path | None,
    check_files: bool,
    allow_temporary_root: bool = False,
) -> dict:
    require_keys(
        manifest,
        ("protocol", "schema_version", "material_id", "revision_id", "entries"),
        "manifest",
    )
    if manifest["protocol"] != "reference-manifest-v1":
        raise ValidationFailure("manifest protocol must be reference-manifest-v1")
    if manifest["schema_version"] != "1.0.0":
        raise ValidationFailure("manifest schema_version must be 1.0.0")
    if not MATERIAL_ID_RE.fullmatch(manifest["material_id"]):
        raise ValidationFailure("manifest material_id is invalid")
    if not REVISION_ID_RE.fullmatch(manifest["revision_id"]):
        raise ValidationFailure("manifest revision_id is invalid")
    if not isinstance(manifest["entries"], list):
        raise ValidationFailure("manifest entries must be an array")
    if check_files and asset_root is None:
        raise ValidationFailure("--asset-root is required with --check-files")
    if asset_root and not allow_temporary_root and (
        str(asset_root.resolve()).startswith(TEMP_PREFIXES)
        or asset_root.resolve() == Path("/tmp")
        or asset_root.resolve() == Path("/private/tmp")
    ):
        raise ValidationFailure("formal asset root cannot be under /tmp or /private/tmp")

    references = {}
    checked_files = 0
    for entry in manifest["entries"]:
        require_keys(
            entry,
            (
                "reference", "asset_id", "role", "storage_relative_path",
                "content_hash", "media_type", "size_bytes",
            ),
            "manifest entry",
        )
        validate_logical_reference(entry["reference"], {"asset", "report"})
        validate_content_hash(entry["content_hash"])
        expected_asset = asset_id_from_hash(entry["content_hash"])
        if entry["asset_id"] != expected_asset or not ASSET_ID_RE.fullmatch(
            entry["asset_id"]
        ):
            raise ValidationFailure("manifest asset_id/content_hash mismatch")
        if entry["reference"] in references:
            raise ValidationFailure(f"duplicate manifest reference: {entry['reference']}")
        references[entry["reference"]] = entry
        relative = PurePosixPath(entry["storage_relative_path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValidationFailure("manifest storage_relative_path is unsafe")
        if is_temp_reference(entry["storage_relative_path"]):
            raise ValidationFailure("manifest contains temporary storage path")
        if check_files:
            root = asset_root.resolve()
            target = (root / Path(*relative.parts)).resolve()
            if os.path.commonpath([str(root), str(target)]) != str(root):
                raise ValidationFailure("manifest target escapes asset root")
            if not target.is_file():
                raise ValidationFailure(f"manifest asset is missing: {target}")
            if target.stat().st_size != int(entry["size_bytes"]):
                raise ValidationFailure(f"manifest asset size mismatch: {target}")
            if sha256_file(target) != entry["content_hash"]:
                raise ValidationFailure(f"manifest asset hash mismatch: {target}")
            checked_files += 1
    return {"references": references, "checked_files": checked_files}


def validate_source_against_manifest(
    record: dict, manifest: dict, manifest_result: dict
) -> None:
    if record["material_id"] != manifest["material_id"]:
        raise ValidationFailure("source material/manifest material_id mismatch")
    if record["revision_id"] != manifest["revision_id"]:
        raise ValidationFailure("source material/manifest revision_id mismatch")
    available = manifest_result["references"]
    for reference in validate_source_material(record):
        parsed = urlparse(reference)
        if parsed.netloc in {"asset", "report"} and reference not in available:
            raise ValidationFailure(f"reference is absent from manifest: {reference}")
    for name in ("raw", "readable"):
        block = record["content"][name]
        if block["storage"] == "reference":
            entry = available[block["reference"]]
            if entry["content_hash"] != block["content_hash"]:
                raise ValidationFailure(
                    f"content.{name} hash does not match manifest entry"
                )
    for item in record["evidence"]:
        entry = available[item["reference"]]
        if entry["content_hash"] != item["content_hash"]:
            raise ValidationFailure(
                f"evidence hash does not match manifest: {item['evidence_id']}"
            )


def identity_command(args: argparse.Namespace) -> dict:
    key = args.source_key or source_key(args.platform, args.source_id, args.source_url)
    output = {
        "source_key": key,
        "material_id": material_id_from_source_key(key),
    }
    if args.content_hash:
        validate_content_hash(args.content_hash)
        output["content_hash"] = args.content_hash
        output["asset_id"] = asset_id_from_hash(args.content_hash)
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(dest="command", required=True)

    identity_parser = subcommands.add_parser("identity")
    identity_parser.add_argument("--source-key")
    identity_parser.add_argument("--platform", default="")
    identity_parser.add_argument("--source-id", default="")
    identity_parser.add_argument("--source-url", default="")
    identity_parser.add_argument("--content-hash")

    hash_parser = subcommands.add_parser("hash-file")
    hash_parser.add_argument("--file", required=True)

    source_parser = subcommands.add_parser("validate-source-material")
    source_parser.add_argument("--input", required=True)
    source_parser.add_argument("--manifest")
    source_parser.add_argument("--asset-root")
    source_parser.add_argument("--check-files", action="store_true")
    source_parser.add_argument("--scope", choices=("formal", "test"), default="formal")

    manifest_parser = subcommands.add_parser("validate-manifest")
    manifest_parser.add_argument("--manifest", required=True)
    manifest_parser.add_argument("--asset-root")
    manifest_parser.add_argument("--check-files", action="store_true")
    manifest_parser.add_argument("--scope", choices=("formal", "test"), default="formal")

    args = parser.parse_args()
    try:
        if args.command == "identity":
            result = identity_command(args)
        elif args.command == "hash-file":
            content_hash = sha256_file(Path(args.file))
            result = {
                "content_hash": content_hash,
                "asset_id": asset_id_from_hash(content_hash),
            }
        elif args.command == "validate-manifest":
            manifest = load_json(Path(args.manifest))
            checked = validate_manifest(
                manifest,
                Path(args.asset_root) if args.asset_root else None,
                args.check_files,
                args.scope == "test",
            )
            result = {
                "status": "valid",
                "entry_count": len(checked["references"]),
                "checked_files": checked["checked_files"],
            }
        else:
            record = load_json(Path(args.input))
            references = validate_source_material(record)
            result = {
                "status": "valid",
                "material_id": record["material_id"],
                "revision_id": record["revision_id"],
                "reference_count": len(references),
            }
            if args.manifest:
                manifest = load_json(Path(args.manifest))
                checked = validate_manifest(
                    manifest,
                    Path(args.asset_root) if args.asset_root else None,
                    args.check_files,
                    args.scope == "test",
                )
                validate_source_against_manifest(record, manifest, checked)
                result["manifest_status"] = "valid"
                result["checked_files"] = checked["checked_files"]
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except ValidationFailure as error:
        print(
            json.dumps(
                {"status": "invalid", "error": str(error)},
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
