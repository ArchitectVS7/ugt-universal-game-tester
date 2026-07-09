# NEXUS World Builder integration (real server, HTTP adapter)

Drives the **real** nexus-world-builder Next.js game (`../nexus-world-builder/apps/game`)
over plain HTTP via `ugt/adapters/nexus_http.py::NexusHttpAdapter` — never a
re-implementation of the game (the `sim_bridge` / warzones-ml lesson).

NEXUS is a terminal-hacking RPG. Its whole observable surface is three test-only
JSON routes the running server exposes (dev / non-production only, gated on
`TEST_API_KEY`), so the adapter is pure `requests` — no websocket, no browser:

| Route | Adapter method | Purpose |
|---|---|---|
| `POST /api/test/bootstrap-player` | `connect()` | create a throwaway player (reachability + warm) |
| `POST /api/test/reset-episode` | `reset(seed)` | re-pin the player to a deterministic seed + baseline |
| `POST /api/test/closed-alpha` | `step()` / `type_text()` | execute ONE game command → `CommandResult` |
| `GET  /api/test/player-state` | `_read_state()` | full observable state (progression, servers, missions, win) |

**Stateless-nav contract (the one non-obvious thing):** `closed-alpha` reads
`currentServerId`/`currentPath` from the *request* and never persists them
(`player-state.currentServerId` stays `null`). The adapter therefore carries nav
state across steps itself — it copies `CommandResult.stateChanges.currentServerId`
/ `.currentPath` forward into the next request. `connect <ip>` surfaces a real
server id; `disconnect` clears it.

## Run

```bash
# 1. Infra: a standalone Docker Postgres for the UGT DB
docker run -d --name nexus_ugt_pg -e POSTGRES_USER=nexus -e POSTGRES_PASSWORD=nexus \
  -e POSTGRES_DB=nexus_ugt -p 5455:5432 postgres:16
export UGT_DB='postgresql://nexus:nexus@127.0.0.1:5455/nexus_ugt'

# 2. Schema + deterministic seed (order matters — each seed deleteMany's):
cd ../nexus-world-builder/apps/game
DATABASE_URL=$UGT_DB POSTGRES_PRISMA_URL=$UGT_DB POSTGRES_URL_NON_POOLING=$UGT_DB \
  npx prisma db push --skip-generate
DATABASE_URL=$UGT_DB npx prisma generate
DATABASE_URL=$UGT_DB POSTGRES_PRISMA_URL=$UGT_DB POSTGRES_URL_NON_POOLING=$UGT_DB \
  npx tsx prisma/seed.ts        # orgs + 100 servers + tutorial mission (WIPES first)
DATABASE_URL=$UGT_DB POSTGRES_PRISMA_URL=$UGT_DB POSTGRES_URL_NON_POOLING=$UGT_DB \
  npx tsx prisma/seed-story.ts  # + 10 story servers + 14 story missions

# 3. Start the real server headless with the deterministic env.
#    DO NOT set NODE_ENV=production — that 403s the test routes; stay in dev.
TEST_API_KEY='ugt-test-key' \
  DATABASE_URL=$UGT_DB POSTGRES_PRISMA_URL=$UGT_DB POSTGRES_URL_NON_POOLING=$UGT_DB POSTGRES_URL=$UGT_DB \
  AI_ENABLED=false AI_FILES_ENABLED=false AI_DIALOGUE_ENABLED=false \
  UGT_DETERMINISTIC=1 AUTH_SECRET=test-secret NEXTAUTH_SECRET=test-secret \
  npx next dev -p 3100 &

# 4. Verify the LISTEN PID on :3100 is YOUR next dev (stale-server lesson):
lsof -nP -iTCP:3100 -sTCP:LISTEN
#    then health-probe: a bootstrap must return a playerId.

# 5. From the UGT repo root (TEST_API_KEY must match the server's):
export TEST_API_KEY='ugt-test-key'
python3 integrations/nexus/spike_nexus.py          # 8/8 raw-HTTP protocol checks
python3 integrations/nexus/smoke_nexus_adapter.py  # 5/5 through the BaseAdapter contract
python3 integrations/nexus/verify_dod.py           # Phase-0 DoD: one full hack loop
```

The config's `engine.api_key` is `null` so it falls back to the `TEST_API_KEY`
env var (the key is not committed).

