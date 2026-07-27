# Conformance fixture — spec

> **Status: SPEC ONLY. Not built.** Written 2026-07-27, after `7b759b8` moved the three sample games out to
> their own repositories and left UGT with no in-repo end-to-end check. Read `PLAN-FORWARD.md` §"The
> regression gap" for how that happened; this file is the design for the replacement.

---

## What this is, and what it is emphatically not

A **conformance fixture** is a deliberately boring test double that a UGT ladder can be run against, in-repo,
with no server, no browser (except one optional variant), no model, and no network. Its job is to answer one
question when someone changes `ugt/core/`:

> Does the ladder still do what the ladder claims to do?

**It is not a game, not a demo, and not a teaching artifact.** The sample games left this repo precisely
because bundling games with the framework taught the wrong pattern. Nothing here should be pleasant to play,
have a README written in the build-diary voice, or be pointed at a reader learning UGT. If it starts looking
like a game, it has drifted. Name the directory and the docs so that confusion is impossible.

**It does not violate "never test a re-implementation of the game."** That rule governs *adapters*, which
must contain zero game logic — it exists because a headless bridge once became a partial copy of the game it
was meant to test, and every agent trained against it learned a different game. A fixture stands in for no
real game and makes no claim about one. It exercises the wire.

**Know exactly what a green conformance run proves** — the same discipline `ugt/core/invariant_fuzzer.py`
had to learn. A green run means: *the ladder scaffold, the adapter contract, the invariant plumbing, the
seeding gate, the generic checks and the playtest loop's mechanics all still behave as specified against a
known-shaped subject.* It does **not** mean UGT can test a real game — real games are messy in ways no
fixture reproduces, and every framework bug the sample games ever caught (`6ffa58a`, `700c46c`) was found by
building against something real. The fixture is a floor, not a ceiling, and this limitation belongs in its
own README in exactly these terms.

---

## The design property that makes it worth building

A fixture that can only go green is decoration. This repo's standing rule is **"prove a check can fail"** —
mutation-check a new assertion by breaking the thing it guards and confirming it catches it.

So the fixture ships with a **defect catalogue**: a set of injectable, named failure modes, each mapped to
the rung and the specific check that must catch it. The conformance runner has two phases:

- **Phase A — clean.** Every fixture runs the full ladder green.
- **Phase B — mutation.** For each catalogued defect: inject it, re-run, and assert the ladder goes **RED at
  the named rung for the named reason**. A defect that fails the run *incidentally* (wrong rung, wrong
  check, crash instead of a finding) counts as a FAILURE of Phase B, not a pass.

Phase B is the part that has real value. It turns "the ladder ran" into "the ladder detects the eleven
failure classes it claims to detect," and it means a refactor of `ugt/core/` that silently disables a check
gets caught the same day instead of the next time a real game happens to trip it.

---

## Layout

```
conformance/
  README.md                     # what a green run proves, and the limitation above, stated loudly
  run_conformance.py            # the runner: Phase A + Phase B, fail-closed
  fixtures/
    sim_fixture.py              # engine.type: simulation — JSON-lines over stdin/stdout
    custom_fixture.py           # engine.type: custom — in-process/TCP, adapter built directly
    browser_fixture/            # engine.type: browser — static HTML + __GET_STATE__/__SEND_ACTION__
      index.html
      serve.py
    defects.py                  # the defect catalogue; one switch, shared by all three fixtures
  ladder/
    spike_fixture.py            # rung 1: raw protocol round-trip, no framework in the way
    smoke_fixture_adapter.py    # rung 2: same path through BaseAdapter
    verify_round1.py            # R1: one full loop + per-command invariants
    verify_round2.py            # R2: every mode to a real outcome (including a win)
    verify_round3.py            # R3: InvariantFuzzer + same-seed replay determinism
    verify_channel.py           # tier-3 channel, driven by a scripted stub model (no LLM)
    invariants.py               # ONE definition, shared by R1/R2 (per command) and R3 (wrapped)
    ugt.config.yaml             # per-engine variants, or one file with an --engine switch
    feature-map.yaml            # so `ugt verify` (tier 1) is covered too
```

