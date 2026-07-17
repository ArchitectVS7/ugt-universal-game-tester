# Nexus Dominion — UGT Integration Feasibility Study

> **OUTCOME (2026-07-16): GO was correct — trial COMPLETE the same day.** Full ladder green
> (spike 11/11 · smoke 6/6 · R1 12/12 · R2 17/17 · R3 43/43), **10 defects fixed upstream**,
> game suite 1109→1137. The "zero game-side retrofit" hope did NOT hold: the game-side needed a
> thin harness *and* 10 real fixes (incl. one critical — the game was inert for its first 10
> cycles). See `RESULTS.md` / `HANDOFF.md`. The study below is the original pre-build analysis,
> preserved for reference.

---

**Date:** 2026-07-16 · **Verdict: GO — highest-feasibility candidate UGT has evaluated.**
Recommended path: **engine-first JSON-lines subprocess harness** (the DDD pattern), runnable
today, independent of the pending human UAT retest.

Baseline verified this session against nexus-dominion `922e53a`:
`npm test` → **1109/1109 green** (41 files, 2.8s) · `npx tsc --noEmit` → clean.
The old survey blockers ("test baseline unverified", "design review first") are resolved:
the repo now has PRD v3.0 + reconciled docs + an orchestrated task DAG, and the suite is green.

---

## 1. Game evaluation

**What it is.** Single-player space-empire "digital boardgame" (Tauri 2 + React 19, LCARS UI).
100 empires (player + 99 bots) across 250 systems / 10 sectors; a 17-phase cycle pipeline
(income → production → … → bot decisions → market → achievements → Reckoning every 10 cycles).
Engine is pure TypeScript under `src/engine/` — 37 source files (~7.7k LOC) with ~12k LOC of
tests (1.55:1), no DOM/React imports, no `Math.random` anywhere in engine source.

**Where it stands.** End of milestone M1.5 (UAT remediation). The first human playtest
(**U-110, 2026-07-16) FAILED** on four findings: overlapping star systems, no onboarding,
no turn-structure indication, and 60 empty COMMIT clicks advancing player rank. All seven
remediation tasks (T-111..T-117: min inter-system distance, map scaling, **orders-queue
turn model**, queued badges, TurnStatus HUD, tutorial state, tutorial overlay) are committed;
the human retest is the open gate. CODING-PLAN's own admission: *"most engine work has never
been played by hand"* — installations, syndicate, covert ops have engine+UI+tests but zero
human play. This is precisely the profile where the exploit-hunter tier earns its keep.

**Design facts that shape a trial:**
- **No win/loss terminal state by design** (TURN-MANAGEMENT-SYSTEM.md:330: "The game does not
  end"). 10 achievement paths (code has 10 in `ACHIEVEMENT_DEFINITIONS`; README/docs say 9 —
  minor doc drift) are milestones, not endings. A harness defines its own episode termination
  (cycle cap and/or achievement watch on `state.earnedAchievements`).
- **No fog of war / player-view redaction.** UI reads the omniscient `GameState`;
  `playerEmpireId` is just a pointer. Simpler than DDD (no PlayerView seam to test), but the
  LLM-playtester tier would see everything unless we project a view ourselves.
- **Known, acknowledged gaps** (CODING-PLAN/TASKS): LLM "Nemesis" bots are a heuristic stub
  (~30%, deliberate); blockade combat ~60%; market-event notifications never reach the player;
  `calculateTransitTime` ignores distance/wormholes; instant colonisation deviates from spec;
  `attack` builds a force from supplied `unitIds` **without validating where those units are
  stationed** (units teleport); idle rank-climb residual from U-110 finding 4 (powerScore
  rewards passive credit growth). Several of these are pre-registered findings for the ladder
  (§5).
- **Performance is specified but unmeasured at scale**: PRD targets <5s/cycle alpha, <1s
  release at 100 empires; the perf milestone T-401 is TODO and `integration.test.ts` defaults
  to 10 empires (one stress case: 100 empires × 50 cycles < 30s). A UGT trial doubles as this
  measurement.

