# UGT — Plan Forward (START HERE)

> **New session? Read this file, then the ⭐ memory notes listed in the memory index.** This is the durable
> handover. Last updated 2026-07-16. The detailed SpacerQuest-era version of this file (Phases 0–2, Gate C,
> the re-verification and velocity campaigns) is preserved verbatim at
> `archive/PLAN-FORWARD-spacerquest.md` — history lives there, the plan lives here.

---

## The bigger picture (why any of this matters)

UGT is a **Universal Game Tester**: a framework that drives real games with autonomous agents to find bugs,
probe balance, and validate behavior. The methodology is the product — each game integration both tests that
game AND stress-tests the methodology, which is then reused on the next game. Five games in, these are the
principles, every one learned the hard way:

1. **Play the game with the game.** The tester must drive the *real* running game, never a re-implementation
   of it. The original SpacerQuest `sim_bridge.ts` slowly became a partial copy of the game (no combat,
   broken upgrades) — every agent trained against it learned a *different game*. A harness that reimplements
   the game is testing itself, not the game. This is the #1 reusable lesson, and the reason adapters contain
   zero game logic (unmapped actions raise `NotImplementedError` by design).
2. **Dual validation.** Every run validates two things at once: that UGT can test the game, and the game
   itself. Surfacing a real game bug mid-test is a success of the process — expect to pause testing, fix the
   game upstream, and return. All five integrations produced fixed-upstream game bugs.
3. **Failed tests are data.** Invariant violations, crashes, negative results, and even aborted campaigns get
   recorded (in `integrations/<game>/RESULTS.md` and memory notes), never discarded as flaky.
4. **Wire-only defects are THE class UGT exists to find.** A game's own client routes around its wire, so a
   green in-process suite cannot see serialization-boundary bugs. DDD proved it: 1,251 in-process tests green
   while 7 of 40 Swarm cards played blank for every wire client (the harness never exposed `legalTargets`),
   and `create` accepted a config that `replay` would refuse — a missing config key silently played a
   *different game*. Rules distilled in memory note `feedback_wire_only_defects` (exact-config-key sets,
   refusal ≠ inertness, kill vacuous greens, suspect your own invariant first).
5. **Audit your own findings.** UGT has been wrong three times and each correction is recorded, not buried:
   SpacerQuest's "battlesWon accounting bug" was a cumulative-counter misread; DDD's "`@ddd/ai` never fills
   targets" was refuted (`integrations/ddd/RESULTS.md` D-C2); DDD's "Focus economy is dead code" was
   over-claimed from a small sample (D-C1, later properly closed). Investigate before *confirming*, not just
   before dismissing — and read RESULTS.md corrections before citing old findings.
6. **Verify the server you're testing is the one you started.** A stale process squatting the port once ran a
   whole campaign against OLD code (health check 200 ≠ your server). After every server start, confirm the
   LISTENING PID is the process you spawned (`lsof -nP -iTCP:<port> -sTCP:LISTEN`).

---

## Where we are (2026-07-16) — five integrations complete

The **trial ladder** (below) has been run to completion against five games, across three transport paradigms.
The game-agnostic scaffold was extracted to `ugt/core/trial.py` (commit `74eee8e`, validated by an exact
NEXUS ladder re-run).

