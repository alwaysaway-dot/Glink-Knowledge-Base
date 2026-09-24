#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${1:-/tmp/guanlan-v0.5-c/validation}"
FIXTURES="$OUT/fixtures"
MODULE="$ROOT/knowledge-foundation-stability/foundation_stability.py"

mkdir -p "$OUT"
python3 "$ROOT/tests/knowledge-foundation-stability/build_fixture.py" "$FIXTURES"

python3 "$MODULE" validate-source-material \
  --input "$FIXTURES/source-material.json" \
  --manifest "$FIXTURES/manifest.json" \
  --asset-root "$FIXTURES/asset-root" \
  --check-files \
  --scope test > "$OUT/schema-reference-validation.json"

python3 "$MODULE" identity \
  --platform youtube \
  --source-id ABCdef12345 > "$OUT/identity-a.json"
python3 "$MODULE" identity \
  --platform youtube \
  --source-id ABCdef12345 > "$OUT/identity-b.json"
cmp "$OUT/identity-a.json" "$OUT/identity-b.json"

if python3 "$MODULE" validate-source-material \
  --input "$FIXTURES/bad-revision-source-material.json" > "$OUT/bad-revision.out" 2>&1; then
  echo "bad revision unexpectedly passed" >&2
  exit 1
fi

if python3 "$MODULE" validate-source-material \
  --input "$FIXTURES/temp-reference-source-material.json" > "$OUT/temp-reference.out" 2>&1; then
  echo "temporary reference unexpectedly passed" >&2
  exit 1
fi

if python3 "$MODULE" validate-source-material \
  --input "$FIXTURES/forbidden-analysis-source-material.json" > "$OUT/forbidden-analysis.out" 2>&1; then
  echo "understanding field in source material unexpectedly passed" >&2
  exit 1
fi

if python3 "$MODULE" validate-manifest \
  --manifest "$FIXTURES/manifest.json" \
  --asset-root "$FIXTURES/asset-root" \
  --check-files > "$OUT/formal-temp-root.out" 2>&1; then
  echo "formal temporary asset root unexpectedly passed" >&2
  exit 1
fi

SWIFT_FLAGS=(-module-cache-path "$OUT/module-cache")
swiftc "${SWIFT_FLAGS[@]}" -parse-as-library \
  "$ROOT/knowledge-generation-engine/KnowledgeGenerationEngine.swift" \
  -o "$OUT/knowledge-generation-engine"

"$OUT/knowledge-generation-engine" \
  --draft "$FIXTURES/draft.json" \
  --plan "$FIXTURES/plan.json" \
  --source-material "$FIXTURES/source-material.json" \
  --source-validation "$OUT/schema-reference-validation.json" \
  --provider local \
  --output "$OUT/no-sidecar-draft.md" \
  --quality "$OUT/no-sidecar-quality.json" \
  --metadata "$OUT/no-sidecar-metadata.json" \
  --record "$OUT/no-sidecar-record.json"

"$OUT/knowledge-generation-engine" \
  --draft "$FIXTURES/draft.json" \
  --plan "$FIXTURES/plan.json" \
  --source-material "$FIXTURES/source-material.json" \
  --source-validation "$OUT/schema-reference-validation.json" \
  --understanding-sidecar "$FIXTURES/sidecar.json" \
  --provider local \
  --output "$OUT/with-sidecar-draft.md" \
  --quality "$OUT/with-sidecar-quality.json" \
  --metadata "$OUT/with-sidecar-metadata.json" \
  --record "$OUT/with-sidecar-record.json"

if "$OUT/knowledge-generation-engine" \
  --draft "$FIXTURES/draft.json" \
  --plan "$FIXTURES/plan.json" \
  --source-material "$FIXTURES/source-material.json" \
  --provider local \
  --output "$OUT/unvalidated-draft.md" \
  --quality "$OUT/unvalidated-quality.json" \
  --metadata "$OUT/unvalidated-metadata.json" \
  --record "$OUT/unvalidated-record.json" > "$OUT/unvalidated.out" 2>&1; then
  echo "unvalidated source material unexpectedly passed" >&2
  exit 1
fi

if "$OUT/knowledge-generation-engine" \
  --draft "$FIXTURES/draft.json" \
  --plan "$FIXTURES/plan.json" \
  --source-material "$FIXTURES/pending-source-material.json" \
  --source-validation "$OUT/schema-reference-validation.json" \
  --provider local \
  --output "$OUT/pending-draft.md" \
  --quality "$OUT/pending-quality.json" \
  --metadata "$OUT/pending-metadata.json" \
  --record "$OUT/pending-record.json" > "$OUT/pending.out" 2>&1; then
  echo "pending source material unexpectedly passed" >&2
  exit 1
fi

if "$OUT/knowledge-generation-engine" \
  --draft "$FIXTURES/draft.json" \
  --plan "$FIXTURES/plan.json" \
  --source-material "$FIXTURES/source-material.json" \
  --source-validation "$OUT/schema-reference-validation.json" \
  --understanding-sidecar "$FIXTURES/bad-sidecar.json" \
  --provider local \
  --output "$OUT/bad-sidecar-draft.md" \
  --quality "$OUT/bad-sidecar-quality.json" \
  --metadata "$OUT/bad-sidecar-metadata.json" \
  --record "$OUT/bad-sidecar-record.json" > "$OUT/bad-sidecar.out" 2>&1; then
  echo "mismatched sidecar unexpectedly passed" >&2
  exit 1
fi

rg -n "fallback_no_content|Source Material|Understanding Sidecar：未提供" \
  "$OUT/no-sidecar-draft.md" > "$OUT/no-sidecar-assertions.txt"
rg -n "validated，可选参考|Revision ID" \
  "$OUT/with-sidecar-draft.md" > "$OUT/with-sidecar-assertions.txt"

echo "SCHEMA_REFERENCE_VALIDATION=$OUT/schema-reference-validation.json"
echo "IDENTITY_VALIDATION=$OUT/identity-a.json"
echo "KNOWLEDGE_GENERATOR_NO_SIDECAR=$OUT/no-sidecar-record.json"
echo "KNOWLEDGE_GENERATOR_WITH_SIDECAR=$OUT/with-sidecar-record.json"
