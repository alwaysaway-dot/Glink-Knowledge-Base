#!/usr/bin/env python3
"""Read/query/reconcile the auxiliary operation index."""

import argparse
import json
from pathlib import Path

from operation_envelope import find_by_reference, get_operation, reconcile_operation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    get = sub.add_parser("get"); get.add_argument("--operation-id", required=True)
    find = sub.add_parser("find"); find.add_argument("--reference", required=True); find.add_argument("--operation-type"); find.add_argument("--started-after")
    reconcile = sub.add_parser("reconcile"); reconcile.add_argument("--operation-id", required=True); reconcile.add_argument("--canonical-reference", required=True); reconcile.add_argument("--canonical-status", choices=("completed", "failed", "partial", "blocked", "unknown"), required=True); reconcile.add_argument("--observed-at")
    args = parser.parse_args()
    if args.command == "get": result = get_operation(args.root, args.operation_id)
    elif args.command == "find": result = find_by_reference(args.root, args.reference, args.operation_type, args.started_after)
    else:
        result = reconcile_operation(args.root, args.operation_id, canonical_ref=args.canonical_reference,
                                     canonical_status=None if args.canonical_status == "unknown" else args.canonical_status,
                                     observed_at=args.observed_at)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)); return 0


if __name__ == "__main__": raise SystemExit(main())
