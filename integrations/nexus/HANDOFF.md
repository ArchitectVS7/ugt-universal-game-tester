# NEXUS UGT Integration — HANDOFF (resume here)

Single doorway for a fresh session. Last updated **2026-07-24** (post-L-030 +
the tutorial-skip disable fix). Companions: `ROLLOUT.md` (the phased plan),
`README.md` (run recipe + findings registry + ladder table), `RESULTS.md`
(the L-xxx findings log — L-014..L-030 is the LLM-tier + E2E arc).

---

## TL;DR — where we are

**Both repos are on `main`, no open branches.** Game gates on the current
build: **typecheck clean, lint 0 errors, unit 1364/1364, E2E 78/78 (chromium)**.
Ladder last confirmed green pre-E2E-work (2026-07-22): **spike 8/8 · R1 25/25 ·
R2 66/66 · R3 9/9 · content-metric 29/29**, ep-0 replay byte-identical — not
re-run since (L-024..L-030 and the tutorial-skip fix below touched the LLM
playtest tier and the Playwright E2E suite, not the ladder scripts; re-run the
ladder before trusting those numbers on a build more than a few commits newer).

**LLM playtest tier status:** channel + pilot validated (gemma4:26b, L-022);
Haiku 4.5 smoke comparisons run (L-024, L-028, both n=1). **The statistically
powered Anthropic balance batch (N runs, CI-gated) still has NOT been run** —
this is the actual next step for the tier, distinct from the smoke runs done
so far. Two UGT-side stall-detection gaps are known and unclosed (see "Open
UGT-side gaps" below) — read them before spending a batch, since they affect
how much a long run's stall/loop behavior can be trusted.

**Recent arc (2026-07-22 → 2026-07-24, see `RESULTS.md` L-024..L-030 for full detail):**
- **L-024**: first gemma4 vs Haiku 4.5 smoke comparison (40 actions each), n=1.
- **L-025/L-026**: found + fixed **NX-L26-1** (game bug, `0d99b21`) — `ls`/`cat`/`cd`
  silently swallowed a leading Unix flag (`ls -la <path>` silently read path `"-la"`,
  zero error). UGT-side: soft repeat-warning upgraded to a hard deterministic
  block (`playtest.repeat_block_threshold`).
- **L-027**: strategy guide §2b added so the pilot samples side-quest content
  instead of tunnel-visioning the main spine.
- **L-028**: first long-form Anthropic run (Haiku 4.5, 600-action budget) —
  deepest run yet (4 missions completed, 20 servers compromised), no win;
  surfaced a stall shape (diffuse repetition across many targets) the
  adjacency-only hard block doesn't catch.
- **L-029/L-030**: real-browser Playwright audit found a game-crashing bug
  (`useWorldSync.ts`, fixed) and 32 pre-existing E2E failures; all 32 fixed for
  real (no hollow passes) → **E2E suite 79/79 green** at the time (`e07b41b`).
  Surfaced **NX-L30-1** (see next).
- **2026-07-24, same-day follow-up (this session, commit `b15c44d`,
  nexus-world-builder `main`)**: **NX-L30-1 resolved — `tutorial skip` is now
  DISABLED** (`TUTORIAL_SKIP_ENABLED = false` in `executors.ts`), not fixed via
  XP-grant. Owner's call: brand-new players shouldn't skip the tutorial at all;
  a returning-player skip-with-real-XP-bump is filed as a **P2 backlog item**
  in the game's own `TODO.md` (blocked on a schema concept of "account has
  prior progress" that doesn't exist yet — `Player` is strictly 1:1 with
  `User`). All 8 tests that exercised skip were updated (pinning tests now
  assert the refusal; setup-shortcut tests switched to a real DB seed
  `db-helpers.ts::seedPlayerProgression`). E2E count moved 79/79 → **78/78**
  (one redundant skip-pinning test consolidated during the rewrite). Also
  confirmed **NX-L19-1 (`help <locked-command>` giving the real access-denied
  shape) was already fixed** — an earlier "still open" note in this doc/memory
  was stale; no action needed there.

