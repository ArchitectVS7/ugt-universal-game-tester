# UGT — Plan Forward (START HERE)

> **New session? Read this file, then the memory notes `architecture-pivot-real-server`,
> `combat-not-in-bridge`, and `rootcause-rl-collapse` (in that order).** This is the durable handover.
> Last updated 2026-07-04.

---

## The bigger picture (why any of this matters)

UGT is a **Universal Game Tester**. SpacerQuest is the *first* game we're wiring up, but **the methodology we
build here is the template we reuse for every future game.** So we optimize for a repeatable process, not a
one-off SpacerQuest hack. Three principles, learned the hard way this project:

1. **Play the game with the game.** The tester must drive the *real* running game, never a re-implementation of
   it. Our `sim_bridge.ts` slowly became a partial copy of SpacerQuest (it had **no combat at all**, and broken
   upgrades), so every RL agent we trained was learning a *different game*. A harness that reimplements the game
   is testing itself, not the game. This is the #1 reusable lesson.
2. **Dual validation.** We are validating two things at once: (a) that UGT *can* test/learn the game, and (b) the
   **game itself**. Expect to surface real game bugs. When we do, the right move is often to **pause testing,
   fix the game, and return** — that is a success of the process, not a detour.
3. **Failed tests are data.** The RL collapse, "combat isn't in the bridge," "trades reward motion not profit" —
   every one was a *negative* result that taught us something durable. Record findings (memory notes), don't
   just discard them. A test that fails informatively is worth more than a green checkmark that certifies the
   wrong thing.

---

## Where we are right now (2026-07-04)

Decision made and **de-risked with a working spike**: retire the reimplementing `sim_bridge.ts`; build an
adapter that drives the **real `spacerquest-web` server** (Socket.IO for auth/screens/combat, HTTP for
navigation + structured state). The spike proved the whole path works headless — auth, real screen loop, and
state read all round-trip. Details + exact commands: memory note `architecture-pivot-real-server`.

Everything below is the plan from here. The old bridge-based RL/Gate work is archived (`archive/`) — its one
surviving idea (cheap learnability check before scaling) lives on as methodology in the User Manual.

---

## THE FOUR NEXT STEPS — Phase 0: build the real-client adapter

These are the four concrete pieces that turn the validated spike into a reusable adapter. Do them in order.

> **STEP 0 DONE (2026-07-05):** the spike is reconstituted, committed, and hardened as a self-verifying file:
> `integrations/spacerquest/spike_realclient.py` (Python `RealClient` class, 7/7 checks, stable across runs).
> It proves the full path headlessly: `dev-login → JWT`, `dev-setup-character` (episode reset), Socket.IO
> `authenticate`, `screen:request`/`screen:input`, **real navigation** (main-menu→shipyard), and
> `GET /api/character`. **Verified protocol facts to carry into step 1** (these bit us in the spike):
> - Screen ids are **lowercase-kebab** (`main-menu`, `shipyard`); an unknown id **silently falls back to
>   `main-menu`** server-side — a typo won't error, it'll mislead.
> - `screen:request` emits **TWO identical** `{output}` renders (dedupe/settle: take the last).
> - A menu key does **not** return content — `screen:input` returns `{output:'\x1b[2J\x1b[H', nextScreen:'<id>'}`;
>   you must then `screen:request` that `nextScreen`. (In-place keys like `X` return content + `>` prompt, no nextScreen.)
> - Bootstrap is DB-surgery-free: `GET /auth/dev-login` (302 → `/?token=…`, creates a user if none) → mints the JWT;
>   `POST /auth/dev-setup-character` (Bearer) is the clean reset. JWT payload is `{userId}`.
> - ~~Env caveat: raise `ENCOUNTER_CHANCE`~~ **CORRECTED 2026-07-05:** `ENCOUNTER_CHANCE` is **dead config** — no code
>   reads it. `generateEncounter()` is deterministic (every trip spawns an encounter, gated ONLY by `NpcRoster`
>   seeding, which IS populated: PIRATE/PATROL/RIM_PIRATE/etc.). So combat already fires on the real server. `.env.ugt`
>   annotated to say so. `websocket-client` now installed (real WS transport; declared in setup.py `[realclient]` extra).

1. ~~**Reusable real-client module.**~~ ✅ **DONE (2026-07-05).** `ugt/adapters/realclient.py` —
   `RealClientAdapter(BaseAdapter)`: optional server lifecycle (spawn/attach) + Socket.IO/HTTP client +
   `screen:request`/`screen:input`/`press_menu_key` + `press_key`/`type_text`/`get_terminal_text`. Registered in
   `env.py` under new `engine.type: "real_server"` (validator + `engine_entry` made optional for it). Verified by
   `integrations/spacerquest/smoke_realclient_adapter.py` (7/7, through the BaseAdapter contract). No game logic
   in the adapter — that's the point.
2. ~~**Per-episode reset.**~~ ✅ **DONE.** `reset()` calls `POST /auth/dev-setup-character` and lands on `main-menu`;
   verified it returns the dev-setup baseline (100k cr, LIEUTENANT, fuel 800, system 1). No DB surgery.
3. ~~**Action map.**~~ ✅ **DONE (2026-07-05).** `RealClientAdapter.ACTION_HANDLERS` covers the training subset
   `[4,6,2,7,8,14,10,11,16,17]`, all mapped to real screens/HTTP (unmapped ids still raise by design). Verified
   protocol (mapped empirically against the live server):
   - accept_cargo: `T`→traders `A`→traders-cargo→`1`→`Y` (sets cargoPods/destination/payment).
   - navigate_cargo_dest: HTTP `POST /api/navigation/launch{destinationSystemId}` + `POST /api/navigation/arrive`
     (same arrive-over-HTTP the real frontend does). **Delivery is AUTOMATIC on arrival** (credits += payment).
   - **combat: the `'combat'` SCREEN via `screen_input('combat', 'A'|'R'|'S')`** — NOT the socket `combat:action`
     (that handler is stateless and never resolves — a dead/buggy path; see finding in memory note).
   - buy_fuel: `T`→`B`→type units. upgrades: `S`→`U`→component key (weapons=5, shields=8). end_turn: `D`
     (CLASSIC_MODE → "wait for next day" no-op).
