# Tiny Escape Room (integration) — Master Task List

Build the UGT-side integration per `PRD.md` in this folder, against `../game`.

## Orchestrator protocol

1. Check out the first `status: TODO` task whose `after:` are all DONE; set IN-PROGRESS.
2. Plan → 3. Code → 4. Review vs **Accept** → 5. Gate, commit `<ID>: <title>`, set DONE, update this file in the same commit.

**Gate (every task):** `python -c "from ugt.utils.config_parser import
UgtConfig; UgtConfig('ugt.config.yaml')"` exits 0. Starting at T-003 (once
`feature-map.yaml` exists), also require `ugt verify --config
ugt.config.yaml --feature-map feature-map.yaml` to exit 0 with 0 FAILED
features.

**Standing constraints:**
- No game logic added here — every rule lives in `../game/src/engine.js`.
  This folder only configures and drives it.
- `../game`'s `npm test` must be green before any ladder script is expected
  to pass.

Statuses: `TODO` | `IN-PROGRESS` | `DONE` | `BLOCKED(reason)`

---

## M0 — Wiring

### T-001 · `ugt.config.yaml` — `status: DONE` · `coder: sonnet` · `after: —`
`engine.type: simulation`, `entry: ../game/src/bridge.js`, action_space
enumerating the fixed action table, observation_space per PRD's numeric
fields, `evaluation.victory_key: escaped`.
**Accept:** `UgtConfig` loads it without error.

**Delivered (2026-07-25):** `ugt.config.yaml`, generated from `node ../game/src/bridge.js --actions` so the 41 action ids come from the CSVs rather than transcription. Observation space maps `moves_taken`/`rooms_visited`/`inventory`(count)/`escaped` — NOT the PRD's `flags_set_count`, which is unmappable because `flags` is a dict and the `count` aggregator is list-only (see README Findings #2).

### T-002 · `ugt smoke-test` passes — `status: DONE` · `coder: sonnet` · `after: T-001`
Run smoke-test; fix any action_id / mapping mismatches against the real
bridge.
**Accept:** `ugt smoke-test` exits 0, 5/5 steps.

## M1 — Correctness (Tier 1)

**Delivered (2026-07-25):** `ugt smoke-test` passes, 5/5 steps, no action_id mismatches. All five random actions were context-invalid no-ops from R01 (which has only a north exit), each returning valid unchanged state — the refusal path the PRD asks for.

### T-003 · `feature-map.yaml` (F1-F6) — `status: DONE` · `coder: opus` · `after: T-002`
Author F1-F6 per PRD's coverage table, including the flag-based workaround
noted for the SafeEvaluator's missing `in` operator.
**Accept:** `ugt verify` exits 0, 6/6 PASSED, 0 FAILED, 0 NOT_REACHED.

## M2 — Robustness (Tier 2)

**Delivered (2026-07-25):** `feature-map.yaml` — **6/6 PASSED, 0 FAILED, 0 NOT_REACHED**. Written as one continuous playthrough of the real 7-link flag chain, because `ugt verify` does not navigate to satisfy preconditions. F5 asserts consumption through refusal semantics rather than the PRD's `inventory_count` (no `len()`/`in` in the assertion language). Proven non-vacuous: inverting F6 produces 1 FAILED. That negative control also surfaced README Finding #1 — `ugt verify` exits 0 even when features fail.

### T-004 · Invariant-fuzzer invariants — `status: DONE` · `coder: opus` · `after: T-003`
Invariants: `moves_taken`/`rooms_visited` monotonic non-decreasing,
`current_room` always a known room_id, `escaped` never reverts to false. Run
≥150 random steps, two seeds; same-seed replay diff empty.
**Accept:** script exits 0; 0 violations both seeds; replay diff empty.

## M3 — Balance (Tier 3)

**Delivered (2026-07-25):** `fuzz_escape_room.py` — **TIER 2 MET, 6/6 checks**. Two seeds x 160 random steps (>=150 required), 0 findings, against 6 invariants read from the game's own rooms.csv. Includes a negative control proving every invariant can fire and none fires on a legitimate transition, plus a non-vacuity check on the determinism proof. Random play reached only 9 distinct states in 61 steps — recorded as README Finding #4, not a defect.

### T-005 · `strategy-guide.md` + playtest run — `status: BLOCKED(awaiting user approval to spend API credits)` · `coder: sonnet` · `after: T-003`
Write the guide (verbs, inventory model, win condition, no assumed context).
Run `ugt playtest --max-actions 40` once.
**Accept:** exits 0; report shows either `escaped: true` or an honest
"insufficient actions" outcome — not a silent stall.

**Prepared (2026-07-25):** `strategy-guide.md` is written and the wiring is ready. The run itself is NOT done: `ugt playtest` bills a real Anthropic API call per action, and this was built unattended overnight — spending credits is the user's call, not the runner's. Trigger with `ugt playtest --config ugt.config.yaml --strategy-guide strategy-guide.md --max-actions 40`, then flip this to DONE if the report shows `escaped: true` or an honest insufficient-actions outcome.

---

**Deliberately deferred:** RL train/evaluate profiles.
