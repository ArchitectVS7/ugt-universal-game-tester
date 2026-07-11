"""
DDD per-command invariants — reusable pure predicates asserted after EVERY action
driven through the DddHarnessAdapter.

Each predicate has the signature

    inv_xxx(before: dict, after: dict, command: str, result: dict) -> str | None

where `before`/`after` are the adapter's NORMALIZED state dicts (the shape
`DddHarnessAdapter._normalize` returns — turn/phase/resultKind/stateHash plus a
`p0`/`p1` seat summary each carrying hp/focus/handCount/deckCount/graveyardCount/
committedCard/…) and `result` is the raw harness `act` response dict (`ok`,
`applied`, `events`, `stateHash`, and the `legalCount` the adapter injects). A
predicate returns a human-readable violation string, or `None` when it holds.
Nothing here re-implements game logic; every check reads observable state back and
compares.

DDD facts these encode (from the engine's own bounds):
  * HP 0–30, focus 0–5, hand ≤7, exactly 3 zones (HAND/GRAVEYARD/DECK, no exile),
    40 cards total per seat — so per seat
    handCount + deckCount + graveyardCount + committedCard == 40, EXACTLY. The
    committedCard term accounts for the single card lifted out of hand into the
    pending committedSelection.
  * turn is monotonic non-decreasing.
  * The adapter only ever sends a LEGAL, self-selected action (never CONCEDE), so a
    RULES_ERROR on such an action (`result.ok is False` for an `act`) is a real
    defect — `inv_no_error_on_legal`.
  * While the match is ONGOING the pending seat always has ≥1 legal action
    (`legalCount>=1`) — `inv_legal_nonempty_while_ongoing`.
"""
from __future__ import annotations

from ugt.core.trial import InvariantSuite

HP_MAX = 30
FOCUS_MAX = 5
HAND_CAP = 7
DECK_TOTAL = 40


# ── individual predicates ────────────────────────────────────────────────────
def inv_hash_present(before, after, command, result):
    """Every step carries a non-empty stateHash (the determinism canary)."""
    h = after.get("stateHash")
    if not h or not isinstance(h, str):
        return f"missing/empty stateHash after {command!r}: {h!r}"
    return None


def inv_hp_bounds(before, after, command, result):
    """Both seats' HP stays within 0..30."""
    for seat in ("p0", "p1"):
        hp = after.get(seat, {}).get("hp")
        if hp is None:
            continue
        if hp < 0 or hp > HP_MAX:
            return f"{seat} hp out of bounds after {command!r}: {hp} (0..{HP_MAX})"
    return None


def inv_focus_bounds(before, after, command, result):
    """Both seats' focus stays within 0..5."""
    for seat in ("p0", "p1"):
        focus = after.get(seat, {}).get("focus")
        if focus is None:
            continue
        if focus < 0 or focus > FOCUS_MAX:
            return f"{seat} focus out of bounds after {command!r}: {focus} (0..{FOCUS_MAX})"
    return None


def inv_hand_cap(before, after, command, result):
    """Neither seat's hand exceeds the 7-card cap."""
    for seat in ("p0", "p1"):
        hand = after.get(seat, {}).get("handCount")
        if hand is None:
            continue
        if hand > HAND_CAP:
            return f"{seat} hand over cap after {command!r}: {hand} (>{HAND_CAP})"
    return None


def inv_card_conservation(before, after, command, result):
    """Per seat, cards are conserved EXACTLY: handCount + deckCount +
    graveyardCount + committedCard == 40. Only 3 zones exist (no exile), and the
    single committed card is accounted for by committedCard."""
    for seat in ("p0", "p1"):
        s = after.get(seat, {})
        hand = s.get("handCount")
        deck = s.get("deckCount")
        grave = s.get("graveyardCount")
        committed = s.get("committedCard", 0)
        if None in (hand, deck, grave):
            continue
        total = hand + deck + grave + committed
        if total != DECK_TOTAL:
            return (f"{seat} card conservation broken after {command!r}: "
                    f"hand{hand}+deck{deck}+grave{grave}+committed{committed} "
                    f"= {total} != {DECK_TOTAL}")
    return None


def inv_turn_monotonic(before, after, command, result):
    """The turn counter never goes backwards across a step."""
    b = before.get("turn")
    a = after.get("turn")
    if b is None or a is None:
        return None
    if a < b:
        return f"turn regressed across {command!r}: {b} -> {a}"
    return None


def inv_no_error_on_legal(before, after, command, result):
    """The adapter only ever sends a LEGAL, self-selected, non-CONCEDE action, so
    an `act` that comes back with ok:false (a RULES_ERROR) is a real defect — the
    adapter picked a move the engine then rejected, or the engine mis-adjudicated a
    legal move."""
    if command != "act":
        return None
    if result.get("ok") is False:
        err = result.get("error", {})
        return (f"RULES_ERROR on a self-selected LEGAL action ({command!r}): "
                f"{err.get('kind')} {err.get('rulesError')}")
    return None


def inv_legal_nonempty_while_ongoing(before, after, command, result):
    """While the match is ONGOING, the seat just driven had ≥1 legal action — a
    zero-legal-action ONGOING state is a soft-lock."""
    if after.get("resultKind") != "ONGOING":
        return None
    if result.get("legalCount", 0) < 1:
        return (f"no legal actions while ONGOING after {command!r} "
                f"(legalCount={result.get('legalCount')})")
    return None


ALL = [
    inv_hash_present,
    inv_hp_bounds,
    inv_focus_bounds,
    inv_hand_cap,
    inv_card_conservation,
    inv_turn_monotonic,
    inv_no_error_on_legal,
    inv_legal_nonempty_while_ongoing,
]

# One definition, both tiers: R1/R2 sweep via SUITE.check_command; R3 hands the
# same predicates to the ExploitHunter via SUITE.to_hunter_invariants().
SUITE = InvariantSuite(ALL)


def build_suite() -> InvariantSuite:
    """Fresh InvariantSuite over ALL predicates (R3 hunter-ready)."""
    return InvariantSuite(ALL)


def check_command(before, after, command, result):
    """Run every invariant for one command; return the list of violation strings
    (empty when all hold)."""
    return SUITE.check_command(before, after, command, result)
