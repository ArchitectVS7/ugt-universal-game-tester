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
    """moves_taken is monotonic non-decreasing within a level."""
    # A level advance resets the counter by design, so only compare inside one level.
    if after["level_index"] == before["level_index"] and after["moves_taken"] < before["moves_taken"]:
        return (f"moves_taken went backwards on level {after['level_index']}: "
                f"{before['moves_taken']} -> {after['moves_taken']}")
    return None


def moves_advance_by_at_most_one(before: dict, after: dict, command: str, result: dict) -> Optional[str]:
    """A single action consumes at most one move."""
    if after["level_index"] != before["level_index"]:
        return None  # level advance resets the counter
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
    """all_levels_solved latches: once true it never reverts."""
    if before["all_levels_solved"] and not after["all_levels_solved"]:
        return "all_levels_solved reverted from True to False"
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
]

SUITE = InvariantSuite(PREDICATES)
