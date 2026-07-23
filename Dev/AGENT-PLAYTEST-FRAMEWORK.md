# Agent Playtest Framework — Engineering Specification

> **2026-07-04 status:** Still the active design spec for UGT's **Phase-2 LLM playtest tier**. One update from
> later lessons: the harness must drive the **real running game** (for SpacerQuest: the `spacerquest-web` server
> over Socket.IO/HTTP, reading the real terminal screens), NOT the `sim_bridge` reimplementation. See
> `PLAN-FORWARD.md` and memory `architecture-pivot-real-server`.

> **What this is:** A design specification for building game-specific, LLM-powered testing
> harnesses that can find bugs, report them, and verify fixes faster than human playtesters.
>
> **What this is not:** A description of UGT (the RL-based balance tester). This spec addresses
> a different problem: correctness testing and feature coverage, not strategy optimization.
>
> **Origin:** Derived from lessons learned across two independent systems — the SpacerQuest
> scripted playtest harness and the UGT RL adapter — plus the failure modes observed when
> RL agents were applied to a problem better suited to LLM reasoning.

---

## The Core Problem

Reinforcement learning agents fail at game correctness testing because they **optimize a
proxy reward**. Given a reward signal and an action space, a PPO agent will find the
highest-reward action sequence — which is rarely "play the game as intended." The canonical
failure: the agent discovers that `upgrade-ship` + `repair` yields a slightly positive
reward signal and executes only those two actions across 200 steps across 20 episodes,
never traveling, never trading, never interacting with 7 of 9 available systems, and
reporting a win rate of 0% while UGT marks the eval "complete."

This is not a bug in the RL system. It is a category error: **RL optimizes; it does not
test.** Testing requires understanding intent — "this action should have caused the fuel
counter to decrease" — which requires reading a game rule and verifying a state delta.
That is a reasoning task, not an optimization task.

The right architecture: an **LLM as the player**, a **scripted planner as the driver**, and
a **coverage map as the specification**. The LLM understands the game; the planner ensures
every feature gets exercised; the map defines what "tested" means. RL belongs downstream —
for balance testing once correctness is established.

---

## I. Principles (Immutable Rules)

These rules must hold in every harness built to this spec. They are ordered by
importance, not by implementation order.

### P1 — All Actions Through the UI

Every action a player could take must go through the same interface a human player uses.
If a player presses `T` to open Traders, the harness presses `T`. If a player types `200`
to buy fuel, the harness types `200`. **The API exists for reading state only.** No action
is performed by calling an HTTP endpoint, invoking a function directly, or any other
shortcut that bypasses the UI layer.

**Why:** Shortcuts hide bugs. The most common class of game bugs is "the backend works but
the UI doesn't wire it up." A test that bypasses the UI will never find those bugs. The
playtest exists to verify the player experience, not to verify that a function exists.

### P2 — State Delta Is the Assertion

Every action must be verified by comparing game state before and after. The assertion is
always of the form: *"after this action, [field] changed in [direction]."* A test that
performs an action without reading state before and after is not a test — it is a script.

- Buy 200 fuel → `state.fuel > before.fuel` ✓
- Press `B` to drink at pub → `state.credits < before.credits` ✓
- Navigate to system 7 → `state.current_system === 7` ✓

### P3 — Feature Coverage Is the Target, Not Game Completion

The harness does not try to win the game. It tries to exercise every player-accessible
feature. These are different goals and produce different agents. A harness that plays to
win will skip low-value features (gambling, registry, jail) because they don't help it win.
A harness that plays to cover will visit them deliberately even when they're suboptimal.

Coverage is tracked per feature, not per session. A feature is **done** when it passes once;
the harness moves on to unvisited features.

### P4 — The Planner Decides, the Executor Acts

Every turn, the planner reads state and decides a task list **once**. The executor then
executes each task to completion. Mid-execution, the planner does not re-evaluate. This
eliminates thrashing (re-queuing the same task because the first execution is still in
progress) and makes the test log linear and readable.

### P5 — Recovery Never Skips Verification

When a task fails or the game enters an unexpected state, the harness must:
1. Record the failure with full context (screen, action sequence, state before/after)
2. Attempt recovery (navigate back to a known screen)
3. Mark the feature FAILED, not skipped

A harness that silently discards failures to keep running is worse than no harness.

