"""Tiny Escape Room invariants — properties that must hold after EVERY command.

Written once, consumed twice, courtesy of `ugt.core.trial.InvariantSuite`:

  * R1/R2 (scripted rounds) call `SUITE.check_command(before, after, cmd, result)`
    after every command they issue.
  * R3 (invariant-fuzzer) calls `SUITE.to_hunter_invariants()` for the SAME
    predicates wrapped to the hunter's signature.

One definition, both tiers — the scripted ladder and the random walk can never
disagree about what "correct" means. (Before this file existed, R3's predicates
lived inline in `fuzz_escape_room.py` and there was nothing for R1/R2 to share.)

None of these re-implements a rule. They read state the GAME returned and check
relationships within it. Nothing here decides whether a door should open; that
lives in `../game/src/engine.js` and only the game gets to say.

Predicate signature: (before, after, command, result) -> violation str | None.
Name and docstring surface in the hunter's finding reports.
"""
from __future__ import annotations

import csv
import os
import sys
from typing import Optional

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from ugt.core.trial import InvariantSuite  # noqa: E402

GAME = os.path.abspath(os.path.join(HERE, "..", "game"))


def _rooms_from_content() -> set:
    """Read room ids from the GAME's own CSV, so this can never drift from the
    shipped content the way a hardcoded list would."""
    with open(os.path.join(GAME, "content", "rooms.csv"), newline="") as fh:
        return {row["room_id"] for row in csv.DictReader(fh)}


def _objects_from_content() -> set:
    with open(os.path.join(GAME, "content", "objects.csv"), newline="") as fh:
        return {row["object_id"] for row in csv.DictReader(fh)}


ROOMS = _rooms_from_content()
OBJECTS = _objects_from_content()


def moves_never_decrease(before: dict, after: dict, command: str, result: dict) -> Optional[str]:
    """moves_taken is monotonic non-decreasing."""
    if after["moves_taken"] < before["moves_taken"]:
        return (f"moves_taken went backwards: "
                f"{before['moves_taken']} -> {after['moves_taken']}")
    return None


def moves_advance_by_at_most_one(before: dict, after: dict, command: str, result: dict) -> Optional[str]:
    """A single command consumes at most one move."""
    delta = after["moves_taken"] - before["moves_taken"]
    if delta > 1:
        return f"one action advanced moves_taken by {delta} (expected 0 or 1)"
    return None


def rooms_visited_never_decreases(before: dict, after: dict, command: str, result: dict) -> Optional[str]:
    """rooms_visited is monotonic non-decreasing."""
    if after["rooms_visited"] < before["rooms_visited"]:
        return (f"rooms_visited went backwards: "
                f"{before['rooms_visited']} -> {after['rooms_visited']}")
    return None


def rooms_visited_within_the_map(before: dict, after: dict, command: str, result: dict) -> Optional[str]:
    """rooms_visited never exceeds the number of rooms that exist."""
    if after["rooms_visited"] > len(ROOMS):
        return (f"rooms_visited={after['rooms_visited']} exceeds the "
                f"{len(ROOMS)} rooms in rooms.csv")
    return None


def current_room_is_real(before: dict, after: dict, command: str, result: dict) -> Optional[str]:
    """current_room is always a room_id defined in the game's rooms.csv."""
    room = after.get("current_room")
    if room not in ROOMS:
        return f"current_room {room!r} is not one of {sorted(ROOMS)}"
    return None


def a_move_goes_to_an_adjacent_room(before: dict, after: dict, command: str, result: dict) -> Optional[str]:
    """A single command changes the room by at most one step, and only to a room
    the previous room actually exits into.

    This is what catches a transport that silently teleports — the shape of bug a
    "did the state change?" check reads as success."""
    src, dst = before.get("current_room"), after.get("current_room")
    if src == dst:
        return None
    exits = _EXITS.get(src, set())
    if dst not in exits:
        return (f"moved {src} -> {dst}, which is not an exit of {src} "
                f"(exits: {sorted(exits) or 'none'})")
    return None


def inventory_holds_only_real_objects(before: dict, after: dict, command: str, result: dict) -> Optional[str]:
    """Every inventory entry is an object_id from objects.csv, with no duplicates."""
    inv = after.get("inventory") or []
    unknown = [o for o in inv if o not in OBJECTS]
    if unknown:
        return f"inventory holds unknown object(s) {unknown}"
    if len(set(inv)) != len(inv):
        return f"inventory holds a duplicate: {inv}"
    return None


