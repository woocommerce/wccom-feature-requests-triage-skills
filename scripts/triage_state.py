#!/usr/bin/env python3
"""
triage_state.py -- State management for the triage-woo-feature-requests orchestrator.

Layout (all files under .triage-state/<product_id>/):

  state.json            Top-level run metadata (product, phases selected, status).
  working_set.jsonl     One FR per line. Source of truth for the run.
  actioned.jsonl        Append-only log: {id, phase, action, status, ts}.
  knowledge_base.json   Cached changelog + docs crawl from detect-completed Phase 1.
  flagged/<phase>.jsonl Per-phase detection output, pre-action.

Subcommands print JSON to stdout for the orchestrator (or subagents) to parse.

Usage examples:
    python3 scripts/triage_state.py init --product-id 27147 --product-name "Foo" \\
        --phases completed,duplicates,spam,support,stale
    python3 scripts/triage_state.py status --product-id 27147
    python3 scripts/triage_state.py paths --product-id 27147
    python3 scripts/triage_state.py append-actioned --product-id 27147 \\
        --phase duplicates --fr-id 123 --action closed --status closed
    python3 scripts/triage_state.py actioned-ids --product-id 27147
    python3 scripts/triage_state.py set-phase --product-id 27147 \\
        --phase duplicates --phase-status in_progress
    python3 scripts/triage_state.py working-set-count --product-id 27147
    python3 scripts/triage_state.py fetched-age --product-id 27147
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PHASES = ["completed", "duplicates", "spam", "support", "stale"]
REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_ROOT = REPO_ROOT / ".triage-state"


def product_dir(pid: str) -> Path:
    return STATE_ROOT / str(pid)


def paths_for(pid: str) -> dict:
    d = product_dir(pid)
    return {
        "dir": str(d),
        "state": str(d / "state.json"),
        "working_set": str(d / "working_set.jsonl"),
        "actioned": str(d / "actioned.jsonl"),
        "knowledge_base": str(d / "knowledge_base.json"),
        "flagged_dir": str(d / "flagged"),
    }


def load_state(pid: str) -> dict | None:
    p = Path(paths_for(pid)["state"])
    if not p.exists():
        return None
    return json.loads(p.read_text())


def save_state(pid: str, state: dict) -> None:
    p = Path(paths_for(pid)["state"])
    p.parent.mkdir(parents=True, exist_ok=True)
    state["last_updated"] = int(time.time())
    p.write_text(json.dumps(state, indent=2))


def cmd_init(args: argparse.Namespace) -> None:
    pid = args.product_id
    d = product_dir(pid)
    d.mkdir(parents=True, exist_ok=True)
    (d / "flagged").mkdir(exist_ok=True)
    selected = [p.strip() for p in args.phases.split(",") if p.strip()]
    for p in selected:
        if p not in PHASES:
            print(f"unknown phase: {p}", file=sys.stderr)
            sys.exit(2)
    existing = load_state(pid) or {}
    state = {
        "product_id": pid,
        "product_name": args.product_name or existing.get("product_name"),
        "phases_selected": selected,
        "phase_status": existing.get("phase_status", {p: "pending" for p in PHASES}),
        "fetched_at": existing.get("fetched_at"),
        "created_at": existing.get("created_at", int(time.time())),
    }
    for p in selected:
        state["phase_status"].setdefault(p, "pending")
    save_state(pid, state)
    print(json.dumps({"ok": True, "paths": paths_for(pid), "state": state}))


def cmd_status(args: argparse.Namespace) -> None:
    pid = args.product_id
    state = load_state(pid)
    if state is None:
        print(json.dumps({"exists": False}))
        return
    p = paths_for(pid)
    counts = {
        "working_set": _line_count(p["working_set"]),
        "actioned": _line_count(p["actioned"]),
    }
    flagged = {}
    fdir = Path(p["flagged_dir"])
    if fdir.exists():
        for f in fdir.glob("*.jsonl"):
            flagged[f.stem] = _line_count(str(f))
    print(json.dumps({"exists": True, "state": state, "counts": counts, "flagged": flagged}))


def cmd_paths(args: argparse.Namespace) -> None:
    print(json.dumps(paths_for(args.product_id)))


def cmd_append_actioned(args: argparse.Namespace) -> None:
    pid = args.product_id
    p = Path(paths_for(pid)["actioned"])
    p.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "id": int(args.fr_id),
        "phase": args.phase,
        "action": args.action,
        "status": args.status,
        "ts": int(time.time()),
    }
    with p.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    print(json.dumps({"ok": True, "entry": entry}))


def cmd_actioned_ids(args: argparse.Namespace) -> None:
    p = Path(paths_for(args.product_id)["actioned"])
    ids: list[int] = []
    if p.exists():
        with p.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ids.append(int(json.loads(line)["id"]))
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue
    print(json.dumps({"ids": sorted(set(ids))}))


def cmd_set_phase(args: argparse.Namespace) -> None:
    pid = args.product_id
    state = load_state(pid) or {"product_id": pid, "phase_status": {}}
    state.setdefault("phase_status", {})[args.phase] = args.phase_status
    save_state(pid, state)
    print(json.dumps({"ok": True, "phase": args.phase, "status": args.phase_status}))


def cmd_set_fetched(args: argparse.Namespace) -> None:
    pid = args.product_id
    state = load_state(pid) or {"product_id": pid}
    state["fetched_at"] = int(time.time())
    save_state(pid, state)
    print(json.dumps({"ok": True, "fetched_at": state["fetched_at"]}))


def cmd_working_set_count(args: argparse.Namespace) -> None:
    print(json.dumps({"count": _line_count(paths_for(args.product_id)["working_set"])}))


def cmd_fetched_age(args: argparse.Namespace) -> None:
    state = load_state(args.product_id)
    if not state or not state.get("fetched_at"):
        print(json.dumps({"fetched": False}))
        return
    age = int(time.time()) - int(state["fetched_at"])
    print(json.dumps({"fetched": True, "age_seconds": age, "fetched_at": state["fetched_at"]}))


def cmd_reset(args: argparse.Namespace) -> None:
    pid = args.product_id
    d = product_dir(pid)
    if not d.exists():
        print(json.dumps({"ok": True, "removed": False}))
        return
    import shutil

    shutil.rmtree(d)
    print(json.dumps({"ok": True, "removed": True}))


def cmd_filter_unactioned(args: argparse.Namespace) -> None:
    """Read working_set.jsonl, drop actioned IDs, write to --out."""
    pid = args.product_id
    paths = paths_for(pid)
    actioned: set[int] = set()
    ap = Path(paths["actioned"])
    if ap.exists():
        with ap.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    actioned.add(int(json.loads(line)["id"]))
                except Exception:
                    continue
    src = Path(paths["working_set"])
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    kept = 0
    skipped = 0
    with src.open() as fin, out.open("w") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            try:
                fr = json.loads(line)
            except json.JSONDecodeError:
                continue
            if int(fr.get("id", -1)) in actioned:
                skipped += 1
                continue
            fout.write(line + "\n")
            kept += 1
    print(json.dumps({"ok": True, "kept": kept, "skipped": skipped, "out": str(out)}))


def _line_count(path: str) -> int:
    p = Path(path)
    if not p.exists():
        return 0
    n = 0
    with p.open() as f:
        for line in f:
            if line.strip():
                n += 1
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init")
    p_init.add_argument("--product-id", required=True)
    p_init.add_argument("--product-name", default=None)
    p_init.add_argument("--phases", required=True, help="Comma-separated phases.")
    p_init.set_defaults(fn=cmd_init)

    p_status = sub.add_parser("status")
    p_status.add_argument("--product-id", required=True)
    p_status.set_defaults(fn=cmd_status)

    p_paths = sub.add_parser("paths")
    p_paths.add_argument("--product-id", required=True)
    p_paths.set_defaults(fn=cmd_paths)

    p_app = sub.add_parser("append-actioned")
    p_app.add_argument("--product-id", required=True)
    p_app.add_argument("--phase", required=True)
    p_app.add_argument("--fr-id", required=True)
    p_app.add_argument("--action", required=True)
    p_app.add_argument("--status", required=True)
    p_app.set_defaults(fn=cmd_append_actioned)

    p_acted = sub.add_parser("actioned-ids")
    p_acted.add_argument("--product-id", required=True)
    p_acted.set_defaults(fn=cmd_actioned_ids)

    p_sp = sub.add_parser("set-phase")
    p_sp.add_argument("--product-id", required=True)
    p_sp.add_argument("--phase", required=True)
    p_sp.add_argument("--phase-status", required=True,
                      choices=["pending", "in_progress", "completed", "skipped"])
    p_sp.set_defaults(fn=cmd_set_phase)

    p_sf = sub.add_parser("set-fetched")
    p_sf.add_argument("--product-id", required=True)
    p_sf.set_defaults(fn=cmd_set_fetched)

    p_wc = sub.add_parser("working-set-count")
    p_wc.add_argument("--product-id", required=True)
    p_wc.set_defaults(fn=cmd_working_set_count)

    p_age = sub.add_parser("fetched-age")
    p_age.add_argument("--product-id", required=True)
    p_age.set_defaults(fn=cmd_fetched_age)

    p_reset = sub.add_parser("reset")
    p_reset.add_argument("--product-id", required=True)
    p_reset.set_defaults(fn=cmd_reset)

    p_filter = sub.add_parser("filter-unactioned")
    p_filter.add_argument("--product-id", required=True)
    p_filter.add_argument("--out", required=True)
    p_filter.set_defaults(fn=cmd_filter_unactioned)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