### P6 — Probabilistic Features Must Be Forced

Features that depend on RNG (travel hazards, combat encounters, gambling outcomes) cannot
be left to chance. A 30% encounter rate means a 50-turn run expects ~15 encounters but
could produce 0. The harness must use **RNG seams** — injectable random number generators
that can be set to deterministic values for specific test scenarios — to exercise
probabilistic features deterministically.

### P7 — The LLM Player Explains Its Reasoning

When an LLM is used to make player decisions, every action must include a `reasoning`
field and an `expectedOutcome`. These are not optional. They serve two purposes: (1) they
constrain the LLM to commit to a prediction before acting, improving reliability; and (2)
they make the test log human-readable, so a developer reviewing a failure can understand
what the agent was trying to do and why it failed.

---

## II. Architecture

```
┌───────────────────────────────────────────────────────────────┐
│                     FIND-FIX-REPEAT LOOP                      │
│                                                               │
│   ┌────────────┐    Bug     ┌──────────────┐   Fix    ┌────┐  │
│   │  Playtest  │ ─────────▶ │  Bug Report  │ ───────▶ │Dev │  │
│   │  Harness   │ ◀───────── │  + Repro     │ ◀─────── │Fix │  │
│   └────────────┘  Verify   └──────────────┘          └────┘  │
└───────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────┐
│         HARNESS LAYERS          │
│                                 │
│  ┌────────────────────────────┐ │
│  │    Layer 3: LLM Explorer   │ │  Adaptive, handles surprises
│  │  (Claude as player)        │ │  Slow, expensive, high fidelity
│  └────────────────────────────┘ │
│  ┌────────────────────────────┐ │
│  │    Layer 2: Scripted Cover │ │  Deterministic, fast, reliable
│  │  (Turn-planner engine)     │ │  Covers all mapped features
│  └────────────────────────────┘ │
│  ┌────────────────────────────┐ │
│  │    Layer 1: Unit Tests     │ │  Milliseconds, no browser
│  │  (Game logic assertions)   │ │  Catches regressions instantly
│  └────────────────────────────┘ │
└─────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────┐
│    GAME INTERFACE PROTOCOL      │
│                                 │
│  Press key → wait for screen    │
│  Read state → diff delta        │
│  Record feature → PASS/FAIL     │
└─────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────┐
│    YOUR GAME (the target)       │
│  (browser, terminal, or API)    │
└─────────────────────────────────┘
```

The layers are independent and can be run separately. Layer 1 (unit tests) runs on every
commit in under 10 seconds. Layer 2 (scripted coverage) runs on every feature branch in
5–15 minutes. Layer 3 (LLM exploration) runs before a release in 30–90 minutes.

---

## III. The Feature Map

The feature map is the contract between the game developer and the testing harness.
It is the **source of truth** for what "fully tested" means. It is written before the
harness is built.

### Format

```yaml
# feature-map.yaml
game: "MyGame"
version: "1.0"

screens:
  main-menu:
    description: "The central hub after login"
    entry_key: null  # first screen after auth

  traders:
    description: "Buy and sell fuel and cargo"
    entry_key: "T"
    exit_key: "M"
    features:
      - id: traders.open
        description: "Navigate to traders screen"
        action: press_key(T)
        from_screen: main-menu
        expected_screen: traders
        assertion: screen === 'traders'
        priority: critical

      - id: traders.buy_fuel
        description: "Purchase fuel"
        action: [press_key(B), type_and_enter('200')]
        from_screen: traders
        expected_screen: traders-buy-fuel
        assertion: state.fuel > before.fuel
        priority: critical
        precondition: state.credits > 500

      - id: traders.sell_fuel
        description: "Sell excess fuel"
        action: [press_key(S), type_and_enter('50')]
        from_screen: traders
        assertion:
          - state.fuel < before.fuel
          - state.credits > before.credits
        priority: major
        precondition: state.fuel > 200

      - id: traders.accept_cargo
        description: "Accept a cargo delivery contract"
        action: [press_key(A), type_and_enter('1'), type_and_enter('Y')]
        from_screen: traders
        assertion: state.cargo_pods > 0
        priority: critical
        precondition: state.cargo_pods === 0

  pub:
    entry_key: "P"
    exit_key: "M"
    features:
      - id: pub.visit
        action: press_key(P)
        assertion: screen === 'pub'
        priority: critical

      - id: pub.drink
        action: press_key(B)
        assertion: state.credits < before.credits
        priority: major

      - id: pub.gamble
        action: [press_key(W), type_and_enter('3'), type_and_enter('50')]
        assertion: state.credits !== before.credits  # could win or lose
        priority: minor
        precondition: state.credits > 200
        rng_controlled: true  # requires RNG seam to test both win/loss paths

# Features that depend on RNG must declare it
rng_features:
  - id: travel.hazard
    description: "Receive a travel hazard on arrival"
    trigger: post-navigation
    test_method: inject_rng(always_hazard=true)
    assertion: state.hull_condition < before.hull_condition OR state.shield < before.shield

  - id: combat.encounter
    description: "Enter combat during travel"
    trigger: post-navigation
    test_method: inject_rng(always_encounter=true)
    assertion: screen === 'combat'

# Priority definitions
priorities:
  critical: "Game cannot function without this — test first, fail loudly"
  major:    "Core gameplay loop — test in every full run"
  minor:    "Edge case or optional content — test when coverage allows"
```

