# UGT — Universal Game Tester: User Manual

> **Purpose of this document:** A practical, end-to-end guide for plugging a new game into UGT,
> teaching it the rules, and running the three test phases in the correct order.
>
> **What this is not:** a tutorial on any single testing technique. You need to understand your
> game's state, actions, and win condition — UGT handles the rest.

---

## Methodology & Hard-Won Lessons (read before onboarding a new game)

> **Canonical source: [`LESSONS.md`](LESSONS.md).** That file is the cross-game lessons registry — every rule
> here plus the LLM-playtest pre-flight audit (section B) and the operational discipline rules (section C),
> each with its evidence and source. Read it before onboarding a game, before advancing a ladder rung, and
> before any LLM playtest run. New lessons go there, not here.

The nine core rules, as one-line index entries only — **the full text and the evidence behind each live in
`LESSONS.md` §A**, the single canonical copy; if a line below ever disagrees with LESSONS, LESSONS wins:

- **M1 · Drive the REAL game, never a re-implementation.** If your adapter contains game *rules*, you're
  testing the adapter, not the game. (A simulation bridge that quietly dropped combat is the founding lesson.)
- **M2 · Dual validation** — finding a real game bug and pausing to fix it upstream is a success, not a
  distraction.
- **M3 · Failed tests are data** — record negative results so the next session doesn't re-learn them.
- **M4 · Prove learnability cheaply** before spending compute.
- **M5 · Verify ≠ Train ≠ Play** — a verifier crutch (extra credits, perfect nav) doesn't prove reachability
  under real play.
- **M6 · Reward realized outcomes, not activity** — express play styles as reward *weights*, not by hiding
  actions.
- **M7 · Right tool per question** — correctness → verify; robustness → exploit-hunter; balance → LLM
  playtester. Don't force one agent to answer all three.
- **M8 · Test over the wire** — a green in-process suite cannot see serialization-boundary bugs.
- **M9 · Audit your own findings** before citing them; record corrections rather than deleting them.

> The tier model below is the current shape: keep the phase *order* (cheap correctness first), and pick
> the agent per the "right tool per question" rule (M7) above.

---

## The Three-Tier Testing Model

**Run these in order. Each tier depends on the previous one being healthy.**

| Tier | Command / mechanism | Question answered | Output file |
|------|---------------------|--------------------|-------------|
| **1. Verify** | `ugt verify` | Does each game feature work correctly? (correctness) | `results/coverage-report.json` |
| **2. Exploit-hunter** | `ugt/core/exploit_hunter.py` — R3 of the trial ladder | Does the game break under random/heuristic pressure? (robustness) | printed `[FINDING]`s + the round's PASS/FAIL footer |
| **3. LLM playtest** | `ugt playtest` | Is the game *good*? Does it feel right to a reasoning player? (balance/judgment) | `results/playtest-report.json` |

> **Why order matters:** tier 3 verdicts on a game that still crashes under tier 2 are noise, and tier 2 on a
> game whose features don't even work under tier 1 is a waste of a random walk. Tier 1 is cheap (minutes); do
> it first.
>
> Use `ugt smoke-test` before Tier 1 as a quick sanity check that the bridge is responding.

### The trial ladder (how integrations actually run Tiers 1–2)

In practice, every real integration (see `integrations/<game>/`) climbs a standardized **trial ladder** of
fail-closed gate scripts rather than the bare CLI commands — five rungs, each with its own exit criteria:

| Rung | Script | What it proves | Exit criteria |
|---|---|---|---|
| **Spike** | `spike_<game>.py` | The raw protocol round-trips headlessly (create/auth → act → read state back) | Every raw-protocol check passes; no protocol quirk left unresolved before writing the adapter |
| **Smoke** | `smoke_<game>_adapter.py` | The same round-trip works through UGT's `BaseAdapter` contract | Same checks pass via `connect()`/`reset()`/`step()`/`close()`, not the raw protocol directly |
| **R1 — playability** | `verify_round1.py` | One scripted full loop of the core game, invariants checked after every command | Every invariant holds across the whole loop; the loop reaches a real, meaningful state change (not a no-op); same-seed reproducible |
| **R2 — full spine** | `verify_round2.py` | Every major mode/system driven to a real outcome (e.g. an actual win), still under invariants | Every mode reaches a genuine terminal outcome under the same invariants; the check count (denominator) is disclosed honestly — no vacuous passes, none silently narrowed or widened |
| **R3 — exploit-hunter** | `verify_round3.py` | Random/heuristic walks (`ugt/core/exploit_hunter.py`) asserting the SAME invariants after every step, across multiple seeded episodes | Zero invariant violations/crashes across every episode and step; every action in the vocabulary exercised at least once; a same-seed replay is byte-identical (determinism) |

