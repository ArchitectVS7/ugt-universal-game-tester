#!/usr/bin/env python3
"""
Archive a completed `playtest_ddd.py --runs N` batch out of results/ into a named
cell directory, stamping the deck order it was played under.

WHY THIS EXISTS: `playtest_ddd.py` writes results/playtest-run-{1..N}.json on a
FIXED path, so the next batch overwrites the previous one in place. The pooled
deck x seat design needs both cells side by side, and a half-overwritten results/
directory silently mixes them — L-008's stale gemma run-7/run-8 files sat in
results/ for hours looking exactly like fresh ones. Archiving is what makes the
two cells separable, and `batch-meta.json` is what lets the analyzer label seats
correctly for a deck-reversed cell instead of assuming the forward order.

    python3 integrations/ddd/archive_batch.py batch-fwd --expect 8 \
        --model claude-haiku-4-5-20251001 --note "L-010 forward cell"
"""
from __future__ import annotations

import argparse
import datetime
import glob
import json
import os
import re
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(HERE, "results")
CONFIG_PATH = os.path.join(HERE, "ugt.config.yaml")


def _decks_from_config():
    with open(CONFIG_PATH) as fh:
        for line in fh:
            m = re.match(r'\s*decks:\s*\[(.*)\]', line)
            if m:
                return [p.strip().strip('"\'') for p in m.group(1).split(",") if p.strip()]
    raise SystemExit(f"[!] Could not read engine.decks from {CONFIG_PATH}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive a DDD playtest batch into a cell directory")
    parser.add_argument("name", help="cell directory name, e.g. batch-fwd / batch-rev")
    parser.add_argument("--expect", type=int, default=None,
                        help="expected run count — refuses to archive on a mismatch")
    parser.add_argument("--model", default=None, help="model the batch was played with")
    parser.add_argument("--provider", default=None, help="provider the batch was played with")
    parser.add_argument("--note", default=None, help="free-text note recorded in batch-meta.json")
    args = parser.parse_args()

    run_files = sorted(
        glob.glob(os.path.join(RESULTS_DIR, "playtest-run-*.json")),
        key=lambda p: int(re.search(r"playtest-run-(\d+)\.json", p).group(1)),
    )
    if not run_files:
        raise SystemExit(f"[!] No playtest-run-*.json in {RESULTS_DIR} — nothing to archive.")
    if args.expect is not None and len(run_files) != args.expect:
        raise SystemExit(
            f"[!] Found {len(run_files)} run file(s), expected {args.expect}. Refusing to "
            f"archive a partial or stale-mixed batch — check results/ by mtime first."
        )

    dest = os.path.join(RESULTS_DIR, args.name)
    if os.path.exists(dest):
        raise SystemExit(f"[!] {dest} already exists — refusing to overwrite an archived cell.")
    os.makedirs(dest)

    decks = _decks_from_config()
    mtimes = {}
    for path in run_files:
        mtimes[os.path.basename(path)] = datetime.datetime.fromtimestamp(
            os.path.getmtime(path)).isoformat(timespec="seconds")
        shutil.move(path, os.path.join(dest, os.path.basename(path)))

    # The batch summary report, if the runs>1 path wrote one.
    summary_src = os.path.join(RESULTS_DIR, "playtest-report.json")
    if os.path.exists(summary_src):
        shutil.move(summary_src, os.path.join(dest, "playtest-report.json"))

    meta = {
        "cell": args.name,
        "decks": decks,                     # decks[0] played seat 0, decks[1] played seat 1
        "seat_deck": {"0": decks[0], "1": decks[1]},
        "run_count": len(run_files),
        "provider": args.provider,
        "model": args.model,
        "note": args.note,
        "archived_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "run_file_mtimes": mtimes,
    }
    with open(os.path.join(dest, "batch-meta.json"), "w") as fh:
        json.dump(meta, fh, indent=2)

    print(f"[+] Archived {len(run_files)} run(s) -> {dest}")
    print(f"[+] seat 0 = {decks[0]} | seat 1 = {decks[1]}")
    print(f"[+] run file mtimes: {min(mtimes.values())} .. {max(mtimes.values())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
