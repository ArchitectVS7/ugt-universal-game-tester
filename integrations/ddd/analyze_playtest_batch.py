#!/usr/bin/env python3
"""
DDD playtest batch analyzer — turns a --runs N `playtest_ddd.py` batch into a
deck-matchup win rate (bb_competitive vs sw_competitive), the actual question
behind DDD's T6.2 (Blitzblade ~36% skilled-play winrate, measured so far only by
the greedy/one-ply AI ladder). The LLM plays BOTH seats across the batch, so a
winner skew here is a read on DECK/CARD balance, not on strategy — the same
signal the AI ladder measures, from a different "skilled play" proxy.

`ugt/core/playtester.py`'s per-run summary only banks numeric `summary_paths`
deltas (p0_hp, p1_hp) — it does not track winner/via, because those fields are
absent while ONGOING and only appear at the terminal step. This script recovers
them from the recorded action_log: `_compute_delta` flattizes nested dicts, so
the terminal step's entry contains a "resultKind" key changing to 'WIN' plus
"result.winner" / "result.via" alongside it.

Run after a batch: python3 integrations/ddd/playtest_ddd.py --runs 8 --max-actions 100
    python3 integrations/ddd/analyze_playtest_batch.py
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")

# Seat 0 always plays engine.decks[0], seat 1 always plays engine.decks[1]
# (ugt.config.yaml: decks: ["bb_competitive", "sw_competitive"]).
SEAT_DECK = {0: "bb_competitive (Blitzblade)", 1: "sw_competitive"}


def _after_value(delta_str: str):
    """'None → 0' -> 0 ; \"'ONGOING' → 'WIN'\" -> 'WIN'. Best-effort literal parse."""
    if not isinstance(delta_str, str) or " → " not in delta_str:
        return None
    after = delta_str.split(" → ", 1)[1]
    m = re.match(r"^'(.*)'$", after)
    if m:
        return m.group(1)
    try:
        return int(after)
    except ValueError:
        return after


def extract_matches(action_log):
    """One dict per completed match found in this run's action_log."""
    matches = []
    for entry in action_log:
        delta = entry.get("state_delta") or {}
        result_kind_delta = delta.get("resultKind", "")
        if not (isinstance(result_kind_delta, str) and result_kind_delta.endswith("'WIN'")):
            continue
        matches.append({
            "step": entry.get("step"),
            "winner": _after_value(delta.get("result.winner", "")),
            "via": _after_value(delta.get("result.via", "")),
        })
    return matches


def main() -> int:
    run_files = sorted(
        glob.glob(os.path.join(RESULTS_DIR, "playtest-run-*.json")),
        key=lambda p: int(re.search(r"playtest-run-(\d+)\.json", p).group(1)),
    )
    if not run_files:
        print(f"[!] No playtest-run-*.json files found in {RESULTS_DIR}. "
              f"Run: python3 integrations/ddd/playtest_ddd.py --runs 8 --max-actions 100")
        return 1

    all_matches = []
    total_bugs = 0
    total_violations = 0
    total_actions = 0
    for path in run_files:
        with open(path) as fh:
            run_report = json.load(fh)
        action_log = run_report.get("action_log", [])
        matches = extract_matches(action_log)
        for m in matches:
            m["run_file"] = os.path.basename(path)
        all_matches.extend(matches)
        summary = run_report.get("summary", {})
        total_bugs += summary.get("bugs_flagged", 0)
        total_violations += summary.get("invariant_violations", 0)
        total_actions += summary.get("actions_taken", 0)

    print(f"[*] {len(run_files)} run report(s), {total_actions} total actions, "
          f"{len(all_matches)} completed match(es)")
    print(f"[*] total bugs flagged = {total_bugs} | total invariant violations = {total_violations}")
    print()

    if not all_matches:
        print("[!] No completed matches found (every run truncated mid-match — "
              "raise --max-actions).")
        return 1

    win_counts = {0: 0, 1: 0}
    via_counts: dict[str, int] = {}
    for m in all_matches:
        if m["winner"] in (0, 1):
            win_counts[m["winner"]] += 1
        via_counts[m["via"]] = via_counts.get(m["via"], 0) + 1

    n = len(all_matches)
    print(f"[=] Deck matchup win rate over {n} match(es):")
    for seat, deck in SEAT_DECK.items():
        wins = win_counts[seat]
        pct = 100.0 * wins / n if n else 0.0
        print(f"    seat {seat} ({deck}): {wins}/{n} = {pct:.1f}%")
    print(f"[=] Win-condition breakdown: {via_counts}")

    out_path = os.path.join(RESULTS_DIR, "playtest-batch-analysis.json")
    with open(out_path, "w") as fh:
        json.dump({
            "run_files": [os.path.basename(p) for p in run_files],
            "total_actions": total_actions,
            "total_bugs_flagged": total_bugs,
            "total_invariant_violations": total_violations,
            "matches": all_matches,
            "win_counts_by_seat": win_counts,
            "via_counts": via_counts,
            "seat_deck": SEAT_DECK,
        }, fh, indent=2)
    print(f"[=] Analysis written to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
