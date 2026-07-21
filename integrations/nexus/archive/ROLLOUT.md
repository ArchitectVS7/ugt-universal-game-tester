# NEXUS — UGT Bridge Rollout Plan

Bridge for driving the **real** `nexus-world-builder` game (Next.js 16 + tRPC + Prisma,
single-player terminal hacking sim, app at `../nexus-world-builder/apps/game`) with UGT's
exploit-hunter tier over HTTP. Mirrors the tarot-war / warzones ladder
(`integrations/tarot-war/README.md`): **test → surface findings live → fix UPSTREAM in the
game → re-test → registry**. Drive the REAL running game, never a re-implementation
(the retired `sim_bridge.ts` lesson).

Status: **not started.** This is the plan to start it.

---

## Head start (what the fix branch already delivered)

The game is on branch `fix/code-review-2026-07` (26 commits ahead of main, pushed to
`origin`; **do not merge to main until the user says**). That branch already closed the two
hardest bridge prerequisites, so R2/R3 are reachable on day one:

- **Winnable end-to-end (A1).** All 8 story missions complete; `full-story-winnable.test.ts`
  drives the real command handler `cat/talk/exploit/crack/connect/choose` to
  `checkWinCondition.isComplete` + `ending_liberation`. This is R2's target, already proven
  in-process.
- **Byte-identical same-seed replay (A2).** NPC delivery is counter-based, output/blob are
  wall-clock-free, the RNG seam fails loud under `UGT_DETERMINISTIC=1`. Contract:
  `../nexus-world-builder/docs/REPLAY-CONTRACT.md`. This is R3's replay gate, spec'd and
  unit-proven (`deterministic-hack-rng.test.ts`).
- **Entry point exists.** `POST /api/test/closed-alpha` — `{ playerId, command }` +
  `X-Test-API-Key` → `CommandResult`. Prod-blocked, API-key-gated.
- **Player bootstrap exists.** `POST /api/test/bootstrap-player` → `{ id }` (creates a player,
  difficulty `normal`).
- **Concurrency/security hardened (A3–A7):** no rngSeed leak, no double-reward, no lost-update,
  fail-closed guards with genuine fail-closed tests. The bridge can rapid-fire safely.

Suite baseline on the branch: unit 1257, integration 147 (0 skip), typecheck + lint clean.

---

## Architecture

`engine.type: real_server` (config parser already supports it; uses `base_url`, no sim entry).
Nexus is simpler than SpacerQuest — no Socket.IO screens, just one HTTP POST per command — so
it needs a **new thin adapter**, not the SpacerQuest `RealClientAdapter`.

- **Transport:** `NexusHttpAdapter(BaseAdapter)` (new, in `integrations/nexus/` or
  `ugt/adapters/nexus_http.py`). A "step" = POST one command string to `/api/test/closed-alpha`.
  - `connect()` — health-check the base URL; **lsof the LISTEN PID and confirm it's the server
    you started** (the stale-server lesson: a squatting old server returns 200 against OLD code).
  - `reset(seed)` — reset the episode's player to a known baseline per REPLAY-CONTRACT (see
    Phase-0 gap #1).
  - `step(action_id)` / `type_text(cmd)` — send a command, return `(state, terminated, truncated,
    info)`; `get_terminal_text()` returns the `CommandResult.output`.
  - Action space = the command vocabulary (`scan`, `connect <ip>`, `exploit <vuln>`,
    `crack <file>`, `cat <path>`, `talk <npc>`, `download`, `backdoor`, `escalate`, `choose <path>`,
    `missions`, `accept`, `status`, `clues`, `contacts`, `help`, …). A heuristic policy composes
    argument values from observed state (discovered IPs, current server files) — never hardcoded.
- **State read (for invariants):** there is **no read endpoint today** — Phase-0 gap #2. The
  bridge needs player state (credits, xp, level, difficulty, storyFlags union, mission statuses,
  gameState blob, compromisedServers, `isComplete`/`ending`, `rngCounter`) to assert invariants.
  Choose one: (a) a new read-only `GET /api/test/player-state` (preferred — black-box faithful,
  mirrors the SpacerQuest `/api/character` extension), or (b) direct Prisma reads from the bridge
  using `DATABASE_URL`. Prefer (a) so invariants test what a client can observe.
