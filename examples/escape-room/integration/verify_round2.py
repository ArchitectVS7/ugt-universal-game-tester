#!/usr/bin/env python3
"""Rung 4 (R2) — the full content spine: every action, every object, every verb.

    python3 examples/escape-room/integration/verify_round2.py

R1 proved one escape works. R2 proves the whole content surface does.

The gap this rung was written to close, measured on 2026-07-26: the feature map
exercises **17 of 41 actions**. The other 24 — every `examine`, every `drop`,
`look`, `inventory`, `go_south`, and all three red herrings — had never been
driven by anything. Untested "does nothing" content is indistinguishable from
broken content, and a red herring is content whose entire job is to do nothing.

Asserted over the real wire:

  * all 41 declared actions are issued at least once;
  * every takeable object survives take -> drop -> re-take (a drop that DELETED
    the item looks identical to a working one if you only read the inventory);
  * every object is examinable where the content says it lives;
  * the non-puzzle objects set no flag under any verb they accept;
  * immovable objects refuse `take`;
  * `look`/`inventory` cost a move and change nothing else;
  * a consumed item is gone for good — not droppable, not usable, not re-takeable;
  * every `use_requires_flag` gate refuses before its prerequisite and succeeds
    after: the same call, two different answers.

There is exactly ONE terminal arm in this game — `escaped`. No lose state, no
timer, no fail ending. So unlike dice's R2 there are no alternative endings to
reach, and the spine here is content breadth rather than outcome variety.
"""
from __future__ import annotations

import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
for _p in (HERE, REPO):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from invariants import SUITE  # noqa: E402
from ugt.adapters.subprocess import SubprocessAdapter  # noqa: E402
from ugt.core.trial import GateRunner  # noqa: E402
from ugt.utils.config_parser import UgtConfig  # noqa: E402

CONFIG = os.path.join(HERE, "ugt.config.yaml")
GAME = os.path.abspath(os.path.join(HERE, "..", "game"))

# ── Routes ───────────────────────────────────────────────────────────────────
# Written out as composed legs rather than pathfound. A pathfinder here would be
# a second implementation of the map, and the map belongs to the game
# (`content/rooms.csv`), not to the tester. Every leg below is a prefix of the
# next, so a break shows up at the earliest room it affects.
# Each leg ends in a named room with a named thing true, and every later leg is
# built from an earlier one — so a break shows up at the earliest room it
# affects, and the gate table below can name the exact state it needs.
TO_R02 = ["go_north"]
TO_R03 = TO_R02 + ["go_east"]                                   # lantern, helmet
TO_R04 = TO_R02 + ["go_west"]                                   # iron key
HOLD_LANTERN = TO_R03 + ["take_lantern"]                        # in R03, unlit
# Opening the banded door: fetch the key, walk back, unlock. Ends in R02.
UNLOCKED = HOLD_LANTERN + ["go_west", "go_west", "take_key_iron",
                           "go_east", "use_key_iron"]
IN_R05 = UNLOCKED + ["go_north"]                                # valve wheel
IN_R06 = IN_R05 + ["go_west"]                                   # oil flask
HOLD_OIL = IN_R06 + ["take_flask_oil", "go_east"]               # back in R05
LIT = HOLD_OIL + ["use_lantern"]                                # lantern_lit
HOLD_VALVE = LIT + ["take_valve_wheel"]
VENTED = HOLD_VALVE + ["use_valve_wheel"]                       # steam_vented, in R05
IN_R07 = VENTED + ["go_north"]                                  # bronze cog
IN_R08 = IN_R07 + ["go_east"]                                   # ledger, skeleton key
HOLD_COG = IN_R07 + ["take_cog_bronze"]
KNOWS_HOUR = HOLD_COG + ["go_east", "take_ledger", "use_ledger"]  # in R08
CLOCK_SET = KNOWS_HOUR + ["go_west", "use_cog_bronze"]          # in R07
IN_R09 = CLOCK_SET + ["go_north"]                               # stone mural