### Coverage Status Output

The feature map drives coverage reporting. Every run produces:

```json
{
  "total_features": 47,
  "passed": 34,
  "failed": 5,
  "skipped": 3,
  "not_reached": 5,
  "coverage_pct": 72.3,
  "results": {
    "traders.buy_fuel": { "status": "PASSED", "delta": {"fuel": "+200"} },
    "traders.accept_cargo": { "status": "FAILED", "error": "cargo_pods unchanged after accept" },
    "combat.surrender": { "status": "NOT_REACHED", "reason": "no encounters in 50 turns" }
  }
}
```

---

## IV. The Game Interface Protocol

Every harness must implement this interface regardless of game type. Browser games use
Playwright; server-side games use direct function calls; terminal games use stdin/stdout.

```typescript
interface GameInterface {
  // Navigation
  pressKey(key: string): Promise<void>;
  typeAndEnter(text: string): Promise<void>;

  // State
  readState(): Promise<GameState>;
  detectScreen(): Promise<string | null>;
  getTerminalText(): Promise<string>;  // last N chars of terminal output

  // Synchronization — NEVER use fixed timeouts
  waitForScreen(name: string, timeoutMs?: number): Promise<void>;
  waitForText(pattern: RegExp, timeoutMs?: number): Promise<void>;

  // Recovery
  returnToKnownScreen(target: string): Promise<void>;

  // Lifecycle
  reset(): Promise<GameState>;     // start a new game session
  close(): Promise<void>;
}
```

### Screen Detection

Every harness must implement reliable screen detection. The canonical approach is to match
terminal text patterns:

```typescript
const SCREEN_PATTERNS: Record<string, RegExp> = {
  'main-menu':       /SPACER QUEST|Press D to end turn/i,
  'traders':         /TRADERS|Buy Fuel|Sell Fuel/i,
  'traders-buy-fuel':  /How many units|Buy Fuel:/i,
  'combat':          /COMBAT|Attack|Retreat|Surrender/i,
  'pub':             /Bar \& Pub|Drink|Wheel/i,
};

async function detectScreen(page: Page): Promise<string | null> {
  const text = await getTerminalText(page);
  for (const [screen, pattern] of Object.entries(SCREEN_PATTERNS)) {
    if (pattern.test(text)) return screen;
  }
  return null;
}
```

**Use the last N characters of terminal output** (e.g., `.slice(-600)`) to avoid matching
stale content from previous screens that's still in the terminal buffer.

### The Wait-for-Screen Contract

`waitForScreen` must poll, not sleep. This is the single most important reliability
improvement over naive scripted tests:

```typescript
async function waitForScreen(
  page: Page,
  expected: string,
  timeoutMs = 8000
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const current = await detectScreen(page);
    if (current === expected) return;
    await page.waitForTimeout(100);
  }
  const current = await detectScreen(page);
  throw new Error(
    `waitForScreen('${expected}') timed out. Current screen: '${current ?? 'unknown'}'`
  );
}
```

Fixed `setTimeout(300)` calls are the leading cause of timing-related test flakiness. Every
300ms pause is a bet that the game takes exactly that long to respond. Replace all of them.

---

