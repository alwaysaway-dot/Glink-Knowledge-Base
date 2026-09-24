#!/usr/bin/env python3
"""Guanlan Unified Operation Envelope v1.

This module is an audit index over canonical domain records.  It deliberately
does not decide asset identity, workflow state, approval, publication or
relation truth.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


SCHEMA_VERSION = "1.0.0"
IMPLEMENTATION_VERSION = "guanlan-v1.2-c-au-b1"
OPERATION_TYPES = {"capture", "transcript", "source_reconciliation", "organize", "publish", "relation_curation"}
STATUSES = {"started", "completed", "failed", "partial", "blocked", "interrupted", "needs_reconciliation"}
TERMINAL = STATUSES - {"started"}
OP_ID = re.compile(r"^op_(capture|transcript|source_reconciliation|organize|publish|relation_curation)_[0-9a-f]{32}$")
STABLE_REF = re.compile(r"^guanlan://[A-Za-z0-9._~:/-]+$")
SENSITIVE = re.compile(r"(?i)(authorization|cookie|token|secret|credential|password|session)[\"']?\s*[:=]")
ALLOWED_FIELDS = {
    "schema_version", "operation_id", "operation_type", "implementation_version",
    "started_at", "completed_at", "status", "parent_operation_id", "retry_of", "resume_of",
    "input_refs", "output_refs", "receipt_refs", "stage_refs", "change_refs", "warnings",
    "failure_class", "failure_detail", "failure_ref", "duration_ms", "record_origin",
    "canonical_authority", "canonical_conflict",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def atomic_write(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    try:
        with temporary.open("wb") as handle:
            handle.write(value); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(descriptor)
        finally: os.close(descriptor)
    finally:
        if temporary.exists(): temporary.unlink()


def new_operation_id(operation_type: str) -> str:
    if operation_type not in OPERATION_TYPES:
        raise ValueError(f"unsupported operation type: {operation_type}")
    return f"op_{operation_type}_{uuid.uuid4().hex}"


def validate_ref(value: str) -> str:
    if not STABLE_REF.fullmatch(value):
        raise ValueError(f"operation references must be stable guanlan:// refs: {value}")
    return value


def normalize_refs(values: Iterable[str] | None) -> list[str]:
    return sorted(set(validate_ref(str(value)) for value in (values or []) if value))


def clean_failure_detail(value: str | None) -> str | None:
    if not value: return None
    text = " ".join(str(value).split())[:500]
    text = re.sub(r"(?i)(authorization|cookie|token|secret|credential|password|session)\s*[:=]\s*\S+", r"\1=[REDACTED]", text)
    return text


def validate_record(record: dict) -> None:
    required = {"schema_version", "operation_id", "operation_type", "implementation_version", "started_at", "status", "input_refs", "output_refs", "receipt_refs", "stage_refs", "change_refs", "warnings"}
    missing = required - record.keys()
    if missing: raise ValueError(f"operation envelope missing fields: {sorted(missing)}")
    unknown = record.keys() - ALLOWED_FIELDS
    if unknown: raise ValueError(f"operation envelope contains non-contract fields: {sorted(unknown)}")
    if record["schema_version"] != SCHEMA_VERSION: raise ValueError("unsupported operation schema")
    if record["operation_type"] not in OPERATION_TYPES or not OP_ID.fullmatch(record["operation_id"]): raise ValueError("invalid operation identity")
    if record["status"] not in STATUSES: raise ValueError("invalid operation status")
    for field in ("input_refs", "output_refs", "receipt_refs", "stage_refs", "change_refs"):
        normalize_refs(record[field])
    raw = json.dumps(record, ensure_ascii=False)
    if SENSITIVE.search(raw):
        # Field names in failure text are redacted before this check; credentials
        # must never appear elsewhere in a formal envelope.
        if "[REDACTED]" not in raw: raise ValueError("sensitive authentication data in operation envelope")


def operation_files(root: Path):
    if not root.exists(): return []
    return sorted(root.glob("[0-9][0-9][0-9][0-9]-[0-9][0-9]/op_*.json"))


def get_operation(root: Path, operation_id: str) -> dict | None:
    if not OP_ID.fullmatch(operation_id): raise ValueError("invalid operation id")
    matches = [path for path in operation_files(root) if path.stem == operation_id]
    if len(matches) > 1: raise ValueError("duplicate operation records")
    if not matches: return None
    value = json.loads(matches[0].read_text(encoding="utf-8")); validate_record(value); return value


def find_by_reference(root: Path, reference: str, operation_type: str | None = None, started_after: str | None = None) -> dict:
    validate_ref(reference)
    records, corrupt = [], []
    for path in operation_files(root):
        try:
            value = json.loads(path.read_text(encoding="utf-8")); validate_record(value)
        except (OSError, ValueError, json.JSONDecodeError):
            corrupt.append(str(path)); continue
        refs = sum((value.get(field, []) for field in ("input_refs", "output_refs", "receipt_refs", "stage_refs", "change_refs")), [])
        if reference not in refs: continue
        if operation_type and value["operation_type"] != operation_type: continue
        if started_after and value["started_at"] < started_after: continue
        records.append(value)
    return {"operations": sorted(records, key=lambda item: item["started_at"]), "corrupt_records": corrupt}


class OperationRecorder:
    """Best-effort writer.  Domain callers must never fail because this index fails."""

    def __init__(self, root: Path, operation_type: str, *, operation_id: str | None = None,
                 input_refs: Iterable[str] | None = None, parent_operation_id: str | None = None,
                 retry_of: str | None = None, resume_of: str | None = None,
                 implementation_version: str = IMPLEMENTATION_VERSION, started_at: str | None = None):
        self.root = Path(root).resolve(); self.operation_type = operation_type
        self.operation_id = operation_id or new_operation_id(operation_type)
        self.started_at = started_at or utc_now(); self.warning: str | None = None; self.path: Path | None = None
        try:
            if not OP_ID.fullmatch(self.operation_id) or not self.operation_id.startswith(f"op_{operation_type}_"):
                raise ValueError("operation id/type mismatch")
            for link in (parent_operation_id, retry_of, resume_of):
                if link is not None and not OP_ID.fullmatch(link): raise ValueError("invalid operation linkage")
            existing = get_operation(self.root, self.operation_id)
            if existing:
                if existing["operation_type"] != operation_type: raise ValueError("operation identity conflict")
                self.started_at = existing["started_at"]
                self.path = next(path for path in operation_files(self.root) if path.stem == self.operation_id)
                return
            month = self.started_at[:7]
            self.path = self.root / month / f"{self.operation_id}.json"
            record = {
                "schema_version": SCHEMA_VERSION, "operation_id": self.operation_id,
                "operation_type": operation_type, "implementation_version": implementation_version,
                "started_at": self.started_at, "completed_at": None, "status": "started",
                "parent_operation_id": parent_operation_id, "retry_of": retry_of, "resume_of": resume_of,
                "input_refs": normalize_refs(input_refs), "output_refs": [], "receipt_refs": [],
                "stage_refs": [], "change_refs": [], "warnings": [], "failure_class": None,
                "failure_detail": None, "failure_ref": None, "duration_ms": None,
                "record_origin": "live_operation", "canonical_authority": False,
            }
            validate_record(record); atomic_write(self.path, canonical(record))
        except Exception as error:
            self.warning = f"operation_index_write_failed:{type(error).__name__}:{clean_failure_detail(str(error))}"
            self.path = None

    @classmethod
    def unavailable(cls, operation_type: str, detail: str):
        value = cls.__new__(cls)
        value.root = Path("/dev/null"); value.operation_type = operation_type
        value.operation_id = new_operation_id(operation_type); value.started_at = utc_now(); value.path = None
        value.warning = f"operation_index_write_failed:Unavailable:{clean_failure_detail(detail)}"
        return value

    def finish(self, status: str, *, output_refs: Iterable[str] | None = None,
               receipt_refs: Iterable[str] | None = None, stage_refs: Iterable[str] | None = None,
               change_refs: Iterable[str] | None = None, warnings: Iterable[str] | None = None,
               failure_class: str | None = None, failure_detail: str | None = None,
               failure_ref: str | None = None, completed_at: str | None = None) -> str | None:
        if status not in TERMINAL: raise ValueError("finish requires terminal status")
        if self.path is None: return self.warning
        try:
            record = json.loads(self.path.read_text(encoding="utf-8")); validate_record(record)
            completed = completed_at or utc_now()
            if record["status"] in TERMINAL:
                desired = (status, normalize_refs(output_refs), normalize_refs(receipt_refs))
                current = (record["status"], record["output_refs"], record["receipt_refs"])
                if desired != current: raise ValueError("duplicate completion conflicts with existing envelope")
                return self.warning
            record.update({
                "completed_at": completed, "status": status,
                "output_refs": normalize_refs(output_refs), "receipt_refs": normalize_refs(receipt_refs),
                "stage_refs": normalize_refs(stage_refs), "change_refs": normalize_refs(change_refs),
                "warnings": sorted(set(str(item)[:240] for item in (warnings or []) if item)),
                "failure_class": failure_class, "failure_detail": clean_failure_detail(failure_detail),
                "failure_ref": validate_ref(failure_ref) if failure_ref else None,
            })
            start = datetime.fromisoformat(record["started_at"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(completed.replace("Z", "+00:00"))
            record["duration_ms"] = max(0, int((end - start).total_seconds() * 1000))
            validate_record(record); atomic_write(self.path, canonical(record)); return self.warning
        except Exception as error:
            self.warning = f"operation_index_write_failed:{type(error).__name__}:{clean_failure_detail(str(error))}"
            return self.warning


def reconcile_operation(root: Path, operation_id: str, *, canonical_ref: str,
                        canonical_status: str | None, observed_at: str | None = None) -> dict:
    """Reconcile a missing/started envelope from explicit canonical evidence.

    The caller supplies an already validated canonical status. Unknown evidence
    never becomes failure merely because time passed.
    """
    validate_ref(canonical_ref)
    status_map = {"completed": "completed", "failed": "failed", "partial": "partial", "blocked": "blocked"}
    target = status_map.get(str(canonical_status))
    existing = get_operation(Path(root), operation_id)
    if existing and existing["status"] in TERMINAL:
        if target and existing["status"] != target:
            existing["canonical_conflict"] = {"reference": canonical_ref, "canonical_status": canonical_status}
            existing["status"] = "needs_reconciliation"
            path = next(path for path in operation_files(Path(root)) if path.stem == operation_id)
            validate_record(existing); atomic_write(path, canonical(existing))
        return existing
    operation_type = OP_ID.fullmatch(operation_id).group(1) if OP_ID.fullmatch(operation_id) else None
    if not operation_type: raise ValueError("invalid operation id")
    if existing is None:
        recorder = OperationRecorder(Path(root), operation_type, operation_id=operation_id, input_refs=[canonical_ref], started_at=observed_at or utc_now())
        if recorder.path is None: raise OSError(recorder.warning)
        record = json.loads(recorder.path.read_text(encoding="utf-8")); record["record_origin"] = "canonical_reconciliation"
        atomic_write(recorder.path, canonical(record))
    else:
        recorder = OperationRecorder(Path(root), operation_type, operation_id=operation_id)
    if target:
        recorder.finish(target, output_refs=[canonical_ref], completed_at=observed_at or utc_now())
    else:
        record = json.loads(recorder.path.read_text(encoding="utf-8")); record["status"] = "needs_reconciliation"
        record["warnings"] = sorted(set(record.get("warnings", []) + ["canonical_result_unknown"]))
        validate_record(record); atomic_write(recorder.path, canonical(record))
    return get_operation(Path(root), operation_id)