## Test ladder (test → fix upstream → re-test)

| Round | Script(s) | Gate |
|---|---|---|
| P0 | `spike_nexus.py` · `smoke_nexus_adapter.py` · `verify_dod.py` | **PASSED (2026-07-08): spike 8/8, smoke 5/5, DoD 7/7** against the live server. Bring-up validated end-to-end; UGT drives a real hack loop (scan → connect → exploit → compromise) through the adapter. Surfaced + fixed **NX-P0-1** (R0 tutorial-gate blocker). |
| R1 | `verify_round1.py` · `invariants.py` | **PASSED (2026-07-09): 25/25** live (spike 8/8). One full `the_breadcrumb` loop through the real handler — `help/status/missions/clues` → refuse garbage → `accept` → `scan` → `connect` → refuse `exploit sql_injection` → `exploit weak_password` (seeded roll) → `crack` (seeded password) → `cat` (mission completes) → refuse re-accept → `progress`. Rewards land EXACTLY once (credits +1000, xp Σgain+250, underground +5, both flags); every refusal game-state inert (rngCounter excluded, NX-OBS-1); per-command invariant sweep clean across BOTH runs; same-seed replay byte-identical + non-vacuous; 8-seed variance sweep varies. Surfaced + fixed **NX-R1-1** (seed dropped canonical mission ids) and **NX-R1-2** (missions with a skipped optional objective completed SILENTLY). |
| R2 | `verify_round2.py` · `invariants.py` | **PASSED (2026-07-09): 36/36** live (spike 8/8). UGT drove the FULL 8-mission story spine (the_breadcrumb → following_the_money → project_meridian → dead_drop → into_the_syndicate → the_other → the_architect → point_of_no_return) to a REAL win through the adapter — `gameStatus.isComplete`, `ending "ending_liberation"`, 8/8 story missions — under **all three difficulty modes** (normal/tutorial/hardcore). Per mission: status completed, reward flags present, credits delta + xp residual (xpΔ − Σ command xpGain) == core-story.json rewards. Rewards land EXACTLY once (re-accept a completed mission → refused + game-state inert). Per-command invariant sweep CLEAN across every command of every mode (failed-hack retries success:false + inert). **XP scaling:** first `cat work_vpn.txt` (base 5) returns round(5·mult) == tutorial 4 / normal 5 / hardcore 8, while mission-reward xp AND credits are mode-INVARIANT (250 / 1000 constant across modes). Same-seed determinism over the non-vacuous M1-M4 prefix is byte-identical (commands + CommandResults + rngCounter + normalized final state; transcript carries a `[Success Rate:` roll AND the seeded `met_sp3ctr3` delivery). Hardcore ~30% odds → the retry-to-success loop earned its keep (a failed-then-retried hack observed). Surfaced + fixed **NX-R2-1** (`talk` could never unlock) and **NX-R2-2** (`talk` refused with AI disabled → `contact_npc` unfireable). |
| R3 | `verify_round3.py` · `invariants.py` | **PASSED (2026-07-09): 9/9** live (spike 8/8). UGT's REAL `ExploitHunter` (`ugt/core/exploit_hunter.py`, unchanged) drove **4 seeded episodes x 90 steps = 360 real steps** through the live handler under a phase-aware heuristic + refusal-probing policy over the whole 20-action vocabulary (args composed from OBSERVED state — discovered servers, analyzed vulns, listed files, live missions, met NPCs). **ZERO findings:** all 7 R1/R2 per-command invariants (wrapped to the hunter's `(before, action_id, info, after, ctx)` signature) PLUS 2 R3-only stateful invariants (completed-story-missions monotonic; no 25-in-a-row soft-lock) held on EVERY step — including under the 8 deliberate refusal probes (ungated/bad-vuln hacks, undiscovered connect, early choose, re-accept-completed, cat-missing-file, an intentionally-unmapped action id `action_18`, and a garbage token), each refused AND game-state inert. Every mapped action id was attempted (full coverage), the walk made real progress (7 server-compromises, 30 seeded rolls, a story mission completed in every episode), and a **fresh same-seed re-run of episode 0 replays byte-identically** (command stream + CommandResult stream + rngCounter progression + normalized per-step player-state, 90/90 steps) and is non-vacuous (≥1 seeded roll). No game defect surfaced → no upstream fix; game suite unchanged (unit 1265 / integration 173). **NEXUS trial ladder COMPLETE.** |

