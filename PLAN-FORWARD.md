# UGT — Plan Forward (START HERE)

> **New session? Read this file, then the ⭐ memory notes listed in the memory index.** This is the durable
> handover. Last updated 2026-07-24. The detailed SpacerQuest-era version of this file (Phases 0–2, Gate C,
> the re-verification and velocity campaigns) is preserved verbatim at
> `Dev/PLAN-FORWARD-spacerquest.md` — history lives there, the plan lives here.

---

## The bigger picture (why any of this matters)

UGT is a **Universal Game Tester**: a framework that drives real games with autonomous agents to find bugs,
probe balance, and validate behavior. The methodology is the product — each game integration both tests that
game AND stress-tests the methodology, which is then reused on the next game. Seven games in, these are the
principles, every one learned the hard way:

1. **Play the game with the game.** The tester must drive the *real* running game, never a re-implementation
   of it. The original SpacerQuest `sim_bridge.ts` slowly became a partial copy of the game (no combat,
   broken upgrades) — every agent trained against it learned a *different game*. A harness that reimplements
   the game is testing itself, not the game. This is the #1 reusable lesson, and the reason adapters contain
   zero game logic (unmapped actions raise `NotImplementedError` by design).
2. **Dual validation.** Every run validates two things at once: that UGT can test the game, and the game
   itself. Surfacing a real game bug mid-test is a success of the process — expect to pause testing, fix the
   game upstream, and return. All seven integrations produced fixed-upstream game bugs.
3. **Failed tests are data.** Invariant violations, crashes, negative results, and even aborted campaigns get
   recorded (in `integrations/<game>/RESULTS.md` and memory notes), never discarded as flaky.
4. **Wire-only defects are THE class UGT exists to find.** A game's own client routes around its wire, so a
   green in-process suite cannot see serialization-boundary bugs. DDD proved it: 1,251 in-process tests green
   while 7 of 40 Swarm cards played blank for every wire client (the harness never exposed `legalTargets`),
   and `create` accepted a config that `replay` would refuse — a missing config key silently played a
   *different game*. Rules distilled in memory note `feedback_wire_only_defects` (exact-config-key sets,
   refusal ≠ inertness, kill vacuous greens, suspect your own invariant first).
5. **Audit your own findings.** UGT has been wrong more than once and each correction is recorded, not
   buried: SpacerQuest's "battlesWon accounting bug" was a cumulative-counter misread; DDD's "`@ddd/ai` never
   fills targets" was refuted (`integrations/ddd/RESULTS.md` D-C2); DDD's "Focus economy is dead code" was
   over-claimed from a small sample (D-C1, later properly closed); NEXUS's L-010 89.8% win-rate batch was
   later found to be rules-blind and superseded by L-011. Investigate before *confirming*, not just before
   dismissing — and read each game's RESULTS.md corrections before citing old findings.
6. **Verify the server you're testing is the one you started.** A stale process squatting the port once ran a
   whole campaign against OLD code (health check 200 ≠ your server). After every server start, confirm the
   LISTENING PID is the process you spawned (`lsof -nP -iTCP:<port> -sTCP:LISTEN`).
7. **Run the §B LLM pre-flight audit before any balance batch.** Two multi-hour DDD balance batches (L-008,
   L-011) each measured a pilot that couldn't see the game — blind to card identities, then to the game's
   public read layer — while reporting a clean pass and a confident win rate. `LESSONS.md` §B (P1–P9) is now
   mandatory reading before spending a batch; it exists because of those two runs.

---

## Where we are (2026-07-24) — seven integrations, three transport paradigms

The **trial ladder** (below) has been run to completion against seven games. The game-agnostic scaffold is
`ugt/core/trial.py` (commit `74eee8e`, validated by an exact NEXUS ladder re-run).

