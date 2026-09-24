#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON="${GUANLAN_WEB_PROVIDER_PYTHON:-python3}"
"$PYTHON" "$ROOT/tests/generic-web-capture/test_generic_web_capture.py"