The game-agnostic skeleton lives in `ugt/core/trial.py`: `GateRunner` (the `[PASS]`/`[FAIL]` accumulator,
`[FINDING]` registry, and the fail-closed "ROUND N MET — p/t" footer), `InvariantSuite` (one predicate
definition reused by both the scripted rounds and the exploit-hunter, so the tiers can't drift apart), and
`first_divergence` (replay compare). Everything game-specific — predicates, probes, policies, state
normalization — stays in the game's `integrations/<game>/` files. A failed check is DATA: findings print
inline, fail the gate, and get fixed upstream in the game.

> **Worked example:** `examples/harness-game/` is a complete, dependency-free implementation of this whole
> ladder — a tiny deterministic game (`engine.py`) driven engine-first over a JSON-lines harness through a
> transport-only adapter, with all five rungs (`spike_foraging.py` … `verify_round3.py`) runnable in one
> command. It is the fastest way to see the ladder, the invariant-suite reuse across R1/R2/R3, and the
> exploit-hunter + determinism check in action. Read its `README.md` first.

### What happens once R3 passes

R3 answers "does it work / does it break" — it does **not** answer "is it good." A green ladder is the
*prerequisite* for the next tier, not the end of testing:

1. **Tier 3 — LLM playtest** (`ugt playtest`, §8 below). An LLM plays through a realistic input channel
   (keypresses, typed terminal commands, or a legal-action list for harness-style games with no terminal)
   and judges balance/strategy, producing `results/playtest-report.json` with state-delta-based bug reports.
   Only makes sense once the ladder is green — balance verdicts on a game that still crashes are noise.
2. **Human / frontend UAT** — a real person plays the actual UI. Not yet CLI-automated by UGT, but the
   established next step after a clean LLM playtest: things like visual readability, animation feel,
   onboarding clarity, and accessibility that no automated tier can see by construction (an engine-level or
   LLM-driven test can confirm the mechanics work; only a human can confirm the game *reads* well). Every
   integration's `HANDOFF.md` should carry a UAT status line once this tier is reached.

---

## Table of Contents

1. [What UGT Does](#1-what-ugt-does)
2. [How It Works (The Big Picture)](#2-how-it-works-the-big-picture)
3. [Installation](#3-installation)
4. [Connecting Your Game — The Bridge](#4-connecting-your-game-the-bridge)
   - 4a. Subprocess Bridge (headless / simulation games)
   - 4b. Browser Bridge (browser / React / Phaser games)
5. [Teaching UGT the Rules — `ugt.config.yaml`](#5-teaching-ugt-the-rules--ugtconfigyaml)
   - 5a. Observation Space
   - 5b. Action Space
6. [Phase 1 — Verify (Correctness Testing)](#6-phase-1--verify-correctness-testing)
   - 6a. Writing a Feature Map
   - 6b. Running `ugt verify`
   - 6c. Reading the Coverage Report
   - 6d. Troubleshooting Verify
7. [Quick Sanity Check — `ugt smoke-test`](#7-quick-sanity-check--ugt-smoke-test)
8. [Phase 2 — Playtest (LLM Player)](#8-phase-2--playtest-llm-player)
   - 8a. Writing a Strategy Guide
   - 8b. Running `ugt playtest`
   - 8c. Reading the Playtest Report
9. [Frontend UI Testing (Browser Games)](#9-frontend-ui-testing-browser-games)
10. [Configuration Reference](#10-configuration-reference)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. What UGT Does

UGT runs three tiers of testing against a game, each answering a different question (see "The Three-Tier
Testing Model" above for the full table and exit criteria):

| Tier | Tool | Question answered | Time |
|------|------|--------------------|------|
| **1. Verify** | `ugt verify` | Does each feature work? (correctness) | ~minutes |
| **2. Exploit-hunter** | R3 of the trial ladder | Does the game break under pressure? (robustness) | ~minutes |
| **3. Playtest** | `ugt playtest` | Does the game feel right to a reasoning agent? (balance) | ~30 min |

All three tiers share the same `ugt.config.yaml` and bridge protocol. Once your bridge is written, all three
are available.

---

## 2. How It Works (The Big Picture)

```
┌─────────────────────────────────────────────────────────────┐
│                        ugt.config.yaml                       │
│      (observation space, action space, seed)                 │
└──────────────────────────┬──────────────────────────────────┘
                           │ read by
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                     UGT Python Core                          │
│                    cli.py (ugt command)                      │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐ │
│  │  verifier.py │  │ exploit_hunter│  │  playtester.py     │ │
│  └──────┬───────┘  └──────┬───────┘  └─────────┬──────────┘ │
│         │                 │                     │            │
│  ┌──────▼─────────────────▼─────────────────────▼──────────┐ │
│  │            an adapter (BaseAdapter subclass)              │ │
│  └──────────────────────────┬────────────────────────────── ┘ │
└─────────────────────────────┼───────────────────────────────┘
                              │ one adapter per engine.type
              ┌───────────────┴──────────────────┐
              │                                  │
              ▼                                  ▼
  ┌───────────────────────┐        ┌────────────────────────────┐
  │  SubprocessAdapter    │        │  PlaywrightAdapter          │
  │  (headless sim games) │        │  (browser / frontend games) │
  │  JSON over stdin/out  │        │  window.__GET_STATE__ etc.  │
  └──────────┬────────────┘        └──────────────┬─────────────┘
             │                                    │
             ▼                                    ▼
  ┌──────────────────────┐         ┌──────────────────────────┐
  │  Your game's bridge  │         │  Your game's frontend     │
  │  (sim_bridge.py/ts)  │         │  (served at localhost)    │
  └──────────────────────┘         └──────────────────────────┘
```

UGT never imports your game code directly. It talks to your game through a **bridge** — a thin wrapper that translates UGT's standard protocol into your game's API. You write the bridge; UGT handles everything else.

The diagram shows the two engine types this manual walks through (`simulation` and `browser`) — the two
that `env.py` dispatches for you. Anything else (a live server over HTTP, a TCP socket to a game engine's
frame loop, a JSON-lines harness) declares `engine.type: custom` and supplies its own transport-only
`BaseAdapter` subclass, which the integration's own ladder scripts construct directly; the scripts in
`examples/harness-game/` show that shape end to end.

---

## 3. Installation

```bash
# From the UGT directory:
pip install -e .

# Verify installation:
ugt --help

# For browser (UI) testing, install Playwright browsers:
pip install playwright
playwright install chromium
```

---

## 4. Connecting Your Game — The Bridge

The bridge is the only piece of code you write. It wraps your game engine in a standard protocol that UGT understands. Pick the engine type that matches how your game runs:

| Your game... | engine.type | Bridge pattern |
|---|---|---|
| ...is a headless subprocess (Python sim, TypeScript harness, Godot/Unity CLI build) | `simulation` | JSON-lines over stdin/stdout (`SubprocessAdapter`) |
| ...runs in a browser (React, Phaser, Vue, vanilla JS, any web frontend) | `browser` | Headless Chromium via Playwright; your game exposes `window.__GET_STATE__` / `window.__SEND_ACTION__` hooks (`PlaywrightAdapter`) |
| ...is anything else (a live server over HTTP/WebSocket, a TCP bridge into an engine's frame loop) | `custom` | You write a small transport-only `BaseAdapter` subclass; your ladder scripts construct it directly (`env.py` does not dispatch it). See `examples/harness-game/` |

Not sure? **Subprocess is the most portable starting point** — `examples/harness-game/` shows it end-to-end with zero dependencies. If your game has a frontend you want to drive through UI interactions, use Browser. Reach for `custom` only when neither transport fits — it costs you a small adapter, but nothing else in the ladder changes.

### 4a. Subprocess Bridge (headless / simulation games)

The subprocess bridge communicates via **newline-delimited JSON on stdin/stdout**. UGT spawns your bridge as a child process, sends commands, and reads responses.

**Protocol:**

| UGT sends → | Your bridge responds → |
|-------------|----------------------|
| `{"command": "reset"}` | `{"state": {...}}` |
| `{"command": "step", "action_id": 3}` | `{"state": {...}, "terminated": bool, "truncated": bool, "info": {}}` |
| `{"command": "close"}` | *(no response required)* |

**Minimal Python bridge template:**

```python
#!/usr/bin/env python3
import sys
import json
import os

# --- Your game import goes here ---
# from my_game import create_game, apply_action

class MyGameBridge:
    def __init__(self):
        self.game = None
        # Read UGT_SEED for reproducible episode sequences
        self.base_seed = int(os.environ.get("UGT_SEED", 12345))
        self.episode_count = 0

    def reset(self):
        episode_seed = self.base_seed + self.episode_count
        self.episode_count += 1
        self.game = create_game(seed=episode_seed)
        return self._build_state()

    def step(self, action_id):
        result = apply_action(self.game, action_id)
        terminated = self.game.is_over()
        truncated = self.game.turn_count >= 200  # step limit
        return self._build_state(), terminated, truncated, {}

    def _build_state(self):
        """Return a flat or nested dict of game state values."""
        return {
            "player": {
                "credits": self.game.player.credits,
                "health":  self.game.player.health,
            },
            "turn": self.game.turn_count,
            "player_won": self.game.winner == "player",
        }


def main():
    bridge = MyGameBridge()
    for line in sys.stdin:
        msg = json.loads(line.strip())
        command = msg.get("command")

        if command == "reset":
            state = bridge.reset()
            print(json.dumps({"state": state}), flush=True)

        elif command == "step":
            state, terminated, truncated, info = bridge.step(msg["action_id"])
            print(json.dumps({
                "state": state,
                "terminated": terminated,
                "truncated": truncated,
                "info": info,
            }), flush=True)

        elif command == "close":
            break

if __name__ == "__main__":
    main()
```

**Key rules for your bridge:**
- Always call `sys.stdout.flush()` (or use `flush=True` in `print`). UGT blocks waiting for a response — if you don't flush, it hangs forever.
- `terminated` = the game reached a natural end state (win or loss). `truncated` = a step limit was hit.
- Read `UGT_SEED` from the environment at startup and use it to seed your RNG. Increment per episode (`base_seed + episode_count`). This makes runs reproducible across identical configs.
- The `state` dict can be nested (e.g., `state.player.credits`). Dot-notation paths in the config traverse nested dicts.
- Never write anything to stdout except your JSON responses. Use stderr for debug output: `print("debug", file=sys.stderr)`.

**TypeScript bridge template:**

UGT can also spawn a TypeScript bridge using `tsx`:

```typescript
// sim_bridge.ts
import * as readline from 'readline';
import { createGame, applyAction } from './my_game.js';

const rl = readline.createInterface({ input: process.stdin });
let game = createGame();
const baseSeed = parseInt(process.env.UGT_SEED ?? '12345', 10);
let episodeCount = 0;

function buildState() {
    return {
        player: { credits: game.player.credits },
        turn:   game.turn,
        player_won: game.winner === 'player',
    };
}

rl.on('line', (line) => {
    const msg = JSON.parse(line);

    if (msg.command === 'reset') {
        game = createGame({ seed: baseSeed + episodeCount++ });
        process.stdout.write(JSON.stringify({ state: buildState() }) + '\n');

    } else if (msg.command === 'step') {
        applyAction(game, msg.action_id);
        const terminated = game.isOver();
        const truncated  = game.turn >= 200;
        process.stdout.write(JSON.stringify({
            state: buildState(), terminated, truncated, info: {}
        }) + '\n');

    } else if (msg.command === 'close') {
        process.exit(0);
    }
});
```

In your config, set `engine.entry: "node --import tsx sim_bridge.ts"`.

---

### 4b. Browser Bridge (browser / frontend games)

For browser games, UGT launches a headless Chromium browser and communicates through three global JavaScript functions that you inject into your game's frontend.

**You must expose these three functions on `window`:**

```javascript
// 1. Returns the current game state as a plain JSON object
window.__GET_STATE__ = function() {
    return {
        player: { credits: game.credits, health: game.health },
        turn:   game.turn,
        player_won: game.isWon(),
    };
};

// 2. Executes an action and returns structured response
window.__SEND_ACTION__ = function(actionId) {
    // Apply the action to game state
    game.applyAction(actionId);

    const terminated = game.isOver();
    const truncated  = game.turn >= 200;

    return {
        state:      window.__GET_STATE__(),
        terminated: terminated,
        truncated:  truncated,
        info:       {},
    };
};

// 3. (Recommended) Soft-reset without a full page reload
//    Without this, UGT falls back to page.reload() which takes ~15 seconds per episode
window.__RESET_GAME__ = function() {
    game.reset();
    window.__STEP_COMPLETE__ = false;
};
```

**Optional: `__STEP_COMPLETE__` flag for async games**

If your game processes actions asynchronously (animations, network calls), set `window.__STEP_COMPLETE__ = true` when the state is ready for reading. UGT will wait for this flag before moving on, instead of using a fixed delay.

```javascript
window.__SEND_ACTION__ = async function(actionId) {
    window.__STEP_COMPLETE__ = false;
    await game.applyAction(actionId);  // async operation
    window.__STEP_COMPLETE__ = true;
    return { state: window.__GET_STATE__(), terminated: game.isOver(), truncated: false, info: {} };
};
```

**For React / Vue games:** inject the hooks in a `useEffect` or `onMounted` that runs after the game state is initialized:

```javascript
// React example
useEffect(() => {
    window.__GET_STATE__  = () => ({ ...gameState });
    window.__SEND_ACTION__ = (id) => { dispatch({ type: 'ACTION', id }); ... };
    window.__RESET_GAME__  = () => dispatch({ type: 'RESET' });
}, [gameState]);  // re-register when state updates if closures need it
```

In your config, set `engine.type: "browser"` and `engine.entry: "http://localhost:8080"`.

---

## 5. Teaching UGT the Rules — `ugt.config.yaml`

The config file is the only place you describe your game to UGT. Start with a template:

```bash
ugt init   # creates ugt.config.yaml in the current directory
```

Then fill in the three sections below.

---

### 5a. Observation Space

**What it is:** The set of numeric values UGT can read from your game state. Think of this as "what the agent can see."

```yaml
observation_space:
  type: "box"
  shape: 6           # must equal the number of mappings below
  mappings:
    - path: "player.credits"    # dot-path into the state dict your bridge returns
      min: 0
      max: 100000               # the expected range; used to normalize inputs
    - path: "player.health"
      min: 0
      max: 100
    - path: "turn"
      min: 0
      max: 200
    - path: "enemy.strength"
      min: 0
      max: 1000
    - path: "player_won"        # boolean fields are fine: false=0, true=1
      min: 0
      max: 1
    - path: "inventory.weapons" # lists can use an aggregator
      aggregator: "count"       # options: count | sum | mean | min | max
      min: 0
      max: 20
```

**Practical guidance:**
- **Include everything that affects a good player's decision.** If a good player would look at it, include it.
- **Set `min`/`max` to the actual game range**, not just 0 and infinity. The agent learns faster when values are normalized. A credit balance of 50,000 in a range of 0–100 is extremely confusing; in a range of 0–100,000 it's normal.
- **You can start with 4–8 features.** More is not always better. Start simple, add features when you see the agent making decisions that no reasonable player would make.
- **Boolean flags** (is_in_combat, has_item) are valuable — include them.
- **Don't include derived/redundant values.** If you have `health` and `max_health`, don't also include `health_percent` — the agent can reason about the ratio itself.

---

### 5b. Action Space

**What it is:** The set of discrete actions the agent can take. Think of this as "the buttons a player can press."

```yaml
action_space:
  type: "discrete"
  size: 5            # must equal the number of actions below
  actions:
    0: { name: "wait" }
    1: { name: "attack_nearest" }
    2: { name: "retreat" }
    3: { name: "buy_health" }
    4: { name: "end_turn" }
```

**Practical guidance:**
- **Actions map to agent integer IDs.** When your bridge receives `{"command": "step", "action_id": 2}`, action 2 (`retreat`) should execute.
- **Handle illegal actions in your bridge, not in the config.** If the player can't buy health when broke, your `step()` should treat action 3 as a no-op in that state (just return the current state unchanged). Don't crash.
- **Keep the action space small to start** (5–15 actions). The agent learns faster with fewer choices. You can always expand it later.
- **Parameterized actions must be pre-defined as macros.** If your game has "attack enemy X" where X is one of 5 enemies, you need 5 separate action IDs: `attack_enemy_0`, `attack_enemy_1`, etc. There is no built-in support for parameterized actions.
- **Every action should be reachable.** If some action is never legal, remove it from the list — it wastes the agent's capacity.

---

## 6. Phase 1 — Verify (Correctness Testing)

`ugt verify` drives your game through a feature map — a YAML file listing every testable behavior — and checks that each feature's state change is what you declared. Run this before playtesting.

### 6a. Writing a Feature Map

Create `feature-map.yaml` alongside your `ugt.config.yaml`. Each entry names an action (by the action name from your config), states what must be true after it runs, and optionally defines a precondition.

```yaml
# feature-map.yaml
game: "MyGame"
version: "1.0"

features:
  - id: economy.invest_increases_credits
    description: "Investing increases the player credit balance"
    action: "invest_credits"          # name from action_space.actions in your config
    assertion: "state.player.credits > before.player.credits"
    priority: critical                # critical | major | minor
    precondition: "state.player.ap >= 2"  # optional: skip if not met

  - id: game.end_turn_advances_counter
    description: "Ending the turn increments the turn counter"
    action: "end_turn"
    assertion: "state.turns_elapsed > before.turns_elapsed"
    priority: critical

  - id: game.win_condition
    description: "Reaching 500 credits triggers victory"
    action: "invest_credits"
    assertion: "state.victory == True"
    priority: critical
    precondition: "state.player.credits >= 450 and state.player.ap >= 2"
```

**Assertion syntax:**
- `state.X` — the game state *after* the action
- `before.X` — the game state *before* the action
- Operators: `>`, `<`, `==`, `!=`, `>=`, `<=`, `and`, `or`, `not`
- Action names must exactly match the `name:` fields in `action_space.actions` in your config

**Priority values:**
- `critical` — game cannot function without this; tested first
- `major` — core gameplay loop; always tested
- `minor` — edge case or optional content; tested when time allows

**Action sequences:** Use a YAML list when a feature requires multiple steps:
```yaml
  - id: traders.buy_then_sell
    action:
      - "buy_fuel"
      - "sell_fuel"
    assertion: "state.credits != before.credits"
    priority: major
```

### 6b. Running `ugt verify`

```bash
cd examples/your-game/
ugt verify --config ugt.config.yaml --feature-map feature-map.yaml
# Options:
#   --max-turns 50     how many turns to drive the game (default: 50)
#   --output path.json custom output path (default: results/coverage-report.json)
```

### 6c. Reading the Coverage Report

`results/coverage-report.json`:

```json
{
  "game": "MyGame",
  "total_features": 6,
  "passed": 4,
  "failed": 1,
  "not_reached": 1,
  "coverage_pct": 66.7,
  "results": {
    "economy.invest_increases_credits": {
      "status": "PASSED",
      "delta": { "player.credits": "+50", "player.ap": "-2" }
    },
    "economy.invest_costs_ap": {
      "status": "FAILED",
      "error": "Assertion failed: state.player.ap < before.player.ap",
      "before": { "player": { "credits": 100, "ap": 10 } },
      "after":  { "player": { "credits": 150, "ap": 10 } }
    },
    "game.win_condition": {
      "status": "NOT_REACHED",
      "note": "precondition never met in 50 turns"
    }
  }
}
```

- **PASSED** — the assertion held; the feature works as declared
- **FAILED** — the assertion did not hold; there is a bug or your assertion is wrong
- **NOT_REACHED** — the precondition was never met; either the feature is unreachable in the test window or the precondition expression is wrong

### 6d. Troubleshooting Verify

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| All features `NOT_REACHED` | Preconditions never satisfied | Check state path spelling; log `current_state` during a smoke-test |
| `FeatureMapError: action 'invest_credits' not found` | Action name mismatch | Check the exact `name:` value in your config's `action_space.actions` |
| Assertion always FAILED but state looks right | State path typo in assertion | Compare the `before` and `after` fields in the report to spot the actual path |
| `game.win_condition` NOT_REACHED | Credits don't reach 450 in 50 turns | Increase `--max-turns` or check if the precondition is achievable |
| Verifier crashes with `RuntimeError` | Bridge connection issue | Run `ugt smoke-test` first to confirm the bridge is working |

---

## 7. Quick Sanity Check — `ugt smoke-test`

The smoke test verifies that your bridge responds correctly before you write a feature map. Takes ~10
seconds, requires no model or feature map.

```bash
cd examples/your-game/
ugt smoke-test --config ugt.config.yaml
```

**What it tests:** bridge connectivity, state dict structure, observation vector mapping. It does NOT test
whether game features behave correctly — use `ugt verify` for that.

**Expected output on success:**
```
[*] Starting connection smoke test for project: MyGame
[+] Connection established! Initial observation vector: [100.  10.   0.   0.]
[*] Running 5 steps with random action commands to verify action space and state mapping...
  [Step 1] Action ID: 2 | Obs: [100.  10.   1.   0.] | Terminated: False
  ...
[+] Smoke test passed successfully! Adapter communication and state mappings are fully operational.
```

**What to fix if it fails:**
- `Connection failed` / `Failed to spawn subprocess` — check your `engine.entry` command; run it manually first
- `Invalid JSON response` — your bridge is printing non-JSON to stdout; redirect debug output to stderr
- `observation_space.shape does not match` — number of `mappings:` entries doesn't equal `shape:`
- `Terminated: True` on step 1 — `reset()` isn't actually starting a fresh game

---

## 8. Phase 2 — Playtest (LLM Player)

`ugt playtest` runs an Anthropic-powered agent through your game. Unlike the scripted verifier, the LLM player reads the game state and reasons about what to do next — it can find bugs that no scripted test would look for, because it plays like a real player would.

### 8a. Writing a Strategy Guide

Create `strategy-guide.md` alongside your config. This is the single most important input: a 1–3 page document that teaches the LLM how your game works.

Include:
- **Win condition** — exactly what state causes the game to end in victory
- **Core loop** — what a competent player does on a typical turn
- **Action vocabulary** — what each action does, when to use it
- **What broken looks like** — describe observable symptoms of bugs (credits unchanged after purchase, screen not changing, etc.)

See `examples/mock-game/strategy-guide.md` for a working example.

### 8b. Running `ugt playtest`

> **Persistent-state games:** Set `diagnose_resets_episode: false` in your config before the first LLM
> playtest run. By default the `diagnose` action resets the episode — in a game with persistent campaign
> state this will erase progress mid-run. (This knob exists because a real run erased 310 turns of valid
> play before the option was added.)
>
> Add to `ugt.config.yaml`:
> ```yaml
> playtest:
>   diagnose_resets_episode: false
> ```

```bash
# Requires: pip install 'ugt[playtest]' and ANTHROPIC_API_KEY
export ANTHROPIC_API_KEY=sk-ant-...

cd examples/your-game/
ugt playtest --config ugt.config.yaml --strategy-guide strategy-guide.md
# Options:
#   --max-actions 100    number of LLM actions to take (default: 100)
#   --output path.json   custom output path (default: results/playtest-report.json)
```

**Cost note:** Each action is one Anthropic API call with ~512 tokens output. At July 2026 pricing:
- **claude-haiku-4-5** ($1/$5 per MTok input/output): ~**$0.75 per 100 actions** — recommended for long exploratory runs
- **claude-opus-4-8** ($5/$25 per MTok input/output): ~**$3–4 per 100 actions** — higher-quality judgment, shorter runs

Both figures include input context growth across the run. Pass `--model claude-haiku-4-5` to use Haiku. For a first run, use `--max-actions 30` to verify it's working before committing to a full run.

### 8c. Reading the Playtest Report

`results/playtest-report.json`:

```json
{
  "game": "MyGame",
  "total_actions": 100,
  "potential_bugs": [
    {
      "step": 23,
      "description": "Credits unchanged after invest_credits despite having AP — economy system may be broken",
      "state": { "player": { "credits": 100, "ap": 8 } }
    }
  ],
  "novel_behaviors": [],
  "action_log": [
    {
      "step": 1,
      "action_type": "action_id",
      "action": "invest_credits",
      "reasoning": "Have 10 AP and need credits — invest to advance toward win condition",
      "expected": "credits increase by 50",
      "state_delta": { "player.credits": "+50", "player.ap": "-2" }
    }
  ]
}
```

- **`potential_bugs`** — states where the LLM observed something unexpected. Read each one and verify manually.
- **`novel_behaviors`** — actions the LLM marked as exercising something outside your feature map. Consider adding these to your `feature-map.yaml`.
- **`action_log`** — full history of what the agent did and why. The `reasoning` field shows the agent's intent; `state_delta` shows what actually changed.

**Browser game note:** Full browser play (with `press_key` and `type_text` flows, screen detection, and `waitForScreen`) is a future enhancement. The current scaffold works fully for simulation/subprocess games.

---

## 9. Frontend UI Testing (Browser Games)

The browser adapter drives your game's actual frontend through a real Chromium browser (headless). This tests:
- That the JS hooks respond correctly
- That state rendering doesn't break after sequences of actions
- That there are no soft-locks (states where the game stops accepting actions)
- That the game doesn't crash on unusual-but-legal action sequences

**Step 1: Expose the JS hooks in your frontend** (see Section 4b).

**Step 2: Configure your game as a browser engine:**

```yaml
engine:
  type: "browser"
  entry: "http://localhost:8080"   # URL where your game is served
  step_delay_ms: 50               # ms to wait per step if no __STEP_COMPLETE__ flag
```

**Step 3: Start your game's dev server, then smoke-test:**

```bash
# Terminal 1: start your game
npm run dev

# Terminal 2: run the smoke test
cd path/to/your/game
ugt smoke-test --config ugt.config.yaml
```

The smoke test drives 5 random actions through the browser and confirms the hooks are wired correctly. Watch both terminals: your game server's logs will show exactly which requests UGT is triggering.

**Step 4: Run a random-play UI stress test:**

There is no dedicated "UI stress test" command — use the exploit-hunter (Tier 2 of the trial ladder,
`ugt/core/exploit_hunter.py`) directly against your browser adapter. It drives random/heuristic actions
through the real UI and re-checks your invariants after every step, which is exactly what a UI stress pass
needs: many different action sequences, not a single scripted path. See "The trial ladder" section above for
how R3 wires this up (`verify_round3.py` in a real integration; `examples/harness-game/verify_round3.py` for
a complete worked example — swap its subprocess adapter for a `PlaywrightAdapter` and it drives your browser
game the same way).

**What to look for:**
- Any episode that terminates with 0 steps (crashed on step 1)
- Episodes that hit the step cap every time but never show a `player_won` or loss signal (soft-lock)
- Errors in your game server's terminal that correspond to specific action IDs

**For headful debugging** (to actually see the browser during testing), edit `playwright.py` line 26 temporarily:

```python
self.browser = self.playwright.chromium.launch(headless=False)  # see the browser
```

This lets you watch UGT play your game in real time. Useful when diagnosing why specific actions seem to have no effect.

**Performance note:** The soft-reset hook (`window.__RESET_GAME__()`) reduces episode reset time from ~15 seconds to <50ms. Always implement it. Without it, 100 episodes = over 25 minutes just in resets.

---

## 10. Configuration Reference

```yaml
project:
  name: "MyGame"         # Human-readable name
  version: "1.0.0"

engine:
  type: "simulation"     # "simulation" (subprocess) or "browser" (Playwright)
  entry: "python sim_bridge.py"  # Command to start bridge (simulation)
                         # or URL for browser type: "http://localhost:8080"
  step_delay_ms: 50      # Browser only: ms delay per step (use __STEP_COMPLETE__ instead if possible)

observation_space:
  type: "box"
  shape: 6               # Must equal number of mappings
  mappings:
    - path: "state.path"   # Dot-path into state dict
      min: 0
      max: 100
      aggregator: "count"  # Optional: count|sum|mean|min|max (for list values)

action_space:
  type: "discrete"
  size: 5                # Must equal number of actions
  actions:
    0: { name: "wait" }
    # ...

evaluation:
  victory_key: "player_won"   # State key that indicates a win (default: checks common names)

playtest:
  # diagnose_resets_episode (default: true)
  # When the LLM playtester issues a `diagnose` action it signals confusion or a
  # suspected broken state. By default UGT resets the entire episode at that point,
  # which is safe for short/stateless games. For games with persistent campaign
  # state (progress that spans many turns or sessions) set this to false — a reset
  # will erase all accumulated progress, not just the current confusing moment.
  # **Set this to false before the first run on any persistent-state game.**
  # (A real run erased 310 turns of valid campaign play before this knob was added.)
  diagnose_resets_episode: true   # set false for persistent-campaign games
```

---

## 11. Troubleshooting

### Bridge hangs on reset / step

Your bridge is not flushing stdout. Add `flush=True` to every `print()` call, or call `sys.stdout.flush()` after writing.

### "Invalid JSON response"

Something is printing to stdout before (or instead of) your JSON. Common culprits: import-time print statements, framework startup banners, Python warnings. Redirect everything non-JSON to stderr.

### Browser: game doesn't mount / __GET_STATE__ not found

UGT waits up to 10 seconds for `window.__GET_STATE__` to exist. If your game takes longer to initialize, the hook registration is in a component that mounts after a delay. Move it to the earliest possible lifecycle point, or add an explicit wait before registering hooks.

### Reproducibility: two runs produce different results

Check that your bridge reads `UGT_SEED` from the environment. Check that there's no `Math.random()` or `random.random()` call in your bridge that isn't seeded by `UGT_SEED`.
