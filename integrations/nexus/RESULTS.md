# NEXUS UGT Trial — Test Results Log

Consolidated, commit-traceable record of every ladder round's final **verified**
outcome. Full per-round narrative + the findings registry are in `README.md`;
the resume-here state is in `HANDOFF.md`. Every round was run against the **live**
game over HTTP (Docker Postgres + `next dev`, AI-off deterministic env,
PID-verified) and **independently re-run by a review agent** before being logged.

Repos: NEXUS game `~/Dev/Games/nexus-world-builder` (on `main`, pushed to origin);
UGT framework `~/Dev/Games/_UGT Universal Game Tester` (on `main`, local-only, no
remote). Game suite baseline at trial end: **unit 1265 / integration 173, 0 skip**,
typecheck + lint clean.

## Ladder — ALL ROUNDS PASSED (trial ladder COMPLETE)

| Round | Date | Script | Result (live) | Findings | UGT commit | Game commit(s) |
|---|---|---|---|---|---|---|
| **Phase 0** | 2026-07-08 | `spike_nexus.py` · `smoke_nexus_adapter.py` · `verify_dod.py` | **spike 8/8 · smoke 5/5 · DoD 7/7** — bring-up + one real hack loop (scan→connect→exploit→compromise) through the adapter | NX-P0-1 (fixed) | `6740027` | `a4fc7a2`, `4d6a227` |
| **R1** | 2026-07-09 | `verify_round1.py` · `invariants.py` | **25/25** (+ spike 8/8) — one full `the_breadcrumb` loop; rewards-exactly-once; per-command invariants clean; byte-identical same-seed replay + 8-seed variance | NX-R1-1, NX-R1-2 (fixed) | `cc7ba7e` | `780bc31` |
| **R2** | 2026-07-09 | `verify_round2.py` · `invariants.py` | **36/36** (+ spike 8/8) — FULL 8-mission spine to a **real win** (`isComplete`, `ending_liberation`, 8/8) under **all 3 difficulty modes**; XP scaling 4/5/8; multi-mission determinism prefix | NX-R2-1, NX-R2-2 (fixed) | `87cd758` | `0e5dd92` |
| **R3** | 2026-07-09 | `verify_round3.py` · `invariants.py` | **9/9** (+ spike 8/8) — real `ExploitHunter`, 4 episodes × 90 = **360 steps, ZERO findings**; 9 invariants/step; all 20 verbs + all 8 refusal-probe kinds inert; byte-identical episode-0 replay (90/90) | none (game clean) | `c86a86c` | — (no game change) |

## Findings surfaced by the ladder

**Game fixes (each pinned by a test in the game suite):**
- **NX-P0-1** — the hack surface was gated behind un-grantable tutorial state → `reset-episode` `baseline:"post_tutorial"`.
- **NX-R1-1** — the story seed dropped canonical mission ids → extracted `story-mission-seed.ts` preserving `id`.
- **NX-R1-2** — missions with a skipped optional objective completed **silently** (no banner) → trust the required-only status.
- **NX-R2-1** — `talk` could never unlock (AND-gated on the ungrantable `met_mercury`) → OR-logic across reachable met flags.
- **NX-R2-2** — `talk` hard-required a live AI provider → delivers scripted lines + emits `contact_npc` when AI is disabled.

**Characterizations (by-design / coverage notes, not defects):**
- **NX-OBS-1** — a refused command still ticks `rngCounter` by design (the per-command clock); invariants exclude it.
- **NX-OBS-2** — the exploit roll is genuinely seeded; ~90% success at the P0 baseline (variance verified via multi-seed sweep).
- **NX-R3** — R3 surfaced zero game defects; two issues fixed harness-side (a parse regex + policy arg-composition bias).
- **NX-R3-OBS** — R3 is a genuine robustness walk (plateaus at 1/8 vs R2's scripted 8/8), not "R2 with probes"; late-game `talk`/`choose` success paths are R2-covered, not re-covered — strengthen later via longer episodes / mid-spine seeded reset.

## How to re-run (reproduce any result)

Per `HANDOFF.md` §"Live bring-up": `docker start nexus_ugt_pg` → from `apps/game`
`next dev -p 3100` with the deterministic AI-off env (`TEST_API_KEY`, the `:5455`
`DATABASE_URL`/`POSTGRES_*`, `AI_ENABLED=false AI_FILES_ENABLED=false
AI_DIALOGUE_ENABLED=false UGT_DETERMINISTIC=1`, `AUTH_SECRET`/`NEXTAUTH_SECRET`;
**not** `NODE_ENV=production`) → `lsof` the LISTEN PID → `python3
integrations/nexus/spike_nexus.py` then `verify_round{1,2,3}.py`.

## Status: NEXUS robustness/trial ladder COMPLETE (2026-07-09)

The game is winnable, byte-identical-replayable, and robust under a 360-step
random walk — all verified live over HTTP. Next tier (not part of this ladder):
the LLM balance-playtester (API-credit-gated), whose findings would drive the
deliberately-deferred progression-math rebalance.
