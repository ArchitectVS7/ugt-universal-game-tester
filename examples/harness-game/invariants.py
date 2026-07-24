"""
Foraging Run invariants — properties that must hold after EVERY command.

These are the game-specific half of the trial ladder. They are written once here
and consumed two ways, courtesy of ugt.core.trial.InvariantSuite:

  * R1/R2 (scripted rounds) call `suite.check_command(before, after, cmd, result)`
    after every command they issue.
  * R3 (exploit-hunter) calls `suite.to_hunter_invariants()` to get the SAME
    predicates wrapped to the hunter's signature.

One definition, both tiers — so the scripted rounds and the random walk can never
drift apart on what "correct" means. Each predicate reads observable state back
and compares; none re-implements a rule (that would just be testing the test).

Predicate signature: (before, after, command, result) -> violation str | None.
The function name and docstring surface in the hunter's finding reports.
"""
from __future__ import annotations

from typing import Optional

from ugt.core.trial import InvariantSuite

HP_MAX = 10  # kept in sync with engine.HP_MAX (invariants read, they don't import rules)

# Fields that must never change once the run is already over.
_FROZEN = ("day", "hp", "supplies", "coins", "location", "rng_counter", "won", "lost")


def hp_in_bounds(before: dict, after: dict, command: str, result: dict) -> Optional[str]:
    """hp stays within [0, HP_MAX]."""
    if not (0 <= after["hp"] <= HP_MAX):
        return f"hp out of bounds: {after['hp']} (allowed 0..{HP_MAX})"
    return None


def supplies_non_negative(before: dict, after: dict, command: str, result: dict) -> Optional[str]:
    """supplies never goes negative."""
    if after["supplies"] < 0:
        return f"supplies negative: {after['supplies']}"
    return None


def coins_non_negative(before: dict, after: dict, command: str, result: dict) -> Optional[str]:
    """coins never goes negative."""
    if after["coins"] < 0:
        return f"coins negative: {after['coins']}"
    return None


def day_monotonic(before: dict, after: dict, command: str, result: dict) -> Optional[str]:
    """The day counter never runs backward."""
    if after["day"] < before["day"]:
        return f"day went backward: {before['day']} -> {after['day']}"
    return None


def location_monotonic(before: dict, after: dict, command: str, result: dict) -> Optional[str]:
    """You never teleport backward along the route."""
    if after["location"] < before["location"]:
        return f"location went backward: {before['location']} -> {after['location']}"
    return None


def rng_advances_only_forward(before: dict, after: dict, command: str, result: dict) -> Optional[str]:
    """The RNG-in-state counter only ever advances — the basis of replayability."""
    if after["rng_counter"] < before["rng_counter"]:
        return f"rng_counter went backward: {before['rng_counter']} -> {after['rng_counter']}"
    return None


def not_both_terminal(before: dict, after: dict, command: str, result: dict) -> Optional[str]:
    """A run is never both won AND lost."""
    if after["won"] and after["lost"]:
        return "state is simultaneously won and lost"
    return None


def terminal_is_sticky_and_noop(before: dict, after: dict, command: str, result: dict) -> Optional[str]:
    """Once a run is over, the outcome never flips and no further action mutates state."""
    was_over = before["won"] or before["lost"]
    if not was_over:
        return None
    # Outcome must not flip.
    if before["won"] != after["won"] or before["lost"] != after["lost"]:
        return (f"terminal outcome flipped: won {before['won']}->{after['won']}, "
                f"lost {before['lost']}->{after['lost']}")
    # Nothing else may change either (a post-terminal action is a pure no-op).
    changed = [k for k in _FROZEN if before[k] != after[k]]
    if changed:
        return f"state changed after run was already over: {changed}"
    return None


ALL_PREDICATES = [
    hp_in_bounds,
    supplies_non_negative,
    coins_non_negative,
    day_monotonic,
    location_monotonic,
    rng_advances_only_forward,
    not_both_terminal,
    terminal_is_sticky_and_noop,
]


def build_invariant_suite() -> InvariantSuite:
    return InvariantSuite(ALL_PREDICATES)