ROUTE_TO = {
    "R01": [], "R02": TO_R02, "R03": TO_R03, "R04": TO_R04, "R05": IN_R05,
    "R06": IN_R06, "R07": IN_R07, "R08": IN_R08, "R09": IN_R09,
}

# Every `use_requires_flag` gate, with a route that HOLDS the object while the
# prerequisite is still unset, and a route that satisfies it. Both arms of the
# same call are then asserted below — refused, then granted.
GATES = [
    # object,        needs,          sets,           refuse-here,   grant-here
    ("lantern",      "has_oil",      "lantern_lit",  HOLD_LANTERN,  HOLD_OIL),
    ("valve_wheel",  "lantern_lit",  "steam_vented", HOLD_OIL + ["take_valve_wheel"], HOLD_VALVE),
    ("ledger",       "has_cog",      "knows_hour",   IN_R08 + ["take_ledger"],
                                                     HOLD_COG + ["go_east", "take_ledger"]),
    ("cog_bronze",   "knows_hour",   "clock_set",    HOLD_COG,      KNOWS_HOUR + ["go_west"]),
    ("key_skeleton", "clock_set",    "gate_open",    IN_R08 + ["take_key_skeleton"],
                                                     CLOCK_SET + ["go_east", "take_key_skeleton"]),
]

gate = GateRunner()


def check(ok, label, detail=""):
    """Adapter to GateRunner's (name, ok, detail) order, so call sites read naturally."""
    return gate.ck(label, ok, detail)


def objects_from_content() -> list:
    with open(os.path.join(GAME, "content", "objects.csv"), newline="") as fh:
        return list(csv.DictReader(fh))


def truthy(v) -> bool:
    return str(v).strip().lower() == "true"


class Driver:
    """Steps the adapter, running the shared invariant suite after every command,
    and recording which declared actions have actually been issued."""

    def __init__(self, adapter, by_name):
        self.ad = adapter
        self.by_name = by_name
        self.violations: list[str] = []
        self.issued: set = set()
        self.commands = 0
        self.state: dict = {}

    def reset(self):
        self.state = self.ad.reset()
        return self.state

    def step(self, name: str):
        before = self.state
        after, _term, _trunc, info = self.ad.step(self.by_name[name])
        self.commands += 1
        self.issued.add(name)
        for v in SUITE.check_command(before, after, name, info or {}):
            self.violations.append(f"after {name} #{self.commands}: {v}")
        self.state = after
        return after

    def run(self, names):
        for n in names:
            self.step(n)
        return self.state

    def goto(self, room: str):
        """Fresh game, then walk the content's own route to `room`."""
        self.reset()
        self.run(ROUTE_TO[room])
        return self.state


