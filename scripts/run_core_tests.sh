#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONDONTWRITEBYTECODE=1
python3 tests/capture-inbox-completion/test_capture_inbox_completion.py
python3 tests/learning-note-generation-v2/test_learning_note_generation_v2.py
python3 tests/multi-asset-workflow/run_multi_asset_workflow.py /tmp/guanlan-public-ci-multi-asset.json
python3 tests/source-promotion-atomicity/run_atomicity_tests.py /tmp/guanlan-public-ci-atomicity.json
python3 tests/freeze-closure/run_freeze_closure.py /tmp/guanlan-public-ci-freeze-closure.json
python3 tests/publisher-safety/test_approval_binding.py
python3 tests/publisher-safety/test_publisher_transaction.py
python3 tests/publisher-safety/test_relation_projection_compat.py
python3 tests/knowledge-relation/test_relation_curation.py
python3 tests/operation-envelope/test_operation_envelope.py
python3 tests/operation-envelope/test_adapter_boundaries.py
python3 tests/media-transcript-quality-gate/test_media_transcript_quality.py
bash tests/contract-validation/run-contract-validation.sh