`conformance/` is **tracked and shareable** — it names no upstream game and depends on nothing under
`integrations/` or `Dev/`.

---

## The three fixtures

One per `engine.type`, because the coverage property is the thing actually worth preserving from the old
examples: a change to shared `ugt/core/` code should be exercised across every transport, not just the one
in front of you.

| Fixture | `engine.type` | Transport | Dependencies |
|---|---|---|---|
| `sim_fixture.py` | `simulation` | JSON lines over stdin/stdout, spawned by `SubprocessAdapter` | none (stdlib) |
| `custom_fixture.py` | `custom` | direct `BaseAdapter` subclass; ladder constructs it, `env.py` never dispatches it | none (stdlib) |
| `browser_fixture/` | `browser` | static page + `window.__GET_STATE__` / `__SEND_ACTION__`, driven by `PlaywrightAdapter` | `[browser]` extra + chromium |

The browser fixture is **optional and skipped-with-a-loud-message** when Playwright or chromium is absent —
never silently skipped. The other two must run anywhere Python does, in seconds.

### The shared state model

All three fixtures expose the *same* tiny model, so the ladder scripts and invariants are written once. It
is chosen to exercise every assertion the ladder makes, and nothing else:

- `credits` — a spendable resource that must never go negative (invariant target).
- `steps` — a monotone counter that legitimately only ever rises (exercises the generic monotone-growth
  check **and** its `monotone_allowlist=` disposition path).
- `keys` — an inventory that can be gained and consumed (so deltas are two-directional).
- `door_open` / `won` — a reachable terminal state, so R2 can drive to a *real outcome*.
- `locked` — a state where specific actions must be **refused and state-inert** (R3's refusal probes).
- `screen` — a text panel returned via `get_terminal_text()`, so the tier-3 channel has something to read
  and truncation/salvage has something to truncate.
- a seeded roll — one action whose outcome derives from `(seed, counter)`, so determinism and replay are
  provable and **non-vacuous** (a rejected command is seed-independent; the replay proof must exercise a
  real roll).
- one action id deliberately unmapped, which must raise `NotImplementedError` naming the action rather than
  fabricating behaviour.

**Seeding is declared, not inferred** (`playtest.seeding`). Ship **two config variants** — one
`per_episode`, one `deterministic` — because those are the two branches whose confusion `ugt/core/seeding.py`
exists to prevent, and the fixture is the only place both can be tested cheaply and on purpose.

---

## The defect catalogue (Phase B)

Selected by `UGT_FIXTURE_DEFECT=<name>`, honoured identically by all three fixtures. Each row is a contract:
*this* defect must be caught at *this* rung by *this* check.

| Defect | What the fixture does wrong | Must be caught by |
|---|---|---|
| `negative_resource` | lets `credits` go below zero | R1 + R3 — no-negative-resource invariant |
| `refusal_mutates` | a refused command still changes state | R3 — refused-state-inert invariant |
| `seed_ignored` | `reset_seeded()` accepts a seed and ignores it | seeding probe (declared `per_episode`, unreproducible) |
| `vacuous_probe` | the configured `probe_action` no longer moves state | seeding probe's own vacuity check |
| `nondeterministic` | the seeded roll draws from real entropy | R3 — same-seed replay is not byte-identical |
| `replay_vacuous` | replay path avoids firing any seeded roll | R3 — replay non-vacuity check |
| `win_unreachable` | the terminal state can never be set | R2 — drive-to-a-real-outcome gate |
| `soft_lock` | after N steps every action refuses | R3 — no-soft-lock stateful invariant |
| `dead_action` | one mapped action becomes a no-op | generic checks — dead-action observation |
| `farmable_resource` | `credits` becomes monotone-only | generic checks — monotone-growth observation |
| `narration_dropped` | `reset()`/`step()` stop returning screen text | channel check — empty terminal panel |
| `reply_truncated` | stub model replies are cut mid-token | channel check — truncation salvage; turn must **not** be charged |

The last two are the shapes that cost the most in practice: `narration_dropped` is `6ffa58a` and `700c46c`
in miniature — a pilot handed an empty screen while every in-process test stays green — and it is exactly
the class a fixture *can* pin permanently.

---

## The channel check, without a model

The tier-3 loop must be covered, but a conformance run has to be **free and deterministic**, so it never
calls an LLM. Instead `verify_channel.py` drives `playtest_game_with_adapter()` with a **scripted stub
provider** that returns canned replies in sequence. This is not a new idea — it is the pattern already
proven in the sokoban example's `--prove-actions` work (`b8a057d`), where five outcomes (push / refuse /
reload / advance / win) were asserted against `get_terminal_text()` — the pilot's actual screen channel —
rather than against `step()`'s return value.