4. ~~**Observation.**~~ ✅ **DONE (2026-07-05, cleanup).** `_read_state()` parses `/api/character` (char + ship in one
   call) into every config obs path — **no hardcoded values.** The blind fields (`is_conqueror`, `is_lost`,
   `in_combat`, `bank_balance`, plus bonus `in_jail`) were previously stubbed to 0; we **extended the game's
   `/api/character`** to expose the real state (win/lost/bank/jail flags + active-combat query) rather than let the
   tester lie. This was the **first dual-validation finding+fix**: SpacerQuest's read API didn't surface win-state to
   a black-box tester. Verified real via `smoke_realclient_adapter.py` (8/8); game typechecks clean (0 tsc errors).

**Definition of done for Phase 0:** ✅ **MET (2026-07-05).** `integrations/spacerquest/verify_dod.py` drives the
live server entirely through `RealClientAdapter.step(action_id)` — resets, steps every subset action, reads state,
and re-drives the **trade loop** (accept→navigate→auto-deliver, credits up) AND a **real combat encounter**
(resolves in <15 attacks, no soft-lock) end-to-end. **13/13 checks.** Regression: spike 7/7, smoke 8/8.

**Findings (as of Phase 1 exploit-hunter, 2026-07-05):**
- ~~battlesWon AND battlesLost both increment in one encounter (accounting bug)~~ **RETRACTED — NOT A BUG.** Focused
  repro (12 base-ship trips → 12 single losses; 1 upgraded trip → 1 clean win) shows each encounter records exactly
  one outcome. The "won=2/lost=2" was a **cumulative-counter misread**: `dev-setup-character` does NOT reset
  `battlesWon`/`battlesLost` (only `patrolBattlesWon/Lost`), so they accumulate across episodes, and one trip can
  chain multiple encounters. Lesson recorded in `[[feedback-intent-over-plan-no-defer]]`: investigate before *confirming*, not just before dismissing.
- **Minor real finding:** `dev-setup-character` leaves `battlesWon`/`battlesLost` uncleared → episodes aren't fully
  isolated on those counters (exploit-hunter uses deltas, so unaffected; would matter for absolute-value analysis).
- **Latent:** the socket `combat:action` handler (`sockets/game.ts:91`) is stateless (never persists/resolves) —
  the real client uses the combat SCREEN, so it's a dead/buggy path, not player-facing. Code-confirmed.

---

## Phase 0 is COMPLETE. Next: Phase 1 (RL/random exploit-hunter) — see the two-tiers section below.

---

## After the adapter — the two tiers (user chose "both, in sequence")

- **Phase 1 — RL/random EXPLOIT-HUNTER (robustness).** Drive random/curiosity-driven *real* inputs + assert
  invariants (no negative fuel, no stuck screens, no dupes, no crash, no soft-lock). Cheap, needs **no reward
  engineering** — this is what RL is actually good at here. Answers *"does the game break?"*
- **Phase 2 — LLM BALANCE playtester.** LLM reads the real terminal, presses keys like a player, plays
  competently, N runs with confidence intervals. Answers *"is the game good/balanced/beatable?"* Slower but
  competent — and for balance, competence beats volume (RL never achieved competent play here). The existing
  `AGENT-PLAYTEST-FRAMEWORK.md` is the design spec for this tier (transport is now the real client, not the bridge).

**Reward-design insight to carry into any agent:** reward realized **profit** (net credits), not raw activity
(trip_count); profiles differ by reward **weights**, not by hiding actions.

---

## How to resume (concrete)

```bash
# 1. Infra (Docker Desktop must be running)
open -a Docker
cd "SpacerQuest/spacerquest-web" && docker compose up -d db redis   # Postgres :5454, Redis :6380

# 2. Start the real game server headless (against the UGT DB)
NODE_ENV=test PORT=3005 \
  DATABASE_URL='postgresql://spacerquest:spacerquest@localhost:5454/spacerquest_ugt' \
  JWT_SECRET='<from .env.ugt>' REDIS_URL='redis://localhost:6380' UGT_TRAINING=1 \
  npx tsx src/app/index.ts
# → listens on http://127.0.0.1:3005 ; Socket.IO on the default path
```
A minimal working spike client (auth + screen loop + `/api/character`) is documented in the
`architecture-pivot-real-server` memory note — use it as the seed for step 1 above.

---

## Key references

| Thing | Where |
|---|---|
| Current direction + protocol + spike | memory `architecture-pivot-real-server` |
| Why we pivoted (combat missing) | memory `combat-not-in-bridge` |
| RL collapse root cause + Gate-1 history | memory `rootcause-rl-collapse` |
| Accurate critical review of UGT | `ASSESSMENT-AND-FIX-ROADMAP.md` |
| LLM playtest design spec (Phase 2) | `AGENT-PLAYTEST-FRAMEWORK.md` |
| Onboard a new game + methodology | `UGT-USER-MANUAL.md` |
| Real game routes (nav/arrive/combat) | `SpacerQuest/spacerquest-web/src/app/routes/`, `src/sockets/game.ts` |
| Retired bridge (do not extend) | `integrations/spacerquest/sim_bridge.ts` |
