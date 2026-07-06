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

**Phase 1 v1 status (2026-07-05):** exploit-hunter built (`ugt/core/exploit_hunter.py` +
`integrations/spacerquest/run_exploit_hunter.py`). Run: **5 episodes × 40 steps = 200 steps**, all 11 subset
actions exercised (accept 69 / navigate 22 / attack 34 / retreat 15 / buy_fuel 21 / upgrades 20 / …),
**0 invariant violations, 0 crashes.** The game is robust on the checked invariants under random+heuristic play.

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

## Phase 0 COMPLETE · Phase 1 COMPLETE · Phase 2 IN PROGRESS (2026-07-05)

**Phase 2 build is done and Gate-A-reviewed** (commit `ed9f290`): `ugt playtest` drives the real server
(`engine.type: real_server` branch in `playtester.py`), with `--runs N` aggregation (per-run baseline-delta
summaries + mean/std/95%-CI), config-driven prompts (`playtest.key_state_paths` — the framework layer now has
ZERO SpacerQuest-specific code), optional invariant injection (Phase-1 checks run alongside LLM play), adapter
current-screen tracking (free-form `press_key` works beyond main-menu), and new
`integrations/spacerquest/{ugt.realserver.config.yaml, run_llm_playtest.py}`. Strategy guide rewritten from
game source. Review process: parallel sub-agent board per gate (Gate A = UGT-intent + correctness review of
the diff; Gate B = methodology review of a real run; Gate C = balance verdict vs the game's documented intent
in `../SpacerQuest/PRD.md`/`User-Manual.md`/`constants.ts`).

**Findings (Phase 2 build, 2026-07-05):**
- **`end_turn` was a no-op in EVERY mode** — `_act_end_turn` sent `D` but never the `Y` confirm, so
  `executeEndTurn` (bot turns + tripCount reset) never ran. All Phase-0/1 runs silently never ended a turn.
  Fixed (adapter now drives the real confirm flow; verified live: trips 2→0, ~3s).
- **GAME BUG (fixed upstream, commit `c0f1b9fa` in spacerquest-web): nondeterministic user/character
  resolution.** `dev-login` used a bare `findFirst()` over ALL users; every route + the socket layer used
  unordered `findFirst({userId})`. With 57 stray test users/characters in the DB (old bridge-era runs), HTTP
  and socket sessions could bind DIFFERENT characters — observed live as battle counters "resetting" 41→0 and
  a 40-attack combat stall (attacks hit character A, `in_combat` read from character B). Fixed with
  oldest-first ordering + dev-setup now enforces one-character-per-user (+ clears `isConqueror`). Test DB
  purged to 1 user/1 character.
- **`DAILY_TRIP_LIMIT` env var is dead config** (like `ENCOUNTER_CHANCE`): the real limit is the hardcoded
  constant **2** in `constants.ts`; `.env.ugt`'s value 10 was never read. Annotated in `.env.ugt`.
- **A damaged ship is a turn-trap without repair:** losing a fight can zero hull condition → launch fails
  ("Ship too badly damaged") → can't complete the 2 trips → can't end_turn. Real players repair at the
  shipyard; `repair_ship` (S→R) is now a mapped action and in the strategy guide.
- **CLASSIC_MODE=true caps any playtest at 2 deliveries total** (end_turn always refused, day advances in
  real time only). Balance runs use `CLASSIC_MODE=false`.
- **Score pacing ground truth:** cargo delivery = **+2 score** (`docking.ts:244`), win at 10,000 → the
  Conqueror win is a ~5,000-delivery marathon BY DESIGN (BBS daily-turn game). Balance runs measure score
  VELOCITY and extrapolate; they do not expect a literal win.
- **Doc-vs-code discrepancy (game doc bug):** `User-Manual.md` Appendix A rank thresholds ≠
  `constants.ts RANK_THRESHOLDS` (code: 150/300/450/750/1200/1650/2250/2700; the manual self-flags as
  unverified). Report upstream; code treated as truth.
- Old `strategy-guide.md` was materially wrong for the real server (claimed 1k cr/fuel 50/hull 5 start, flat
  10k upgrades, ~50-200 score per delivery). Lesson: **source guides from game code, not memory.**

