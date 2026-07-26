# Dice Duel (integration) — Master Task List

Build the UGT-side integration per `PRD.md` in this folder, against the built
game in `../game`.

## Orchestrator protocol

1. Check out the first `status: TODO` task whose `after:` are all DONE; set IN-PROGRESS.
2. Plan → 3. Code → 4. Review vs **Accept** → 5. Gate, commit `<ID>: <title>`, set DONE, update this file in the same commit.

**Gate (every task):** `python -c "import glob, py_compile; [py_compile.compile(f, doraise=True) for f in glob.glob('*.py')]"`
(compiles any `.py` files present; passes vacuously before any exist) exits
0. Starting at T-004 (once `feature-map.yaml` exists), also require `ugt
verify --config ugt.config.yaml --feature-map feature-map.yaml` to exit 0
with 0 FAILED features.

**Standing constraints:**
- No game logic in any file under this folder — every rule lives in
  `../game/src/engine.js`. If a check needs logic UGT doesn't have, that's a
  missing hook in the game, not something to fake here.
- `../game` must be built (`npm run build` in `../game`) and served before any
  ladder script runs.

Statuses: `TODO` | `IN-PROGRESS` | `DONE` | `BLOCKED(reason)`

---

## M0 — Wiring

### T-001 · `ugt.config.yaml` — `status: DONE` · `coder: sonnet` · `after: —`
Write the config per PRD: `engine.type: browser`, observation/action
mappings, `evaluation.victory_key: winner`. Point `entry` at a locally-served
built bundle (default `http://localhost:8080/index.html`).
**Accept:** `UgtConfig` loads it without error (`python -c "from
ugt.utils.config_parser import UgtConfig; UgtConfig('ugt.config.yaml')"` exits
0).

**Delivered (2026-07-25):** `ugt.config.yaml` — browser engine, 7 allocation presets `a6_d0`..`a0_d6` matching ../game/PRD.md's __SEND_ACTION__ mapping, 5-field observation projection, `evaluation.victory_key: winner`.

### T-002 · Static server for the built bundle — `status: DONE` · `coder: sonnet` · `after: T-001`
Add `serve.py`, adapted from `examples/browser-game/serve.py`, serving
`../game/dist`.
**Accept:** `python serve.py &` then `curl localhost:8080` returns 200; script
stoppable with a single signal.

**Delivered (2026-07-25):** `serve.py`, adapted from examples/browser-game/serve.py. Two changes for a *built* bundle: it fails loudly when ../game/dist is missing (rather than serving 404s that look like game bugs to the adapter), and it handles SIGINT/SIGTERM so a ladder script can spawn and reap it. `--port` added so callers can avoid a squatted 8080. Verified: HTTP 200 on /index.html, LISTEN pid confirmed via lsof.

### T-003 · `ugt smoke-test` passes — `status: DONE` · `coder: sonnet` · `after: T-002`
Run `ugt smoke-test --config ugt.config.yaml` against the served bundle; fix
any observation/action mapping mismatches.
**Accept:** `ugt smoke-test` exits 0 with 5/5 steps succeeding.

## M1 — Correctness (Tier 1)

**Delivered (2026-07-25):** `ugt smoke-test` passes, 5/5 steps, no mapping mismatches. Real gameplay visible in the obs vector, including the round-3 reinforcement bonus.

### T-004 · `feature-map.yaml` (F1-F6) — `status: DONE` · `coder: opus` · `after: T-003`
Author the feature map per PRD's coverage table (F1-F6), including
preconditions and delta/state assertions.
**Accept:** `ugt verify --config ugt.config.yaml --feature-map
feature-map.yaml` exits 0, `coverage-report.json` shows 6/6 PASSED, 0 FAILED,
0 NOT_REACHED.

## M2 — Robustness (Tier 2)

**Delivered (2026-07-25) — with a deliberate, evidenced deviation from the stated accept.** `ugt verify` reports **5/5 PASSED, 0 FAILED, 0 NOT_REACHED**, not 6/6, because two of the PRD's six features are NOT EXPRESSIBLE as feature-map entries. Both are covered in `exploit_hunt.py` instead, so all six rules are still verified:

