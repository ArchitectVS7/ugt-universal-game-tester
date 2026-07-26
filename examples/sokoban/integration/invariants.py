"""Sokoban Mini invariants — properties that must hold after EVERY command.

Written once, consumed twice, courtesy of `ugt.core.trial.InvariantSuite`:

  * R1/R2 (scripted rounds) call `SUITE.check_command(before, after, cmd, result)`
    after every command they issue.
  * R3 (invariant-fuzzer) calls `SUITE.to_hunter_invariants()` for the SAME
    predicates wrapped to the hunter's signature.

One definition, both tiers — the scripted ladder and the random walk can never
disagree about what "correct" means.

None of these re-implements a rule. They read state the GAME returned and check
relationships within it. Nothing here decides whether a push was legal; that
lives in `../game/scripts/board.gd` and only the game gets to say.

Predicate signature: (before, after, command, result) -> violation str | None.
Name and docstring surface in the hunter's finding reports.
"""
from __future__ import annotations

import os
import sys
from typing import Optional

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from ugt.core.trial import InvariantSuite  # noqa: E402

LEVEL_COUNT = 3  # levels shipped by ../game; read, not enforced


def moves_never_decrease(before: dict, after: dict, command: str, result: dict) -> Optional[str]:
    """moves_taken never decreases, except a reload rewinds it to exactly 0.

    Pinned by the game's own test suite: the counter counts the whole session
    and is NOT zeroed by a level advance — only `reset_level` (action 4)
    zeroes it. So the only legal decrease is to exactly 0; any other backwards
    step is a wire or rules defect.
    """
    if after["moves_taken"] < before["moves_taken"] and after["moves_taken"] != 0:
        return (f"moves_taken went backwards to a non-zero value: "
                f"{before['moves_taken']} -> {after['moves_taken']}")
    return None


def moves_advance_by_at_most_one(before: dict, after: dict, command: str, result: dict) -> Optional[str]:
    """A single action consumes at most one move (a reload's rewind is negative,
    which this deliberately ignores — moves_never_decrease owns that side)."""
    delta = after["moves_taken"] - before["moves_taken"]
    if delta > 1:
        return f"one action advanced moves_taken by {delta} (expected 0 or 1)"
    return None


def player_within_bounds(before: dict, after: dict, command: str, result: dict) -> Optional[str]:
    """The player's coordinates are never negative."""
    if after["player_x"] < 0 or after["player_y"] < 0:
        return f"player left the grid: ({after['player_x']}, {after['player_y']})"
    return None


def boxes_on_target_within_total(before: dict, after: dict, command: str, result: dict) -> Optional[str]:
    """0 <= boxes_on_target <= boxes_total."""
    got, total = after["boxes_on_target"], after["boxes_total"]
    if not (0 <= got <= total):
        return f"boxes_on_target={got} outside 0..{total}"
    return None


def boxes_total_is_positive(before: dict, after: dict, command: str, result: dict) -> Optional[str]:
    """Every level has at least one box — a level with none would be vacuously solved."""
    if after["boxes_total"] < 1:
        return f"boxes_total={after['boxes_total']} (a level with no boxes is trivially 'solved')"
    return None


def level_index_never_regresses(before: dict, after: dict, command: str, result: dict) -> Optional[str]:
    """level_index only ever advances, and never past the last shipped level."""
    if after["level_index"] < before["level_index"]:
        return f"level_index went backwards: {before['level_index']} -> {after['level_index']}"
    if after["level_index"] >= LEVEL_COUNT and not after["all_levels_solved"]:
        return (f"level_index={after['level_index']} is past the last of {LEVEL_COUNT} levels "
                f"while all_levels_solved is False")
    return None


def solved_flag_matches_box_count(before: dict, after: dict, command: str, result: dict) -> Optional[str]:
    """level_solved is true only when every box is on a target.

    The converse is deliberately NOT asserted: on the final level the game may
    advance/settle, so "all boxes home" without the flag is not by itself wrong.
    Claiming solved while a box is loose always is.
    """
    if after["level_solved"] and after["boxes_on_target"] != after["boxes_total"]:
        return (f"level_solved=True with only {after['boxes_on_target']}/"
                f"{after['boxes_total']} boxes on target")
    return None


def all_levels_solved_is_terminal(before: dict, after: dict, command: str, result: dict) -> Optional[str]:
    """all_levels_solved latches, except across a reload (PRD: retrying the last
    level un-freezes the board).

    A legal un-latching transition is recognisable by its shape, not by the
    command (the fuzzer passes no command string): the after-state must be a
    fresh start of the SAME level — moves_taken 0, level_index unchanged. Any
    other revert is a defect.
    """
    if before["all_levels_solved"] and not after["all_levels_solved"]:
        is_reload = (after["moves_taken"] == 0
                     and after["level_index"] == before["level_index"])
        if not is_reload:
            return "all_levels_solved reverted from True to False outside a reload"
    return None


def grid_matches_scalar_state(before: dict, after: dict, command: str, result: dict) -> Optional[str]:
    """The player-facing grid and the scalar fields describe the SAME position.

    The grid is a render, the scalars are the state — if they ever disagree, a
    human and a machine player are being shown different games. Checks: exactly
    one player marker, at (player_x, player_y); box markers count boxes_total;
    '*' markers count boxes_on_target.
    """
    grid = after.get("grid")
    if not isinstance(grid, list) or not grid:
        return f"grid missing or empty: {type(grid).__name__}"
    players = [(x, y) for y, row in enumerate(grid)
               for x, ch in enumerate(row) if ch in "@+"]
    if players != [(after["player_x"], after["player_y"])]:
        return (f"grid shows player at {players}, scalars say "
                f"({after['player_x']}, {after['player_y']})")
    boxes = sum(row.count("$") + row.count("*") for row in grid)
    if boxes != after["boxes_total"]:
        return f"grid shows {boxes} boxes, boxes_total says {after['boxes_total']}"
    on_target = sum(row.count("*") for row in grid)
    if on_target != after["boxes_on_target"]:
        return (f"grid shows {on_target} boxes on targets, "
                f"boxes_on_target says {after['boxes_on_target']}")
    return None


PREDICATES = [
    moves_never_decrease,
    moves_advance_by_at_most_one,
    player_within_bounds,
    boxes_on_target_within_total,
    boxes_total_is_positive,
    level_index_never_regresses,
    solved_flag_matches_box_count,
    all_levels_solved_is_terminal,
    grid_matches_scalar_state,
]

SUITE = InvariantSuite(PREDICATES)