## V. The Turn-Planner (Scripted Layer)

The scripted layer uses a **per-turn task list** architecture. It is the workhorse of the
harness — deterministic, fast, and capable of covering all mapped features without an LLM.

### The Algorithm

```typescript
async function runScriptedPlaytest(
  game: GameInterface,
  featureMap: FeatureMap,
  coverage: CoverageTracker,
  maxTurns: number = 50
): Promise<PlaytestReport> {
  const report = new PlaytestReport();

  for (let turn = 1; turn <= maxTurns; turn++) {
    // P4: Read state once. Decide once. Execute in sequence.
    const state = await game.readState();
    const tasks = buildTurnPlan(state, coverage, featureMap);

    for (const task of tasks) {
      const before = await game.readState();
      try {
        await executeTask(game, task, coverage);
        const after = await game.readState();
        report.recordResult(task.feature_id, 'PASSED', diff(before, after));
      } catch (err) {
        report.recordResult(task.feature_id, 'FAILED', { error: err.message });
        await game.returnToKnownScreen('main-menu');
      }
    }

    await advanceTurn(game);
  }

  return report;
}
```

### Building the Turn Plan

```typescript
function buildTurnPlan(
  state: GameState,
  coverage: CoverageTracker,
  featureMap: FeatureMap
): Task[] {
  const plan: Task[] = [];

  // 1. EMERGENCY: fix broken game state first
  if (state.hull_condition < 3 && state.credits > 1000)
    plan.push(task('repair'));

  if (state.fuel < 20 && state.credits > 500)
    plan.push(task('buy-fuel'));

  // 2. ACTIVE OBLIGATIONS: complete in-progress actions
  if (state.cargo_pods > 0 && state.destination > 0 && state.fuel >= 10)
    plan.push(task('deliver-cargo'));

  // 3. UNTESTED FEATURES: drive toward coverage (critical first, then major, then minor)
  for (const feature of featureMap.byPriority()) {
    if (!coverage.isPassed(feature.id) && meetsPreCondition(state, feature)) {
      plan.push(taskForFeature(feature));
    }
    if (plan.length >= 5) break;  // cap tasks per turn
  }

  // 4. FALLBACK: keep playing if nothing untested
  if (plan.length === 0) {
    plan.push(state.cargo_pods > 0 ? task('deliver-cargo') : task('get-cargo'));
  }

  return deduplicate(plan);
}
```

### Task Execution Template

Every task follows the same pattern:

```typescript
async function executeTask(
  game: GameInterface,
  task: Task,
  coverage: CoverageTracker
): Promise<void> {
  // Verify we start at main menu (invariant: all tasks start here)
  const screen = await game.detectScreen();
  if (screen !== 'main-menu') {
    throw new Error(`Task '${task.name}' started on wrong screen: '${screen}'`);
  }

  const before = await game.readState();

  // Execute the task's action sequence
  for (const step of task.steps) {
    if (step.type === 'press_key') {
      await game.pressKey(step.value);
      if (step.wait_for_screen) await game.waitForScreen(step.wait_for_screen);
      if (step.wait_for_text)   await game.waitForText(step.wait_for_text);
    } else if (step.type === 'type_and_enter') {
      await game.typeAndEnter(step.value);
    }
  }

  // Verify the assertion (P2: state delta is the assertion)
  const after = await game.readState();
  for (const assertion of task.assertions) {
    if (!evaluateAssertion(assertion, before, after)) {
      throw new Error(
        `Assertion failed for '${task.feature_id}': ${assertion}\n` +
        `Before: ${JSON.stringify(relevant(before, assertion))}\n` +
        `After:  ${JSON.stringify(relevant(after, assertion))}`
      );
    }
  }

  // Return to main menu (invariant: all tasks end here)
  if (task.exit_to_main) {
    await game.pressKey(task.exit_key ?? 'M');
    await game.waitForScreen('main-menu');
  }

  coverage.markPassed(task.feature_id);
}
```

---

## VI. The LLM Player (Exploratory Layer)

The LLM player is used when the scripted layer cannot handle a situation: a screen it
doesn't recognize, a conditional flow it wasn't programmed for, or an explicit "explore
freely for N turns" mode to find bugs the feature map didn't anticipate.

### The LLM Player Contract

The LLM receives exactly three inputs and produces exactly one output:

