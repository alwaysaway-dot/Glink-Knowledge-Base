#!/usr/bin/env python3
"""Post-publish, non-blocking incremental Relation discovery hook."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from relation_common import atomic_json
from relation_governance import incremental_discover, now, reconcile_observations
from relation_apply import endpoint_asset, execute, validate_revisions


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault", required=True); parser.add_argument("--registry", required=True); parser.add_argument("--published-asset", required=True)
    parser.add_argument("--observation-pool", required=True); parser.add_argument("--output", required=True)
    parser.add_argument("--execute-auto", action="store_true", help="apply only Gate-qualified Strong candidates after a successful publish")
    parser.add_argument("--rollback-root"); parser.add_argument("--receipt-root")
    args = parser.parse_args()
    try:
        registry = json.loads(Path(args.registry).read_text(encoding="utf-8"))
        result = incremental_discover(Path(args.vault).resolve(), registry, args.published_asset, now())
        reconcile_observations(Path(args.observation_pool), result["medium_candidates"], result["strong_candidates"], result["created_at"])
        result["auto_applied"] = []
        if args.execute_auto:
            if not args.rollback_root or not args.receipt_root:
                raise ValueError("--execute-auto requires --rollback-root and --receipt-root")
            vault = Path(args.vault).resolve()
            for candidate in result["strong_candidates"]:
                source, target = endpoint_asset(candidate, "source", vault), endpoint_asset(candidate, "target", vault)
                validate_revisions(candidate, source, target)
                receipt = Path(args.receipt_root) / f"{candidate['candidate_id']}.json"
                result["auto_applied"].append(execute(candidate, source, target, args.registry, None, args.rollback_root, receipt, auto=True))
        result["relation_scan_status"] = "completed" if result["strong_candidates"] or result["medium_candidates"] else "completed_no_relation"
    except Exception as error:
        result = {"protocol": "relation-publish-hook-v1", "relation_scan_status": "failed_retryable", "error": str(error)}
    atomic_json(Path(args.output), result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