What the stub run must assert:
- the prompt is assembled and the guide is delivered whole (the P3 budget gate fires when it is not);
- state and terminal panels are non-empty and reflect the action just taken;
- a refusal is visible to the pilot as a refusal;
- the win is reachable through the channel and is reported as a win;
- a truncated reply is salvaged or discarded per spec, and **does not cost a turn**;
- the action ledger, repeat-block and stall counters populate with the values the scripted sequence implies.

Because the replies are scripted, every one of those is an exact-value assertion, not a range.

---

## The runner

```bash
python3 conformance/run_conformance.py                 # Phase A + B, all available engines
python3 conformance/run_conformance.py --engine simulation
python3 conformance/run_conformance.py --phase clean   # skip mutation (fast pre-commit)
python3 conformance/run_conformance.py --defect seed_ignored   # one row of the catalogue
```

- **Fail-closed**: exit 0 only when every check in every selected phase passed.
- **Reports what it did NOT cover** — skipped browser fixture, skipped defects, unavailable extras — because
  a silent cap reads as "covered everything." No silent skips.
- **Budget**: the `simulation` + `custom` Phase A path must finish in **under ~60s**, and Phase A + B in
  **under ~5 min**. If it is slow, it will not be run, and a check nobody runs is worth nothing.

---

## Acceptance criteria

The fixture is done when all of the following hold:

1. Phase A green on `simulation` and `custom` with no optional dependencies installed.
2. Phase A green on `browser` with the `[browser]` extra, and cleanly skipped-with-a-message without it.
3. **Phase B green on every row of the catalogue** — each defect caught at the named rung by the named
   check. This is the acceptance criterion that matters; 1–2 without 3 is decoration.
4. Both seeding variants (`per_episode`, `deterministic`) exercised, with the correct `sample_note` in each.
5. `ugt verify` covered against `feature-map.yaml` for the engines that support it.
6. `conformance/README.md` states, in its own words, what a green run does **not** prove.
7. `CLAUDE.md` "Verification & running things" repointed to it, replacing the interim "there is currently NO
   in-repo end-to-end check" text.

## Open questions for whoever builds it

- **One fixture with three transports, or three fixtures?** One shared state model behind three thin
  transports is less code and keeps the ladder scripts single-sourced, but it risks a transport bug hiding
  behind shared logic. Leaning: shared model, genuinely separate transport layers.
- **Does the defect switch live in the fixture or in a wrapper?** In-fixture is simpler; a wrapper keeps the
  clean fixture readable as a reference implementation. Leaning: `defects.py` applying to a clean fixture.
- **Should Phase B run in CI on every commit, or only on `ugt/core/` changes?** Path-filtering is tempting
  and is exactly how a check quietly stops running. Leaning: every commit, given the 5-minute budget.