**Input 1: Terminal text** — the last 600 characters of the terminal output, verbatim.

**Input 2: Game context** — current screen, parsed game state, turn number, what features
have been covered, what features remain.

**Input 3: Strategy guide** — a short, human-readable document describing the game's rules,
what each screen is for, how to navigate between them, and what to watch for as bugs.
This is the most important input. The quality of the strategy guide determines the quality
of the agent.

**Output: A single action** — with reasoning, expected outcome, and confidence:

```typescript
interface LLMAction {
  type: 'press_key' | 'type_and_enter' | 'wait' | 'diagnose' | 'end_turn';
  value: string;
  reasoning: string;         // Why this action right now
  expected_outcome: string;  // What you expect to see after
  expected_screen?: string;  // What screen you expect to land on
  is_novel?: boolean;        // True if this exercises something the feature map missed
  potential_bug?: string;    // If the LLM suspects a bug in the current state
}
```

### The Strategy Guide

Write the strategy guide as if briefing a new QA tester who has never played the game.
It should be 1–3 pages. Include:

1. **The win condition** — how does a player succeed? What does the game consider "done"?
2. **The core loop** — what does a typical turn look like for a competent player?
3. **Screen map** — what keys go where, what each screen does in one sentence
4. **What good state looks like** — fuel > 100, cargo pod accepted, hull at 9
5. **Known edge cases** — what situations require unusual handling
6. **Bug signatures** — what does a broken screen look like vs. a working one?

```markdown
# SpacerQuest Strategy Guide (for the testing agent)

## Win Condition
Accumulate score points by delivering cargo and winning battles until reaching Conqueror rank
(10,000 pts), then fly to Maligna (system 27) or complete the Andromeda route.

## Core Loop (one turn)
1. Check fuel — buy if < 100 (T → B → type amount → Escape → M)
2. Accept cargo if no pods (T → A → type 1 → type Y → M)
3. Deliver cargo if pods > 0 and fuel OK (N → type destination → wait for arrival)
4. Visit shipyard if credits > 2000 and components < max (S → U → pick upgrade → M)
5. Press D to end turn

## Screen Map
- M key: return to main menu from anywhere
- T key: Traders (fuel, cargo)
- S key: Shipyard (upgrades, repairs)
- N key: Navigate (travel to another system)
- P key: Pub (gambling, drinks)
- B key: Bank (deposit, withdraw — unlocks at Commander rank)
- R key: Registry (Space Patrol, library)
- D key: End day/turn

## Bug Signatures
- You're on main menu but pressing T produces no screen change → navigation broken
- Fuel counter unchanged after buying fuel → economy bug
- Credits unchanged after delivering cargo → reward bug
- Screen shows "undefined" or "NaN" → data rendering bug
- Screen shows raw JSON → template not applied
- Turn counter not advancing after D → end-turn bug
```

### Prompting the LLM

```typescript
async function getLLMAction(
  game: GameInterface,
  coverage: CoverageTracker,
  strategyGuide: string
): Promise<LLMAction> {
  const terminalText = await game.getTerminalText();
  const state = await game.readState();
  const screen = await game.detectScreen();

  const prompt = `
You are playing ${GAME_NAME} as a QA tester. Your goal is to exercise untested features.