## 2. Integration surface (why this is the best candidate yet)

The engine already has everything the DDD harness had to be *built* to provide:

| Need | nexus-dominion answer |
|---|---|
| Start campaign | `createNewCampaign(config, name?, {tutorial?})` — `src/engine/campaign/campaign-factory.ts:48` (seed in `config.seed`) |
| Advance turn | `processCycle(state, playerActions, powerHistory, botAccumulated)` → `{state, report, committed, error?}` — `src/engine/cycle/cycle-processor.ts:53`, **atomic** (Tier-1 failure returns original state + error string) |
| Player actions | 15 order types, one `switch` in `resolvePlayerActions` (`cycle-processor.ts:537-955` + `move-fleet` at `:969`): claim-system, build-unit, select-doctrine, select-specialization, research, build-installation, build-wormhole, trade, propose-pact, break-pact, fund-syndicate, purchase-black-register, launch-covert-op, attack, move-fleet |
| Serialize state | `serializeGameState`/`deserializeGameState` (`src/engine/persistence/state-serializer.ts:50,58`) — tagged Map/Set encoding, pure, Node-safe |
| Headless drive loop | **already exists**: `src/engine/integration/integration.test.ts` threads state through `processCycle` for multi-cycle sims — the harness copies this loop verbatim |
| Determinism contract | already a tested property (same seed + same actions ⇒ identical state, `integration.test.ts:242`) |

**Determinism audit: sound.** Mulberry32 `SeededRNG` (`src/engine/utils/rng.ts`), re-derived
each cycle from `seed + currentCycle` (+ per-subsystem offsets / `simpleHash`), so there is no
PRNG stream position to lose across save/load; all subsystem engines take the RNG by parameter.
Zero `Math.random` in engine source (T-205 closed the last three strays). The serializer
preserves Map/Set order, so sort-tie/iteration determinism survives reload. The **only**
nondeterminism is metadata: `campaign.id` (`campaign-${Date.now()}-…`), `createdAt`,
`lastSavedAt` (`campaign-factory.ts:171-174`) and persistence `savedAt` — none feed gameplay
or RNG, but whole-state replay comparison must normalize them out.

**Tauri is a pure webview shell** (boilerplate `greet` + opener plugin only; persistence is
localStorage). Nothing gameplay-relevant depends on Tauri — the engine runs standalone in Node.

**Browser path is NOT viable as-is:** no `window.__GET_STATE__`/`__SEND_ACTION__` hooks exist
anywhere. Subprocess dominates; hooks could be added later if a UI-tier trial is wanted (§6).

## 3. Recommended architecture

Same shape as `integrations/ddd/` (DddHarnessAdapter):