def main() -> int:
    print("Escape Room R2 — the full content spine over the real wire\n")

    cfg = UgtConfig(CONFIG)
    by_name = {v["name"]: int(k) for k, v in cfg.action_mappings.items()}
    declared = set(by_name)
    objects = objects_from_content()

    ad = SubprocessAdapter(cfg)
    ad.connect()
    d = Driver(ad, by_name)
    try:
        # ── every route actually arrives ─────────────────────────────────────
        print("  -- the routes reach every room that holds an object --")
        wrong = []
        for room in sorted(ROUTE_TO):
            if d.goto(room)["current_room"] != room:
                wrong.append(f"{room}(got {d.state['current_room']})")
        check(not wrong, f"all {len(ROUTE_TO)} routes arrive where they claim",
              f"misrouted: {wrong}" if wrong else "")

        # ── observation verbs ────────────────────────────────────────────────
        print("\n  -- look / inventory are observation-only --")
        d.reset()
        b = d.state
        a = d.step("look")
        check(a["moves_taken"] == b["moves_taken"] + 1
              and {k: v for k, v in a.items() if k != "moves_taken"}
              == {k: v for k, v in b.items() if k != "moves_taken"},
              "`look` costs a move and changes nothing else",
              f"moves {b['moves_taken']} -> {a['moves_taken']}")
        b = d.state
        a = d.step("inventory")
        check(a["moves_taken"] == b["moves_taken"] + 1
              and a["current_room"] == b["current_room"]
              and a["inventory"] == b["inventory"],
              "`inventory` costs a move and changes nothing else")

        # ── a direction with no exit ─────────────────────────────────────────
        print("\n  -- a direction with no exit --")
        b = d.state
        a = d.step("go_south")          # R01 has no south exit
        check(a == b, "a direction with no exit is COMPLETELY inert",
              f"still in {a['current_room']} at {a['moves_taken']} moves")

        # ── immovable objects ────────────────────────────────────────────────
        print("\n  -- immovable objects refuse `take` --")
        immovable = [o for o in objects if not truthy(o["takeable"])]
        for obj in immovable:
            oid, room = obj["object_id"], obj["start_room"]
            d.goto(room)
            b = d.state
            d.step(f"examine_{oid}")
            check(d.state["moves_taken"] == b["moves_taken"] + 1,
                  f"`examine_{oid}` works in {room} — it is really there")
            check(f"take_{oid}" not in declared,
                  f"no `take_{oid}` action is even declared (takeable=false)")
        check(len(immovable) == 2, "the content still ships exactly 2 immovable objects",
              f"{[o['object_id'] for o in immovable]}")

        # ── red herrings ─────────────────────────────────────────────────────
        # "No puzzle role" = sets no flag when taken AND accepts no `use` verb.
        # That is 4 objects, not the 3 narrative red herrings: the two immovable
        # scenery pieces qualify too. Deriving the set from the CSV rather than
        # naming it keeps a content edit honest — the first draft of this check
        # asserted 3 from memory and was wrong about its own content.
        print("\n  -- objects with no puzzle role set no flag --")
        inert_objects = [o for o in objects
                         if not o["take_sets_flag"] and not o["use_verb"]]
        for obj in inert_objects:
            oid, room = obj["object_id"], obj["start_room"]
            d.goto(room)
            before_flags = dict(d.state["flags"])
            names = [n for n in (f"examine_{oid}", f"take_{oid}", f"drop_{oid}")
                     if n in declared]
            d.run(names)
            check(d.state["flags"] == before_flags,
                  f"{oid}: {len(names)} action(s), no flag touched", f"tried {names}")
        check(len(inert_objects) == 4,
              "the content still ships exactly 4 objects with no puzzle role",
              f"{[o['object_id'] for o in inert_objects]}")

        # ── take -> drop -> re-take ──────────────────────────────────────────
        print("\n  -- take -> drop -> re-take, every takeable object --")
        takeable = [o for o in objects if truthy(o["takeable"])]
        broken = []
        for obj in takeable:
            oid, room = obj["object_id"], obj["start_room"]
            d.goto(room)
            held = d.step(f"take_{oid}")["inventory"]
            dropped = d.step(f"drop_{oid}")["inventory"]
            retaken = d.step(f"take_{oid}")["inventory"]
            if not (oid in held and oid not in dropped and oid in retaken):
                broken.append(oid)
        check(not broken,
              f"all {len(takeable)} takeable objects survive take -> drop -> re-take",
              "a dropped item is left in the room, not destroyed"
              if not broken else f"broken: {broken}")

        # ── examine reaches everything ───────────────────────────────────────
        print("\n  -- examine reaches every object --")
        unexaminable = []
        for obj in objects:
            oid, room = obj["object_id"], obj["start_room"]
            d.goto(room)
            b = d.state
            if d.step(f"examine_{oid}")["moves_taken"] != b["moves_taken"] + 1:
                unexaminable.append(oid)
        check(not unexaminable,
              f"all {len(objects)} objects are examinable in their start room",
              f"not examinable: {unexaminable}" if unexaminable else "")

        # ── every use-gate: refused, then granted ────────────────────────────
        # The same call, two different answers. The feature map can only make
        # this claim for ONE object (F3/F4 on the lantern); here it is every gate.
        print("\n  -- every use_requires_flag gate: refused, then granted --")
        gated = [o for o in objects if o["use_verb"] and o["use_requires_flag"]]
        covered = set()
        for oid, needs, sets, refuse_route, grant_route in GATES:
            covered.add(oid)
            # Arm 1 — held, prerequisite unset: the call must change NOTHING.
            d.reset()
            d.run(refuse_route)
            check(oid in d.state["inventory"] and not d.state["flags"][needs],
                  f"{oid}: staged holding it with {needs} still unset",
                  f"held={oid in d.state['inventory']} {needs}={d.state['flags'][needs]}")
            b = d.state
            d.step(f"use_{oid}")
            check(d.state == b,
                  f"{oid}: refused while {needs} is unset — nothing at all changed")
            # Arm 2 — the SAME call, prerequisite now set: it must fire.
            d.reset()
            d.run(grant_route)
            check(d.state["flags"][needs] and not d.state["flags"][sets],
                  f"{oid}: staged with {needs} set and {sets} not yet",
                  f"{needs}={d.state['flags'][needs]} {sets}={d.state['flags'][sets]}")
            d.step(f"use_{oid}")
            check(d.state["flags"][sets] is True,
                  f"{oid}: the SAME call sets {sets} once {needs} holds")
        check(covered == {o["object_id"] for o in gated},
              f"all {len(gated)} gated objects were exercised on BOTH sides",
              f"untested gates: {sorted({o['object_id'] for o in gated} - covered) or 'none'}")

        # ── consumption is permanent ─────────────────────────────────────────
        print("\n  -- consumption is permanent --")
        d.reset()
        d.run(KNOWS_HOUR + ["go_west"])              # in R07, cog held, hour known
        held_before = list(d.state["inventory"])
        d.step("use_cog_bronze")
        check(d.state["flags"]["clock_set"] is True, "the cog sets clock_set when used")
        check("cog_bronze" not in d.state["inventory"],
              "a use_consumes object leaves the inventory",
              f"{held_before} -> {d.state['inventory']}")
        b = d.state
        d.step("drop_cog_bronze")
        check(d.state == b, "a consumed item cannot be dropped (gone, not hidden)")
        d.step("use_cog_bronze")
        check(d.state == b, "a consumed item cannot be used a second time")
        d.step("take_cog_bronze")
        check(d.state == b, "a consumed item cannot be re-taken from the room")
        consuming = [o for o in objects if truthy(o["use_consumes"])]
        check(len(consuming) == 3, "the content still ships exactly 3 consuming objects",
              f"{[o['object_id'] for o in consuming]}")

        # ── the spine still ends in an escape ────────────────────────────────
        print("\n  -- and the run still escapes --")
        d.run(["go_east", "take_key_skeleton", "go_west",
               "go_north", "use_key_skeleton", "go_north"])
        check(d.state["escaped"] is True,
              "the run that exercised the whole content surface still escapes",
              f"room={d.state['current_room']} moves={d.state['moves_taken']}")

        # ── action coverage ──────────────────────────────────────────────────
        print("\n  -- action coverage --")
        reached_in_play = len(d.issued)
        leftover = sorted(declared - d.issued)
        for name in leftover:
            d.step(name)                 # issue it; inert is a fine outcome here
        check(not (declared - d.issued),
              f"all {len(declared)} declared actions were issued at least once",
              f"{reached_in_play} reached during play"
              + (f", {len(leftover)} swept at the end: {leftover}" if leftover else ""))

        # ── invariants ───────────────────────────────────────────────────────
        print("\n  -- invariants --")
        check(not d.violations,
              f"{len(SUITE.predicates)} invariants held across all {d.commands} commands",
              "" if not d.violations else "; ".join(d.violations[:3]))
        check(d.commands > 200, "the sweep is NON-VACUOUS (a long, real playthrough)",
              f"{d.commands} commands checked")
    finally:
        ad.close()

    return gate.finish(
        "ROUND 2",
        "The whole content surface is exercised: every declared action issued, every object "
        "taken/dropped/examined, every use-gate refused then granted, consumption proven "
        "permanent, red herrings proven inert — and the run still escapes.")


if __name__ == "__main__":
    sys.exit(main())
