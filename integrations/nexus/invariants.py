"""
NEXUS per-command invariants — reusable pure predicates asserted after EVERY
command driven through the NexusHttpAdapter.

Each predicate has the signature

    inv_xxx(before: dict, after: dict, command: str, result: dict) -> str | None

where `before`/`after` are the adapter's parsed player-state dicts (the shape
`NexusHttpAdapter._read_state()` returns — ints already coerced for
level/xp/credits/rngCounter) and `result` is the raw `CommandResult` dict the
closed-alpha route returned. A predicate returns a human-readable violation
string, or `None` when the invariant holds. Nothing here re-implements game
logic; every check reads the observable state back and compares it.

Two pre-carved NEXUS quirks are encoded here so they are NOT mis-flagged:

  * NX-OBS-1 — a command ticks `rngCounter` UNCONDITIONALLY at handler entry,
    BEFORE command lookup, so even a refused/garbage command advances the
    per-command RNG clock by exactly 1. `inv_rng_tick` therefore requires +1 on
    EVERY step (refusals included), and `inv_refused_state_inert` compares a
    game-state fingerprint that DELIBERATELY EXCLUDES `rngCounter`.

  * NX-OBS-2 — the exploit/crack success roll is genuinely seeded but runs at a
    high (~90%) base rate; that is a characterization of the roll, not an
    invariant, so it lives in the verify script's variance sweep, not here.
"""
from __future__ import annotations


# ── individual predicates ────────────────────────────────────────────────────
def inv_well_formed(before, after, command, result):
    """The CommandResult must carry a bool `success` and a str `output`."""
    if not isinstance(result, dict):
        return f"result is not a dict for {command!r}: {result!r}"
    if not isinstance(result.get("success"), bool):
        return (f"result.success is not a bool for {command!r}: "
                f"{result.get('success')!r}")
    if not isinstance(result.get("output"), str):
        return (f"result.output is not a str for {command!r}: "
                f"{type(result.get('output')).__name__}")
    return None


def inv_resources(before, after, command, result):
    """No negative resources: credits >= 0, xp >= 0, level >= 1."""
    credits = after.get("credits", 0)
    xp = after.get("xp", 0)
    level = after.get("level", 0)
    if credits < 0:
        return f"credits went negative after {command!r}: {credits}"
    if xp < 0:
        return f"xp went negative after {command!r}: {xp}"
    if level < 1:
        return f"level dropped below 1 after {command!r}: {level}"
    return None


def inv_xp_monotonic(before, after, command, result):
    """xp never decreases across a command."""
    if after.get("xp", 0) < before.get("xp", 0):
        return (f"xp decreased across {command!r}: "
                f"{before.get('xp')} -> {after.get('xp')}")
    return None


def inv_rng_tick(before, after, command, result):
    """rngCounter advances by EXACTLY 1 on every command — refusals included
    (NX-OBS-1: the tick is unconditional at handler entry, the per-command clock
    and the strongest replay canary). Do NOT exempt refused commands."""
    b = before.get("rngCounter", 0)
    a = after.get("rngCounter", 0)
    if a != b + 1:
        return (f"rngCounter did not advance by exactly 1 across {command!r}: "
                f"{b} -> {a} (delta {a - b})")
    return None


def inv_flags_append_only(before, after, command, result):
    """Story flags are append-only — a flag present before must still be present
    after (they may only accumulate)."""
    lost = set(before.get("storyFlags", [])) - set(after.get("storyFlags", []))
    if lost:
        return f"storyFlags lost {sorted(lost)} across {command!r} (must be append-only)"
    return None


# Legal per-mission status transitions (from -> allowed set).
_LEGAL_TRANSITIONS = {
    "active": {"active", "completed", "failed"},
    "completed": {"completed"},
    "failed": {"failed"},
}


def _by_id(missions):
    out = {}
    for m in missions or []:
        mid = m.get("missionId")
        if mid is not None:
            out[mid] = m
    return out