1. **Game-side** (`nexus-dominion` repo): a thin `tsx` JSON-lines CLI, ~150–250 LOC, **zero
   game logic** — the `ACTION_HANDLERS` discipline. Commands:
   - `create {seed, empireCount?, galaxySize?, tutorial:false}` → `createNewCampaign`
   - `orders {actions:[{type, details}]}` + `commit` → `processCycle`; emit serialized state
     + `report` + `committed`/`error` per line
   - `state` → `serializeGameState(state)` (optionally a trimmed projection for obs mapping)
   - `save`/`load` → serializer round-trip (NOT the localStorage adapter)
   - Harness owns the two **caller-owned accumulators** the engine does not maintain:
     `powerHistory` (push each empire's `powerScore` after every cycle) and `botAccumulated`.
     Getting these wrong is silent — a prime wire-only-defect candidate, so the harness should
     mirror `integration.test.ts:127-139` exactly.
2. **UGT-side**: adapter modeled on `ugt/adapters/ddd_harness.py` (spawn subprocess, JSON
   lines over stdin/stdout), ladder scripts built on `ugt/core/trial.py` (GateRunner /
   InvariantSuite / first_divergence).

**Episode definition** (no terminal state): fixed cycle cap (R1: ~25 cycles; R2: ≥30 to cross
two Reckonings; R3 episodes: 50+) plus achievement-triggered early success.

## 4. Trial ladder sketch

- **Spike** — raw round-trip: create(seed) → 3 commits → state lines parse; kill/restart.
- **Smoke** — same via BaseAdapter (`reset`/`step`/`close`).
- **R1 (playability)** — one campaign ~25 cycles with real orders (claim, build-unit, trade,
  move-fleet, attack) + per-cycle invariants + **serialize→deserialize→continue vs
  uninterrupted run, `first_divergence` on normalized state** (round-trip-and-continue is
  untested upstream — the exact class the DDD trial caught).
- **R2 (full spine)** — all 15 order types each to a *real observed state delta* (refusal ≠
  inertness); combat through all 3 phases; a Reckoning firing at cycle 10 with tier re-sort;
  covert op resolved both detected/undetected; syndicate funding → Black Register purchase;
  at least one achievement earned; save/load mid-campaign.
- **R3 (exploit-hunter)** — seeded episodes of random/heuristic order soup; invariants every
  cycle; **unmapped/malformed action probes** (unknown types currently fall through the switch
  *silently* — a refusal-vs-inertness finding in waiting); same-seed replay byte-identical
  after metadata normalization (this would be the game's first full-state determinism proof —
  upstream only asserts 4 scalar fields).

**Invariant candidates:** no negative resources/population; system count constant at 250 with
consistent ownership (empire↔system cross-references agree); units/fleets located in real
systems; pact symmetry; `earnedAchievements` monotone; `committed=true` or surfaced `error`
(never both/neither); powerScore finite; bot count 99 (no eliminations exist — `eliminatedCount`
is hardwired 0 at `cycle-processor.ts:427`); cycle time under the 5s alpha budget at 100 empires.

## 5. Pre-registered findings to confirm live

1. **attack teleports units** — `unitIds` not location-validated (TASKS.md:195). Exploit-hunter
   should demonstrate it through the wire.
2. **Unknown order types are silent no-ops** — switch fall-through; dedupe table defaults to
   `stackable`. Probe with garbage types; silence is the finding.
3. **Empty-commit rank climb** — U-110 finding 4 residual; verify T-113/T-116 actually changed
   engine outcomes, not just UI affordances (a 60-empty-commit run is one script).
4. **Instant colonisation** and **transit time ignores distance/wormholes** — spec deviations to
   measure, feed the deferred balance pass.
5. **Full-state same-seed divergence** — upstream determinism test covers 4 fields; the whole
   serialized tree has never been compared. Any divergence found here is new information.

## 6. What this trial does NOT cover — and effort

**An engine-first trial cannot sign off U-110.** Findings 1–3 of the failed UAT are visual/UX
(map readability, onboarding, HUD) — invisible to a subprocess harness. The human retest stays
on the critical path for the game; the UGT trial runs in parallel and instead validates the
never-played engine depth (and delivers PRD's own specified-but-unbuilt "Simulation" test tier,
`docs/prd.md:564`, plus the T-401 perf measurement). If UI-tier coverage is wanted later, add
`window.__GET_STATE__`/`__SEND_ACTION__` hooks à la warzones/tarot-war (~1 day).

**Effort estimate** (calibrated against the DDD trial, the closest precedent):
- Game-side JSON-lines CLI: **~1 day** (loop already written in `integration.test.ts`).
- UGT adapter + spike/smoke: **~0.5–1 day** (clone `ddd_harness.py` shape).
- R1–R3 ladder on `trial.py`: **~2–3 days** including the usual fix-upstream round-trips.
- Total: **~4–5 days** to a complete ladder. Cheap to run: pure Node subprocess, no server,
  no browser; 100-empire × 50-cycle sims complete in <30s today.

**Risks:** (low) Map/Set serializer is the wire boundary — all traffic must round-trip through
`state-serializer.ts`, and the serialized tree is large at 100 empires (obs mapping should
project, not ship, the full tree per step); (low) per-cycle cost at full scale unmeasured —
first spike measures it; (moderate) game may churn under M1.5→U-110 retest → pin the trial to
a commit and re-run the ladder on movement, as with DDD.
