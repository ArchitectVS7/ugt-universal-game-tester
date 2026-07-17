"""
Nexus Dominion invariants — shared by verify_round{1,2,3}.py.

Two layers:

  * FLAT predicates (before, after, command, result) over the adapter's
    normalized state (`_read_state` flat dict) — registered in an
    InvariantSuite so R1/R2 run them per step and R3 hands the SAME
    predicates to the ExploitHunter (one definition, both tiers).

  * FULL-STATE checks over the decoded GameState (adapter.game_state — the
    game's own serialized form, Map/Set-decoded). Heavier; R1/R2 run them at
    checkpoints, R3 wraps them behind a closure invariant.

Nothing here re-implements game rules: every check compares facts the game
itself reports. A violation is DATA — it prints, fails the gate, and gets
fixed upstream in the game.

Game-shape notes the invariants encode (all read from the game's own docs/
state, not invented):
  - empires are never eliminated (eliminatedCount is hardwired 0 upstream),
    so empire/bot counts are constant;
  - systems are never abandoned — ownership only transfers (combat) or goes
    unclaimed->claimed, so unclaimedSystems is non-increasing;
  - achievements are permanent milestones (earnedAchievements only grows);
  - the game has NO terminal state, so `terminated` is never expected.
"""
from __future__ import annotations

RESOURCE_KEYS = (
    "player_credits", "player_food", "player_ore", "player_fuelCells",
    "player_researchPoints", "player_intelligencePoints",
)


# ── FLAT per-step predicates (before, after, command, result) ────────────────

def inv_cycle_advances_only_on_commit(before, after, command, result):
    """A committed cycle advances time by exactly 1; an aborted one not at all."""
    if command != "commit":
        return None
    b, a = before.get("cycle"), after.get("cycle")
    if result.get("committed"):
        if a != b + 1:
            return f"committed cycle jumped {b}->{a} (expected +1)"
    else:
        if a != b:
            return f"ABORTED commit still moved the cycle {b}->{a}"
    return None


def inv_no_negative_resources(before, after, command, result):
    """Player resources never go negative (and are real numbers)."""
    for key in RESOURCE_KEYS:
        v = after.get(key)
        if v is None or not isinstance(v, (int, float)) or v != v:  # NaN check
            return f"{key} is not a number: {v!r}"
        if v < 0:
            return f"{key} went NEGATIVE: {v}"
    return None


def inv_population_bounds(before, after, command, result):
    """Population is a non-negative number."""
    v = after.get("player_population")
    if v is None or not isinstance(v, (int, float)) or v != v or v < 0:
        return f"player_population out of bounds: {v!r}"
    return None


def inv_empire_counts_constant(before, after, command, result):
    """No elimination exists in the engine — empire/bot counts never change."""
    if (after.get("empireCount") != before.get("empireCount")
            or after.get("botCount") != before.get("botCount")):
        return (f"empire/bot count changed: {before.get('empireCount')}/"
                f"{before.get('botCount')} -> {after.get('empireCount')}/"
                f"{after.get('botCount')}")
    return None


def inv_system_count_constant(before, after, command, result):
    """The galaxy never gains or loses systems."""
    if after.get("systemCount") != before.get("systemCount"):
        return (f"systemCount changed {before.get('systemCount')} -> "
                f"{after.get('systemCount')}")
    return None


def inv_unclaimed_non_increasing(before, after, command, result):
    """Systems go unclaimed->claimed (or transfer), never back to unclaimed."""
    b, a = before.get("unclaimedSystems"), after.get("unclaimedSystems")
    if isinstance(b, int) and isinstance(a, int) and a > b:
        return f"unclaimedSystems INCREASED {b} -> {a} (a system was abandoned?)"
    return None


def inv_achievements_monotonic(before, after, command, result):
    """Achievements are permanent milestones — the sets only grow."""
    if after.get("totalAchievements", 0) < before.get("totalAchievements", 0):
        return (f"totalAchievements shrank {before.get('totalAchievements')} -> "
                f"{after.get('totalAchievements')}")
    lost = set(before.get("playerAchievements") or []) - set(
        after.get("playerAchievements") or [])
    if lost:
        return f"player LOST achievements: {sorted(lost)}"
    return None


def inv_stability_in_range(before, after, command, result):
    """Stability score stays within its 0..100 scale."""
    v = after.get("player_stabilityScore")
    if v is None or not isinstance(v, (int, float)) or not (0 <= v <= 100):
        return f"player_stabilityScore out of [0,100]: {v!r}"
    return None


def inv_committed_or_error(before, after, command, result):
    """An uncommitted cycle must carry the engine's error message (atomicity
    is allowed; SILENT failure is not)."""
    if command != "commit":
        return None
    if not result.get("committed") and not result.get("error"):
        return "commit returned committed:false with NO error message"
    return None


def inv_hash_progress(before, after, command, result):
    """A committed cycle always changes the state hash (time advanced)."""
    if command != "commit" or not result.get("committed"):
        return None
    if result.get("hashBefore") and after.get("stateHash") == result.get("hashBefore"):
        return "committed cycle left the stateHash UNCHANGED"
    return None


ALL_FLAT_PREDICATES = [
    inv_cycle_advances_only_on_commit,
    inv_no_negative_resources,
    inv_population_bounds,
    inv_empire_counts_constant,
    inv_system_count_constant,
    inv_unclaimed_non_increasing,
    inv_achievements_monotonic,
    inv_stability_in_range,
    inv_committed_or_error,
    inv_hash_progress,
]


# ── FULL-STATE checks (decoded GameState) ────────────────────────────────────

def full_state_violations(g: dict) -> list[str]:
    """Cross-reference integrity of the game's own serialized state."""
    out = []
    systems = g.get("galaxy", {}).get("systems") or {}
    empires = g.get("empires") or {}
    fleets = g.get("fleets") or {}
    units = g.get("units") or {}

    # Ownership bijection: system.owner <-> empire.systemIds agree exactly.
    owned_by_system = {sid: s.get("owner") for sid, s in systems.items()
                       if s.get("owner")}
    claimed = {}
    for eid, e in empires.items():
        for sid in e.get("systemIds") or []:
            if sid in claimed:
                out.append(f"system {sid} claimed by BOTH {claimed[sid]} and {eid}")
            claimed[sid] = eid
            if owned_by_system.get(sid) != eid:
                out.append(f"empire {eid} lists {sid} but system.owner="
                           f"{owned_by_system.get(sid)!r}")
    for sid, owner in owned_by_system.items():
        if claimed.get(sid) != owner:
            out.append(f"system {sid} owner={owner} missing from that empire's "
                       f"systemIds")

    # Fleet integrity: locations are real systems; unit refs resolve; each
    # unit belongs to at most one fleet.
    seen_units = {}
    for fid, f in fleets.items():
        loc = f.get("locationSystemId")
        if loc is not None and loc not in systems:
            out.append(f"fleet {fid} is located at nonexistent system {loc}")
        for uid in f.get("unitIds") or []:
            if uid not in units:
                out.append(f"fleet {fid} references nonexistent unit {uid}")
            if uid in seen_units:
                out.append(f"unit {uid} is in TWO fleets: {seen_units[uid]}, {fid}")
            seen_units[uid] = fid

    # Orphan units: exist in the roster but sit in no fleet.
    for uid in units:
        if uid not in seen_units:
            out.append(f"unit {uid} exists but belongs to no fleet (orphan)")

    return out