## Current Terminal Output (last 600 chars)
\`\`\`
${terminalText.slice(-600)}
\`\`\`

## Current State
Screen: ${screen ?? 'unknown'}
Turn: ${state.turn}
Credits: ${state.credits}
Fuel: ${state.fuel}

## Coverage Status
Passed: ${coverage.passed().join(', ')}
Still needed: ${coverage.remaining().slice(0, 10).join(', ')}

## Strategy Guide
${strategyGuide}

Choose exactly ONE action. Explain your reasoning. Predict what will happen.
If you see something that looks broken (wrong screen, missing data, unexpected state),
set potential_bug to describe it.

Respond in JSON matching the LLMAction schema.
`.trim();

  const response = await anthropic.messages.create({
    model: 'claude-opus-4-8',
    max_tokens: 512,
    messages: [{ role: 'user', content: prompt }],
  });

  return JSON.parse(extractJSON(response.content[0].text)) as LLMAction;
}
```

### LLM Player Loop

```typescript
async function runLLMPlaytest(
  game: GameInterface,
  coverage: CoverageTracker,
  strategyGuide: string,
  maxActions: number = 200
): Promise<PlaytestReport> {
  const report = new PlaytestReport();
  let consecutiveFailures = 0;

  for (let i = 0; i < maxActions; i++) {
    const action = await getLLMAction(game, coverage, strategyGuide);

    // Log potential bugs immediately
    if (action.potential_bug) {
      report.flagPotentialBug({
        action_number: i,
        description: action.potential_bug,
        terminal_text: await game.getTerminalText(),
        state: await game.readState(),
      });
    }

    const before = await game.readState();
    const before_screen = await game.detectScreen();

    // Execute
    if (action.type === 'press_key')      await game.pressKey(action.value);
    if (action.type === 'type_and_enter') await game.typeAndEnter(action.value);
    if (action.type === 'diagnose')       { await handleDiagnose(game, report, action); continue; }
    if (action.type === 'end_turn')       { await advanceTurn(game); continue; }

    // Wait for expected screen if declared
    if (action.expected_screen) {
      try {
        await game.waitForScreen(action.expected_screen, 5000);
        consecutiveFailures = 0;
      } catch {
        // Expected screen didn't appear — the reasoning was wrong or there's a bug
        const actual_screen = await game.detectScreen();
        report.recordScreenMismatch({
          expected: action.expected_screen,
          actual: actual_screen,
          action,
          reasoning: action.reasoning,
        });
        consecutiveFailures++;
        if (consecutiveFailures >= 3) {
          await game.returnToKnownScreen('main-menu');
          consecutiveFailures = 0;
        }
      }
    }

    const after = await game.readState();

    // Record if LLM marked this as novel (covers something outside the feature map)
    if (action.is_novel) {
      report.recordNovelBehavior(action, before, after);
    }
  }

  return report;
}
```

---

## VII. Bug Report Format

All bugs, whether found by the scripted layer or the LLM layer, are recorded in a standard
format. This format is designed to be consumed by a coding agent that will propose a fix.

```typescript
interface BugReport {
  // Identity
  id: string;                    // auto-generated, e.g. "BUG-2026-07-01-001"
  game: string;
  version: string;
  severity: 'critical' | 'major' | 'minor';

  // Location
  feature_id: string | null;     // from feature map, if applicable
  screen: string;                // screen where bug was observed
  layer: 'unit' | 'scripted' | 'llm';

  // Reproduction
  preconditions: Record<string, unknown>;  // game state before the failing action
  action_sequence: Action[];              // exact steps to reproduce
  post_state: Record<string, unknown>;    // game state after the failing action

  // Description
  expected: string;              // what should have happened
  actual: string;                // what actually happened
  delta: Record<string, unknown>; // diff of state before/after

