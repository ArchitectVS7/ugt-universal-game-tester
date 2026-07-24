# Example: `harness-game` — the trial ladder, end to end

**Foraging Run** is a tiny, fully self-contained demo game that exists to show
UGT's *current* methodology in miniature: an **engine-first subprocess-harness
integration** driven through the full **trial ladder** (spike → smoke → R1 → R2 →
R3), with the exploit-hunter and same-seed determinism replay.

It has **zero external dependencies** — the "game" is ~150 lines of Python — so
you can run the whole ladder immediately and read every moving part.

> This example replaces a retired one that demonstrated the opposite: an adapter
> that *re-implemented* a real game's rules and silently drifted from it (no
> combat, broken upgrades). That is the failure UGT's rule **M1** exists to
> prevent (`../../LESSONS.md`). Here, the contrast is the lesson.

## The one idea: the adapter contains zero game logic

All the rules — foraging, travel risk, win/loss — live in **`engine.py`**, and
nothing else knows them. `harness_adapter.py` spawns the engine's process, writes
a JSON request, reads a JSON response, and hands the state back. It never decides
what an action *does*. That is the discipline that keeps UGT testing the game
instead of testing a copy of it.

```
verify_round*.py ──uses──▶ HarnessAdapter ──spawns / JSON-lines──▶ harness.py ──▶ engine.py
   (the ladder)            (transport only)                        (the wire)     (ALL rules)
```

## Files

| File | Role |
|---|---|
| `engine.py` | The whole game. Deterministic; RNG lives *in the state* (`rng_counter`), seeded once — the basis of replayability. |
| `harness.py` | JSON-lines process wrapping the engine (the "engine-first subprocess contract"). stdout is protocol-only. |
| `harness_adapter.py` | Transport-only `BaseAdapter`: `connect`/`reset`/`step`/`close` + `_read_state`. **No game rules.** |
| `invariants.py` | The properties that must hold after every command, defined once and reused by R1/R2 *and* R3 (`InvariantSuite`). |
| `spike_foraging.py` | Rung 1 — raw protocol round-trips (no adapter). |
| `smoke_foraging_adapter.py` | Rung 2 — same round-trip through the `BaseAdapter` contract. |
| `verify_round1.py` | Rung 3 — one full loop to a real **win**, invariants after every command, reproducible. |
| `verify_round2.py` | Rung 4 — every action + both outcomes (win **and** loss) to a real result. |
| `verify_round3.py` | Rung 5 — exploit-hunter random walk + byte-identical same-seed replay. |
| `ugt.config.yaml` | The config *shape* a game provides (documentary — see note below). |
| `strategy-guide.md` | The tier-3 (LLM playtest) briefing artifact, written to `LESSONS.md` §B. |

## Run it (from the repo root)

```bash
for s in spike_foraging smoke_foraging_adapter verify_round1 verify_round2 verify_round3; do
  python3 examples/harness-game/$s.py || break
done
```

Each script is a **fail-closed gate**: it prints `[PASS]`/`[FAIL]` lines and a
`ROUND N MET — p/t` footer, exiting non-zero if any check fails. Expected result:
spike 13/13 · smoke 10/10 · R1 5/5 · R2 4/4 · R3 5/5.

## How the rungs map to UGT's three tiers

- **Tier 1 — correctness:** the R1/R2 scripted rounds assert `invariants.py` after
  every command (the `ugt verify` question, answered in-harness here).
- **Tier 2 — robustness:** R3 runs `ugt/core/exploit_hunter.py` — random actions,
  same invariants after every step, plus determinism. Answers "does it break?".
- **Tier 3 — balance ("is it good?"):** an LLM playtester reading `strategy-guide.md`.
  Not run here (it needs API credits and a direct-adapter entry point), but the
  guide shows the artifact and the pre-flight discipline in `LESSONS.md` §B.

## Honest notes

- **Python-only for zero deps.** Real engine-first integrations spawn the game's
  *own* process (a Node or Godot build). We use a Python harness so the example
  runs with nothing installed — but the pattern (a separate engine process spoken
  to over JSON-lines) is identical.
- **Not wired into `env.py`.** Like the real subprocess-harness integrations, the
  adapter is constructed directly by the ladder scripts rather than registered
  under an `engine.type`. The sibling `../mock-game` shows the
  `engine.type: simulation` CLI path (`ugt verify` / `ugt playtest`).
- **Determinism is earned, not assumed.** Because every roll is
  `hash(seed, rng_counter)` and `rng_counter` is part of the state, a run is a
  pure function of its seed and action sequence — which is what makes R3's
  byte-identical replay check meaningful. If you add real randomness to a game,
  give it the same treatment or R3 cannot certify it.
