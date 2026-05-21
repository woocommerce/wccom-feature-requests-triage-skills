#!/usr/bin/env python3
"""
save_frs.py — Merge paged wccom-feature-requests-list tool results into a single JSONL cache.

Usage:
    python3 save_frs.py <page1.txt> [page2.txt ...] -o <output.jsonl>

Each input file is the raw JSON output from wccom-feature-requests-list
(format: {"items": [...], "total": N, "total_pages": N}).

Example:
    python3 save_frs.py /tmp/page1.txt /tmp/page2.txt -o /tmp/frs-27147.jsonl
"""

import argparse
import json
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge paged FR result files into JSONL.")
    parser.add_argument("inputs", nargs="+", help="Tool result JSON files (one per page)")
    parser.add_argument("-o", "--output", required=True, help="Output JSONL path")
    args = parser.parse_args()

    seen: set[int] = set()
    written = 0

    with open(args.output, "w") as out:
        for path in args.inputs:
            with open(path) as f:
                raw = f.read().strip()

            # Handle both plain JSON object and JSONL-wrapped output
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                # Try reading first non-empty line
                for line in raw.splitlines():
                    line = line.strip()
                    if line:
                        data = json.loads(line)
                        break

            items = data.get("items", [])
            for fr in items:
                if fr["id"] in seen:
                    continue
                seen.add(fr["id"])
                out.write(json.dumps(fr) + "\n")
                written += 1

    print(f"Wrote {written} unique FRs to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
