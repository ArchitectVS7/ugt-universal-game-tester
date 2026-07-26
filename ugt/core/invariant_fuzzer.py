"""
Invariant fuzzer — UGT's robustness tier.

Drives a game through random/heuristic *real* actions and asserts invariants after every
step. It answers "does the game break?" — cheaply, with no reward engineering (what random
search is actually good at here). The LLM balance tier answers "is the game good?".

RENAMED 2026-07-26. This was `ExploitHunter` in `exploit_hunter.py`, and that name promised
something it does not do — it implied an adversarial search for exploits, when what runs is
random input against an oracle. A green run was being read as "no exploits". Be precise
about what you actually get:

  * CRASHES — free. Any exception from `reset()` or `step()` becomes a finding, with no
    need for anyone to have anticipated it.
  * YOUR INVARIANTS — properties a human wrote down for this game. As good as that list.
  * GENERIC CHECKS — a framework-owned floor every game inherits (`generic_checks.py`):
    monotone-growth (the anti-farming check), state cycles, dead actions, nondeterminism,
    state starvation. Zero configuration; they discover what they need from the states.

What it is NOT is an adversarial search for exploits. The policy is random by default and
a fixed heuristic at best; it has no notion of reward, score or progress, so it will not go
LOOKING for a profitable loop — it can only stumble into one and have a check notice. A
green run means "no crashes, no invariant violated, no generic check tripped". It does not
mean "nobody can game this".

The distinction that makes it worth running anyway: the ORACLE is (partly) author-written,
but the PATH to a violation is not. "Force strength never rises" is a cheap general
property; the value is random search finding the sequence that breaks it.

This module is GAME-AGNOSTIC. It drives any `BaseAdapter` and takes the game-specific
pieces as inputs:
  - `invariants`: list[Invariant] — properties that must hold after every step.
  - `action_ids`: the mapped action ids the policy may choose from.
  - `policy`: optional (state, action_ids, rng, ctx) -> action_id; defaults to uniform random.

A failed test is DATA: every invariant violation and every crash is captured as a finding
(with the action + before/after state that produced it), not swallowed.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable, Optional

from ugt.core.generic_checks import (
    StepRecord, Trace, run_generic_checks, state_key, _flatten_numbers,
)


# An invariant checks (before, action_id, info, after, ctx) and returns a violation
# message (str) or None. `ctx` is a per-episode mutable dict for stateful invariants
# (e.g. counting consecutive combat steps).
CheckFn = Callable[[dict, int, dict, dict, dict], Optional[str]]


@dataclass
class Invariant:
    name: str
    check: CheckFn
    description: str = ""


@dataclass
class Finding:
    kind: str                # "invariant" | "crash"
    name: str                # invariant name or "exception"
    message: str
    episode: int
    step: int
    action_id: int
    action_name: str = ""
    before: Optional[dict] = None
    after: Optional[dict] = None
    info: Optional[dict] = None


@dataclass
class FuzzReport:
    episodes: int = 0
    total_steps: int = 0
    findings: list = field(default_factory=list)
    action_counts: dict = field(default_factory=dict)
    unique_signatures: set = field(default_factory=set)  # dedup key per finding
    # Framework-owned generic-check output. Informational: these do NOT fail a
    # gate by themselves (see generic_checks.py design rule 2). An integration
    # that wants one enforced promotes it explicitly.
    observations: list = field(default_factory=list)
    trace: Optional[Trace] = None

    def add(self, f: Finding) -> None:
        sig = (f.kind, f.name, f.action_name, f.message[:80])
        if sig not in self.unique_signatures:
            self.unique_signatures.add(sig)
            self.findings.append(f)


def uniform_policy(state: dict, action_ids: list, rng: random.Random, ctx: dict) -> int:
    return rng.choice(action_ids)


class InvariantFuzzer:
    """Random/heuristic action driver + invariant oracle. See the module docstring
    for exactly what a green run does and does not prove.

    `monotone_allowlist` holds state paths already dispositioned as legitimate
    counters (`round_number`, `roll_counter`, ...), so the anti-farming check
    stays quiet until a NEW one-way-growing field appears.
    """

    def __init__(self, adapter, invariants, action_ids, action_names=None,
                 policy: Callable = uniform_policy, seed: int = 0,
                 monotone_allowlist=()):
        self.adapter = adapter
        self.invariants = invariants
        self.action_ids = list(action_ids)
        self.action_names = action_names or {}
        self.policy = policy
        self.rng = random.Random(seed)
        self.monotone_allowlist = tuple(monotone_allowlist)

    def run(self, episodes: int = 5, steps_per_episode: int = 40,
            log: Callable[[str], None] = print) -> FuzzReport:
        report = FuzzReport()
        trace = Trace(action_ids=list(self.action_ids))
        for ep in range(episodes):
            ctx: dict = {}
            try:
                before = self.adapter.reset()
            except Exception as exc:  # a reset crash is itself a finding
                report.add(Finding("crash", "reset", f"{type(exc).__name__}: {exc}", ep, 0, -1))
                log(f"[ep {ep}] reset CRASHED: {exc}")
                continue

            report.episodes += 1
            ep_findings = 0
            for step in range(steps_per_episode):
                action_id = self.policy(before, self.action_ids, self.rng, ctx)
                aname = self.action_names.get(action_id, str(action_id))
                report.action_counts[aname] = report.action_counts.get(aname, 0) + 1

                # ── step the real game ────────────────────────────────────
                try:
                    after, terminated, truncated, info = self.adapter.step(action_id)
                except Exception as exc:
                    f = Finding("crash", "exception", f"{type(exc).__name__}: {exc}",
                                ep, step, action_id, aname, before=before)
                    report.add(f); ep_findings += 1
                    log(f"[ep {ep} step {step}] {aname} CRASHED: {exc}")
                    # try to recover the state; if we can't, end the episode.
                    # Adapters name their raw reader differently (_read_state on
                    # harness adapters, _get_game_state on browser) — accept either.
                    try:
                        read = (getattr(self.adapter, "_read_state", None)
                                or getattr(self.adapter, "_get_game_state", None))
                        if read is None:
                            break
                        after = read()
                    except Exception:
                        break
                    before = after
                    continue

                report.total_steps += 1

                # ── record the trace for the framework-owned checks ───────
                # Hashes + numeric leaves only, not whole states: a long run
                # would otherwise hold every state it ever saw in memory.
                bkey, akey = state_key(before), state_key(after)
                trace.add(StepRecord(
                    episode=ep, step=step, action_id=action_id, action_name=aname,
                    before_key=bkey, after_key=akey,
                    numbers=_flatten_numbers(after), changed=bkey != akey,
                ))

                # ── check invariants ──────────────────────────────────────
                for inv in self.invariants:
                    try:
                        msg = inv.check(before, action_id, info, after, ctx)
                    except Exception as exc:
                        msg = f"invariant raised {type(exc).__name__}: {exc}"
                    if msg:
                        f = Finding("invariant", inv.name, msg, ep, step, action_id, aname,
                                    before=before, after=after, info=info)
                        report.add(f); ep_findings += 1
                        log(f"[ep {ep} step {step}] VIOLATION {inv.name}: {msg}  (action={aname})")

                before = after
                if terminated:
                    break
            log(f"[ep {ep}] done — {ep_findings} finding(s) this episode")

        # ── framework-owned checks over the whole run ────────────────────────
        # These are the floor every game inherits without writing an invariant.
        # Informational by design: they are reported, never fatal on their own.
        report.trace = trace
        report.observations = run_generic_checks(
            trace, monotone_allowlist=self.monotone_allowlist)
        for ob in report.observations:
            log(f"  {ob}")
        return report