  // Context
  terminal_text: string;         // last 600 chars of terminal when bug was detected
  timestamp: string;
  reproducible: boolean;         // was this verified across multiple runs?
  suggested_fix?: string;        // LLM's hypothesis about root cause (if available)
}
```

### Example Bug Report

```json
{
  "id": "BUG-2026-07-01-003",
  "game": "SpacerQuest",
  "version": "4.0",
  "severity": "critical",
  "feature_id": "traders.buy_fuel",
  "screen": "traders-buy-fuel",
  "layer": "scripted",
  "preconditions": {
    "credits": 2500,
    "fuel": 45,
    "screen": "traders"
  },
  "action_sequence": [
    { "type": "press_key", "value": "T" },
    { "type": "press_key", "value": "B" },
    { "type": "type_and_enter", "value": "200" }
  ],
  "post_state": {
    "credits": 2500,
    "fuel": 45
  },
  "expected": "fuel > 45 AND credits < 2500 after purchasing 200 units",
  "actual": "fuel and credits unchanged — purchase had no effect",
  "delta": {},
  "terminal_text": "Buy Fuel:\nAmount: 200\nProcessing...\nTraders Menu",
  "timestamp": "2026-07-01T14:32:11Z",
  "reproducible": true,
  "suggested_fix": "The buy-fuel handler may not be committing the transaction. Check that the POST /api/economy/buy-fuel endpoint is being called and that the response is being applied to game state."
}
```

---

## VIII. The Find-Fix-Repeat Loop

This is the operating model for using the harness during active game development.

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│  1. RUN SCRIPTED COVERAGE                                       │
│     ugt-harness run --mode scripted --config feature-map.yaml   │
│     → produces coverage report + bug reports                    │
│                                                                 │
│  2. TRIAGE FAILURES                                             │
│     for each FAILED feature:                                    │
│       - is this a known bug? → skip (already tracked)          │
│       - is this a new regression? → HIGH priority              │
│       - is this a first-time failure? → NORMAL priority        │
│                                                                 │
│  3. CODING AGENT FIXES                                          │
│     for each bug report:                                        │
│       - agent reads BugReport.action_sequence                   │
│       - agent reads BugReport.expected vs BugReport.actual      │
│       - agent searches source for the relevant handler          │
│       - agent proposes fix + writes test                        │
│                                                                 │
│  4. VERIFY THE FIX                                              │
│     ugt-harness run --mode targeted --feature traders.buy_fuel  │
│     → re-runs only the failed feature                           │
│     → if PASSED: mark bug resolved                              │
│     → if FAILED: escalate to LLM explorer                       │
│                                                                 │
│  5. REGRESSION CHECK                                            │
│     ugt-harness run --mode scripted                             │
│     → verify the fix didn't break adjacent features             │
│                                                                 │
│  6. LLM EXPLORATION (pre-release only)                          │
│     ugt-harness run --mode llm --max-actions 300                │
│     → finds bugs outside the feature map                        │
│     → reports novel behaviors as new feature map candidates     │
│                                                                 │
│  Repeat from step 1 until coverage = 100% and 0 FAILED.        │
└─────────────────────────────────────────────────────────────────┘
```

### Cadence

| Event | Layers run | Expected time | Trigger |
|-------|-----------|---------------|---------|
| Every commit | Layer 1 only | < 30s | Pre-push hook |
| Every PR | Layer 1 + 2 | 5–15 min | CI |
| Pre-release | All three | 30–90 min | Manual / nightly |
| After a bug fix | Layer 2 targeted | 1–3 min | Manual |

---

## IX. RNG Seams

Any game feature that depends on probability must have an injectable RNG so the harness
can test both the "event fires" and "event doesn't fire" paths deterministically.

### The Seam Pattern (TypeScript)

```typescript
// In your game code:
export type RngFn = () => number;
const defaultRng: RngFn = Math.random;

export function generateHazard(
  distance: number,
  rng: RngFn = defaultRng
): HazardResult {
  const roll = rng();
  if (roll < 0.15) return { type: 'hull_damage', amount: Math.floor(rng() * 5) + 1 };
  if (roll < 0.25) return { type: 'shield_drain', amount: 1 };
  return { type: 'none' };
}

// In your test:
const alwaysHazard: RngFn = () => 0.05;  // always below 0.15 threshold
const neverHazard:  RngFn = () => 0.99;  // always above all thresholds

const hazard = generateHazard(10, alwaysHazard);
assert(hazard.type !== 'none');
```

### The Seam Pattern (Python)

```python
import random
from typing import Callable

RngFn = Callable[[], float]

def generate_encounter(distance: int, rng: RngFn = random.random) -> dict:
    if rng() < 0.30:
        return {"type": "combat", "enemy_strength": int(rng() * 100)}
    return {"type": "safe"}

# In test:
always_encounter = lambda: 0.01
never_encounter  = lambda: 0.99
```

**Rule:** Every function that calls `Math.random()` or `random.random()` must accept an
`rng` parameter with the default as the system random. No exceptions. This is enforced
at code review. Functions that hardcode `Math.random()` are untestable.

---

## X. Implementation Guide — Porting to a New Game

To build a harness for a new game, follow these steps in order. Estimated time per step
is included for planning purposes.

### Step 1: Write the Feature Map (2–4 hours)

Before touching any code, enumerate every player-accessible feature. For each feature:
- What screen is it on?
- What key sequence triggers it?
- What state change proves it worked?
- Is it gated behind a precondition?
- Does it depend on RNG?

If you cannot write the assertion (the state change that proves it worked), you cannot
test the feature. The game must expose readable state.

### Step 2: Implement the Game Interface (4–8 hours)

Write the `GameInterface` adapter for your game:
- Browser game: Playwright + `page.evaluate()` for `readState()`
- Server-side game: direct function calls on the game logic
- Terminal game: stdin/stdout + parsing terminal output

