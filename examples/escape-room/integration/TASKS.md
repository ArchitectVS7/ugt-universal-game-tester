# Tiny Escape Room (integration) — Master Task List

Build the UGT-side integration per `PRD.md` in this folder, against `../game`.

## Orchestrator protocol

1. Check out the first `status: TODO` task whose `after:` are all DONE; set IN-PROGRESS.
2. Plan → 3. Code → 4. Review vs **Accept** → 5. Gate, commit `<ID>: <title>`, set DONE, update this file in the same commit.

**Gate (every task):** `ugt verify --config ugt.config.yaml --feature-map
feature-map.yaml` exits 0 with 0 FAILED features.

**Standing constraints:**
- No game logic added here — every rule lives in `../game/src/engine.js`.
  This folder only configures and drives it.
- `../game`'s `npm test` must be green before any ladder script is expected
  to pass.

Statuses: `TODO` | `IN-PROGRESS` | `DONE` | `BLOCKED(reason)`

---

## M0 — Wiring

### T-001 · `ugt.config.yaml` — `status: TODO` · `coder: sonnet` · `after: —`
`engine.type: simulation`, `entry: ../game/src/bridge.js`, action_space
enumerating the fixed action table, observation_space per PRD's numeric
fields, `evaluation.victory_key: escaped`.
**Accept:** `UgtConfig` loads it without error.

### T-002 · `ugt smoke-test` passes — `status: TODO` · `coder: sonnet` · `after: T-001`
Run smoke-test; fix any action_id / mapping mismatches against the real
bridge.
**Accept:** `ugt smoke-test` exits 0, 5/5 steps.

## M1 — Correctness (Tier 1)

### T-003 · `feature-map.yaml` (F1-F6) — `status: TODO` · `coder: opus` · `after: T-002`
Author F1-F6 per PRD's coverage table, including the flag-based workaround
noted for the SafeEvaluator's missing `in` operator.
**Accept:** `ugt verify` exits 0, 6/6 PASSED, 0 FAILED, 0 NOT_REACHED.

## M2 — Robustness (Tier 2)

### T-004 · Exploit-hunter invariants — `status: TODO` · `coder: opus` · `after: T-003`
Invariants: `moves_taken`/`rooms_visited` monotonic non-decreasing,
`current_room` always a known room_id, `escaped` never reverts to false. Run
≥150 random steps, two seeds; same-seed replay diff empty.
**Accept:** script exits 0; 0 violations both seeds; replay diff empty.

## M3 — Balance (Tier 3)

### T-005 · `strategy-guide.md` + playtest run — `status: TODO` · `coder: sonnet` · `after: T-003`
Write the guide (verbs, inventory model, win condition, no assumed context).
Run `ugt playtest --max-actions 40` once.
**Accept:** exits 0; report shows either `escaped: true` or an honest
"insufficient actions" outcome — not a silent stall.

---

**Deliberately deferred:** RL train/evaluate profiles.