**Phase 2 MAIN CAMPAIGN (cell C) — 10 runs × 100 actions, claude-sonnet-5, 2026-07-05**
(`results/campaign-10x100-summary.json`; per-run `playtest-run-{i}.json`):
- **Robustness: perfect.** 1,000 LLM-chosen actions against the live server: 0 invariant violations, 0 crashes,
  0 early terminations, 0 episode resets. (Combined with Phase 1's 200 random steps: the game does not break.)
- **Score velocity: 18.4 ± 2.4 per 100 actions** (95% CI; 9 of 10 runs in 18–22). At +2/delivery this is
  ~9 deliveries per run. Extrapolated win (score 10,000): **~54,000 actions** — the Conqueror is a
  months-long marathon, consistent with the PRD's daily-turn BBS intent, unreachable in any single session.
- **Economy: profitable loop, high-variance capex.** credits_gain mean +14,640 but 95% CI [−11,500, +40,700]
  — CI includes 0. 8/10 runs positive (+6k to +44k); 2 runs deep negative (−87.6k, −28.0k) from aggressive
  upgrade spending (upgrade price scales (str/10+1)×10k, so chasing strength eats capital fast). Recurring
  loop economics (deliveries − fuel) are consistently positive; profitability at 100 actions hinges on
  upgrade discipline.
- **Combat: ship-investment check works as intended.** 35 wins / 1 loss across all runs after weapons/shields
  20; loot tiny (~70 cr) — combat is a fuel toll on trade, not an income source (matches original design).
- **Promotions: exactly 1/run** (COMMANDER honorarium at first end_turn — by construction of the score-148
  dev baseline; honorarium +20k is a significant chunk of run profit).
- LLM flagged 0 potential_bugs in 1,000 actions; the mechanical surprise-metric flagged ~34 steps/run for
  triage. Gate-C reviewers judge both.
- Cell D re-scoped: measured velocity makes a 600–800-action "win probe" pointless (arithmetic already
  answers it); replaced with a 1×300 ENDURANCE run (post-capex economy stability, velocity persistence).
- **Endurance (1×300, `results/endurance-1x300-report.json`):** credits +178,940 (+68k/+69k/+41k per
  100-action third) — the loop is strongly profitable at scale; score +53; 7W/0L; 20 retreats / 20 repairs /
  14 refuels (the survival loop works); **the LLM flagged the fuel-in-combat anomaly twice** (steps 94/203).

## GATE C VERDICT (2026-07-05) — sub-agent board: SpacerQuest-intent + methodology reviewers

**Balance verdict: the ECONOMY meets the game's documented design intent under competent play; the
PROGRESSION does not — and the gap traces to CONFIRMED rewrite deviations from the 1991 source, not to
design.** Robustness is exemplary: 0 invariant violations, 0 crashes, 0 soft-locks in 1,300 LLM actions +
200 Phase-1 random steps.

**Corrected statistics (methodology ruling):** the mean±CI headline was the wrong frame. Decomposed:
**trade-loop OPERATING profit = +71.6k mean / +77.5k median per 100 actions, 10/10 runs positive** (verified
per-run from state deltas; reconciles exactly). Net-of-capex median +33.8k. Upgrade purchases are a separate
strategy-variance line (40k–120k per run at LLM discretion). Run 3 excluded from the balance aggregate
(57/100 actions were silent no-ops — it measures a stall, not the economy; promoted to finding G1). Also:
the guaranteed +20k COMMANDER honorarium (dev baseline score 148) is LARGER than the raw mean credits_gain —
back it out and raw mean ≈ −5.4k; future campaigns should start the baseline mid-band (e.g. score 200) or
subtract it in analysis.

**Findings for the SpacerQuest developers (ranked, all with file:line evidence in the Gate-C reports):**
1. **CONFIRMED (high, progression): cargo-docking score dropped the original's distance (q6) and
   battles-won (wb) terms** — flat +2/delivery vs authentic `2 + distance + wins − losses`
   (`docking.ts:227-244`, comment literally says "regular=TBD"; `SP.DOCK1.txt:163-169`; `patrol.ts:197`
   already implements it correctly). Root cause of the ~54,000-action conquest extrapolation; restoring it
   returns pacing to the authentic months-scale order of magnitude.
2. **CONFIRMED (high, combat/economy): no fuel gate on attacking** — full-power attacks are FREE at
   fuel < weapons/2; fuel clamps at 0 (`screens/combat.ts:177-178`). The original made weapons
   "Malfunction!" (attack skipped, enemy still fires — `SP.FIGHT1.txt:308-310`). Not a soft-lock (retreat is
   always free) but an exploit + authenticity break. Found live by the LLM (endurance steps 94/203) and hit
   silently in campaign run 9 (4 no-op combat rounds at fuel 0).
3. **CONFIRMED (medium, economy): Roscoe's strength upgrade grants +10 for the original's per-+1 price**
   (`upgrades.ts:442` vs `SP.SPEED.txt:158-179`; contradicts its own comment at `upgrades.ts:10-15`; home-
   system discount omitted). Simultaneously 10× too generous vs the original and a mid-game capital trap vs
   the shipyard tier path (strength 90 for 10k flat). Explains the campaign's capex-crater runs.
4. **CONFIRMED (medium, near-soft-lock, root cause open): cargo contracts silently no-op in some state.**
   Campaign-wide: all 44 successful accepts at credits ≥ 39,870, all 29 failures at ≤ 12,420 (run 3,
   steps 43+) with NO state feedback — the signing path has no credit check, so the correlation is a proxy
   (candidate causes: empty/exhausted daily manifest board, location, fuel gate). Player-facing issue: the
   refusal is silent. Repro data: `playtest-run-3.json`.
5. **CONFIRMED (medium, docs): User-Manual Appendix A rank thresholds wrong from Admiral up**
   (600/900/1,100/1,400/1,700 listed vs correct 750/1,200/1,650/2,250/2,700 per `constants.ts` +
   `SP.END.txt:373-381`).
6. **CONFIRMED (low, pacing): `DAILY_TRIP_LIMIT = 2` conflates the original's 2 sessions/day with its
   3 cargo trips/day** (`constants.ts:162`; `travel.ts:203-207` prints the session message when blocking a
   trip; Manual §2.8). Compounds finding 1.
7. **PLAUSIBLE (low, docs): PRD §9.2's "~50% combat win rate" metric is unachievable under the authentic
   jm/jn encounter-band matchmaking** (upgraded ships only ever fight K1 → 35W/1L observed). Amend the
   metric, not the mechanics.

**UGT methodology findings (fixed or queued):**
- The LLM alone under-flags: 0 volunteered flags in 1,000 campaign actions despite two known flag-worthy
  events (run 3's 29 contradictions of the guide; run 9's fuel-0 stall, noticed then rationalized). **Fixed:**
  playtester now has a mechanical contradiction detector (same action → no material delta ×3 while the agent
  expects change → auto-filed potential_bug); verified live (auto-flagged gemma's accept-spam on first try).
- Anywhere "0 bugs in 1,000 actions" is cited it must read "0 LLM-volunteered flags; 2 post-hoc misses".
- Queued: promote potential_bugs to PLAYTEST-DESIGN's `BugReport` shape; coverage note — verdict covers the
  core loop only (`deliver_cargo`/`wait` never chosen; jail/lost/bank/surrender paths untouched).

---

## RE-VERIFICATION (2026-07-06) — all 7 Gate-C findings fixed upstream; fixes CONFIRMED live

SpacerQuest `main` (through `98868f04`) fixed all 7 ranked findings (see the FIX STATUS table in
`../SpacerQuest/UGT-PLAYTEST-FINDINGS.md`). Re-verified from this repo against the live server
(`CLASSIC_MODE=false`), 3×100 actions, `claude-haiku-4-5-20251001` (user-directed model; old-code
haiku control run scored 17/100 vs sonnet's 18.4 → near-equivalent driver for this guide-driven loop).

**Results** (`integrations/spacerquest/results/reverify-newcode-2026-07-06/`, old-code control in
`results/oldcode-haiku-2026-07-06/`, pre-fix campaign preserved in `results/baseline-2026-07-05/`):
- **Finding 1 (docking varfix) CONFIRMED FIXED** — per-delivery score = 2 + trip distance − losses,
  verified per-step (+11 for a 9-distance haul; −4 dockings after lost battles). Also probe-verified
  +7 for a clean 1→6 hop on both plain-dock and cargo paths.
- **Finding 2 (fuel malfunction gate) CONFIRMED FIXED** — keystroke-path probe at fuel 1: "Weapons
  Malfunction!", 0 fuel burned, enemy still fires. The gate BITES: haiku went 0W/14L across 300
  actions, losing every fight it entered at fuel 0 (vs 35W/1L pre-fix free-attack exploit).
- **Finding 6 (3-trip cap) CONFIRMED** — 3 trips/turn flow; strategy-guide.md updated (was teaching 2).
- **Finding 4 (Commandant hijack)** — no recurrence: 0 silent contract-refusal stretches in 300 actions
  (weapons+shields crossed 50 in every run, the old trigger condition).
- **Score velocity: 33.7 mean [11, 50, 40] per 100 actions vs 17 same-model old-code (~2-3×).** The
  5-15× projection needs combat WINS (+wb) and long hauls; under haiku fuel discipline losses (−lb)
  drag it. Robustness held: **0 invariant violations in 300 actions.**

**NEW findings for SpacerQuest (noted in its UGT-PLAYTEST-FINDINGS.md, uncommitted):**
1. **Bare `POST /api/navigation/arrive` with no active travel is a score pump** — each call runs the
   plain-docking varfix (+2, q6=0) and spawns an encounter. New with the varfix-on-plain-docking fix.
   Not UI-reachable; guard: reject arrive when no TravelState exists.
2. **Poverty trap: `end_turn` requires tripCount == DAILY_TRIP_LIMIT (now 3)** and refuses otherwise,
   while `buy_fuel` refuses silently when credits < price (both auto-flagged by the contradiction
   detector, run 1 steps 35/56). A broke player who can't fund a 3rd trip can neither fly nor end the
   turn. Recoverable in our runs, but the refusals are invisible in tracked state.

**Process lesson (cost a full aborted 3×100 campaign):** the first campaign ran against a STALE server
from a previous session still holding :3005 — our fresh server died on EADDRINUSE and the health check
passed against the old process. After starting a server, verify the LISTENING PID is the process you
spawned (`lsof -nP -iTCP:3005 -sTCP:LISTEN`) before trusting any results.

### NEXT STEPS (2026-07-06) — in priority order

The authoritative continue-from-here doc is `../SpacerQuest/HANDOVER.md` (rewritten this session);
summary of the UGT-side work:

1. **Sonnet-competence velocity run** — 3×100 with `claude-sonnet-5`. The 5–15× projection is still
   unmeasured under play that WINS battles (haiku went 0W/14L, so the `+wb` term never fired live and
   `−lb` dragged velocity to 2–3×). This is the remaining acceptance check on Finding 1's pacing.
2. **Coverage expansion (playtester)** — the balance verdict still covers only the core loop. Never
   exercised: jail, bank, lost-in-space rescue, surrender/tribute, pub, patrol commissions, missions,
   Andromeda. Extend the action map + strategy guide per system, one at a time.
3. **API-surface robustness sweep (exploit-hunter)** — the bare-arrive score pump was found by hand,
   not by the hunter, because the hunter only drives UI-level actions. Add a probe tier that fuzzes
   the HTTP routes the frontend uses (arrive with no travel, double-arrive, launch-while-in-combat,
   negative/oversized bodies) and asserts state invariants after each.
4. **Guide tuning for the new meta** — haiku's weapons-99 death spiral suggests the guide's
   `upgrade_cheapest when credits > 40k` rule needs a cap tied to fuel economy (each attack costs
   weapons/2 fuel); consider "keep fuel ≥ 3 × weapons/2 before any launch".
5. **Baseline honorarium** — still start test baselines mid-band (e.g. score 200) or subtract the +20k
   COMMANDER honorarium in analysis (standing caveat from Gate C).

**STATUS UPDATE (2026-07-06, loose-ends session):** the two NEW findings above are **FIXED in the game**
(spacerquest `394cf100`, branch `ugt-reverify-findings`: arrive 400s without TravelState; end_turn is now a
trip ALLOWANCE — suite 1,953 green) — live re-verification of both rides with the next campaign. UGT side:
step 4 DONE (guide teaches fuel-reserve ≥ 3×floor(weapons/2), fuel-capped upgrades, allowance end_turn);
step 5 DONE (per-run `credits_gain_honorarium_adjusted` via rank_index deltas × `RANK_HONORARIA` from game
constants — applied to the haiku reference set it flips mean credits +18.2k → **−1.8k**, so raw haiku play
was net-negative); queued BugReport promotion DONE (all 3 flag sites emit the PLAYTEST-DESIGN shape).
Live 1×10 smoke on the fixed server: 10/10 actions, 0 violations, end_turn-after-1-trip verified live,
honorarium adjustment correct. Remaining before the sonnet campaign (step 1): nothing — it's next.

**SONNET VELOCITY CAMPAIGN (2026-07-06, `results/sonnet-newcode-2026-07-06/`):** 3×100 claude-sonnet-5;
run 3 truncated at 23 actions by an Anthropic **API credit-balance exhaustion** (billing 400 — top up before
any further LLM campaigns). Results from the two complete runs + partial:
- **Score velocity 78 and 113 per 100 actions (run 3 pace ≈ 139) vs 18.4 same-model old-code = 4.2–6.1×
  (partial-run pace 7.6×) — the 5–15× projection's lower bound is REACHED**, and entirely WITHOUT the +wb
  term: sonnet went 0W/0L (fuel-disciplined hit-and-retreat: attack while hull > 3, retreat, repair, deliver
  long hauls). Conquest extrapolation at ~95/100 actions: ~10,400 actions (was ~54,000 pre-fix) — back to the
  authentic months-scale order. Residual gap: battles_won=+wb has STILL never fired in live campaign play
  (verified only by upstream unit tests + keystroke probes); a win-seeking guide variant would close it.
- **Economy: raw credits mean −28.4k/100 actions; honorarium-adjusted −48.4k [CI −81.8k, −15.0k], 2/3 runs
  deeply negative.** Post-fix competent play is score-positive but credits-NEGATIVE at 100-action scale
  (upgrades+repairs+fuel outrun delivery payments; zero combat loot without kills). Candidate balance
  finding for SpacerQuest triage — or a long-horizon effect (capex front-loading) needing an endurance run.
- **Robustness: 0 invariant violations / 0 flags in 223 more live actions.** Allowance end_turn used
  deliberately (run 3 step 16 ended at trip 2 to bank a fragile ship). Guide compliance visibly exact
  (attack-cost arithmetic quoted per combat step). Stage-1 fixes held live.

---

## After the adapter — the two tiers (user chose "both, in sequence")

- **Phase 1 — RL/random EXPLOIT-HUNTER (robustness).** Drive random/curiosity-driven *real* inputs + assert
  invariants (no negative fuel, no stuck screens, no dupes, no crash, no soft-lock). Cheap, needs **no reward
  engineering** — this is what RL is actually good at here. Answers *"does the game break?"*
- **Phase 2 — LLM BALANCE playtester.** LLM reads the real terminal, presses keys like a player, plays
  competently, N runs with confidence intervals. Answers *"is the game good/balanced/beatable?"* Slower but
  competent — and for balance, competence beats volume (RL never achieved competent play here). `PLAYTEST-DESIGN.md`
  is the design spec for this tier. Concrete starting task: `ugt playtest` (`ugt/core/playtester.py`) only
  supports `browser`/`simulation` engines today — wire in `RealClientAdapter` for `engine.type: "real_server"`.

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

## Framework backlog (cross-game, not SpacerQuest-specific)

Salvaged from the archived `DEV-CHECKLIST.md` — still-open work on UGT itself, independent of any one game
integration. Revisit when a task below actually blocks the current game, not on a schedule:

- **Browser feature map + screen detection** — `press_key`/`type_text` action syntax in `feature-map.yaml`,
  plus `detect_screen()`/`waitForScreen()` for browser games (needed for `ugt verify` to cover browser titles).
- **`ugt verify`/`ugt playtest` don't support `engine.type: "real_server"`** — see Phase 2 above; the same gap
  applies to `verify`, lower priority since the exploit-hunter scripts cover robustness for now.
- **Desktop adapter** (Adapter 4) — `pyautogui` or a computer-use API for non-browser, non-terminal games.
- **HTML coverage report** — human-readable `coverage-report.html` generated from the JSON.
- **`ugt init --with-feature-map`** — scaffold a starter `feature-map.yaml` alongside `ugt.config.yaml`.

## Key references

| Thing | Where |
|---|---|
| Current direction + protocol + spike | memory `architecture-pivot-real-server` |
| Why we pivoted (combat missing) | memory `combat-not-in-bridge` |
| RL collapse root cause + Gate-1 history | memory `rootcause-rl-collapse` |
| LLM playtest design spec (Phase 2) | `PLAYTEST-DESIGN.md` |
| Onboard a new game + methodology | `UGT-USER-MANUAL.md` |
| Real game routes (nav/arrive/combat) | `SpacerQuest/spacerquest-web/src/app/routes/`, `src/sockets/game.ts` |
| Retired bridge (do not extend) | `integrations/spacerquest/sim_bridge.ts` |
| Superseded docs (why + where content went) | `archive/README.md` |
