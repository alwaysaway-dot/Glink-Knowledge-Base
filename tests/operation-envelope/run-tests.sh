#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ROOT" python3 "$ROOT/tests/operation-envelope/test_operation_envelope.py"
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ROOT" python3 "$ROOT/tests/operation-envelope/test_adapter_boundaries.py"
