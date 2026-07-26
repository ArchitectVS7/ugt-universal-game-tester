#!/usr/bin/env python3
"""Rung 3 (R1) — playability: one full escape, with invariants after every step.

    python3 examples/escape-room/integration/verify_round1.py

Drives the game's own committed `content/walkthrough.json` end to end through
the adapter, checking `invariants.py` after every single command, and asserts
each link of the 8-flag chain individually rather than as a lump "it escaped" —
which is only possible because the content CSVs pin down exactly what sets what.

**Why this exists when `ugt verify` reports 6/6.** Two reasons, both structural:

  1. `ugt verify` exits 0 even when features FAIL — `handle_verify` only exits
     non-zero on an exception. Re-confirmed 2026-07-26 by inverting an assertion:
     `1 FAILED` in the report, exit code still 0. A gate that reads `$?` passes a
     red run. This rung is fail-closed.
  2. The feature map asserts on state deltas at six checkpoints; it cannot check
     an invariant after every intermediate step, and it cannot assert what
     happens AFTER the win (escaped latching, post-escape inertness).
"""
from __future__ import annotations

import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
for _p in (HERE, REPO):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from invariants import EXIT_ROOM, ROOMS, SUITE  # noqa: E402
from ugt.adapters.subprocess import SubprocessAdapter  # noqa: E402
from ugt.core.trial import GateRunner  # noqa: E402
from ugt.utils.config_parser import UgtConfig  # noqa: E402

CONFIG = os.path.join(HERE, "ugt.config.yaml")
GAME = os.path.abspath(os.path.join(HERE, "..", "game"))
WALKTHROUGH = os.path.join(GAME, "content", "walkthrough.json")

gate = GateRunner()


def check(ok, label, detail=""):
    """Adapter to GateRunner's (name, ok, detail) order, so call sites read naturally."""
    return gate.ck(label, ok, detail)


def flag_chain_from_content() -> list:
    """Every flag the content can set, read from the game's own objects.csv.

    Derived, never hardcoded: a content edit that adds a puzzle link shows up
    here automatically instead of silently going untested."""
    flags = []
    with open(os.path.join(GAME, "content", "objects.csv"), newline="") as fh:
        for row in csv.DictReader(fh):
            for col in ("take_sets_flag", "use_sets_flag"):
                if row.get(col) and row[col] not in flags:
                    flags.append(row[col])
    return flags


class Driver:
    """Steps the adapter, running the shared invariant suite after every command."""

    def __init__(self, adapter, by_name):
        self.ad = adapter
        self.by_name = by_name
        self.violations: list[str] = []
        self.commands = 0
        self.state: dict = {}
        self.terminated = False
        self.rooms_seen: set = set()
        self.flag_first_set: dict = {}

    def reset(self):
        self.state = self.ad.reset()
        self.rooms_seen.add(self.state["current_room"])
        return self.state

    def step(self, name: str):
        before = self.state
        after, term, _trunc, info = self.ad.step(self.by_name[name])
        self.commands += 1
        self.terminated = term
        for v in SUITE.check_command(before, after, name, info or {}):
            self.violations.append(f"after {name} #{self.commands}: {v}")
        for flag, now in (after.get("flags") or {}).items():
            if now and flag not in self.flag_first_set:
                self.flag_first_set[flag] = (self.commands, name)
        self.rooms_seen.add(after["current_room"])
        self.state = after
        return after