| | |
|---|---|
| **NEXUS game** | `~/Dev/Games/nexus-world-builder`, app in `apps/game`, on `main` (latest: `b15c44d`). Gates green: typecheck+lint clean, **unit 1364/1364, E2E 78/78 (chromium)**. |
| **UGT framework** | `~/Dev/Games/_UGT Universal Game Tester`, on `main`. Nexus integration under `integrations/nexus/` + adapter `ugt/adapters/nexus_http.py`. |

## Open items (not blocking, but real)

- **The powered Anthropic balance batch hasn't been run** — the tier's actual
  deliverable. Everything to date is n=1 smoke comparisons.
- **NX-L14-1 (game, characterization only)** — the progression economy is
  inert (no command spends credits, tool-tier bonus hardcoded to BASIC, skills
  not player-directed, failed rolls cost nothing). Never handed to the owner
  as its own decision point; feeds the deferred progression-math rebalance.
- **Open UGT-side stall-detection gaps (playtester.py, game-agnostic, not
  NEXUS-specific):**
  1. The hard repeat-block only catches immediate-adjacency loops (same
     action 3x running). L-028's Haiku run showed diffuse repetition across
     many different futile targets (`progress` retried 30-48 times,
     interleaved with other dead attempts) that never trips it. Would need
     per-target futile-attempt tracking across a whole run — not built.
  2. Even where the block fires, L-026's gemma4 run showed an oscillation
     pattern: try a blocked command twice, get forced to `wait` on the 3rd
     (which resets the adjacency counter), then return to the SAME dead
     target. Bounds damage per cycle, doesn't stop returning to a proven-dead
     target.
- **Returning-player tutorial skip + XP bump** — filed as P2 in
  nexus-world-builder's own `TODO.md`, blocked on a new schema field. Not
  urgent; documented so it isn't lost.

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
| R3 | `verify_round3.py` | real `ExploitHunter`: seeded episodes, heuristic policy, invariants every step, zero findings, byte-identical replay | **DONE (live-green 2026-07-09): 9/9 + spike 8/8.** UGT's REAL `ExploitHunter` (unchanged) drove 4 seeded episodes x 90 steps under a phase-aware heuristic + refusal-probing policy over the 20-action vocabulary (args composed from observed state). ZERO findings: the 7 R1/R2 per-command invariants (wrapped to the hunter's `(before, action_id, info, after, ctx)` signature) + 2 R3-only stateful invariants (completed-story-missions monotonic, no 25-in-a-row soft-lock) held on every step, including under 8 deliberate refusal probes (each refused + game-state inert). Full action coverage, real progress (7 compromises / 30 rolls / a story mission completed every episode), and a fresh same-seed episode-0 replay is byte-identical (90/90) + non-vacuous. No game defect surfaced → game repo untouched (unit 1265 / integration 173). Config action_space extended 14 → 20 (ids 0–13 frozen); base `_compose_command` gained simple defaults for the new verbs, all state-driven/probe/directed composition lives in `verify_round3.py::R3NexusAdapter`. |

After R3 (robustness tier complete): the LLM balance-playtester tier (gated on API
credits), whose findings should drive the **deferred progression-math rebalance**
(tool tiers / skill cap / hidden +15% baseline / XP curve) — held back on purpose so
it's evidence-driven, with the user in the loop.

## R3 (DONE 2026-07-09) — how it was built

`verify_round3.py` graduated from R2's FIXED scripted spine to the real UGT
`ExploitHunter` (`ugt/core/exploit_hunter.py`, used UNCHANGED). Shape:

