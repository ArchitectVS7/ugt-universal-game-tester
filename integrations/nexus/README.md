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
| R2 | _todo_ | Full modes/paths: multi-server compromise chains, mission acceptance→progress→completion, difficulty variants, same-seed replay of a multi-command episode byte-identical. |
| R3 | _todo_ | UGT `ExploitHunter` tier: seeded stochastic policy (`NexusHttpAdapter.policy` stub is the seam), N-episode robustness run with invariants after every step (no negative resources, rngCounter +1/command, no crash/soft-lock, no stuck screen), deduped `Finding`/`HuntReport`. |

## Findings registry

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

Game-side baseline: `apps/game`'s own gates stay green after the NX-P0-1 change —
typecheck clean, lint 0 errors, **unit 1259/1259** (+2 story-mission-seed
NX-R1-1 pins), **integration 173/173** (+1 objective-tracker NX-R1-2 pin),
0 skipped.

Action ids in `ugt.config.yaml` must stay in lockstep with
`NexusHttpAdapter._compose_command`.
