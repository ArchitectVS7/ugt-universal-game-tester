"""
Framework-owned checks that need NO per-game configuration.

WHY THIS EXISTS
---------------
The fuzzer's oracle used to be entirely author-supplied: it caught crashes (free)
and violations of invariants a human thought to write (not free). That is a real
gap, and there is a worked example of it in the sample games — the dice game ran its
robustness rung green at 11/11 for weeks while one allocation strictly dominated
every other, which made the game's only decision meaningless. A green rung meant
"no crashes, and none of the properties we listed were violated". It never meant
"nobody can game this".

The checks below give every game a floor it inherits for free. They are the
generic shapes of "degenerate but legal play" — the failure mode that killed the
original RL tier, where an agent farmed reward without playing the game.

DESIGN RULES
------------
1. **Zero configuration.** Every check discovers what it needs from the observed
   states. A check that needs to be told what to look at belongs in the game's
   own `invariants.py`, not here.
2. **Observations, not failures.** These emit `Observation`s, which print and are
   returned but do NOT fail a gate on their own. Several are inherently
   dispositional — "these fields only ever grew; confirm each is a counter and
   not a farmable resource" is a question for a human, not a verdict. An
   integration that wants one enforced can promote it to a hard check itself.
   This also means adding them cannot turn an existing green ladder red for
   reasons nobody has reviewed yet.
3. **Every observation carries its evidence.** Counts, paths, examples. A bare
   "suspicious" is useless (LESSONS O7).
4. **Conservative thresholds.** A noisy channel gets ignored, which is worse than
   no channel at all.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Observation:
    """A generic-check result. Informational by default — see design rule 2."""
    check: str
    summary: str
    detail: str = ""
    evidence: list = field(default_factory=list)

    def __str__(self) -> str:
        head = f"[{self.check}] {self.summary}"
        return f"{head}\n      {self.detail}" if self.detail else head


# --------------------------------------------------------------------------- #
# Trace capture
# --------------------------------------------------------------------------- #

def _flatten_numbers(obj: Any, prefix: str = "", out: Optional[dict] = None) -> dict:
    """Every numeric leaf in a state dict, keyed by dot-path.

    Booleans are excluded: `bool` is an `int` subclass in Python, and a flag
    flipping False->True is not a resource growing.
    """
    if out is None:
        out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            _flatten_numbers(v, f"{prefix}.{k}" if prefix else str(k), out)
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            _flatten_numbers(v, f"{prefix}[{i}]", out)
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        out[prefix] = float(obj)
    return out


def state_key(state: dict) -> str:
    """A stable identity for a state, for cycle detection."""
    try:
        return json.dumps(state, sort_keys=True, default=str)
    except Exception:
        return repr(state)


@dataclass
class StepRecord:
    episode: int
    step: int
    action_id: int
    action_name: str
    before_key: str
    after_key: str
    numbers: dict          # flattened numeric leaves of `after`
    changed: bool


@dataclass
class Trace:
    """What the fuzzer records so these checks have something to analyze."""
    steps: list = field(default_factory=list)
    action_ids: list = field(default_factory=list)
    first_numbers: dict = field(default_factory=dict)

    def add(self, rec: StepRecord) -> None:
        self.steps.append(rec)


# --------------------------------------------------------------------------- #
# The checks
# --------------------------------------------------------------------------- #

def check_monotone_growth(trace: Trace, allowlist=(), min_rises: int = 5) -> list:
    """Numeric fields that ONLY ever grew — the signature of a farmable resource.

    This is the anti-farming check, and the direct answer to "R3 only finds what
    we tell it to". It needs no field list: it discovers every numeric leaf in
    the observed state and reports the ones that never once decreased in ANY
    episode long enough to judge, while rising repeatedly in at least one.

    It CANNOT distinguish a farmable resource from a legitimate counter
    (`round_number`, `roll_counter`) without game knowledge, and pretending
    otherwise would be a lie. So it reports all of them and asks for a
    disposition; pass `allowlist` with the paths already dispositioned as
    counters, and the next run only shows you what is new.
    """
    if not trace.steps:
        return []

    # PER EPISODE, not across the whole run. A reset legitimately puts every
    # field back, so a run-wide series shows a fall at every episode boundary
    # and nothing would ever flag — the check would be silently vacuous. Farming
    # happens WITHIN a life, so that is the window to measure.
    per_ep: dict = {}
    for rec in trace.steps:
        for path, val in rec.numbers.items():
            per_ep.setdefault(path, {}).setdefault(rec.episode, []).append(val)

    flagged = []
    for path, episodes in sorted(per_ep.items()):
        if path in allowlist:
            continue
        usable = [v for v in episodes.values() if len(v) >= min_rises + 1]
        if not usable:
            continue
        # Flag only if it never fell in ANY episode long enough to judge, and
        # rose enough in at least one. One counter-example is enough to clear it.
        if any(b < a for vals in usable for a, b in zip(vals, vals[1:])):
            continue
        best = max(usable, key=lambda v: sum(1 for a, b in zip(v, v[1:]) if b > a))
        rises = sum(1 for a, b in zip(best, best[1:]) if b > a)
        if rises >= min_rises:
            flagged.append((path, best[0], best[-1], rises))

    if not flagged:
        return []
    lines = [f"{p}: {lo:g} -> {hi:g} over {n} increases, never once decreased"
             for p, lo, hi, n in flagged]
    return [Observation(
        "monotone-growth",
        f"{len(flagged)} numeric field(s) only ever increased, within every "
        f"episode of {len(trace.steps)} steps of random play",
        "Disposition each: a turn/roll counter is expected, but a RESOURCE that "
        "can only go up is farmable. Add confirmed counters to the allowlist so "
        "this channel stays quiet until something new appears.",
        lines,
    )]


def check_state_cycles(trace: Trace) -> list:
    """An exact state repeat means an unbounded loop is available from here.

    Returning to a byte-identical state after k>0 actions proves the sequence can
    be repeated forever. Harmless in a game with a turn limit, damning in one
    without — and either way it is the substrate every farming exploit is built
    on, so it is worth surfacing with the loop actually named.
    """
    seen: dict = {}
    cycles = []
    for rec in trace.steps:
        prev = seen.get(rec.after_key)
        if prev is not None:
            length = (rec.episode, rec.step)[1] - prev[1]
            if rec.episode == prev[0] and length > 0:
                cycles.append((prev[1], rec.step, length, rec.action_name))
        seen[rec.after_key] = (rec.episode, rec.step)
    if not cycles:
        return []
    shortest = min(cycles, key=lambda c: c[2])
    return [Observation(
        "state-cycle",
        f"{len(cycles)} exact state repeat(s) — the game returned to a state it "
        f"had already been in, so that action sequence can be repeated forever",
        f"Shortest loop is {shortest[2]} action(s) (steps {shortest[0]}->{shortest[1]}, "
        f"closed by '{shortest[3]}'). Confirm a turn limit or a resource cost bounds it.",
        [f"steps {a}->{b}, length {n}, closing action '{act}'" for a, b, n, act in cycles[:5]],
    )]


def check_dead_actions(trace: Trace) -> list:
    """Actions that never once changed the state, across the entire run.

    Either unimplemented content, an action the adapter cannot really send, or a
    legal no-op nobody documented. All three are worth knowing, and none of them
    require a game-specific invariant to notice.
    """
    tried: dict = {}
    effective: dict = {}
    for rec in trace.steps:
        tried[rec.action_id] = rec.action_name
        if rec.changed:
            effective[rec.action_id] = True
    dead = [(aid, nm) for aid, nm in sorted(tried.items()) if aid not in effective]
    never_tried = [a for a in trace.action_ids if a not in tried]

    obs = []
    if dead:
        obs.append(Observation(
            "dead-action",
            f"{len(dead)} action(s) never changed the state even once",
            "An action with no observable effect is unimplemented content, an "
            "adapter that cannot really send it, or an undocumented no-op.",
            [f"action {aid} ('{nm}') tried "
             f"{sum(1 for r in trace.steps if r.action_id == aid)}x, always inert"
             for aid, nm in dead],
        ))
    if never_tried:
        obs.append(Observation(
            "action-coverage",
            f"{len(never_tried)} mapped action(s) were never tried at all",
            "The run cannot say anything about these. Raise the step budget or "
            "check the policy is not excluding them.",
            [f"action {a}" for a in never_tried],
        ))
    return obs


def check_nondeterminism(trace: Trace) -> list:
    """The same state + the same action producing a different result.

    UGT requires seeded determinism at the robustness rung (it is what makes
    same-seed replay assertable), so within one run this should never happen. It
    is fully generic: no knowledge of what the state MEANS is needed to notice
    that identical inputs diverged.
    """
    outcomes: dict = {}
    clashes = []
    for rec in trace.steps:
        k = (rec.before_key, rec.action_id)
        prev = outcomes.get(k)
        if prev is not None and prev != rec.after_key:
            clashes.append((rec.action_name, rec.episode, rec.step))
        outcomes.setdefault(k, rec.after_key)
    if not clashes:
        return []
    return [Observation(
        "nondeterminism",
        f"{len(clashes)} case(s) where the SAME state + SAME action produced a "
        f"different result",
        "Either the game holds hidden state the observation does not expose, or "
        "it is consuming unseeded randomness. Both break same-seed replay.",
        [f"action '{a}' diverged at episode {e} step {s}" for a, e, s in clashes[:5]],
    )]


def check_state_starvation(trace: Trace, min_ratio: float = 0.10) -> list:
    """A long run that only ever saw a handful of distinct states.

    The signature of a game that is stuck, or of a driver that is not really
    driving it. Cheap insurance against a rung that passes because nothing ever
    happened (LESSONS O2 — a vacuous green is worse than a red).
    """
    if len(trace.steps) < 20:
        return []
    distinct = len({r.after_key for r in trace.steps})
    ratio = distinct / len(trace.steps)
    if ratio >= min_ratio:
        return []
    return [Observation(
        "state-starvation",
        f"only {distinct} distinct states across {len(trace.steps)} steps "
        f"({ratio:.0%})",
        "The run may be stuck, or the driver may not be reaching real gameplay. "
        "Check before reading anything else in this report as coverage.",
    )]


ALL_CHECKS = (
    check_monotone_growth,
    check_state_cycles,
    check_dead_actions,
    check_nondeterminism,
    check_state_starvation,
)


def run_generic_checks(trace: Trace, monotone_allowlist=()) -> list:
    """Every framework-owned check, in one call."""
    obs = []
    for fn in ALL_CHECKS:
        if fn is check_monotone_growth:
            obs.extend(fn(trace, allowlist=monotone_allowlist))
        else:
            obs.extend(fn(trace))
    return obs
