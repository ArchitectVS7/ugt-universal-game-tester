"""Dice Duel invariants — properties that must hold after EVERY round.

Written once, consumed twice via `ugt.core.trial.InvariantSuite`:

  * R1/R2 (scripted rounds) call `SUITE.check_command(before, after, cmd, result)`
    after every action they issue.
  * R3 (invariant-fuzzer) calls `SUITE.to_hunter_invariants()` for the same
    predicates wrapped to the hunter's signature.

One definition, both tiers — the scripted ladder and the random walk cannot
disagree about what "correct" means.

None of these re-implements a rule. They state relationships that must hold in
whatever state the GAME returned; nothing here decides how much damage a die
should do. That lives in `../game/src/engine.js`, and only the game gets a vote.

Predicate signature: (before, after, command, result) -> violation str | None.
"""
from __future__ import annotations

import os
import sys
from typing import Optional

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from ugt.core.trial import InvariantSuite  # noqa: E402

# The game's balance constants, READ FROM THE GAME rather than copied here.
#
# These were hardcoded (STARTING_FS = 20, MAX_ROUNDS = 12) until the 2026-07-26
# retune, which moved STARTING_FS to 12 and left the harness asserting a bound
# that was silently 8 too loose — an invariant that cannot fail is worth nothing.
# Parsing the game's own exported constants means a retune needs no edit here,
# and a renamed constant fails loudly instead of quietly.
#
# This is a READ of a published bound, not a re-implementation of a rule: the
# harness still never decides what damage a die should do.
import re

_ENGINE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "..", "game", "src", "engine.js")


def _const(name: str) -> int:
    src = open(_ENGINE).read()
    m = re.search(rf"^export const {name} = (\d+)", src, re.M)
    if not m:
        raise RuntimeError(
            f"{name} not found in {_ENGINE}. If the game renamed or removed it, this "
            f"harness needs updating — failing loudly rather than guessing a bound."
        )
    return int(m.group(1))


STARTING_FS = _const("STARTING_FS")
MAX_ROUNDS = _const("MAX_ROUNDS")
LEGAL_WINNERS = (None, "player", "enemy", "draw")


def force_strength_in_range(before: dict, after: dict, command: str, result: dict) -> Optional[str]:
    """Both sides' force_strength stays within 0..STARTING_FS."""
    for side in ("player", "enemy"):
        fs = after[side]["force_strength"]
        if not (0 <= fs <= STARTING_FS):
            return f"{side}.force_strength out of range: {fs} (allowed 0..{STARTING_FS})"
    return None


def force_strength_never_heals(before: dict, after: dict, command: str, result: dict) -> Optional[str]:
    """No allocation restores force_strength — it is non-increasing within a battle."""
    for side in ("player", "enemy"):
        if after[side]["force_strength"] > before[side]["force_strength"]:
            return (f"{side}.force_strength rose "
                    f"{before[side]['force_strength']} -> {after[side]['force_strength']}")
    return None


def round_number_advances_by_at_most_one(before: dict, after: dict, command: str, result: dict) -> Optional[str]:
    """round_number never decreases, and one action resolves at most one round."""
    d = after["round_number"] - before["round_number"]
    if d < 0:
        return f"round_number went backwards: {before['round_number']} -> {after['round_number']}"
    if d > 1:
        return f"one action advanced round_number by {d}"
    return None


def round_number_within_cap(before: dict, after: dict, command: str, result: dict) -> Optional[str]:
    """round_number never exceeds the game's MAX_ROUNDS cap."""
    if after["round_number"] > MAX_ROUNDS:
        return f"round_number {after['round_number']} exceeds the {MAX_ROUNDS}-round cap"
    return None


def winner_implies_battle_over(before: dict, after: dict, command: str, result: dict) -> Optional[str]:
    """A winner is only ever set on a concluded battle."""
    if after["winner"] is not None and not after["battle_over"]:
        return f"winner={after['winner']!r} while battle_over is False"
    return None


def winner_is_legal(before: dict, after: dict, command: str, result: dict) -> Optional[str]:
    """winner is null, 'player', 'enemy' or 'draw' — never anything else."""
    if after["winner"] not in LEGAL_WINNERS:
        return f"illegal winner value {after['winner']!r}"
    return None


def concluded_battle_is_inert(before: dict, after: dict, command: str, result: dict) -> Optional[str]:
    """battle_over latches, and a finished battle ignores everything.

    Still asserted after the D14 envelope fix let the adapter see termination:
    an episode-driven tier stops at the end now, but a scripted rung can still
    push past it deliberately (R1 and R2 both do), and "a finished battle is
    inert" is a real property of the game rather than an artefact of the wire.
    """
    if before["battle_over"] and not after["battle_over"]:
        return "battle_over reverted to False"
    if before["battle_over"] and after != before:
        changed = {k: (before[k], after[k]) for k in after if after[k] != before[k]}
        return f"a concluded battle still changed state: {changed}"
    return None


def bonus_dice_are_plausible(before: dict, after: dict, command: str, result: dict) -> Optional[str]:
    """bonus_dice is a small non-negative count.

    The game's three bonus rules can grant at most +1 (Morale) +1 (Dug in)
    +2 (Reinforcements) = 4 in a single round.
    """
    for side in ("player", "enemy"):
        b = after[side]["bonus_dice"]
        if not (0 <= b <= 4):
            return f"{side}.bonus_dice = {b}, outside the 0..4 the three bonus rules can produce"
    return None


PREDICATES = [
    force_strength_in_range,
    force_strength_never_heals,
    round_number_advances_by_at_most_one,
    round_number_within_cap,
    winner_implies_battle_over,
    winner_is_legal,
    concluded_battle_is_inert,
    bonus_dice_are_plausible,
]

SUITE = InvariantSuite(PREDICATES)