Write `detectScreen()` using terminal text patterns. Write `waitForScreen()` using polling.
Never use `setTimeout()` for synchronization.

### Step 3: Write the Strategy Guide (1–2 hours)

Write 1–3 pages describing the game to an LLM that has never played it. Focus on:
- What winning looks like
- The core loop
- The screen map
- Bug signatures (what does broken look like?)

### Step 4: Implement RNG Seams (varies — 30 min per feature)

For every probabilistic feature in your feature map, add an `rng` parameter to the
generating function in your game code. This is a code change to the game, not to the
harness. It must happen before you can test those features deterministically.

### Step 5: Build the Scripted Task Library (4–12 hours)

For each feature in your feature map, write a task:
- The action sequence (press_key / type_and_enter calls)
- The assertion (state delta check)
- The precondition check
- The exit path back to main menu

Wire tasks into the turn-planner's `buildTurnPlan` function.

### Step 6: Smoke Test (30 min)

Run the harness for 5 turns with verbose logging. Verify:
- All tasks start and end on main menu
- State reads are returning real data (not zeros or nulls)
- Screen detection is accurate
- At least 3–5 features PASS

### Step 7: Full Coverage Run (ongoing)

Run the harness for 50 turns. Review the coverage report. For every FAILED or NOT_REACHED
feature:
- NOT_REACHED: the turn planner isn't selecting the feature — check the priority and
  precondition logic
- FAILED: there is either a bug in the game or a bug in the assertion — read the delta
  carefully to distinguish

### Step 8: Add LLM Exploration

Add the LLM player using the strategy guide from Step 3. Run it for 200 actions before
a release to find bugs outside the feature map. Every novel behavior the LLM flags should
become a new feature map entry if it represents a real game action.

---

## XI. What This Framework Is Not

Clarity on scope prevents scope creep:

**Not a balance tester.** This framework tests correctness — whether features work as
designed. Whether the game is balanced (are some strategies too powerful? can a trained
agent beat it?) is a separate question answered by UGT's RL pipeline. Run this framework
first; run UGT second.

**Not a regression suite.** The feature map is not a unit test suite. It is a live
integration test that requires a running game. Unit tests (Layer 1) are the regression
suite. This framework is the integration layer.

**Not a performance tester.** Response time, throughput, and load testing are separate
disciplines. This framework measures correctness of game behavior, not speed.

**Not a substitute for human playtesting.** This framework finds broken features. It
cannot find "this mechanic is confusing" or "this UI feels wrong" or "the pacing is off."
Those require a human. The goal is to eliminate the category of bug a human would find
in the first five minutes of play — so the human's time is spent on the harder,
judgment-dependent questions.

---

## Appendix: Diagnostic Mode

When the LLM player cannot determine where it is or what to do, it emits `{ type: "diagnose" }`.
The harness handles diagnosis:

```typescript
async function handleDiagnose(
  game: GameInterface,
  report: PlaytestReport,
  action: LLMAction
): Promise<void> {
  const terminal = await game.getTerminalText();
  const state = await game.readState();
  const screen = await game.detectScreen();

  const diagnosisPrompt = `
The QA agent is confused. Current state:
Screen detected: ${screen ?? 'UNKNOWN'}
Terminal output: ${terminal.slice(-600)}
Game state: ${JSON.stringify(state, null, 2)}

Is this a game bug, or is the agent confused about where it is?
If it is a bug, describe it precisely.
If the agent is confused, list recovery actions (key sequence) to return to main menu.
`.trim();

  const response = await anthropic.messages.create({
    model: 'claude-opus-4-8',
    max_tokens: 256,
    messages: [{ role: 'user', content: diagnosisPrompt }],
  });

  const diagnosis = JSON.parse(extractJSON(response.content[0].text)) as DiagnosisResult;

  if (diagnosis.is_bug) {
    report.flagPotentialBug({
      description: diagnosis.problem,
      terminal_text: terminal,
      state,
      action_number: -1,
    });
  }

  // Attempt recovery regardless
  for (const recoveryAction of diagnosis.recovery_actions) {
    if (recoveryAction.type === 'press_key') await game.pressKey(recoveryAction.value);
    await game.waitForTimeout(300);
    if (await game.detectScreen() === 'main-menu') break;
  }
}
```