def inv_mission_transitions(before, after, command, result):
    """Mission rows only transition legally and never disappear.

    - No mission row that existed before may vanish.
    - Rows present in BOTH must follow a legal status transition
      (active -> active/completed/failed; completed -> completed;
       failed -> failed). No resurrection (completed/failed -> active).
    - A row NEW in `after` may only enter as "active".
    - While a mission stays active, its objectivesCompleted is non-decreasing.
    """
    b = _by_id(before.get("missions", []))
    a = _by_id(after.get("missions", []))

    for mid in b:
        if mid not in a:
            return f"mission {mid!r} disappeared across {command!r}"

    for mid, arow in a.items():
        astatus = arow.get("status")
        if mid not in b:
            if astatus != "active":
                return (f"new mission {mid!r} entered as {astatus!r} across "
                        f"{command!r} (new rows must be 'active')")
            continue
        brow = b[mid]
        bstatus = brow.get("status")
        allowed = _LEGAL_TRANSITIONS.get(bstatus, {bstatus})
        if astatus not in allowed:
            return (f"illegal mission transition for {mid!r} across {command!r}: "
                    f"{bstatus!r} -> {astatus!r}")
        if bstatus == "active" and astatus == "active":
            if arow.get("objectivesCompleted", 0) < brow.get("objectivesCompleted", 0):
                return (f"objectivesCompleted regressed for active mission {mid!r} "
                        f"across {command!r}: {brow.get('objectivesCompleted')} -> "
                        f"{arow.get('objectivesCompleted')}")
    return None


def _game_fingerprint(state):
    """A GAME-STATE fingerprint that DELIBERATELY EXCLUDES rngCounter (NX-OBS-1):
    a refused command legitimately ticks the counter, so counter-inertness is NOT
    an invariant — game-state inertness IS."""
    reputation = state.get("reputation") or {}
    missions = tuple(sorted(
        (m.get("missionId"), m.get("status"), m.get("objectivesCompleted", 0))
        for m in (state.get("missions") or [])
    ))
    compromised = tuple(sorted(
        c.get("ipAddress") for c in (state.get("compromisedServers") or [])
        if c.get("ipAddress") is not None
    ))
    discovered = tuple(sorted(state.get("discoveredServers") or []))
    game_status = state.get("gameStatus") or {}
    return (
        state.get("level"),
        state.get("xp"),
        state.get("credits"),
        tuple(sorted(reputation.items())),
        tuple(sorted(state.get("storyFlags") or [])),
        missions,
        compromised,
        discovered,
        bool(game_status.get("isComplete", False)),
    )


def inv_refused_state_inert(before, after, command, result):
    """THE critical one: a REFUSED command (result.success is False) must leave
    the GAME STATE unchanged. The fingerprint EXCLUDES rngCounter on purpose
    (NX-OBS-1) — the counter tick on a refusal is by design, not a state change.
    Only evaluated when the command was refused."""
    if result.get("success") is not False:
        return None
    fb = _game_fingerprint(before)
    fa = _game_fingerprint(after)
    if fb != fa:
        # Report the first differing facet for a readable message.
        facets = ("level", "xp", "credits", "reputation", "storyFlags",
                  "missions", "compromised", "discovered", "isComplete")
        diffs = [f"{name}: {vb!r} -> {va!r}"
                 for name, vb, va in zip(facets, fb, fa) if vb != va]
        return (f"refused command {command!r} mutated game state (rngCounter "
                f"excluded): {'; '.join(diffs)}")
    return None


ALL = [
    inv_well_formed,
    inv_resources,
    inv_xp_monotonic,
    inv_rng_tick,
    inv_flags_append_only,
    inv_mission_transitions,
    inv_refused_state_inert,
]


def check_command(before, after, command, result):
    """Run every invariant for one command; return the list of violation strings
    (empty when all hold)."""
    violations = []
    for inv in ALL:
        msg = inv(before, after, command, result)
        if msg:
            violations.append(msg)
    return violations
