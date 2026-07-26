"""Episode seeding as a DECLARED, CHECKED property of the game under test.

Why this module exists
----------------------
The playtest tier needs to know one thing before it can report anything: are N
episodes N samples, or one sample played N times? Until now that was answered
implicitly, by whether `playtest.episode_seeds` happened to be present:

  * seeds present  -> rotate them, and raise if the adapter cannot seed;
  * seeds absent   -> plain `reset()`, silently.

The silent branch is the problem, because "absent" means two opposite things.
A deterministic game (no RNG anywhere — one map, one solution) is CORRECT to
replay: its episodes are replays by nature and one is the honest sample size.
A game that simply never configured seeds is about to publish a win rate with an
N-sized denominator over a 1-sized sample. Both look identical in the config and
identical in the report, so the tier cannot tell the difference and neither can
the reader.

So the game declares which it is, and the declaration is PROVEN rather than
believed. `playtest.seeding` is one of:

  per_episode    The game's RNG is seedable and `episode_seeds` rotates one seed
                 per episode. Episodes are independent samples.
  deterministic  The game has no RNG at all. Episodes are replays BY DESIGN;
                 the sample size is 1 regardless of N, and a win rate over them
                 is not a measurement. This is the honest declaration for e.g. a
                 fixed-layout puzzle or a single-solution text adventure.
  uncontrolled   The game has randomness we cannot seed. Episodes differ, but a
                 finding cannot be replayed and a run cannot be reproduced.

The declaration is not a promise, it is a hypothesis
----------------------------------------------------
Every mode is probed against the live game before the run starts, because a
declaration that is never checked is prose in a different file. The failure this
guards against is real and was measured on a browser dice game: JavaScript
discards extra arguments in silence, so `__RESET_GAME__(seed)` against a game
that never implemented seeding returns a normal state, raises nothing, and the
run reports N seeds while playing one match N times — the exact bug the seeding
mechanism was built to remove, surviving the fix and wearing a green light.

`BaseAdapter.reset_seeded()` raising is necessary and not sufficient. This is
the sufficient half, and it is here rather than in one game's integration script
so that every game inherits it instead of re-deriving it.
"""
from __future__ import annotations

import json

PER_EPISODE = "per_episode"
DETERMINISTIC = "deterministic"
UNCONTROLLED = "uncontrolled"
MODES = (PER_EPISODE, DETERMINISTIC, UNCONTROLLED)

# How many steps the probe drives per trial. Two states are rarely enough to
# distinguish seeds: many games open on an identical position regardless of seed
# (both sides at full strength, the same starting room), so a probe that
# compared only the reset state would call every game deterministic.
PROBE_STEPS = 4


class SeedingError(Exception):
    """The seeding declaration is missing, malformed, or contradicted by the game."""


def resolve(playtest_cfg: dict) -> tuple:
    """(mode, seeds) from a `playtest:` config block. Raises SeedingError.

    An explicit `seeding:` always wins. When it is absent the mode is INFERRED —
    but only in the direction that cannot be ambiguous: a declared, non-empty
    seed list means per_episode and nothing else. Absent seeds with no
    declaration is the ambiguous case, and it is refused rather than guessed.
    """
    cfg = playtest_cfg or {}
    seeds = list(cfg.get("episode_seeds") or [])
    mode = cfg.get("seeding")

    if mode is None:
        if seeds:
            return PER_EPISODE, seeds     # unambiguous: seeds were declared
        raise SeedingError(
            "playtest.seeding is not declared and no episode_seeds are configured, "
            "so the tier cannot tell whether N episodes are N samples or one "
            "sample played N times.\n"
            f"  Declare one of {list(MODES)} under `playtest:` in the config:\n"
            "    per_episode   - seedable RNG; also set episode_seeds (>= 2)\n"
            "    deterministic - the game has no RNG; episodes are replays by "
            "design and the sample size is 1\n"
            "    uncontrolled  - the game has RNG that cannot be seeded"
        )

    if mode not in MODES:
        raise SeedingError(f"playtest.seeding must be one of {list(MODES)}, got {mode!r}")

    if mode == PER_EPISODE and len(seeds) < 2:
        raise SeedingError(
            f"playtest.seeding is {PER_EPISODE!r} but only {len(seeds)} seed(s) are "
            f"configured. Rotation needs at least 2, or the run replays one seed "
            f"while claiming variety."
        )
    if mode in (DETERMINISTIC, UNCONTROLLED) and seeds:
        raise SeedingError(
            f"playtest.seeding is {mode!r} but episode_seeds are configured. "
            f"Those seeds would never be used — either the declaration or the "
            f"list is wrong."
        )
    return mode, seeds