| # | Game | Transport / adapter | Ladder result | LLM playtest tier | Status |
|---|------|--------------------|---------------|--------------------|--------|
| 1 | SpacerQuest (Rimward restart) | `simulation`, stdio protocol bridge | verify 9/9 · train (PPO) · evaluate VALID (+124.0 vs random −8.4) | Not wired — RL-only so far | **Current active gap: no LLM tier exists yet.** The old Museum-Edition integration (`spacerquest_old`) was **deleted 2026-07-21**, entirely superseded by this restart; its history is in `Dev/PLAN-FORWARD-spacerquest.md` / `Dev/UGT-TRACK-RECORD.md` |
| 2 | Warzones | browser, `PlaywrightAdapter` | R1 23/23 · R2 12/12 · R3(`verify_round10.py`) 6/6 | Not wired (game entered active dev before that work started) | **Paused for active game-side dev.** WZ-R3 (ContractScene never launched) open, scoped to v0.9. Do not advance/retest until owner signals stable |
| 3 | Tarot-war | browser, `PlaywrightAdapter` | R1 22/22 · R2 12/12 · R3 7/7, all 8 findings closed | Wired + smoke-run (L-005, ollama, 30/30 real dispatches, 0 bugs) | **Paused — owner running a dedicated human-dev expansion season.** A deeper balance verdict (stronger model) is the open next step once expansion lands |
| 4 | NEXUS (nexus-world-builder) | live HTTP test routes, `NexusHttpAdapter` | spike 8/8 · R1 25/25 · R2 66/66 · R3 9/9 (re-run pending post-E2E-work) | Extensively exercised through **L-030**: gemma4/Haiku smoke comparisons, hard repeat-block, real-browser Playwright audit fixed a game-crashing bug + all 32 pre-existing E2E failures (suite now 78/78 green, no hollow passes) | **Active.** Statistically-powered Anthropic balance batch (N runs, CI-gated) is the one remaining next step for this tier. `NX-L30-1` filed to the game's own `TODO.md` (tutorial-skip/exploit-unlock interaction) — not a UGT blocker |
| 5 | DDD | subprocess JSON-lines harness, `DddHarnessAdapter` | spike 10/10 · smoke 5/5 · R1 11/11 · R2 26/26 · R3 32/32, zero open findings | Extensively exercised through **L-013**: fixed-opponent matchup batches (gemma4 + Haiku 4.5) reproduce a Blitzblade-over-Swarm asymmetry; cause (deck/pilot/mechanic) still undetermined | **Active.** Open: DDD's own T6.2 Blitzblade retune, T6.3 conformance audit #2 (tracked in the DDD repo, not UGT) |
| 6 | Nexus Dominion | engine-first subprocess JSON-lines harness, `NexusDominionHarnessAdapter` | spike 11/11 · smoke 6/6 · R1 12/12 · R2 17/17 · R3 43/43, zero findings | Wired + validated (L-003, ollama, 22 actions/18 delta steps, 0 violations) | **Active.** Statistically-powered balance batch not yet run. **U-110 human UAT retest is on the game's own critical path** — the engine trial can't sign off visual/UX findings |
| 7 | Pond (Pond Conspiracy) | Godot 4.7.1, subprocess JSON-lines harness, `PondHarnessAdapter` | spike 13/13 · smoke 8/8(×3) · R1 18/18 · R2 45/45 (2 owner-accepted limitations) · R3 11/11, zero findings | Wired + MET (L-004, macro-layer, ollama, 7/7 level-up decisions across 9 runs) | **Paused for active game-side dev** since 2026-07-21. Do not advance/retest until owner signals stable |

Per-game detail lives in `integrations/<game>/` — **`HANDOFF.md` is the resume-here doorway**, `RESULTS.md`
the commit-traceable findings log, `README.md` the how-to-run. See `integrations/README.md` for the
single-table index with real pass counts.

---

## The trial ladder (the repeatable process)

Each new game climbs the same ladder; every rung is a fail-closed gate script in `integrations/<game>/`:

1. **Spike** (`spike_<game>.py`) — prove the raw protocol round-trips headlessly (auth/create → act → read
   state). Empirically pins protocol facts that would otherwise bite later.
2. **Smoke** (`smoke_<game>_adapter.py`) — the same path through the `BaseAdapter` contract
   (`connect`/`reset`/`step`/`close`).
3. **R1 — playability gate** (`verify_round1.py`) — scripted "one full loop" of the core game under
   per-command invariants.
4. **R2 — full spine** (`verify_round2.py`) — every major mode/system driven to a real outcome (e.g. a win),
   still under invariants.
5. **R3 — exploit-hunter** (`verify_round3.py` / `ugt/core/exploit_hunter.py`) — random+heuristic walks with
   the same invariants asserted after every step, plus determinism checks (same-seed replay must be
   byte-identical). Findings are structured and read, not counted.

The shared skeleton is `ugt/core/trial.py` (`GateRunner`, `InvariantSuite` — one predicate definition reused
by both the scripted rounds and the hunter — and `first_divergence` for replay compare). Everything
game-specific (predicates, probes, policies, state normalization) stays in the game's `integrations/<game>/`
files.