def main() -> int:
    print("Escape Room R1 — one full escape over the real wire\n")

    cfg = UgtConfig(CONFIG)
    by_name = {v["name"]: int(k) for k, v in cfg.action_mappings.items()}
    walk = json.load(open(WALKTHROUGH))
    seq = [(f"{s['verb']}_{s['object']}" if s.get("object") else s["verb"]) for s in walk]

    check(all(n in by_name for n in seq),
          "every walkthrough step maps to a declared action id",
          f"{len(seq)} steps; unmapped: {[n for n in seq if n not in by_name] or 'none'}")

    ad = SubprocessAdapter(cfg)
    ad.connect()
    d = Driver(ad, by_name)
    try:
        s0 = d.reset()
        check(s0["moves_taken"] == 0 and not s0["escaped"] and not any(s0["flags"].values()),
              "a fresh game starts at 0 moves, no flags, not escaped",
              f"room={s0['current_room']}")

        # ── refusals BEFORE the chain is walked ──────────────────────────────
        # Both are asserted here rather than trusted: they are the semantics R2's
        # red-herring probes and the feature map's F1/F5 all rest on.
        print("\n  -- refusals cost nothing --")
        b = d.state
        d.step("go_north")            # R01 -> R02
        a = d.step("go_north")        # R02 -> R05 needs iron_door_open: refused
        check(a["current_room"] == "R02",
              "a room with an unmet entry_requires_flag refuses entry",
              f"still in {a['current_room']}")
        check(a["moves_taken"] == b["moves_taken"] + 1,
              "two moves issued, ONE counted — the refused move consumed nothing",
              f"moves {b['moves_taken']} -> {a['moves_taken']}")

        before_use = d.state
        d.step("go_east")             # R02 -> R03
        d.step("take_lantern")
        after_use = d.step("use_lantern")   # needs has_oil: refused
        check(after_use["flags"]["lantern_lit"] is False,
              "`use` with an unmet use_requires_flag sets no flag")
        check(after_use["moves_taken"] == before_use["moves_taken"] + 2,
              "three actions issued, TWO counted — the refused `use` consumed nothing",
              f"moves {before_use['moves_taken']} -> {after_use['moves_taken']}")

        # ── the full walkthrough, from scratch ───────────────────────────────
        print("\n  -- the committed walkthrough, start to escape --")
        d.reset()
        for name in seq:
            d.step(name)
        final = d.state
        check(final["escaped"] is True, "the walkthrough reaches escaped",
              f"room={final['current_room']} moves={final['moves_taken']}")
        check(d.terminated is True, "the adapter sees `terminated` on the winning step")
        check(final["current_room"] == EXIT_ROOM,
              f"the escape happens in the exit room {EXIT_ROOM}",
              f"room={final['current_room']}")
        check(final["moves_taken"] == len(seq),
              "every walkthrough step was ACCEPTED (no silent mid-run refusal)",
              f"moves_taken={final['moves_taken']} steps={len(seq)}")

        # ── the flag chain, link by link ─────────────────────────────────────
        print("\n  -- the puzzle chain --")
        chain = flag_chain_from_content()
        unset = [f for f in chain if not final["flags"].get(f)]
        check(not unset, f"all {len(chain)} content flags were set during the run",
              f"chain={chain}" if not unset else f"never set: {unset}")
        order = sorted(d.flag_first_set.items(), key=lambda kv: kv[1][0])
        check(len(order) == len(chain),
              "each flag was observed being set, in order",
              " -> ".join(f"{f}@{n}" for f, (n, _c) in order))

        # ── coverage ─────────────────────────────────────────────────────────
        print("\n  -- coverage --")
        check(d.rooms_seen == ROOMS,
              f"all {len(ROOMS)} rooms were visited",
              f"missed: {sorted(ROOMS - d.rooms_seen) or 'none'}")
        check(final["rooms_visited"] == len(ROOMS),
              "the game's own rooms_visited counter agrees",
              f"rooms_visited={final['rooms_visited']}")

        # ── after the win ────────────────────────────────────────────────────
        # The feature map stops at the win. A latching terminal flag is exactly
        # where a state machine goes wrong, so keep pressing.
        print("\n  -- after the escape --")
        post = d.state
        still = True
        for name in ("go_south", "look", "inventory", "drop_lantern", "go_north"):
            after = d.step(name)
            if not after["escaped"]:
                still = False
                break
        check(still, "escaped LATCHES across 5 further actions of any kind",
              f"moves {post['moves_taken']} -> {d.state['moves_taken']}")

        # ── invariants ───────────────────────────────────────────────────────
        print("\n  -- invariants --")
        check(not d.violations,
              f"{len(SUITE.predicates)} invariants held across all {d.commands} commands",
              "" if not d.violations else "; ".join(d.violations[:3]))
        check(d.commands >= len(seq),
              "the invariant sweep is NON-VACUOUS (it ran on a real playthrough)",
              f"{d.commands} commands checked")
    finally:
        ad.close()

    return gate.finish(
        "ROUND 1",
        "The game is playable end to end over the wire: every content flag fires, every room "
        "is reachable, refusals cost nothing, the win latches, and no invariant broke.")


if __name__ == "__main__":
    sys.exit(main())