- **Determinism:** the REPLAY-CONTRACT is the seeded seam — already built. Per episode the driver
  sets `Player.rngSeed` (fixed constant) + `rngCounter` (0), resets gameplay state, and runs with
  `AI_ENABLED=AI_FILES_ENABLED=AI_DIALOGUE_ENABLED=false` and `UGT_DETERMINISTIC=1`, commands
  strictly sequential, excluding the documented timestamp columns from any state diff.

---

## Phase 0 — infra, game-side test endpoints, adapter, spike (BEFORE R1)

Deliverables (game side, on the `fix/code-review-2026-07` branch — these ARE dual-validation
game fixes, commit them there):

1. **Deterministic episode reset.** Extend `bootstrap-player` (or add
   `POST /api/test/reset-episode`) to accept a `seed` and set `rngSeed` to a fixed constant +
   `rngCounter: 0` + reset the gameplay state to a known baseline (per REPLAY-CONTRACT §"per
   episode"). Today bootstrap leaves `rngSeed` at the DB-generated default → not replay-stable.
2. **Read-only state endpoint** `GET /api/test/player-state?playerId=…` (API-key-gated,
   prod-blocked) returning the invariant surface listed above. Reuse `mission.getGameStatus`
   for `isComplete`/`ending` and the flag-union logic (A3/W7-1) for storyFlags.

Deliverables (UGT side, `integrations/nexus/`):

3. **`NexusHttpAdapter`** implementing `BaseAdapter`.
4. **`spike_nexus.py`** — protocol spike: bootstrap a player, POST ~6 commands
   (`help`, `scan`, `connect`, `cat`, a hack), assert each returns a well-formed `CommandResult`;
   confirm reset pins the seed (two resets → identical first-roll). ~7 checks, like
   SpacerQuest's `spike_realclient.py`.
5. **`smoke_nexus_adapter.py`** — 5 random real actions through the `BaseAdapter` contract
   (`connect`/`reset`/`step`/`close`), wiring check.
6. **`verify_dod.py`** — definition-of-done: one full hack loop end-to-end via the adapter
   (bootstrap → scan → connect → crack/exploit a first server → cat a file → an objective
   completes), asserting the state-read reflects it.
7. **`ugt.config.yaml`** — `engine.type: real_server`, `base_url`, `action_space.actions`
   (command vocabulary), `observation_space.mappings` (paths into the state-read JSON), and the
   invariant set. (Exploit-hunter has no config-driven CLI path yet, so R1–R3 are standalone
   scripts that build a minimal `_Cfg` shim + `NexusHttpAdapter` directly — mirror tarot-war.)

Phase-0 gate: spike 7/7, smoke green, DoD one clean hack loop.

---

## The ladder (each: standalone `verify_roundN.py`, gate = N/N, findings fixed upstream)

### R1 — one full playable loop + determinism
`verify_round1.py [seed]`. Seeded reset → the real first-mission slice through the handler:
`accept` the_breadcrumb → `exploit` its server (IP-targeted, A1's fix) → `cat` the target file →
objective completes → mission auto-completes + rewards granted once. Plus: info/UI commands
accessible (`help`, `status`, `missions`, `clues`), same-seed determinism (two seeded runs →
identical `CommandResult.output` + identical `rngCounter` progression + identical state-read),
and a short invariant pass after every command. **Gate: all checks pass; surfaced findings fixed
upstream and re-tested.**

### R2 — multi-mission progression to a win, all modes, under invariants
`verify_round2.py [base_seed]`. Drive the **full 8-mission story spine to
`isComplete`/`ending`** through the real commands (the `full-story-winnable` path, but over
HTTP through the adapter, not in-process) — including `talk` after counter-based NPC delivery,
the Foundation-server leg, and `choose`. Run all three difficulty modes (tutorial/normal/hardcore
— exercises A5/W7-7 XP scaling). Per-command invariants after every step (list below). Same-seed
determinism over a multi-mission prefix. **Gate: a real win is reproduced; invariants hold every
step; findings fixed upstream.**

### R3 — exploit-hunter tier, seeded episodes, zero findings, byte-identical replay
`verify_round3.py [base_seed]`. UGT's real `ExploitHunter` (`ugt/core/exploit_hunter.py`):
N seeded episodes (e.g. 3 × 300–400 steps), a phase-aware heuristic policy over the command
vocabulary that composes real arguments from observed state and deliberately probes refusal
paths (hack an undiscovered/ungated server, `choose` before the climax, unmapped/garbage
commands), **all invariants checked after every step**, target **zero findings**, and a
**same-seed byte-identical replay** of one episode (per REPLAY-CONTRACT: identical
`CommandResult` stream + identical state-read modulo the excluded timestamp columns).
**Gate: zero findings across all episodes + byte-identical replay — TRIAL LADDER COMPLETE.**

### Invariant set (assert after every command; a violation is DATA → a finding)
- No crash: every command returns a well-formed `CommandResult` (never a 500).
- No negative resources: `credits >= 0`, `xp >= 0`, `level >= 1`.
- Monotonic where required: `xp` non-decreasing; `rngCounter` increases by exactly 1 per command
  (the A2a/A3 clock — a strong replay canary).
- Story flags append-only (never lose a flag); mission status transitions legal
  (active→completed/failed only; no completed→active).
- No double-reward: completing a mission grants its rewards exactly once (A3/A4 territory —
  detect via xp/credits deltas).
- No soft-lock: from any reachable state the player can still make progress (some command changes
  state); a win remains reachable on the intended path.
- Refused actions inert: a rejected command (gated server, wrong phase, bad arg) leaves state
  unchanged and never advances progress.
- Determinism: same seed + same command sequence → identical outputs + state (the R3 replay).

---

## Findings discipline (the point of the exercise)
Every invariant violation / crash / statistical anomaly is a **finding**, recorded in
`integrations/nexus/README.md` (mirror tarot-war's registry: id, severity, live observation,
root cause, upstream fix + the pinning test). Fix in the **game** (on the branch), add a
pinning test to the game's suite, re-run the round. "A failed check is data, not noise."
Expect to pause and fix the game mid-ladder — that's dual validation working.

---

## Ops / infra

Start the real game against a dedicated UGT Postgres, headless, with the deterministic env:

```bash
# 1. Postgres for the bridge (embedded via the game's test harness, or a docker instance)
# 2. Push schema + seed missions/story-servers into it (prisma db push + the seed scripts)
# 3. Start the Next.js server (from ../nexus-world-builder/apps/game):
NODE_ENV=test PORT=<p> \
  DATABASE_URL='postgresql://…/nexus_ugt' TEST_API_KEY='<key>' \
  AI_ENABLED=false AI_FILES_ENABLED=false AI_DIALOGUE_ENABLED=false \
  UGT_DETERMINISTIC=1 \
  npm run start   # (or `next dev` — confirm the closed-alpha route is reachable)

# 4. VERIFY THE LISTEN PID IS YOUR SERVER (stale-server lesson):
lsof -nP -iTCP:<p> -sTCP:LISTEN
# health 200 != your server — confirm the PID is the process you just launched.

# 5. From the UGT repo root, drive it:
python3 integrations/nexus/spike_nexus.py
python3 integrations/nexus/verify_dod.py
python3 integrations/nexus/verify_round1.py   # then round2, round3
```

---

## Open decisions to confirm before Phase 0
- State-read: new `GET /api/test/player-state` endpoint (preferred) vs. direct DB reads.
- Reset: extend `bootstrap-player` vs. a dedicated `reset-episode` route.
- Postgres: reuse the game's embedded-PG test harness for the bridge DB, or a standalone docker
  instance kept alive across a ladder run.
- These are the first things the Phase-0 planning stage settles.

## First three actions to start
1. Add the two game-side test endpoints (deterministic reset + state read) on the branch, with
   pinning tests — Phase-0 gap #1 and #2.
2. Build `NexusHttpAdapter` + `spike_nexus.py`; get the spike to 7/7 against a locally-running
   server (PID-verified).
3. Write `verify_round1.py` and drive the first hack loop; open `integrations/nexus/README.md`
   with the findings registry and log whatever the first run surfaces.
