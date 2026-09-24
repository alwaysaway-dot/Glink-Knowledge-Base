#!/usr/bin/env python3
"""Small mutation-safety layer for existing Learning/Derivative publishers.

The original publish receipt remains canonical.  The journal only explains an
unfinished multi-file write and permits guarded recovery under the ledger lock.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def file_hash(path: Path) -> str:
    return sha(path.read_bytes()) if path.is_file() else "missing"


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def durable_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}-{uuid.uuid4().hex}")
    try:
        with temporary.open("xb") as handle:
            handle.write(data); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(descriptor)
        finally: os.close(descriptor)
    finally:
        if temporary.exists(): temporary.unlink()


def durable_json(path: Path, value: dict) -> None:
    durable_write(path, canonical(value))


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@contextmanager
def ledger_lock(governance: Path, *, timeout_seconds: float = 10):
    """Kernel-owned flock; a dead PID releases automatically, no mtime guess."""
    governance.mkdir(parents=True, exist_ok=True)
    lock_path = governance / ".publisher-ledger.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    acquired = False
    try:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB); acquired = True; break
            except BlockingIOError:
                time.sleep(0.05)
        if not acquired: raise ValueError("publisher_ledger_lock_busy")
        durable_json(governance / "lock-owner.json", {"pid": os.getpid(), "acquired_at": now(), "token": uuid.uuid4().hex})
        yield
    finally:
        if acquired: fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def inject(point: str, fault: str, scope: str) -> None:
    if scope != "test" or fault in {"", "none"}: return
    if fault == point: raise OSError(f"injected_{point}")
    if fault == f"kill:{point}": os._exit(91)


def index_contains(index: dict, transaction_id: str) -> bool:
    return any(item.get("transaction_id") == transaction_id for item in index.get("publications", []))


def check_index(index_path: Path, journal: dict) -> dict:
    if index_path.is_file():
        index = read_json(index_path)
    else:
        index = journal["index_initial"]
    current = file_hash(index_path)
    if current != journal["index_predecessor_hash"] and not index_contains(index, journal["transaction_id"]):
        raise ValueError("publisher_index_conflict: predecessor changed outside transaction")
    return index


def recover_one(journal_path: Path, *, governance: Path, vault_root: Path, fault: str = "none", scope: str = "production") -> str:
    journal = read_json(journal_path)
    inject("during_recovery", fault, scope)
    if journal.get("protocol") != "publisher-transaction-journal-v1": raise ValueError("publisher_journal_invalid")
    if journal.get("state") == "committed": return "already_committed"
    if journal.get("state") in {"rolled_back", "safe_to_discard"}: return "safe_to_discard"
    if journal.get("state") == "conflict": raise ValueError("publisher_recovery_conflict: journal requires manual reconciliation")
    target = Path(journal["target_path"]); receipt_path = Path(journal["receipt_path"])
    stage = Path(journal["stage_path"])
    index_path = Path(journal["index_path"]); prepared = Path(journal["prepared_receipt_path"])
    if (vault_root.resolve() not in target.resolve().parents or
            governance.resolve() not in receipt_path.resolve().parents or
            index_path.parent.resolve() != governance.resolve() or
            stage.parent.resolve() != target.parent.resolve() or
            prepared.parent.resolve() != journal_path.parent.resolve()):
        raise ValueError("publisher_recovery_path_conflict")
    expected = journal["projection_hash"]
    actual = file_hash(target)
    if actual not in {"missing", expected}:
        journal["state"] = "conflict"; journal["recovery_state"] = "needs_reconciliation"
        durable_json(journal_path, journal)
        raise ValueError("publisher_recovery_conflict: target externally modified")
    if actual == "missing":
        if receipt_path.is_file() and read_json(receipt_path).get("validation_result") == "committed":
            journal["state"] = "conflict"; journal["recovery_state"] = "needs_reconciliation"
            durable_json(journal_path, journal)
            raise ValueError("publisher_recovery_conflict: committed receipt without asset")
        if stage.exists():
            if file_hash(stage) != expected:
                journal["state"] = "conflict"; journal["recovery_state"] = "needs_reconciliation"
                durable_json(journal_path, journal)
                raise ValueError("publisher_recovery_conflict: staged asset changed")
            os.replace(stage, journal_path.parent / "abandoned-stage.md")
        journal["state"] = "safe_to_discard"; journal["recovery_state"] = "safe_to_discard"
        durable_json(journal_path, journal)
        return "safe_to_discard"
    if stage.exists():
        if file_hash(stage) != expected:
            journal["state"] = "conflict"; journal["recovery_state"] = "needs_reconciliation"
            durable_json(journal_path, journal)
            raise ValueError("publisher_recovery_conflict: leftover stage changed")
        os.replace(stage, journal_path.parent / "recovered-stage.md")
    if not prepared.is_file() or file_hash(prepared) != journal["prepared_receipt_hash"]:
        journal["state"] = "conflict"; journal["recovery_state"] = "needs_reconciliation"
        durable_json(journal_path, journal)
        raise ValueError("publisher_recovery_conflict: prepared receipt missing or changed")
    receipt = read_json(prepared)
    if (receipt.get("transaction_id") != journal["transaction_id"] or
            receipt.get("projection_hash") != expected or
            receipt.get("approval_binding_hash") != journal.get("approval_binding_hash")):
        raise ValueError("publisher_recovery_conflict: prepared receipt does not match journal")
    index = check_index(index_path, journal)
    if receipt_path.is_file():
        existing = read_json(receipt_path)
        if (existing.get("transaction_id") != journal["transaction_id"] or
                existing.get("validation_result") != "committed" or
                existing.get("projection_hash") != expected or
                existing.get("approval_binding_hash") != journal.get("approval_binding_hash")):
            raise ValueError("publisher_recovery_conflict: formal receipt differs")
        for key, value in receipt.items():
            if key not in {"validation_result", "relation_hook_status"} and existing.get(key) != value:
                raise ValueError("publisher_recovery_conflict: formal receipt fields differ")
    else:
        receipt["validation_result"] = "committed"; receipt["committed_at"] = now()
        durable_json(receipt_path, receipt)
    for item in index.get("publications", []):
        if item.get("transaction_id") == journal["transaction_id"] and item != journal["index_item"]:
            raise ValueError("publisher_recovery_conflict: index item differs")
    if not index_contains(index, journal["transaction_id"]):
        index["publications"].append(journal["index_item"]); index["updated_at"] = now()
        durable_json(index_path, index)
    journal["state"] = "committed"; journal["recovery_state"] = "safe_to_resume"; journal["completed_steps"] = ["asset", "receipt", "index", "commit"]
    durable_json(journal_path, journal)
    durable_json(journal_path.parent / "commit.json", {"status": "committed", "target": str(target), "receipt": str(receipt_path)})
    return "safe_to_resume"


def recover_pending(governance: Path, vault_root: Path, *, fault: str = "none", scope: str = "production") -> list[dict]:
    outcomes = []
    for path in sorted((governance / "transactions").glob("*/journal.json")):
        state = read_json(path).get("state")
        if state in {"committed", "rolled_back", "safe_to_discard"}: continue
        outcomes.append({"journal": str(path), "result": recover_one(path, governance=governance, vault_root=vault_root, fault=fault, scope=scope)})
    return outcomes


def archive_retryable(tx_dir: Path) -> None:
    """Preserve rolled-back/staging evidence while allowing a fresh retry."""
    journal_path = tx_dir / "journal.json"
    if not journal_path.is_file():
        if tx_dir.exists(): raise ValueError("publisher_transaction_dir_without_journal")
        return
    state = read_json(journal_path).get("state")
    if state not in {"rolled_back", "safe_to_discard"}:
        raise ValueError("publisher_transaction_unfinished")
    history = tx_dir.parent / "history"; history.mkdir(parents=True, exist_ok=True)
    os.replace(tx_dir, history / f"{tx_dir.name}-{uuid.uuid4().hex}")


def commit(*, governance: Path, vault_root: Path, target: Path, target_bytes: bytes, receipt: dict,
           receipt_path: Path, index_path: Path, index: dict, index_item: dict, tx_dir: Path,
           fault: str, scope: str) -> dict:
    transaction_id = receipt["transaction_id"]
    journal_path = tx_dir / "journal.json"; prepared = tx_dir / "receipt.prepared.json"
    if target.exists() or receipt_path.exists() or journal_path.exists():
        raise ValueError("publisher_predecessor_conflict: target, receipt, or transaction already exists")
    tx_dir.mkdir(parents=True, exist_ok=False)
    staged = target.with_name(f".{transaction_id}.{uuid.uuid4().hex}.stage")
    if staged.exists(): raise ValueError("publisher_staging_conflict")
    journal = {
        "protocol": "publisher-transaction-journal-v1", "schema_version": "1.0.0",
        "transaction_id": transaction_id, "created_at": now(), "state": "prepared", "recovery_state": "not_started",
        "asset_id": index_item.get("asset_id") or index_item.get("knowledge_asset_id"),
        "candidate_id": index_item.get("candidate_id"), "approval_binding_hash": receipt.get("approval_binding_hash"),
        "target_path": str(target), "receipt_path": str(receipt_path), "index_path": str(index_path),
        "stage_path": str(staged), "prepared_receipt_path": str(prepared),
        "projection_hash": sha(target_bytes), "index_predecessor_hash": file_hash(index_path),
        "prepared_receipt_hash": sha(canonical(receipt)), "index_initial": index if not index_path.exists() else None,
        "index_item": index_item, "completed_steps": [], "commit_marker": False,
    }
    durable_json(prepared, receipt)
    durable_json(journal_path, journal)
    inject("after_journal", fault, scope)
    durable_write(staged, target_bytes)
    journal["completed_steps"].append("staging"); durable_json(journal_path, journal)
    inject("after_staging", fault, scope)
    inject("before_asset", fault, scope)
    # Create-only publication: an out-of-band writer cannot be overwritten.
    os.link(staged, target)
    staged.unlink()
    descriptor = os.open(target.parent, os.O_RDONLY)
    try: os.fsync(descriptor)
    finally: os.close(descriptor)
    journal["completed_steps"].append("asset"); durable_json(journal_path, journal)
    inject("after_asset", fault, scope)
    inject("prepared_receipt", fault, scope)
    if file_hash(target) != journal["projection_hash"]: raise ValueError("publisher_asset_hash_conflict")
    if file_hash(index_path) != journal["index_predecessor_hash"]: raise ValueError("publisher_index_conflict")
    if receipt_path.exists(): raise ValueError("publisher_receipt_predecessor_conflict")
    receipt["validation_result"] = "committed"; receipt["committed_at"] = now()
    inject("committed_receipt_before", fault, scope)
    inject("before_receipt", fault, scope)
    durable_json(receipt_path, receipt)
    journal["completed_steps"].append("receipt"); durable_json(journal_path, journal)
    inject("after_receipt", fault, scope)
    inject("committed_receipt_after", fault, scope)
    inject("before_index", fault, scope)
    if file_hash(index_path) != journal["index_predecessor_hash"]: raise ValueError("publisher_index_conflict")
    index["publications"].append(index_item); index["updated_at"] = now(); durable_json(index_path, index)
    journal["completed_steps"].append("index"); durable_json(journal_path, journal)
    inject("after_index", fault, scope)
    journal["state"] = "committed"; journal["commit_marker"] = True; journal["completed_steps"].append("commit")
    durable_json(journal_path, journal)
    durable_json(tx_dir / "commit.json", {"status": "committed", "target": str(target), "receipt": str(receipt_path)})
    inject("after_commit", fault, scope)
    return {"status": "published", "target": str(target), "receipt": str(receipt_path)}


def guarded_abort(tx_dir: Path, *, target: Path, receipt_path: Path) -> str:
    journal_path = tx_dir / "journal.json"
    if not journal_path.is_file(): return "not_started"
    journal = read_json(journal_path)
    if journal.get("state") == "committed": return "already_committed"
    if receipt_path.is_file() and read_json(receipt_path).get("validation_result") == "committed":
        return "safe_to_resume"
    stage = Path(journal["stage_path"])
    if stage.exists():
        if file_hash(stage) != journal["projection_hash"]:
            journal["state"] = "conflict"; durable_json(journal_path, journal)
            return "needs_reconciliation"
        os.replace(stage, tx_dir / "rollback-stage.md")
    if target.exists():
        if file_hash(target) != journal["projection_hash"]:
            journal["state"] = "conflict"; durable_json(journal_path, journal)
            return "needs_reconciliation"
        backup = tx_dir / "rollback-asset.md"
        if backup.exists(): return "needs_reconciliation"
        os.replace(target, backup)
    journal["state"] = "rolled_back"; journal["recovery_state"] = "guarded_rollback"
    durable_json(journal_path, journal)
    durable_json(tx_dir / "rollback.json", {"status": "rolled_back", "recoverable_asset": str(tx_dir / "rollback-asset.md")})
    return "rolled_back"
