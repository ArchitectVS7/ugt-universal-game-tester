#!/usr/bin/env python3
"""
DDD playtest batch analyzer — turns one or more `playtest_ddd.py --runs N` batches
into a deck-matchup win rate (bb_competitive vs sw_competitive), the actual question
behind DDD's T6.2 (Blitzblade ~36% skilled-play winrate, measured so far only by
the greedy/one-ply AI ladder). The LLM plays BOTH seats across a batch, so a winner
skew here is a read on DECK/CARD balance, not on strategy — the same signal the AI
ladder measures, from a different "skilled play" proxy.

WHY MULTIPLE DIRECTORIES (the L-008 lesson): a single batch fixes `engine.decks`,
and `DddHarnessAdapter._pending_seat()` always resolves seat 0 first every phase, so
one batch samples ONE cell of the deck x seat design. Seat/turn-order is a KNOWN
confound in this engine — `apps/ladder/bin/ladder.mjs` pools a 4-cell design for
exactly this reason. A per-SEAT win rate from one batch is therefore uninterpretable
as balance. Pass one --dir per cell (forward + deck-reversed) and this script pools
by DECK, which is the number that means something.

`ugt/core/playtester.py`'s per-run summary only banks numeric `summary_paths`
deltas (p0_hp, p1_hp) — it does not track winner/via, because those fields are
absent while ONGOING and only appear at the terminal step. This script recovers
them from the recorded action_log: `_compute_delta` flattens nested dicts, so
the terminal step's entry contains a "resultKind" key changing to 'WIN' plus
"result.winner" / "result.via" alongside it.

Seat->deck mapping comes from each batch directory's `batch-meta.json` (written by
archive_batch.py at archive time) and falls back to ugt.config.yaml's `engine.decks`
for a live, un-archived results/ directory. It is NEVER hardcoded — the reversed
cell has the opposite mapping, and mislabeling it would silently invert the result.

    # single cell (health check only — NOT a balance read)
    python3 integrations/ddd/analyze_playtest_batch.py
    python3 integrations/ddd/analyze_playtest_batch.py --dir integrations/ddd/results/batch-fwd

    # pooled across cells — the actual balance read
    python3 integrations/ddd/analyze_playtest_batch.py \
        --dir integrations/ddd/results/batch-fwd \
        --dir integrations/ddd/results/batch-rev
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(HERE, "results")
CONFIG_PATH = os.path.join(HERE, "ugt.config.yaml")


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


def _decks_from_config():
    """engine.decks straight out of ugt.config.yaml (no yaml dep needed — the key is
    a flat inline list). Returns None if it cannot be read confidently."""
    try:
        with open(CONFIG_PATH) as fh:
            for line in fh:
                m = re.match(r'\s*decks:\s*\[(.*)\]', line)
                if m:
                    return [p.strip().strip('"\'') for p in m.group(1).split(",") if p.strip()]
    except OSError:
        pass
    return None


def _seat_deck_for(directory):
    """{0: deckname, 1: deckname} for a batch directory, plus the metadata source."""
    meta_path = os.path.join(directory, "batch-meta.json")
    if os.path.exists(meta_path):
        with open(meta_path) as fh:
            meta = json.load(fh)
        decks = meta.get("decks")
        if decks and len(decks) == 2:
            return {0: decks[0], 1: decks[1]}, meta
    decks = _decks_from_config()
    if not decks or len(decks) != 2:
        raise SystemExit(
            f"[!] Cannot determine the seat->deck mapping for {directory}: no "
            f"batch-meta.json and engine.decks unreadable in {CONFIG_PATH}. "
            f"Refusing to guess — a wrong mapping silently inverts the result."
        )
    return {0: decks[0], 1: decks[1]}, {"decks": decks, "source": "ugt.config.yaml (live)"}


def _wilson(wins, n, z=1.96):
    """Wilson score 95% interval — correct at the small n and lopsided p this tier
    produces, where the normal approximation is not."""
    if n == 0:
        return (0.0, 0.0)
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def load_cell(directory):
    """Every completed match in one batch directory, labelled by deck."""
    run_files = sorted(
        glob.glob(os.path.join(directory, "playtest-run-*.json")),
        key=lambda p: int(re.search(r"playtest-run-(\d+)\.json", p).group(1)),
    )
    if not run_files:
        raise SystemExit(
            f"[!] No playtest-run-*.json files found in {directory}. Run: "
            f"python3 integrations/ddd/playtest_ddd.py --runs 8 --max-actions 100"
        )
    seat_deck, meta = _seat_deck_for(directory)

    matches, bugs, violations, actions = [], 0, 0, 0
    for path in run_files:
        with open(path) as fh:
            run_report = json.load(fh)
        for m in extract_matches(run_report.get("action_log", [])):
            m["run_file"] = os.path.basename(path)
            m["cell"] = os.path.basename(directory.rstrip("/"))
            m["winner_deck"] = seat_deck.get(m["winner"]) if m["winner"] in (0, 1) else None
            matches.append(m)
        summary = run_report.get("summary", {})
        bugs += summary.get("bugs_flagged", 0)
        violations += summary.get("invariant_violations", 0)
        actions += summary.get("actions_taken", 0)

    return {
        "dir": directory,
        "name": os.path.basename(directory.rstrip("/")),
        "run_files": [os.path.basename(p) for p in run_files],
        "seat_deck": seat_deck,
        "meta": meta,
        "matches": matches,
        "total_actions": actions,
        "total_bugs_flagged": bugs,
        "total_invariant_violations": violations,
    }


def _tally(matches, key):
    counts: dict = {}
    for m in matches:
        counts[m.get(key)] = counts.get(m.get(key), 0) + 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="DDD playtest batch analyzer")
    parser.add_argument("--dir", action="append", dest="dirs", default=None,
                        help="a batch directory (repeatable — one per deck x seat cell)")
    parser.add_argument("--out", default=None, help="analysis JSON path (default: <first dir>/playtest-batch-analysis.json)")
    args = parser.parse_args()

    dirs = args.dirs or [RESULTS_DIR]
    cells = [load_cell(d) for d in dirs]

    all_matches = [m for c in cells for m in c["matches"]]
    total_actions = sum(c["total_actions"] for c in cells)
    total_bugs = sum(c["total_bugs_flagged"] for c in cells)
    total_violations = sum(c["total_invariant_violations"] for c in cells)

    print(f"[*] {len(cells)} cell(s), {sum(len(c['run_files']) for c in cells)} run report(s), "
          f"{total_actions} total actions, {len(all_matches)} completed match(es)")
    print(f"[*] total bugs flagged = {total_bugs} | total invariant violations = {total_violations}")
    print()

    if not all_matches:
        print("[!] No completed matches found (every run truncated mid-match — raise --max-actions).")
        return 1

    # ---- per-cell (seat-confounded; a health check, not a balance read) ----
    for c in cells:
        n = len(c["matches"])
        print(f"[=] cell '{c['name']}' — {n} match(es), decks {c['seat_deck'][0]} (seat 0) "
              f"vs {c['seat_deck'][1]} (seat 1)")
        seat_wins = _tally(c["matches"], "winner")
        for seat in (0, 1):
            wins = seat_wins.get(seat, 0)
            pct = 100.0 * wins / n if n else 0.0
            print(f"      seat {seat} ({c['seat_deck'][seat]}): {wins}/{n} = {pct:.1f}%")
        print(f"      via: {_tally(c['matches'], 'via')}")
    print()

    # ---- pooled by SEAT (the turn-order effect, visible only across cells) ----
    seat_wins = _tally(all_matches, "winner")
    n = len(all_matches)
    print(f"[=] Pooled by SEAT over {n} match(es) — the turn-order effect:")
    for seat in (0, 1):
        wins = seat_wins.get(seat, 0)
        lo, hi = _wilson(wins, n)
        print(f"    seat {seat}: {wins}/{n} = {100.0 * wins / n:.1f}%  (95% CI {100*lo:.1f}–{100*hi:.1f}%)")

    # ---- pooled by DECK (the balance read) ----
    deck_wins = _tally(all_matches, "winner_deck")
    decks = sorted(k for k in deck_wins if k)
    print()
    if len(cells) < 2:
        print("[!] ONE CELL ONLY — the deck figure below is CONFOUNDED with seat/turn-order")
        print("[!] and is NOT a balance read. Run the deck-reversed cell and pool.")
    print(f"[=] Pooled by DECK over {n} match(es):")
    for deck in decks:
        wins = deck_wins.get(deck, 0)
        lo, hi = _wilson(wins, n)
        print(f"    {deck}: {wins}/{n} = {100.0 * wins / n:.1f}%  (95% CI {100*lo:.1f}–{100*hi:.1f}%)")
    print(f"[=] Win-condition breakdown: {_tally(all_matches, 'via')}")

    out_path = args.out or os.path.join(dirs[0], "playtest-batch-analysis.json")
    with open(out_path, "w") as fh:
        json.dump({
            "cells": [{
                "name": c["name"], "dir": c["dir"], "run_files": c["run_files"],
                "seat_deck": {str(k): v for k, v in c["seat_deck"].items()},
                "meta": c["meta"],
                "total_actions": c["total_actions"],
                "total_bugs_flagged": c["total_bugs_flagged"],
                "total_invariant_violations": c["total_invariant_violations"],
                "win_counts_by_seat": {str(k): v for k, v in _tally(c["matches"], "winner").items()},
                "match_count": len(c["matches"]),
            } for c in cells],
            "pooled": {
                "match_count": n,
                "total_actions": total_actions,
                "total_bugs_flagged": total_bugs,
                "total_invariant_violations": total_violations,
                "win_counts_by_seat": {str(k): v for k, v in seat_wins.items()},
                "win_counts_by_deck": deck_wins,
                "via_counts": _tally(all_matches, "via"),
                "confounded_single_cell": len(cells) < 2,
            },
            "matches": all_matches,
        }, fh, indent=2)
    print(f"[=] Analysis written to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