The ladder answers *"does the game work / does it break?"* (tiers 1–2 of the three-tier model). The third
tier — the **LLM balance playtester** (`ugt playtest`, spec in `PLAYTEST-DESIGN.md`) — answers *"is the game
good?"*. It has now run in anger against five of seven games (see table above); **before running it on any
game, work through `LESSONS.md` §B (P1–P9)** — the pre-flight information-integrity audit that two DDD
balance batches paid for the hard way.

---

## NEXT STEPS (2026-07-24, priority order)

1. **Statistically-powered LLM balance batches** for NEXUS, DDD, and Nexus Dominion — each game's tier is
   wired and smoke-validated, but the CI-gated, seat/turn-order-controlled batch that actually produces a
   trustworthy verdict hasn't been run for any of the three. Read `LESSONS.md` §B first for each.
2. **Wire the LLM tier for SpacerQuest (Rimward)** — the one integration with no LLM playtest work at all yet
   (RL-only so far). This is a gap, not a pause.
3. **Re-run Nexus Dominion's human UAT (U-110)** now that its one engine-reachable symptom (ND-3) is fixed
   upstream — this sits on the game's own critical path, not UGT's, but is worth tracking here since it's the
   only open cross-repo dependency.
4. **Resume paused integrations once their owners signal stability**: Warzones (active dev), Tarot-war (human
   expansion season), Pond (active dev). Do not advance their ladder rung or re-run existing tiers before then.
5. **Game #8 candidate: `overlord`.** The last portfolio re-ranking (2026-07-09, memory note
   `project_portfolio_validation`) shortlisted it ahead of what were then DDD/Nexus Dominion — both now done,
   and Pond was added from a later pass. Confirm it's still the right pick (the portfolio hasn't been
   re-surveyed since Pond was added) before onboarding.

---

## Framework backlog (cross-game, not game-specific)

Revisit when an item actually blocks the current game, not on a schedule:

- **Config-driven CLI path for the trial ladder** — the per-game `verify_round*.py` scripts construct
  adapters directly; several adapters aren't registered under an `engine.type` in `env.py`. Worth a look now
  that seven integrations each hand-roll their own ladder scripts, and the L-002 direct-adapter playtest
  entry point was added specifically to sidestep this rather than solve it.
- **Formalize human/frontend UAT as an explicit fourth doorway.** It's only been tracked ad hoc for the two
  most recent engine-first games (Nexus Dominion, Pond), and in both cases it caught things — visual
  readability, onboarding, animation feel — no engine-level tier can see by construction. Every future
  integration's `HANDOFF.md` should carry a UAT status line the same way it already carries ladder status.
- **Browser feature map + screen detection** — `press_key`/`type_text` action syntax in `feature-map.yaml`,
  plus `detect_screen()`/`waitForScreen()` (needed for `ugt verify` to cover browser titles).
- **`ugt verify` doesn't support `engine.type: "real_server"`** — low priority; the ladder scripts cover it.
- **Desktop adapter** — `pyautogui` or a computer-use API for non-browser, non-terminal games.
- **HTML coverage report** — human-readable `coverage-report.html` generated from the JSON.
- **`ugt init --with-feature-map`** — scaffold a starter `feature-map.yaml` alongside `ugt.config.yaml`.

---

## Key references

| Thing | Where |
|---|---|
| Resume any integration | `integrations/<game>/HANDOFF.md` |
| Findings + corrections per game | `integrations/<game>/RESULTS.md` |
| Cross-game lessons registry (methodology + LLM pre-flight audit + operational discipline) | `LESSONS.md` |
| Trial-ladder scaffold | `ugt/core/trial.py` (+ `ugt/core/exploit_hunter.py` for R3) |
| Onboard a new game + methodology | `UGT-USER-MANUAL.md` |
| LLM playtest design spec (tier 3) | `PLAYTEST-DESIGN.md` |
| Wire-only defect rules | memory note `feedback_wire_only_defects` |
| Stale-server PID rule | memory note `feedback_verify_server_pid` |
| SpacerQuest era in full (Phases 0–2, Gate C) | `Dev/PLAN-FORWARD-spacerquest.md` |
| Why the sim-bridge died / RL collapse history | memory notes `combat-not-in-bridge`, `rootcause-rl-collapse` |
| Superseded docs (why + where content went) | `Dev/README.md` |