- **F2** (all-defense takes less damage than all-attack) is a comparison BETWEEN TWO ROUNDS. A feature only sees before/after of its own action list, so it cannot hold one round's damage and compare it with another's. It is run in Tier 2 as a controlled A/B on one seed: all-attack lost 6 FS over 4 rounds, all-defense lost 3.
- **F5** (0 force strength sets a decisive winner) is **unreachable on the game's default seed**, and the feature map has no way to select a seed (`engine.reset_command` is silently ignored whenever `__RESET_GAME__` exists — README Finding 3). Evidence: 205 sequences on seed `'dice-duel'` — 5 fixed policies + 200 aggression-biased random — never got the enemy below 1 FS inside the 12-round cap. Tier 2 drives it on seed 0, where an all-attack line knocks the enemy out at round 11.

The map adds one feature of its own, `battle.concluded_battle_is_inert`, because the adapter never observes termination for this game (README Finding 2) and therefore keeps sending actions into a finished battle.

### T-005 · Invariant-fuzzer invariants + same-seed replay — `status: DONE` · `coder: opus` · `after: T-004`
Write an invariants module (`0 ≤ force_strength ≤ 20`, `round_number`
monotonic, `winner` implies `battle_over`) and a script that runs the
invariant-fuzzer for ≥100 steps across two seeds, then replays one seed twice
and diffs state.
**Accept:** script exits 0; 0 invariant violations across both seeds; replay
diff is empty (byte-identical).

## M3 — Balance (Tier 3)

**Delivered (2026-07-25):** `exploit_hunt.py` — **TIER 2 MET, 8/8 checks**. 7 invariants (force in 0..20 and non-increasing, round monotonic and capped, winner implies battle_over, battle_over terminal+inert, winner value legal), 2 seeds x 120 random steps (>=100 required), 0 findings; byte-identical same-seed replay proven non-vacuous; negative control proving all 7 invariants can fire and none false-positives. Also carries PRD F2 and F5, which the feature-map model cannot express (see README). Spawns/reaps its own server on an ephemeral port so a stale :8080 cannot substitute a different bundle.

**Superseded (2026-07-26):** `exploit_hunt.py` has been replaced by the full trial ladder — `spike_dice.py`, `smoke_dice_adapter.py`, `verify_round1.py`, `verify_round2.py`, `verify_round3.py`. Everything it did is still covered and then some: its random walks and determinism check are now R3, its defense-vs-attack A/B and its knockout drive are now R2 (where they belong, since both are content-spine claims). Invariants moved into a shared `invariants.py` built on `InvariantSuite`, so R1/R2 and R3 assert the identical predicates instead of two hand-maintained copies.

### T-008 · LESSONS §B pre-flight, driven on a LOCAL model — `status: TODO` · `coder: opus` · `after: T-007`
**This is the prep, and it must happen BEFORE T-006 spends a single credit.** It
runs entirely on local Ollama, so it costs nothing and is not blocked by
anything.

**This is not a paper audit — it is a real playtest loop against a free model**
(`LESSONS.md` §B P12). Drive a few basic allocations first, then a **30-action
smoke test**, and iterate: run → read the logged `reasoning` → fix the guide or
the prompt → run again, until the pilot cleanly processes the basic battle loop.

```bash
# ollama running at localhost:11434, no API key
cd examples/dice/integration && python3 serve.py --port 8080 &
ugt playtest --config ugt.config.yaml --strategy-guide strategy-guide.md \
  --provider ollama --model gemma4:26b --max-actions 30
```

Stop at ~100 actions. Past ~200 local calls the decisions degrade below Haiku's,
and a longer run buys worse play rather than more evidence. **Local proves the
channel; it never produces a balance number for this game.**

`LESSONS.md` §B (P1–P12) is the mandatory information-integrity audit. Skipping
it cost two multi-hour balance batches on another game that measured the wrong
thing — both permanently unpoolable with anything measured afterwards. The
failure mode is invisible in the output: the loop reports `PLAYTEST MET`, zero
violations, and a confident-sounding win rate, while the pilot was playing
blind.

**Write a cited disposition for every check P1–P12.** The ones most likely to
bite this game, based on what the D18 work already turned up:

- **P6 (the guide must teach the RULES that create the skill)** — the live risk
  here, and it has already happened once. Before D18 the guide taught "the cap
  is a draw, so race for the kill". That is now *actively wrong advice*: the cap
  decides on points. It was rewritten on 2026-07-26 — re-read it against
  `game/PRD.md` and confirm it teaches the two-for-one block, the points
  decision, and that all-out attack LOSES. A pilot reading a stale guide plays
  the old game badly and the model gets the blame.
