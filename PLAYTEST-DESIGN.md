# LLM Playtester — Design Spec (Phase 2: Balance Tier)

> Extracted and corrected from the archived `AGENT-PLAYTEST-FRAMEWORK.md` on 2026-07-05. That document was
> written before the RL/LLM pivot and got the division of labor backwards (it cast the LLM as a correctness/
> coverage tool and RL as the balance judge). Current direction, per `PLAN-FORWARD.md`: **the LLM playtester is
> the balance tier** (competent play, N runs with confidence intervals — "is the game good?"); the
> **exploit-hunter (RL/random) is the robustness tier** (crashes, soft-locks, invariant violations — "does the
> game break?"). This doc keeps only the design content that still applies to that role, ported to how the
> project actually works today: Python, driving the **real** running game as a client (a live server, a real
> browser, or the game's own subprocess harness), never a bridge reimplementation.
>
> **Status:** This document describes implemented behavior unless a section is explicitly marked as future work; where it diverges from the code, the code is authoritative.

> **Before running this tier against any game, work through `LESSONS.md` §B — the pre-flight
> information-integrity audit (P1–P11).** It is the accumulated cost of two real balance rounds: a playtest can
> report `PLAYTEST MET`, zero violations and a confident win rate while the pilot is blind to entity
> identities, to the game's public read layer, or to the rules that create its skill. Every check there needs
> a written, cited disposition before a batch is worth running.

## Where this fits today

`ugt playtest` (`ugt/core/playtester.py`) already implements the core LLM-action contract described below
(`LLM_ACTION_SCHEMA`: `reasoning`, `expected_outcome`, `potential_bug`, `is_novel`) for `browser`/`simulation`
engines. Games on `engine.type: custom` are covered too, via a different door: build your adapter and call
`playtest_game_with_adapter()` directly, which runs the identical LLM loop — `playtest_game()` is only the
config-dispatched convenience wrapper around it.

## Principles worth keeping

- **State delta is the assertion.** Every action is verified by comparing state before/after, never by "the
  call succeeded." E.g. buy fuel → `state.fuel > before.fuel`, not just "the request returned 200."
- **The LLM explains its reasoning.** Every action carries `reasoning` and `expected_outcome` *before* it's
  executed — this constrains the model to commit to a prediction (improves reliability) and makes the run log
  human-readable when triaging a failure.
- **Probabilistic features must be forced, where they're still probabilistic.** Any RNG-gated mechanic needs an
  injectable seam so both outcomes can be tested deterministically. **Caveat from experience:** don't assume a
  mechanic is RNG-gated without checking — one game's combat encounters turned out to be deterministic already
  (an encounter fired on *every* trip, gated only by roster seeding; the `ENCOUNTER_CHANCE` config was dead
  code, confirmed by grep). This principle applies to genuinely probabilistic mechanics (e.g. travel hazards,
  gambling minigames) — verify a mechanic is really RNG-gated first, and don't assume RNG seams are needed
  everywhere just because one mechanic needed one.
- **Recovery never skips verification.** If the LLM's expected screen doesn't appear, record it as a mismatch
  (potential bug or reasoning error) before attempting recovery — never silently reset and move on.

## The LLM Player Contract

Already implemented in `playtester.py::LLM_ACTION_SCHEMA`. Kept here as the reference for extending it:

```python
{
    "action_type": "action_id" | "press_key" | "type_text" | "wait" | "diagnose" | "end_turn",
    "value": "...",              # action name, key, or text
    "reasoning": "...",          # why this action right now
    "expected_outcome": "...",   # what should happen after
    "potential_bug": "...",      # optional — describe a suspected bug in the CURRENT state
    "is_novel": false,           # true if this exercises something outside known coverage
}
```

Three inputs drive each decision: the last ~600 chars of terminal text (`get_terminal_text`), the current
parsed state + recent action log, and the strategy guide. The strategy guide is the highest-leverage input —
write it like a briefing for a QA tester who's never played the game:

1. Win condition — how does a player succeed?
2. Core loop — what does a competent turn look like?
3. Screen map — what keys go where
4. What good state looks like (fuel > 100, hull at max, etc.)
5. Bug signatures — what does a broken screen look like vs. a working one (undefined/NaN, raw JSON, no state
   change after an action that should change something)

## Bug report shape

Every flagged `potential_bug` should carry enough to reproduce without re-running the whole session:

```python
{
    "action_sequence": [...],      # exact steps that led here
    "preconditions": {...},        # state before
    "post_state": {...},           # state after
    "expected": "...", "actual": "...",
    "terminal_text": "...",        # last ~600 chars at the time of the flag
    "reproducible": None,          # fill in after a targeted re-run, if one is done
}
```

**Done (2026-07-06):** `playtester.py::_make_bug_report()` now emits this exact shape from all three flag
sites — LLM-volunteered `potential_bug`, the `diagnose`/agent-confusion path, and the mechanical contradiction
detector — so reports are consistent across runs. The design keys above are the floor; each report also keeps
`step`, `source` (which detector fired), and `description` for triage. `expected`/`actual` are populated per
site (LLM flag: chosen action's `expected_outcome` vs. the suspected-bug text; contradiction detector: the
agent's expected change vs. "no material state change after N repeats"). `action_sequence` is the last ~10
action-log steps plus the action in flight; `terminal_text` is the last ~600 chars at flag time;
`reproducible` stays `None` until a targeted re-run fills it in.

## RNG seam pattern (Python), if a new probabilistic feature needs one

```python
import random
from typing import Callable

RngFn = Callable[[], float]

def generate_hazard(distance: int, rng: RngFn = random.random) -> dict:
    if rng() < 0.15:
        return {"type": "hull_damage", "amount": int(rng() * 5) + 1}
    return {"type": "none"}

# test: always_hazard = lambda: 0.01 ; never_hazard = lambda: 0.99
```

Rule: any game function that calls `random.random()`/`Math.random()` directly is untestable for that branch —
it needs an injectable `rng` parameter with the real RNG as the default. This is a change to the **game**, not
the harness, and should only be made where a probabilistic feature actually needs deterministic test coverage
(confirm it's really RNG-gated first — see the caveat above).
