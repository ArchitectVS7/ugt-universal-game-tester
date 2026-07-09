# NEXUS UGT Integration — HANDOFF (resume here)

Single doorway for a fresh session. Last updated **2026-07-08**, after Phase 0.
Companions: `ROLLOUT.md` (the phased plan), `README.md` (run recipe + findings
registry + ladder table).

---

## TL;DR — where we are

Phase 0, **R1 and R2** of the UGT bridge are **complete and verified live**. Both
repos are on `main` and green. **R3 (the `ExploitHunter` robustness tier) is the
next step.** No open defects.

| | |
|---|---|
| **NEXUS game** | `~/Dev/Games/nexus-world-builder`, app in `apps/game`. On `main` = `origin/main`. Gates green: typecheck+lint clean, **unit 1265/1265, integration 173/173** (0 skip). |
| **UGT framework** | `~/Dev/Games/_UGT Universal Game Tester`. On `main` (NO git remote — local commits only). Nexus integration under `integrations/nexus/` + adapter `ugt/adapters/nexus_http.py`. |

**Work on `main` in both repos now** — the earlier "do not merge to main" constraint
is LIFTED (user merged the fix branch via PRs #121/#122). The old
`fix/code-review-2026-07` (nexus) and `integration/nexus-bridge` (UGT) branches are
merged/stale.

---

## The working process (do NOT deviate — it's why the work holds up)

Every ladder step runs the same **plan → code → review** pipeline, orchestrated
from the main session, strictly sequential, commit-per-item on green:

1. **Plan — Fable agent** (read-only, FREE-FORM output; NEVER a structured-output
   schema — a rigid schema crashed an earlier run). Reads the real code + the live
   contract, returns a precise implementation plan.
2. **Code — Opus agent.** Implements the plan, runs gates / the live bridge, leaves
   changes UNCOMMITTED.
3. **Review — Sonnet agent.** Adversarial: re-runs gates FOREGROUND, re-runs the
   live bridge where relevant, and for any "this is proven" claim actually runs the
   experiment (e.g. revert a guard → confirm the test goes RED). Returns PASS/FAIL.
   FAIL → back to the coder; PASS → orchestrator re-verifies and commits.

Findings surfaced by a round are **fixed upstream in the game** (on `main`, with a
pinning test in the game's own suite), then the round is re-run — the dual-validation
loop. "A failed check is data, not noise."

---

## What exists (the bridge contract)

Game side (`apps/game`, all API-key-gated via `X-Test-API-Key === TEST_API_KEY`,
`403` in production):
- `POST /api/test/bootstrap-player` → `{userId, playerId, username, email, password}`.
- `POST /api/test/reset-episode` `{playerId, seed, difficulty?, baseline?}` →
  `{ok, playerId, rngSeed, rngCounter:0, difficulty}`. `baseline:"fresh"` (default)
  = pristine; `baseline:"post_tutorial"` = past the tutorial gate so the hack
  surface is reachable (level 5 / xp 4000 / `tutorial_complete` / unlockedCommands /
  discovered story IPs). Pins `rngSeed` to the caller's seed (replay).
- `POST /api/test/closed-alpha` `{playerId, command, currentServerId?, currentPath?}`
  → `CommandResult`. **STATELESS on navigation** — reads currentServerId/currentPath
  from the request, never persists them. The adapter carries them across steps.
- `GET /api/test/player-state?playerId=…` → invariant surface: level, xp/credits
  (BigInt→**string**), difficulty, reputation, `rngCounter` (rngSeed NEVER exposed —
  A3), storyFlags (column∪blob union), unlockedCommands, currentServerId,
  discoveredServers, compromisedServers, missions (status + objective counts),
  gameStatus (isComplete/ending via checkWinCondition).

UGT side:
- `ugt/adapters/nexus_http.py` — `NexusHttpAdapter(BaseAdapter)`, pure `requests`.
  Carries nav state from each `CommandResult.stateChanges`; coerces BigInt strings;
  `reset()` uses `baseline:"post_tutorial"`; `_read_state()` GETs player-state;
  `_compose_command` (fixed script now; graduates to a real policy at R3).
- `integrations/nexus/{ROLLOUT.md, README.md, HANDOFF.md, ugt.config.yaml,
  spike_nexus.py, smoke_nexus_adapter.py, verify_dod.py}`.

`docs/REPLAY-CONTRACT.md` (nexus repo) = what a driver must reset/exclude for
byte-identical replay: set `rngSeed`+`rngCounter`, `AI_*=false`, `UGT_DETERMINISTIC=1`,
run sequentially, exclude the DB timestamp columns from diffs.

---

## Live bring-up recipe (needed for every round)

```bash
docker start nexus_ugt_pg          # seeded DB persists on :5455 (or re-create per README §1)
# from apps/game, with DATABASE_URL/POSTGRES_PRISMA_URL/POSTGRES_URL_NON_POOLING = the :5455 url:
TEST_API_KEY='ugt-test-key' DATABASE_URL=… POSTGRES_PRISMA_URL=… POSTGRES_URL_NON_POOLING=… \
  AI_ENABLED=false AI_FILES_ENABLED=false AI_DIALOGUE_ENABLED=false UGT_DETERMINISTIC=1 \
  AUTH_SECRET=test-secret NEXTAUTH_SECRET=test-secret npx next dev -p 3100 &
lsof -nP -iTCP:3100 -sTCP:LISTEN   # STALE-SERVER LESSON: confirm the PID is the next dev you launched
# then from the UGT repo root:
python3 integrations/nexus/spike_nexus.py        # 8/8 (sanity that the server is on current code)
python3 integrations/nexus/verify_round1.py      # R1 (to be written)
```
Do **not** set `NODE_ENV=production` — it disables the test routes. Full seed/first-run
recipe (docker run + prisma db push + `seed.ts` THEN `seed-story.ts`) is in `README.md` §1.

---

## The ladder — status

| Round | Script | Gate | Status |
|---|---|---|---|
| Phase 0 | spike/smoke/verify_dod | spike 8/8, smoke 5/5, DoD 7/7 | **DONE (live-green 2026-07-08)** |
| R1 | `verify_round1.py` + `invariants.py` | one playable loop + same-seed determinism + per-command invariants | **DONE (live-green 2026-07-09): 25/25 + spike 8/8.** Fixed NX-R1-1 (seed dropped canonical mission ids) + NX-R1-2 (silent mission completion when optional objective skipped); game suite unit 1259 / integration 173 green. |
| R2 | `verify_round2.py` | full 8-mission spine to a win via the adapter, all difficulty modes, per-command invariants | **DONE (live-green 2026-07-09): 36/36 + spike 8/8.** Drove the whole spine to `isComplete` + `ending_liberation` + 8/8 under normal/tutorial/hardcore; per-mission credits/xp-residual/flags asserted, rewards-once (double-reward probe), invariant sweep clean every mode, XP scaling 4/5/8 with mode-invariant mission rewards, M1-M4 same-seed replay byte-identical. Fixed **NX-R2-1** (`talk` AND-gate required the ungrantable `met_mercury` → never unlocked) + **NX-R2-2** (`talk` refused with AI off → `contact_npc` unfireable); game suite unit 1259→1265 / integration 173 green. |
| R3 | `verify_round3.py` | real `ExploitHunter`: seeded episodes, heuristic policy, invariants every step, zero findings, byte-identical replay | TODO (next) |

After R3 (robustness tier complete): the LLM balance-playtester tier (gated on API
credits), whose findings should drive the **deferred progression-math rebalance**
(tool tiers / skill cap / hidden +15% baseline / XP curve) — held back on purpose so
it's evidence-driven, with the user in the loop.

## R3 spec (next)

`verify_round3.py` graduates from R2's FIXED scripted spine to the real UGT
`ExploitHunter` robustness tier: a seeded stochastic/heuristic policy
(`NexusHttpAdapter.policy` is the seam) drives N episodes of REAL actions, with
`invariants.check_command` asserted after EVERY step (reuse `invariants.py`
unchanged — the 7 predicates carry across all rounds), deduped `Finding`/`HuntReport`,
and byte-identical same-seed replay. Zero surviving findings = gate. Findings →
fixed upstream on `main` with a pinning test, then re-run (the dual-validation loop).

Invariant set (from `ROLLOUT.md`, encoded in `invariants.py`): no crash · credits/xp
≥ 0 · xp non-decreasing · `rngCounter` +1 per command · storyFlags append-only ·
legal mission transitions · refused-actions **state-inert** · same-seed determinism.

R2 (done) is the reference for driving the game over HTTP: `verify_round2.py` +
`invariants.py`. The full 8-mission spine (with exact IPs, vulns, file paths, and
the two `talk` legs + `choose`) lives in `verify_round2.py::SPINE` — reuse it as the
"known-good playthrough" an ExploitHunter episode can seed from or check against.

---

## Gotchas (learned the hard way)

- **NX-OBS-1: a refused command still ticks `rngCounter` by design** (the tick is
  unconditional at handler entry — the per-command clock). So "refused-actions-inert"
  must be defined as **game-state inert**, NOT counter-inert. Don't flag the tick.
- **Determinism proofs must be non-vacuous.** A seed-pin test must exercise a real
  seeded roll (exploit/crack success + generated password), not a rejected command —
  a rejection is seed-independent and the test passes even if the seed isn't pinned
  (the P0-1 failure the reviewer caught). At the P0 baseline exploit succeeds ~90%
  (NX-OBS-2), so use a multi-seed variance sweep, not a single pair.
- **Stale-server lesson:** always `lsof` the LISTEN PID after starting the server —
  a squatting old server returns health 200 against OLD code.
- **package-lock churn:** `npm install` on macOS prunes the linux-only
  `@next/swc-linux-x64-gnu` optionalDependency (needed by ubuntu CI + Vercel deploy).
  If it shows in a diff, DISCARD it — keep the linux entry.
- **Action ids in `ugt.config.yaml` must stay in lockstep** with
  `NexusHttpAdapter._compose_command` (config_parser enforces size == count).

## Key files

- Adapter: `ugt/adapters/nexus_http.py`
- Scripts/config: `integrations/nexus/{spike_nexus,smoke_nexus_adapter,verify_dod}.py`, `ugt.config.yaml`
- Game endpoints: `apps/game/src/app/api/test/{reset-episode,player-state,closed-alpha,bootstrap-player}/route.ts`
- Game endpoint tests: `apps/game/tests/integration/api/{reset-episode,player-state}.test.ts`
- Winnability reference: `apps/game/tests/integration/missions/full-story-winnable.test.ts`
- Determinism reference: `apps/game/tests/integration/game/deterministic-hack-rng.test.ts`