- **P2 (adapter passes through every PUBLIC field)** — diff the normalized state
  against `__GET_STATE__`'s projection. Note `bonus_dice` is the previous
  round's grant, so confirm the pilot can tell what it will get NEXT round or
  knows that it cannot.
- **P3 (truncation is silent starvation)** — assert
  `len(strategy-guide.md) <= playtest.guide_char_budget`. The guide grew in the
  D18 rewrite; the budget was set before it.
- **P1/P4 (identities, and the action channel sends what the LLM thinks)** —
  this game's 7 actions are named `a6_d0`…`a0_d6`, which is legible, but confirm
  the prompt shows the allocation and not a bare index.
- **P11 (a prompt-level warning is advice, not a guarantee)** — the game refuses
  out-of-range ids by THROWING (spike finding), unlike the other two examples.
  Confirm the playtest loop survives that rather than counting it as a turn.

**Accept:** a clean 30-action local run that reaches a real battle outcome, PLUS
a written disposition per check P1–P12, each citing the specific file/line
compared — "looks fine" is not a disposition (O7). Any gap fixed before T-006
runs.

*Reading the local run (§B P12): the P7 competence grep is a POSITIVE signal
only. If gemma's reasoning names the two-for-one block or the points decision,
the channel is proven. If it does not, that is ambiguous — starvation and a weak
model look identical from outside — so re-check on T-006 rather than closing a
P1/P2/P6 finding here.*

### T-006 · `ugt playtest` run on Haiku — `status: BLOCKED(awaiting user approval to spend API credits)` · `coder: sonnet` · `after: T-008`
Once T-008's local loop is clean, run the paid tier — Haiku, the working default
for speed and cost — with `--max-actions 30` to confirm the LLM can play a full
battle. This is the run that is allowed to produce a number.
**Accept:** `ugt playtest` exits 0 and produces `results/playtest-report.json`
with at least one completed battle (`battle_over: true` reached, or
max-actions budget honestly reported as insufficient).

**Guide status (rewritten 2026-07-26):** `strategy-guide.md` covers the 7
allocations, all three bonus-dice rules and how they stack, the observable
state, the two-for-one defense block, and the fact that the cap decides on
points so surviving one point ahead is a full win.

> ⚠️ The previous note here claimed the guide warned that "the round-12 cap
> makes a draw the DEFAULT outcome". That was true when written and D18 made it
> false — the cap now decides on force strength. The note survived the rule
> change by four commits. **This is exactly the P6 drift T-008 exists to catch,
> and it is recorded rather than quietly edited away.**

The run itself is NOT done: this stage bills a real Anthropic API call per
action. After T-008 passes, trigger with:

```bash
ugt playtest --config ugt.config.yaml --strategy-guide strategy-guide.md \
  --provider anthropic --model claude-haiku-4-5-20251001 --max-actions 30
```

then flip to DONE. Expect to iterate afterwards — on the harness or on the game
— and to re-run. That loop is faster than human testing, and the target is that
the **first human UAT is already relatively bug-free**, so a person's time goes
on feel and readability rather than on defects a free local run would catch.

---

**Deliberately deferred:** RL train/evaluate profiles (legacy tier, not the
point of this example).

## M4 — Trial ladder (added 2026-07-26)

The rungs below were not in the original list; this integration was written
CLI-first (`ugt verify` + a standalone hunt) and later brought up to the same
five-rung shape the other integrations use, so all three examples can be run
and read the same way.

### T-007 · Full trial ladder — `status: DONE` · `coder: opus` · `after: T-005`
`serve_process.py` (shared server lifecycle, ephemeral port), `invariants.py`
(8 predicates via `InvariantSuite`, shared by all rungs), and the five rungs.
**Accept:** every rung fail-closed via `GateRunner`, each proving its own
non-vacuity, all green from a cold machine.

**Delivered (2026-07-26):** SPIKE 17/17 (+1 finding) · SMOKE 8/8 (+1 finding) ·
R1 12/12 · R2 10/10 (+1 finding) · R3 10/10 (+1 finding). The spike immediately
found something the CLI tiers never touched — `__SEND_ACTION__` THROWS on an
out-of-range action id where the other two examples return unchanged state —
and R3 quantified the termination gap: only ~9% of a 120-step random episode
lands on a live battle, because the adapter never sees the battle end.