## Findings registry

- **NX-R3 (round result) — CLEAN (2026-07-09).** *No game defect.* The
  `ExploitHunter` robustness walk (4x90 real steps, 9 invariants/step, 8 refusal
  probe kinds) surfaced **zero** invariant violations / crashes / soft-locks /
  statistical anomalies against the live handler, so there was nothing to fix
  upstream — the game repo is untouched by R3. Two issues were caught and fixed
  **in the harness** (`verify_round3.py`), NOT the game: (1) the available-mission
  parser first captured the trailing quote from `Use 'accept <id>' to start`
  (sending `accept the_breadcrumb'` → every accept refused → an accept-loop that
  correctly tripped the `no_soft_lock` invariant); tightened the regex to stop at
  the closing quote. (2) A purely uniform connect/cat almost never aligns with a
  mission's one specific server+file inside a short episode, so the policy now
  leans on the known spine targets (the same test-side game knowledge R1/R2 use)
  as its progress heuristic while keeping 15% refusal probes + 10% uniform
  exploration + stochastic vuln/file fallbacks + the unmapped/garbage ids — with
  a guaranteed-legal back-off after a run of failures (a real player retreats to
  info commands; a genuine game soft-lock would still surface because those would
  also fail). The `no_soft_lock` invariant remains fully armed at 25.
- **NX-R3-OBS (coverage characterization, not a defect).** Verified independently
  that R3 is a genuine robustness walk, not "R2 with probes": R2's *scripted* spine
  wins all 8 missions, but R3 plateaus at exactly **1/8 story missions in every
  4×90 episode** — stochasticity dominates (cat+ls alone are 217/360 steps, 20
  distinct verbs, all 8 probe kinds fire). The honest limitation: because the walk
  rarely gets past mission 1, the deeper directed legs — `crack` mission legs and
  the **success** paths of `talk`/`choose` (`the_other`/`the_architect`/
  `point_of_no_return`) — are exercised here only in their **refused** form; their
  success paths are covered by **R2**, not re-covered by R3. This does not weaken
  the R3 gate (breadth + refusals + all-invariants-every-step + byte-identical
  replay). To strengthen later: longer episodes or a mid-spine seeded reset would
  let the directed machinery drive the mid/late-game legs under the random walk.
