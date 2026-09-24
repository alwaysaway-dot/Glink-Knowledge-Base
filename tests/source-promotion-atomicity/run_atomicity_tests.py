#!/usr/bin/env python3
"""Crash, retry, concurrency and atomic-visibility tests for Source Promotion."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROMOTION = ROOT / "source-material-generator/promote_readable_original_revision.py"
INGESTION = ROOT / "knowledge-ingestion-manager/source_asset_ingestion.py"
FAULT_ENV = "GUANLAN_SOURCE_PROMOTION_FAULT"
SIGNAL_ENV = "GUANLAN_SOURCE_PROMOTION_SIGNAL_FILE"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


freeze = load_module("atomicity_freeze_fixture", ROOT / "tests/freeze-closure/run_freeze_closure.py")


def run(command, *, env=None, success=True):
    result = subprocess.run([str(item) for item in command], text=True, capture_output=True, env=env)
    if success and result.returncode != 0:
        raise AssertionError(f"command failed ({result.returncode}): {' '.join(map(str, command))}\n{result.stdout}\n{result.stderr}")
    if not success and result.returncode == 0:
        raise AssertionError(f"command unexpectedly passed: {' '.join(map(str, command))}")
    return result


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def tree_hash(path: Path) -> str:
    value = hashlib.sha256()
    for item in sorted(entry for entry in path.rglob("*") if entry.is_file()):
        value.update(item.relative_to(path).as_posix().encode("utf-8"))
        value.update(item.read_bytes())
    return value.hexdigest()


def wait_for(path: Path, process: subprocess.Popen, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(f"process exited before pause point: {process.returncode}\n{stdout}\n{stderr}")
        time.sleep(0.02)
    process.kill()
    raise AssertionError(f"timed out waiting for {path}")


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: run_atomicity_tests.py OUTPUT_JSON [--keep]")
    output = Path(sys.argv[1]).resolve()
    keep = "--keep" in sys.argv[2:]
    base = Path(tempfile.mkdtemp(prefix="guanlan-source-promotion-atomicity.", dir="/private/tmp"))
    results = {"protocol": "source-promotion-atomicity-test-v1", "cases": [], "sandbox": str(base)}

    def record(case_id, name, status, observed, **extra):
        results["cases"].append({"id": case_id, "name": name, "status": status, "observed": observed, **extra})

    try:
        seed = freeze.build_case(base, "atomicity-seed", "audio", {
            "duration_seconds": 47, "segment_count": 3, "start_time": "00:00:00", "end_time": "00:00:47"
        })
        case = seed["dir"]

        def command(target: Path, summary: Path | None = None):
            return [
                sys.executable, PROMOTION,
                "--source-material", case / "source.json",
                "--manifest", case / "manifest.json",
                "--readable-original", case / "readable.md",
                "--quality-result", case / "quality.json",
                "--approval-input", case / "approval.json",
                "--source-type", "audio",
                "--asset-root", seed["root"],
                "--material-dir", target,
                "--project-root", ROOT,
                "--created-at", "2026-08-31T00:00:00Z",
                "--output-summary", summary or target.parent / (target.name + "-summary.json"),
                "--scope", "test",
            ]

        def env_for(fault_name: str, signal_file: Path | None = None, pause_seconds=60):
            value = os.environ.copy()
            value[FAULT_ENV] = fault_name
            value["GUANLAN_SOURCE_PROMOTION_PAUSE_SECONDS"] = str(pause_seconds)
            if signal_file:
                value[SIGNAL_ENV] = str(signal_file)
            return value

        def final_dirs(target: Path):
            revisions = target / "revisions"
            return [] if not revisions.exists() else sorted(
                item for item in revisions.iterdir() if item.is_dir() and not item.name.startswith(".")
            )

        def staging_dirs(target: Path):
            revisions = target / "revisions"
            return [] if not revisions.exists() else sorted(item for item in revisions.glob(".*.staging.*") if item.is_dir())

        def retry(target: Path):
            summary = target.parent / (target.name + "-retry.json")
            run(command(target, summary))
            value = json.loads(summary.read_text(encoding="utf-8"))
            assert value["transaction"]["status"] in {"committed", "already_committed"}
            assert len(final_dirs(target)) == 1
            assert not staging_dirs(target)
            assert not list((target / "revisions").glob("*.promotion.lock"))
            return value

        crash_points = (
            ("FI-01", "crash_after_staging_create"),
            ("FI-02", "crash_after_first_file"),
            ("FI-03", "crash_midway_files"),
            ("FI-04", "crash_before_manifest"),
            ("FI-05", "crash_after_manifest"),
            ("FI-06", "crash_after_validation"),
            ("FI-07", "crash_before_atomic_rename"),
        )
        for case_id, point in crash_points:
            target = base / case_id.lower()
            failed = run(command(target), env=env_for(point), success=False)
            assert failed.returncode == 86 and not final_dirs(target)
            before = [str(item.relative_to(target)) for item in staging_dirs(target)]
            recovered = retry(target)
            record(case_id, point, "PASS", "no partial final; retry committed", staging_before_retry=before,
                   recovery=recovered["transaction"]["recovery"])

        target = base / "fi-08"
        failed = run(command(target), env=env_for("crash_after_atomic_rename"), success=False)
        assert failed.returncode == 86 and len(final_dirs(target)) == 1
        recovered = retry(target)
        assert recovered["transaction"]["status"] == "already_committed"
        record("FI-08", "crash_after_atomic_rename", "PASS", "complete final detected; retry already_committed")

        for case_id, sig, point in (("FI-09", signal.SIGTERM, "pause_after_first_file"),
                                    ("FI-10", signal.SIGKILL, "pause_before_atomic_rename")):
            target = base / case_id.lower(); marker = base / f"{case_id}.signal"
            process = subprocess.Popen(command(target), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       env=env_for(point, marker, 60))
            wait_for(marker, process)
            os.kill(process.pid, sig)
            process.communicate(timeout=10)
            assert process.returncode != 0
            assert not final_dirs(target)
            retry(target)
            record(case_id, signal.Signals(sig).name, "PASS", "real child process killed; stale transaction recovered")

        for case_id, point in (("FI-11", "file_write_failure"), ("FI-12", "manifest_write_failure"),
                               ("FI-19", "flush_failure"),
                               ("FI-20", "disk_write_failure")):
            target = base / case_id.lower()
            failed = run(command(target), env=env_for(point), success=False)
            assert failed.returncode != 0 and not final_dirs(target)
            retry(target)
            record(case_id, point, "PASS", "explicit I/O failure left no final; retry committed")

        target = base / "fi-13"; marker = base / "FI-13.signal"
        permission_probe = subprocess.Popen(command(target), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                            env=env_for("pause_before_atomic_rename", marker, 2))
        wait_for(marker, permission_probe)
        revisions = target / "revisions"; original_mode = stat.S_IMODE(revisions.stat().st_mode)
        try:
            revisions.chmod(0o500)
            permission_out, permission_err = permission_probe.communicate(timeout=10)
        finally:
            revisions.chmod(original_mode)
        assert permission_probe.returncode != 0 and not final_dirs(target), permission_out + permission_err
        retry(target)
        record("FI-13", "final parent permission denied", "PASS",
               "real target-parent mode removal blocked rename; restored permission retry committed")

        target = base / "fi-14"; marker = base / "FI-14.signal"
        owner = subprocess.Popen(command(target), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 env=env_for("pause_before_atomic_rename", marker, 3))
        wait_for(marker, owner)
        contender = run(command(target, base / "fi-14-contender.json"), success=False)
        assert "concurrent_transaction_detected" in (contender.stderr + contender.stdout)
        owner_out, owner_err = owner.communicate(timeout=10)
        assert owner.returncode == 0, owner_out + owner_err
        retry(target)
        record("FI-14", "duplicate concurrent promotion", "PASS", "one owner committed; contender explicitly blocked")

        target = base / "fi-15"
        run(command(target), env=env_for("crash_after_first_file"), success=False)
        recovered = retry(target)
        actions = recovered["transaction"]["recovery"]["staging_actions"]
        assert any(item["state"] == "stale_incomplete" for item in actions)
        record("FI-15", "stale incomplete staging", "PASS", "detected, removed under lock, and rebuilt")

        target = base / "fi-16"
        run(command(target), env=env_for("crash_before_atomic_rename"), success=False)
        recovered = retry(target)
        actions = recovered["transaction"]["recovery"]["staging_actions"]
        assert any(item["state"] == "stale_valid" for item in actions)
        record("FI-16", "valid stale staging", "PASS", "revalidated and atomically committed")

        target = base / "fi-17"
        committed = retry(target); final = Path(committed["revision_directory"])
        projection = final / "source-asset-projection.md"
        projection.write_bytes(projection.read_bytes() + b"\nconflict\n")
        conflict = run(command(target, base / "fi-17-conflict.json"), success=False)
        assert "identity_conflict" in (conflict.stderr + conflict.stdout)
        record("FI-17", "same revision identity with changed content", "PASS", "strict identity conflict; no overwrite")

        target = base / "fi-18"
        first = retry(target); final = Path(first["revision_directory"]); initial_hash = tree_hash(final)
        statuses = []
        for index in range(5):
            summary = base / f"fi-18-retry-{index}.json"
            run(command(target, summary)); value = json.loads(summary.read_text(encoding="utf-8"))
            statuses.append(value["transaction"]["status"])
        assert statuses == ["already_committed"] * 5 and tree_hash(final) == initial_hash
        record("FI-18", "five identical retries", "PASS", "all already_committed; final tree hash unchanged",
               retries=5, final_hash=initial_hash)

        target = base / "fi-21"; marker = base / "FI-21.signal"
        owner = subprocess.Popen(command(target), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 env=env_for("pause_before_atomic_rename", marker, 60))
        wait_for(marker, owner)
        stages = staging_dirs(target); assert len(stages) == 1
        stage = stages[0]; vault = base / "fi-21-vault/10 原始资料"; vault.mkdir(parents=True)
        blocked = run([
            sys.executable, INGESTION, "--command", "ingest", "--scope", "test",
            "--source-material", stage / "source-material-v3.json",
            "--manifest", stage / "reference-manifest.json",
            "--projection", stage / "source-asset-projection.md",
            "--validation", stage / "source-asset-validation.json",
            "--confirmation", stage / "source-asset-approval.json",
            "--vault", vault, "--filename", "2026-08-31_staging.md", "--record", base / "fi-21-ingest.json",
        ], success=False)
        assert "revision_not_committed" in (blocked.stderr + blocked.stdout)
        owner.send_signal(signal.SIGTERM); owner.communicate(timeout=10); retry(target)
        record("FI-21", "Source Ingestion cannot consume staging", "PASS", "revision_not_committed")

        target = base / "historical-partial"
        complete = retry(base / "historical-source"); complete_dir = Path(complete["revision_directory"])
        partial = target / "revisions" / complete_dir.name; partial.mkdir(parents=True)
        shutil.copy2(complete_dir / "source-material-v3.json", partial / "source-material-v3.json")
        blocked = run(command(target), success=False)
        assert "partial_revision_detected" in (blocked.stderr + blocked.stdout)
        assert sorted(item.name for item in partial.iterdir()) == ["source-material-v3.json"]
        record("FI-22", "historical partial final", "PASS", "detected and preserved; no automatic overwrite")

        same_device_target = base / "device-check"; same_device_target.mkdir()
        assert os.stat(same_device_target).st_dev == os.stat(same_device_target.parent).st_dev
        record("FI-23", "same-filesystem staging", "PASS", "fixture confirms target-local staging and atomic rename device")

        target = base / "fi-24"; revisions = target / "revisions"; revisions.mkdir(parents=True)
        probe = retry(base / "fi-24-identity-probe"); revision_id = Path(probe["revision_directory"]).name
        unknown_lock = revisions / f".{revision_id}.promotion.lock"; unknown_lock.write_text("{invalid", encoding="utf-8")
        blocked = run(command(target), success=False)
        assert "active_unknown" in (blocked.stderr + blocked.stdout) and unknown_lock.exists() and not final_dirs(target)
        record("FI-24", "unknown lock owner", "PASS", "blocked without guessing or deleting ambiguous lock")

        failures = [item for item in results["cases"] if item["status"] != "PASS"]
        results["summary"] = {"total": len(results["cases"]), "pass": len(results["cases"]) - len(failures), "fail": len(failures)}
        write_json(output, results)
        print(json.dumps(results["summary"], ensure_ascii=False, indent=2))
        if failures:
            raise SystemExit(1)
    finally:
        if not keep:
            shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    main()
