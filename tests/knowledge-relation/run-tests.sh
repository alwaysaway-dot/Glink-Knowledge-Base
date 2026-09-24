#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONPATH="$ROOT/knowledge-relation-manager" python3 -m unittest -v "$ROOT/tests/knowledge-relation/test_relation_layer.py"
PYTHONPATH="$ROOT/knowledge-relation-manager" python3 -m unittest -v "$ROOT/tests/knowledge-relation/test_relation_governance.py"
PYTHONPATH="$ROOT/knowledge-relation-manager" python3 -m unittest -v "$ROOT/tests/knowledge-relation/test_relation_curation.py"