- **`R3NexusAdapter(NexusHttpAdapter)`** (in the script): NO-ARG `reset()` (the
  hunter's contract) pins seed `f"{base}-ep{n}"` and clears per-episode observed
  caches (`_known_vulns` / `_known_files` / `_read_files` / `_available_missions`
  / `_cur_ip`); `step()` records a trajectory row + parses the command output back
  into those caches; an overridden `_compose_command` fills args from live state,
  from a one-shot refusal-`_probe`, or from a one-shot objective-directed
  `_forced_command`.
- **Policy** `make_nexus_policy(adapter)` (bound so it can read carried nav state
  + caches the raw player-state does NOT expose): a failure back-off → 15%
  refusal probes (8 kinds) → 10% uniform exploration (guarantees the rare verbs)
  → an objective-directed spine leg → phase-aware fallback. Deterministic given
  `(state, rng, ctx, caches)`.
- **Invariants**: the 7 `invariants.ALL` predicates `wrap()`-ped from
  `(before, after, command, result)` to the hunter's
  `(before, action_id, info, after, ctx)` signature, + 2 R3-only stateful ones
  (`story_missions_monotonic`, `no_soft_lock` via `ctx["consecutive_fails"]`).
- **Config**: `action_space` extended 14 → 20 (ids 0–13 frozen); the base
  `_compose_command` got simple defaults for `talk`/`choose`/`disconnect`/
  `whoami`/`garbage`, and `action_18` falls through to a verbatim send.
- **Replay**: episode 0 ONLY (the policy rng is shared across episodes, so a fresh
  hunter+adapter reproduces ep0's draw order) — byte-identical + non-vacuous.

Gate = 9/9 (all episodes ran · zero findings · R3 stateful invariants clean ·
full action coverage · unmapped+garbage inert · refusal probes fired · non-vacuous
progress · byte-identical ep-0 replay). Live-green 2026-07-09. No game defect
surfaced. `verify_round2.py::SPINE` remains the source of the exact IPs/vulns/file
paths the R3 directed heuristic biases toward.

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
- LLM playtest (L-006): after the Live bring-up recipe above (server on :3100,
  PID-verified) + `ollama serve`, run
  `TEST_API_KEY=… python3 integrations/nexus/playtest_nexus.py --provider ollama`.
  It uses the L-002 direct-adapter entry point in `action_mode="text"`: the LLM TYPES
  raw command lines through the adapter's `type_text`/`get_terminal_text` (the real
  terminal UX), and `NexusHttpAdapter.type_text_step` reports each transition so deltas
  are genuine (see RESULTS.md "L-006" for the fix-round-1 root-cause repair to the
  shared loop's type_text branch). `strategy-guide.md` + the additive `playtest:`
  config block drive it. Exit 0 + "PLAYTEST MET" = ≥20 actions, ≥1 typed command with a
  real state delta, invariant suite ran, and the progressive-content metric ran.
- Progressive-content engagement metric (L-020): `playtest.revealed_content` in
  `ugt.config.yaml` → `ugt/core/playtester.py::_RevealTracker`. Answers the owner's
  "is the pilot agile about newly revealed commands / quest lines?" criterion; numbers
  land in `results/playtest-report.json` under `content_engagement` (+ three keys in
  `summary`). Its own gate needs NO server and NO LLM:
  `python3 integrations/nexus/verify_content_metric.py` (27/27, mutation-tested — it
  replays synthetic logs where the pilot ignores content and asserts the metric FAILS).
  Read the two shipped limitations in RESULTS.md L-020 before quoting any number.
- Game endpoints: `apps/game/src/app/api/test/{reset-episode,player-state,closed-alpha,bootstrap-player}/route.ts`
- Game endpoint tests: `apps/game/tests/integration/api/{reset-episode,player-state}.test.ts`
- Winnability reference: `apps/game/tests/integration/missions/full-story-winnable.test.ts`
- Determinism reference: `apps/game/tests/integration/game/deterministic-hack-rng.test.ts`