- **NX-R2-1 (game fix) — FIXED & VERIFIED LIVE (2026-07-09).** *Severity: high
  (story unwinnable over the real command surface).* **Live observation:** with
  BOTH `met_sp3ctr3` and `met_axiom` present in the player's flags, `talk sp3ctr3`
  still returned `{success:false, error:"Unknown command", "Command not found:
  talk"}` — the verb never unlocked, so the two `contact_npc` missions (`the_other`,
  `the_architect`) could never complete and the 8-mission spine was unwinnable.
  **Root cause:** `src/lib/commands/registry.ts` gated `talk` with a SINGLE
  unlock path AND-ing `["met_sp3ctr3", "met_axiom", "met_mercury"]`
  (`unlock-checker.ts`: AND within a path, OR across paths). `met_mercury` is
  granted only on delivery of the MERCURY message, whose trigger `bureau_aware` is
  a DEAD trigger — no command, cat, or reward ever grants it — so the AND-path
  could never be satisfied. The `full-story-winnable` integration test only passed
  because it seeds `ALL_COMMANDS` into `unlockedCommands` (an explicit bypass in
  `checkCommandUnlock`), masking the dead gate. **Fix (nexus `main`):** rewrote
  `talk.unlockRequirements` to OR-logic across the REACHABLE met flags —
  `paths: [{flags:["met_sp3ctr3"]}, {flags:["met_axiom"]}, {flags:["met_elena_cross"]}]`
  — so meeting ANY surfaced NPC unlocks the verb; the authoritative per-NPC gate
  stays in the executor (`talkCommand`'s `met_<npc>` check), so an unlocked `talk`
  still refuses `talk e.cross` until Elena Cross is actually met. **Pinning test:**
  `tests/unit/commands/unlock-checker.test.ts` (describe "talk command unlock
  (NX-R2-1)": locked with no met flag; unlocks on `met_sp3ctr3` / `met_axiom` /
  `met_elena_cross` alone; regression guard that `met_mercury` is NOT required and
  `met_sp3ctr3`+`met_axiom` unlocks).
- **NX-R2-2 (game fix) — FIXED & VERIFIED LIVE (2026-07-09).** *Severity: high
  (story unwinnable in the deterministic / AI-off env).* **Live observation:**
  after NX-R2-1, `talk sp3ctr3` passed the unlock + met gates but returned
  `{success:false, error:"AI dialogue disabled", "AI dialogue is currently
  disabled."}` — so `contact_npc` never fired and `the_other`/`the_architect`
  never completed. **Root cause:**
  `src/lib/commands/executors-narrative.ts::talkCommand` required
  `AI_ENABLED && AI_DIALOGUE_ENABLED` and short-circuited to a failure BEFORE
  emitting `ObjectiveEvents.contactNpc`. The bridge / replay env runs AI OFF by
  design (`AI_*=false`, `UGT_DETERMINISTIC=1`), and the winnable test only worked
  because it set `AI_ENABLED=true` and MOCKED `generateNPCDialogue` — neither of
  which exists over the real HTTP surface. The objective is to CONTACT the NPC,
  not to obtain an AI-authored reply. **Fix (nexus `main`, AI-off-preserving):**
  when AI dialogue is disabled, `talk` now delivers the NPC's canonical SCRIPTED
  lines (`npc.messages[0].lines`) and STILL emits `contact_npc` so the objective
  completes deterministically, with `xpGain:5` parity. The met-gate above still
  enforces WHO may be talked to; no live AI model is required. **Pinning test:**
  `tests/unit/commands/executors-narrative.test.ts` (describe "talkCommand — AI
  disabled delivers scripted dialogue (NX-R2-2)": with `AI_ENABLED=false`, `talk
  sp3ctr3` succeeds with canned lines + `xpGain 5`, and `mission.updateObjective`
  is called to complete the `contact_npc` objective — replaced the old test that
  asserted the now-removed failure behavior).
- **NX-R1-1 (game fix) — FIXED & VERIFIED LIVE (2026-07-09).** *Severity:
  medium.* **Live observation:** `accept the_breadcrumb` (the canonical stable
  mission id used by mission prereqs, objective events, the loader, and the
  game's own `full-story-winnable` test) returned
  `{success:false, error:"Mission with ID the_breadcrumb not found"}`; the
  `missions` command instead quoted `accept <cuid>`. No mission could be
  accepted by its canonical id, so the R1 loop (and every downstream check)
  failed. **Root cause:** `prisma/seed-story.ts::storyMissionToPrismaInput`
  built the Prisma create input WITHOUT the `id` field, so `Mission.id` fell
  back to `@default(cuid())` — the canonical string id (`the_breadcrumb`) was
  discarded at seed time. `acceptMission` looks a mission up by
  `Mission.findUnique({ where: { id } })`, so only the random per-seed cuid
  resolved. This also made seeded mission ids non-deterministic across
  re-seeds and diverged from the intended contract (`full-story-winnable`
  seeds `id: m.id`). **Fix (nexus `main`):** extracted the mapper to
  `src/lib/narrative/story-mission-seed.ts` (importable + side-effect-free) and
  set `id: mission.id`; `seed-story.ts` now imports it. **Pinning test:**
  `tests/unit/narrative/story-mission-seed.test.ts` (2 cases: every story
  mission's canonical id is preserved and is never a cuid; `the_breadcrumb`
  maps to its canonical id with core fields intact).
- **NX-R1-2 (game fix) — FIXED & VERIFIED LIVE (2026-07-09).** *Severity:
  medium (player-facing feedback).* **Live observation:** completing
  `the_breadcrumb` (via `cat` of the VPN file) auto-completed the mission and
  granted its rewards (player-state showed `status:completed`, credits +1000,
  xp +250, underground +5), but the `cat` output showed only
  `"[✓] Objective completed! (1 objective)"` — never the `"MISSION COMPLETED!"`
  banner or the reward summary. The mission completed SILENTLY. **Root cause:**
  `src/lib/missions/objective-tracker.ts::checkMissionObjectives` decided
  `missionCompleted` by comparing `getProgress().objectiveStats.completed ===
  total`, which counts OPTIONAL objectives. `the_breadcrumb` has 2 required + 1
  optional objective; after the 2 required were done `completed(2) !==
  total(3)`, so it reported `missionCompleted:false` — even though the
  authoritative `mission.updateObjective` had already auto-completed the mission
  on REQUIRED objectives only (mission.ts: `requiredObjectives.every(...)`) and
  granted rewards. Any mission whose optional objective is skipped completes
  with no completion feedback — including the game's very first story mission.
  **Fix (nexus `main`):** `checkMissionObjectives` now trusts the status
  returned by `updateObjective` (`updatedMission.status === "completed"`) rather
  than re-deriving completion (and drops the redundant `getProgress`
  round-trip). **Pinning test:** `tests/integration/missions/objective-tracker.test.ts`
  new case "reports missionCompleted when the last REQUIRED objective finishes
  and an optional one is skipped (NX-R1-2)" (required done + optional skipped →
  `missionCompleted:true` + rewards + `"MISSION COMPLETED!"`); existing mocks
  updated to return the authoritative `status` the real router returns.
- **NX-P0-1 (tooling/game fix) — FIXED & VERIFIED LIVE (2026-07-08).** The
  `reset-episode` route only had a **fresh** baseline (level 1, empty
  `storyFlags`/`unlockedCommands`), which leaves the entire hacking surface
  (`scan`/`connect`/`exploit`/`crack`/`cat`) **locked behind the tutorial gate**
  — and the `closed-alpha` command path never grants those flags, so a
  black-box driver could reach the server but not play it (every command comes
  back `"Command not found"`). Confirmed live: a `fresh` reset then `scan` →
  `{success:false, "Command not found: scan"}`. Fix (dual-validation, game
  side, branch `fix/code-review-2026-07`): `reset-episode` now accepts an
  optional `baseline: "post_tutorial"` that seeds a just-past-tutorial player —
  `storyFlags:[tutorial_complete]` (column **and** narrative blob), the
  tutorial-granted `unlockedCommands` affordance, the story-server IPs marked
  discovered, and level 5 with `xp:4000` seeded coherently so the level survives
  `applyCommandRewards`' recompute (`floor(xp/1000)+1`). The adapter resets with
  `baseline:"post_tutorial"` by default (configurable via `engine.baseline`).
  Pinned by the game's own `tests/integration/api/reset-episode.test.ts` (3 new
  cases: fresh leaves `scan` locked → the R0 repro; `post_tutorial` seeds the
  row + unlocks `scan` → drives connect→exploit through the real handler).
- **NX-OBS-1 (observation, by design — not a defect).** A **rejected** command
  (unknown/garbage) still advances `rngCounter` by 1. This is intentional in
  NEXUS: `executeCommand` ticks the per-command RNG cursor **unconditionally,
  before command lookup**, so replays are position-stable and a retried failed
  roll re-rolls rather than repeating (`handler.ts` W7-2 comment). Recorded so a
  future invariant author expects the tick on refusals rather than flagging it.
- **NX-OBS-2 (characterization).** `exploit`'s success roll is genuinely seeded
  (same seed → byte-identical output; 16-seed sweep varies OK/FAIL). At the P0
  baseline (level 5 vs `neighbor_pc` securityLevel 2) the rate is ~90%, so any
  two arbitrary seeds usually land the same outcome — expected, not an
  unseeded-RNG bug. Verified empirically: 23 success / 1 fail over 24 distinct
  seeds.

Game-side baseline: `apps/game`'s own gates stay green after the R2 fixes —
typecheck clean, lint 0 errors, **unit 1265/1265** (+6 vs R1: 5 NX-R2-1 talk-unlock
pins + net 1 for the reworked NX-R2-2 AI-disabled talk test), **integration
173/173**, 0 skipped.

Action ids in `ugt.config.yaml` must stay in lockstep with
`NexusHttpAdapter._compose_command` (R3 extended the vocabulary 14 → 20:
`talk`/`choose`/`disconnect`/`whoami` + an intentionally-unmapped `action_18`
and a `garbage` token; ids 0–13 are frozen). The base adapter holds only simple
defaults for the new verbs — all state-driven/probe/objective-directed arg
composition lives in `verify_round3.py::R3NexusAdapter`, never the base.
