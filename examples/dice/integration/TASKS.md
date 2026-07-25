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

### T-001 · `ugt.config.yaml` — `status: TODO` · `coder: sonnet` · `after: —`
Write the config per PRD: `engine.type: browser`, observation/action
mappings, `evaluation.victory_key: winner`. Point `entry` at a locally-served
built bundle (default `http://localhost:8080/index.html`).
**Accept:** `UgtConfig` loads it without error (`python -c "from
ugt.utils.config_parser import UgtConfig; UgtConfig('ugt.config.yaml')"` exits
0).

### T-002 · Static server for the built bundle — `status: TODO` · `coder: sonnet` · `after: T-001`
Add `serve.py`, adapted from `examples/browser-game/serve.py`, serving
`../game/dist`.
**Accept:** `python serve.py &` then `curl localhost:8080` returns 200; script
stoppable with a single signal.

### T-003 · `ugt smoke-test` passes — `status: TODO` · `coder: sonnet` · `after: T-002`
Run `ugt smoke-test --config ugt.config.yaml` against the served bundle; fix
any observation/action mapping mismatches.
**Accept:** `ugt smoke-test` exits 0 with 5/5 steps succeeding.

## M1 — Correctness (Tier 1)

### T-004 · `feature-map.yaml` (F1-F6) — `status: TODO` · `coder: opus` · `after: T-003`
Author the feature map per PRD's coverage table (F1-F6), including
preconditions and delta/state assertions.
**Accept:** `ugt verify --config ugt.config.yaml --feature-map
feature-map.yaml` exits 0, `coverage-report.json` shows 6/6 PASSED, 0 FAILED,
0 NOT_REACHED.

## M2 — Robustness (Tier 2)

### T-005 · Exploit-hunter invariants + same-seed replay — `status: TODO` · `coder: opus` · `after: T-004`
Write an invariants module (`0 ≤ force_strength ≤ 20`, `round_number`
monotonic, `winner` implies `battle_over`) and a script that runs the
exploit-hunter for ≥100 steps across two seeds, then replays one seed twice
and diffs state.
**Accept:** script exits 0; 0 invariant violations across both seeds; replay
diff is empty (byte-identical).

## M3 — Balance (Tier 3)

### T-006 · `strategy-guide.md` + playtest run — `status: TODO` · `coder: sonnet` · `after: T-004`
Write the strategy guide per PRD (ruleset, 7 choices, win condition, no
assumed context). Run `ugt playtest` once with `--max-actions 30` to confirm
the LLM can play a full battle.
**Accept:** `ugt playtest` exits 0 and produces `results/playtest-report.json`
with at least one completed battle (`battle_over: true` reached, or
max-actions budget honestly reported as insufficient).

---

**Deliberately deferred:** RL train/evaluate profiles (legacy tier, not the
point of this example).