def inventory_changes_by_at_most_one(before: dict, after: dict, command: str, result: dict) -> Optional[str]:
    """One command moves at most one item into or out of the inventory."""
    b, a = set(before.get("inventory") or []), set(after.get("inventory") or [])
    if len(a ^ b) > 1:
        return (f"one action changed the inventory by {len(a ^ b)} items: "
                f"{sorted(b)} -> {sorted(a)}")
    return None


def escaped_never_reverts(before: dict, after: dict, command: str, result: dict) -> Optional[str]:
    """escaped latches: once true it can never go back to false."""
    if before.get("escaped") and not after.get("escaped"):
        return "escaped reverted from True to False"
    return None


def escaped_is_only_ever_won_in_the_exit_room(before: dict, after: dict, command: str, result: dict) -> Optional[str]:
    """escaped can only BECOME true on entering the exit room (the last row of
    rooms.csv — the game's own authoring convention).

    Asserted on the TRANSITION, not on the standing state. The first draft of
    this predicate checked `escaped => in the exit room`, which R1 immediately
    contradicted: R10 exits south back to R09, and `escaped` latches, so walking
    back out leaves a true flag in another room. That is the PRD's documented
    behaviour, and the predicate — not the game — was wrong. Latching and
    "you won it here" are different claims; only the second one is checkable."""
    if after.get("escaped") and not before.get("escaped"):
        if after.get("current_room") != EXIT_ROOM:
            return (f"escaped became True in {after.get('current_room')!r}, "
                    f"not the exit room {EXIT_ROOM!r}")
    return None


def flags_never_unset(before: dict, after: dict, command: str, result: dict) -> Optional[str]:
    """A set flag is never cleared — the whole puzzle chain depends on latching."""
    for name, was in (before.get("flags") or {}).items():
        if was and not (after.get("flags") or {}).get(name):
            return f"flag {name!r} reverted from True to False"
    return None


def the_flag_key_set_is_stable(before: dict, after: dict, command: str, result: dict) -> Optional[str]:
    """The set of flag NAMES never changes mid-run.

    The engine seeds the whole flag universe as False up front precisely so a
    client can trust the key set; a flag appearing mid-run would mean a consumer
    reading `flags.x == False` was reading a missing key, not a false one."""
    b, a = set((before.get("flags") or {})), set((after.get("flags") or {}))
    if a != b:
        return f"the flag key set changed: appeared={sorted(a - b)} vanished={sorted(b - a)}"
    return None


def a_free_action_changes_nothing_at_all(before: dict, after: dict, command: str, result: dict) -> Optional[str]:
    """If moves_taken did not advance, NOTHING advanced.

    The engine's documented refusal semantics: an inapplicable action "consumes
    no state". Both the feature map's F1/F5 and R2's red-herring probes are built
    on it, so it is asserted directly rather than assumed."""
    if after["moves_taken"] == before["moves_taken"] and after != before:
        changed = sorted(k for k in after if after.get(k) != before.get(k))
        return (f"a refused action left moves_taken at {after['moves_taken']} "
                f"but still changed {changed}")
    return None


def _exits_from_content() -> dict:
    """room_id -> set of rooms it exits into, read from the game's own CSV."""
    out = {}
    with open(os.path.join(GAME, "content", "rooms.csv"), newline="") as fh:
        for row in csv.DictReader(fh):
            out[row["room_id"]] = {
                row[c] for c in ("exit_north", "exit_south", "exit_east", "exit_west")
                if row.get(c)
            }
    return out


def _exit_room_from_content() -> str:
    """The engine's authoring convention: the LAST row of rooms.csv is the exit."""
    with open(os.path.join(GAME, "content", "rooms.csv"), newline="") as fh:
        return list(csv.DictReader(fh))[-1]["room_id"]


_EXITS = _exits_from_content()
EXIT_ROOM = _exit_room_from_content()


PREDICATES = [
    moves_never_decrease,
    moves_advance_by_at_most_one,
    rooms_visited_never_decreases,
    rooms_visited_within_the_map,
    current_room_is_real,
    a_move_goes_to_an_adjacent_room,
    inventory_holds_only_real_objects,
    inventory_changes_by_at_most_one,
    escaped_never_reverts,
    escaped_is_only_ever_won_in_the_exit_room,
    flags_never_unset,
    the_flag_key_set_is_stable,
    a_free_action_changes_nothing_at_all,
]

SUITE = InvariantSuite(PREDICATES)
