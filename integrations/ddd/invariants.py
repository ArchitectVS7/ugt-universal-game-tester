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
  * HP 0–30, focus 0–5, hand ≤7, exactly 3 zones (HAND/GRAVEYARD/DECK, no exile) —
    so per seat handCount + deckCount + graveyardCount + committedCard is CONSERVED
    across every step. The committedCard term accounts for the single card lifted
    out of hand into the pending committedSelection.
    The ABSOLUTE total is format-relative (COMPETITIVE 40, TUTORIAL 25), so it is
    NOT asserted here — `inv_card_conservation` asserts the conservation law, which
    holds in every format, and scripts that know their format assert the absolute
    figure themselves (`absolute_total`, used by verify_round1/verify_round2).
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


def _seat_total(seat_state):
    """handCount + deckCount + graveyardCount + committedCard, or None if unknown.

    Only 3 zones exist (HAND/GRAVEYARD/DECK — no exile), and the single card lifted
    out of hand into a pending committedSelection is accounted for by committedCard.
    """
    hand = seat_state.get("handCount")
    deck = seat_state.get("deckCount")
    grave = seat_state.get("graveyardCount")
    committed = seat_state.get("committedCard", 0)
    if None in (hand, deck, grave):
        return None
    return hand + deck + grave + committed


def inv_card_conservation(before, after, command, result):
    """Per seat, cards are CONSERVED: the zone total never changes across a step.

    Stated as a conservation LAW (total_after == total_before) rather than a
    hard-coded `== 40`, because the absolute total is format-relative — COMPETITIVE
    decks are 40 cards, TUTORIAL decks are 25 — while conservation holds in every
    format. The literal-40 form was a real bug in this file: it reported a violation
    on every step of every TUTORIAL match, where the true total is 25 and the game
    was conserving it correctly.

    This still catches everything the absolute form did (a card created, destroyed,
    duplicated, or lost between zones), and it catches it in formats the absolute
    form could not even run in. Scripts that KNOW their format additionally assert
    the absolute total (see verify_round1/2) — that is where 40-vs-25 belongs.
    """
    for seat in ("p0", "p1"):
        t_after = _seat_total(after.get(seat, {}))
        t_before = _seat_total(before.get(seat, {}))
        if t_after is None or t_before is None:
            continue
        if t_after != t_before:
            a, b = after.get(seat, {}), before.get(seat, {})
            return (f"{seat} card conservation broken across {command!r}: "
                    f"total {t_before} -> {t_after} "
                    f"(before hand{b.get('handCount')}+deck{b.get('deckCount')}"
                    f"+grave{b.get('graveyardCount')}+committed{b.get('committedCard', 0)}; "
                    f"after hand{a.get('handCount')}+deck{a.get('deckCount')}"
                    f"+grave{a.get('graveyardCount')}+committed{a.get('committedCard', 0)})")
    return None


def absolute_total(state, seat) -> int | None:
    """The seat's zone total — for scripts that know the format's expected size
    (COMPETITIVE 40 / TUTORIAL 25) and want to assert it explicitly."""
    return _seat_total(state.get(seat, {}))


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
    """A RULES_ERROR on an action drawn from the engine's OWN legal list is a defect.

    For every non-probe action id the adapter selects only from the legal list the
    harness itself returned, so a refusal means either the enumerator offered a move
    the adjudicator then rejected, or the adjudicator mis-handled a legal move.
    Either way the two halves of the engine disagree, which is exactly what this
    exists to catch.

    SCOPED TO NON-PROBES: the `probe_illegal` / `probe_garbage` ids deliberately send
    actions from OUTSIDE the legal list, so this invariant's premise does not hold
    for them and a refusal there is the CORRECT outcome, not a defect. Probes are
    covered by the opposite assertion (R3's `inv_probe_refused`: a probe that is
    ACCEPTED is the finding). Skipping them here is a scoping fix, not a weakening —
    without it the invariant fires on its own test fixture.
    """
    if command != "act":
        return None
    if result.get("probe"):
        return None
    if result.get("ok") is False:
        err = result.get("error", {})
        return (f"RULES_ERROR on an action taken from the engine's own legal list "
                f"({result.get('actionName')!r}): {err.get('kind')} {err.get('rulesError')}")
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