| # | Game | Transport / adapter | Ladder result | Game bugs → fixed upstream | Status |
|---|------|--------------------|---------------|----------------------------|--------|
| 1 | SpacerQuest | Socket.IO+HTTP real server, `realclient.py` | Phases 0–2 + LLM campaigns (see archived plan) | 9 findings (7 Gate-C ranked + 2 API exploits), all fixed & re-verified live | **DELETED 2026-07-21** — entirely superseded by the Rimward rebuild at `integrations/spacerquest/`; its integration (`integrations/spacerquest_old/`) is gone from the tree, history preserved in `Dev/PLAN-FORWARD-spacerquest.md` and `Dev/UGT-TRACK-RECORD.md` |
| 2 | Warzones | browser, `playwright.py` | R1 23/23 · R2 12/12 · R3 6/6 | 2 criticals (empty commodity registry, flee-never-resolves) fixed; 400-step same-seed replay byte-identical | Done 2026-07-07 (WZ-R3 deferred to game v0.9) |
| 3 | Tarot-war | browser, `playwright.py` | R1 22/22 · R2 12/12 · R3 7/7 | 8 findings ALL closed (7 fixed upstream); game suite 434→448 | Done 2026-07-07; LLM tier pending |
| 4 | NEXUS | live HTTP test routes, `nexus_http.py` | spike 8/8 · R1 25/25 · R2 36/36 · R3 9/9 | 5 fixes pinned; game suite 1265/173 green | Done 2026-07-09; LLM tier pending |
| 5 | DDD | subprocess JSON-lines harness, `ddd_harness.py` | spike 10/10 · smoke 5/5 · R1 11/11 · R2 26/26 · R3 32/32 | 2 wire-only defects fixed (DDD `61125b64`); D-C1 closed on the `0eb0df83` re-run | Done 2026-07-12; LLM tier (DDD T8.2) pending |

Per-game detail lives in `integrations/<game>/` — **`HANDOFF.md` is the resume-here doorway**, `RESULTS.md`
the commit-traceable findings log, `README.md` the how-to-run.

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
good?"* and has so far run in anger only against SpacerQuest, where it drove the Gate-C balance verdict and
found live exploits the hunter missed.

---

## NEXT STEPS (2026-07-16, priority order)

1. **Top up Anthropic API credits.** Every tier-3 (LLM playtest) run is gated on this — the balance
   evaluation exhausted credits mid-campaign on 2026-07-06 and nothing LLM-driven has run since.
2. **Game #6: `overlord`** (shortlist from the 2026-07-09 portfolio re-ranking: overlord > nexus-dominion;
   the original next-trial ranking is exhausted, and solar-realms-elite is deprioritized along with the
   SpacerQuest hold). Onboard it up the trial ladder using `ugt/core/trial.py` — this is also the first
   integration to start from the extracted scaffold rather than copy-paste.
3. **LLM balance playtests for tarot-war, NEXUS, and DDD** once credits exist. DDD needs a structured-JSON
   drive mode first: `DddHarnessAdapter` has no `press_key`/`get_terminal_text` (the harness is JSON, not a
   terminal), so the playtester would drive `legal`/`act` directly.
4. **DDD-side open items** (tracked in the DDD repo, not UGT work): T6.2 Blitzblade retune, T6.3 conformance
   audit #2.

---

## Framework backlog (cross-game, not game-specific)

Revisit when an item actually blocks the current game, not on a schedule:

- **Config-driven CLI path for the trial ladder** — the per-game `verify_round*.py` scripts construct
  adapters directly; `NexusHttpAdapter`/`DddHarnessAdapter` aren't registered under an `engine.type` in
  `env.py`. Fine at five games; worth folding into the CLI if integrations keep multiplying.
- **`ugt playtest` structured-JSON drive mode** — needed for harness-style games (DDD) with no terminal.
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
| Trial-ladder scaffold | `ugt/core/trial.py` (+ `ugt/core/exploit_hunter.py` for R3) |
| Onboard a new game + methodology | `UGT-USER-MANUAL.md` |
| LLM playtest design spec (tier 3) | `PLAYTEST-DESIGN.md` |
| Wire-only defect rules | memory note `feedback_wire_only_defects` |
| Stale-server PID rule | memory note `feedback_verify_server_pid` |
| SpacerQuest era in full (Phases 0–2, Gate C) | `archive/PLAN-FORWARD-spacerquest.md` |
| Why the sim-bridge died / RL collapse history | memory notes `combat-not-in-bridge`, `rootcause-rl-collapse` |
| Superseded docs (why + where content went) | `archive/README.md` |
