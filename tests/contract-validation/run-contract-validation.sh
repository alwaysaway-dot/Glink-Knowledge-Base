#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
OUT_DIR="${GUANLAN_CONTRACT_OUT:-/tmp/guanlan-contract-validation}"

mkdir -p "$OUT_DIR"
python3 "$ROOT_DIR/tests/contract-validation/validate_active_contracts.py" \
  --root "$ROOT_DIR" \
  --manifest "$ROOT_DIR/tests/contract-validation/active-runtime-contracts.json" \
  --output "$OUT_DIR/contract-validation-report.json"

echo "REPORT=$OUT_DIR/contract-validation-report.json"