def _trial(adapter, seed, probe_action: int) -> list:
    """Drive a short fixed sequence and return the observable state stream."""
    if seed is None:
        adapter.reset()
    else:
        adapter.reset_seeded(seed)
    out = []
    for _ in range(PROBE_STEPS):
        state, terminated, _trunc, _info = adapter.step(probe_action)
        out.append(json.dumps(state, sort_keys=True, default=str))
        if terminated:
            break
    return out


def probe(adapter, mode: str, seeds: list, probe_action: int = 0) -> str:
    """Prove the declaration against the live game. Raises SeedingError if the
    game contradicts it; returns a one-line human-readable proof if it holds.

    Every mode is checked in BOTH directions where both directions exist, because
    a one-directional check passes for the wrong reasons: a reset hook returning
    random state would satisfy "two seeds differ" while being just as broken as
    one that ignores the seed entirely.
    """
    if mode == PER_EPISODE:
        a1 = _trial(adapter, seeds[0], probe_action)
        b1 = _trial(adapter, seeds[1], probe_action)
        a2 = _trial(adapter, seeds[0], probe_action)
        if a1 == b1:
            raise SeedingError(
                f"seeding={PER_EPISODE!r} is contradicted: seeds {seeds[0]!r} and "
                f"{seeds[1]!r} produce an IDENTICAL {len(a1)}-step stream. The seed is "
                f"being ignored, so every episode is the same match and no batch "
                f"computed from this run means anything."
            )
        if a1 != a2:
            raise SeedingError(
                f"seeding={PER_EPISODE!r} is contradicted: seed {seeds[0]!r} did not "
                f"reproduce itself across two trials, so a 'seed' names nothing and "
                f"no finding from this run can be replayed."
            )
        return (f"seeding=per_episode PROVEN: {seeds[0]!r} and {seeds[1]!r} diverge, "
                f"and {seeds[0]!r} replays identically ({len(a1)} steps compared)")

    if mode == DETERMINISTIC:
        a1 = _trial(adapter, None, probe_action)
        a2 = _trial(adapter, None, probe_action)
        if a1 != a2:
            raise SeedingError(
                f"seeding={DETERMINISTIC!r} is contradicted: two plain resets driven "
                f"with the same action produced DIFFERENT streams, so the game does "
                f"have randomness. Re-declare as {PER_EPISODE!r} (if it can be seeded) "
                f"or {UNCONTROLLED!r}."
            )
        if len(set(a1)) <= 1:
            raise SeedingError(
                f"seeding={DETERMINISTIC!r} could not be proven: the probe never "
                f"changed the state, so 'identical' is vacuous. Set "
                f"playtest.probe_action to an action that does something from the "
                f"opening position."
            )
        return (f"seeding=deterministic PROVEN: two resets replay identically over "
                f"{len(a1)} steps, and the probe really moved ({len(set(a1))} distinct states)")

    # UNCONTROLLED — the useful direction is the opposite one. A game declared
    # unseedable that actually replays identically is mislabelled, and its
    # episodes are replays being counted as samples.
    a1 = _trial(adapter, None, probe_action)
    a2 = _trial(adapter, None, probe_action)
    if a1 == a2 and len(set(a1)) > 1:
        raise SeedingError(
            f"seeding={UNCONTROLLED!r} is contradicted: two plain resets replayed "
            f"IDENTICALLY over {len(a1)} steps, so this game is deterministic. "
            f"Declare {DETERMINISTIC!r} — episodes are replays, and counting them as "
            f"independent samples would inflate the denominator."
        )
    return f"seeding=uncontrolled: two resets diverged over {len(a1)} steps, as declared"


def sample_note(mode: str, episodes_recorded: int, distinct_seeds: int) -> str:
    """One line for the report saying what the episode count is worth.

    A reader should never have to infer the sample structure from a seed column.
    This is the sentence that stops an N-sized denominator being read as an
    N-sized sample.
    """
    if mode == DETERMINISTIC:
        return (f"{episodes_recorded} episode(s) of a DETERMINISTIC game: these are "
                f"replays of one scenario by design, so the effective sample size is 1. "
                f"Report competence (did it finish, in how many actions), not a rate.")
    if mode == UNCONTROLLED:
        return (f"{episodes_recorded} episode(s) with UNCONTROLLED randomness: "
                f"independent, but not reproducible — a finding here cannot be replayed.")
    if distinct_seeds <= 1 and episodes_recorded > 1:
        return (f"{episodes_recorded} episodes but only {distinct_seeds} distinct seed: "
                f"these are the same scenario repeated. Effective sample size is 1.")
    return (f"{episodes_recorded} episode(s) across {distinct_seeds} distinct seed(s) — "
            f"independent samples.")
