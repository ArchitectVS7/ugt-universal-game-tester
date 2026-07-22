# UGT — Universal Game Tester: User Manual

> **Purpose of this document:** A practical, end-to-end guide for plugging a new game into UGT,
> teaching it the rules, and running the three test phases in the correct order.
>
> **What this is not:** a tutorial on reinforcement learning. You don't need to understand RL
> internals to use UGT. You do need to understand your game's state, actions, and win condition.

---

## Methodology & Hard-Won Lessons (read before onboarding a new game)

> **Canonical source: [`LESSONS.md`](LESSONS.md).** That file is the cross-game lessons registry — every rule
> here plus the LLM-playtest pre-flight audit (section B) and the operational discipline rules (section C),
> each with its evidence and source. Read it before onboarding a game, before advancing a ladder rung, and
> before any LLM playtest run. New lessons go there, not here.

The core methodology, in brief (full text + evidence in `LESSONS.md` §A):

1. **Drive the REAL game, never a re-implementation.** The single biggest failure mode: building an adapter/bridge
   that reimplements game logic (travel, combat, economy) instead of calling the running game. Whatever the bridge
   forgets silently does not exist for the agent — we shipped a "bridge" with **no combat**, and every trained
   agent learned a game that couldn't fight. If your adapter contains game *rules*, you're testing the adapter,
   not the game. Prefer, in order: (a) drive the game's real server/UI as a client; (b) call the game's own
   functions (single source of truth); never (c) a parallel copy.
2. **Dual validation — expect to find game bugs and pause.** UGT validates two things: that it can test the game,
   *and* the game itself. Finding a real game bug and **pausing to fix the game** is a successful outcome of the
   process, not a distraction. Budget for round-trips between "test" and "fix the game."
3. **Failed tests are data — record them.** Negative results (an agent that collapses, a mechanic that's
   unreachable, a reward that rewards the wrong thing) are often the most valuable findings. Write them down as
   durable notes so the next session doesn't re-learn them.
4. **Prove learnability cheaply before scaling.** Before spending real compute, prove an agent can beat a random
   baseline on the *simplest reachable* version of the objective (small action set, reachable goal, hard
   beat-random gate). If it can't clear that bar cheaply, more compute won't save it — change the approach. (This
   is the surviving idea from the now-archived Gate-1 learnability spec.)
5. **Verify ≠ Train ≠ Play.** A feature passing a *verifier* (often with crutches like extra credits or perfect
   nav) does **not** mean an agent can reach it under real play. Make sure the environment an agent trains/plays
   in is the same MDP you certified.
6. **Reward realized outcomes, not activity.** Reward the thing you actually want (profit, wins, progress), not a
   proxy for effort (number of trips, actions taken) — proxies get gamed. Express agent "personalities" as reward
   *weights* over a shared action set, not by hiding actions.
7. **Right tool per question.** *Correctness* → verify. *Robustness / does-it-break* → a cheap random/RL
   exploit-hunter (no reward engineering). *Balance / is-it-good* → an LLM playtester (competent play beats
   volume). Don't force one agent to answer all three.
8. **Test over the wire — a green in-process suite cannot see serialization-boundary bugs.** The game's own
   client and tests route around the wire, so defects on it are invisible to them: DDD had 1,251 in-process
   tests green while 7 of 40 cards played blank for every wire client (a field never exposed) and `create`
   accepted a config `replay` would refuse (a missing config key silently played a *different game*). Demand
   exact-config-key sets, treat a refusal as different from silent inertness, kill vacuous greens, and when
   an invariant never fires, suspect your own invariant first.
9. **Audit your own findings before citing them.** UGT itself has over-claimed from small samples and misread
   cumulative counters. Investigate before *confirming*, not just before dismissing — and record corrections
   in the integration's `RESULTS.md` rather than deleting the mistake.

> The tier model below is the current shape. Note: on SpacerQuest, RL as a *balance oracle* was tried and
> demoted to exploit-hunting (see `PLAN-FORWARD.md`); the LLM tier carries strategy/balance. Keep the phase
> *order* (cheap correctness first), but pick the agent per the "right tool per question" rule above.

---

## The Three-Tier Testing Model

**Run these in order. Each tier depends on the previous one being healthy.** (This supersedes an older
framing that cast Phase 2 as RL balance-training — that path still runs, see the note at the end of this
section, but it is no longer the balance judge. The LLM playtester is.)

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

### What happens once R3 passes

R3 answers "does it work / does it break" — it does **not** answer "is it good." A green ladder is the
*prerequisite* for the next tier, not the end of testing:

1. **Tier 3 — LLM playtest** (`ugt playtest`, §9 below). An LLM plays through a realistic input channel
   (keypresses, typed terminal commands, or a legal-action list for harness-style games with no terminal)
   and judges balance/strategy, producing `results/playtest-report.json` with state-delta-based bug reports.
   Only makes sense once the ladder is green — balance verdicts on a game that still crashes are noise.
2. **Human / frontend UAT** — a real person plays the actual UI. Not yet CLI-automated by UGT, but the
   established next step after a clean LLM playtest: things like visual readability, animation feel,
   onboarding clarity, and accessibility that no automated tier can see by construction (an engine-level or
   LLM-driven test can confirm the mechanics work; only a human can confirm the game *reads* well). Every
   integration's `HANDOFF.md` should carry a UAT status line once this tier is reached.

> **Legacy path, not part of the current model:** `ugt train` / `ugt evaluate` (PPO/DQN/A2C via
> stable-baselines3) still exist and work against `simulation`/`browser` engines, and are documented in §8
> below for games that still use them. They were the original "Phase 2" balance judge but were demoted after
> a well-documented collapse (RL trained an agent that gamed the reward instead of playing well) — the LLM
> playtester is the current balance/judgment tier. Don't reach for `train`/`evaluate` as a substitute for
> `ugt playtest` on a new integration.

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
   - 5c. Reward Profiles
6. [Phase 1 — Verify (Correctness Testing)](#6-phase-1--verify-correctness-testing)
   - 6a. Writing a Feature Map
   - 6b. Running `ugt verify`
   - 6c. Reading the Coverage Report
   - 6d. Troubleshooting Verify
7. [Quick Sanity Check — `ugt smoke-test`](#7-quick-sanity-check--ugt-smoke-test)
8. [Phase 2 — Balance Testing](#8-phase-2--balance-testing)
   - 8a. Training an Agent
   - 8b. Running Evaluation
   - 8c. Reading the Results
   - 8d. Interpreting Collapse Detection
   - 8e. Seed-Band Stability
9. [Phase 3 — Playtest (LLM Player)](#9-phase-3--playtest-llm-player)
   - 9a. Writing a Strategy Guide
   - 9b. Running `ugt playtest`
   - 9c. Reading the Playtest Report
10. [Frontend UI Testing (Browser Games)](#10-frontend-ui-testing-browser-games)
11. [Configuration Reference](#11-configuration-reference)
12. [Troubleshooting](#12-troubleshooting)

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
are available. (`ugt train`/`ugt evaluate` — RL training — still exist for `simulation`/`browser` engines but
are a legacy path, not the current balance tier; see the note at the end of "The Three-Tier Testing Model".)

---

## 2. How It Works (The Big Picture)

```
┌─────────────────────────────────────────────────────────────┐
│                        ugt.config.yaml                       │
│  (observation space, action space, reward profiles, seed)    │
└──────────────────────────┬──────────────────────────────────┘
                           │ read by
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                     UGT Python Core                          │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐ │
│  │  trainer.py  │  │ evaluator.py │  │  cli.py (ugt cmd)  │ │
│  └──────┬───────┘  └──────┬───────┘  └─────────┬──────────┘ │
│         │                 │                     │            │
│  ┌──────▼─────────────────▼─────────────────────▼──────────┐ │
│  │               UniversalGameEnv (Gymnasium)               │ │
│  └──────────────────────────┬────────────────────────────── ┘ │
└─────────────────────────────┼───────────────────────────────┘
                              │ one of two adapters
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

# Optional: TensorBoard for visualizing training:
pip install tensorboard
```

---

## 4. Connecting Your Game — The Bridge

The bridge is the only piece of code you write. It wraps your game engine in a standard protocol that UGT understands. Choose one of two bridge types based on how your game runs:

| Bridge type | Use when |
|-------------|----------|
| **Subprocess** | Game is a Python sim, TypeScript sim, or any headless process you can spawn |
| **Browser** | Game runs in a browser (React, Phaser, Vue, vanilla JS) |

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

### 5c. Reward Profiles

**What it is:** A formula that scores each game state, plus bonuses for winning and losing. Think of this as "what the agent is trying to maximize."

```yaml
reward_profiles:
  # Profile for aggressive play style
  aggro:
    formula: "(state.player.credits * 0.001) + (state.enemy.strength * -0.1) - (state.turn * 0.5)"
    win_bonus: 500
    loss_penalty: 100

  # Profile for economic / defensive play style
  eco:
    formula: "(state.player.credits * 0.005) - (state.turn * 0.2)"
    win_bonus: 500
    loss_penalty: 200
```

**The formula language:**
- Variables are accessed as `state.path.to.field`
- Operators: `+`, `-`, `*`, `/`, `**`
- Built-in functions: `min(a, b)`, `max(a, b)`, `abs(x)`
- All other Python functions are blocked for safety

**Critical guidance — reward design determines whether balance testing is valid:**

1. **Win/loss bonuses matter more than the formula.** The formula provides shaping (guides the agent toward good play), but the win/loss outcome is what you actually care about. Make `win_bonus` large relative to the formula (e.g., winning should be worth 10× the typical per-step formula value).

2. **The formula is a proxy — design it carefully.** If the formula rewards something other than the actual win condition, the agent will optimize that thing and ignore winning. Example: rewarding credits accumulation might produce an agent that hoards credits and never fights, even if fighting is required to win.

3. **Use different profiles to test different play styles.** One profile per intended strategy (aggressive, economic, stealth, etc.). Train a separate agent for each profile and compare their win rates — if one strategy dominates all others, that's a balance signal.

4. **Check that your formula produces negative values on loss states.** A formula that's always positive (even in losing states) means the `loss_penalty` is the only signal distinguishing win from loss, which makes learning harder.

5. **You can define as many profiles as you want.** Each trains and evaluates independently.

---

## 6. Phase 1 — Verify (Correctness Testing)

`ugt verify` drives your game through a feature map — a YAML file listing every testable behavior — and checks that each feature's state change is what you declared. Run this before training.

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

The smoke test verifies that your bridge responds correctly before any training. Takes ~10 seconds, requires no model or feature map.

```bash
cd examples/your-game/
ugt smoke-test --config ugt.config.yaml --profile aggro
```

**What it tests:** bridge connectivity, state dict structure, observation vector mapping, reward formula evaluation. It does NOT test whether game features behave correctly — use `ugt verify` for that.

**Expected output on success:**
```
[*] Starting connection smoke test for project: MyGame
[+] Connection established! Initial observation vector: [100.  10.   0.   0.]
[*] Running 5 steps with random action commands...
  [Step 1] Action ID: 2 | Obs: [100.  10.   1.   0.] | Reward: -0.50 | Terminated: False
  ...
[+] Smoke test passed!
```

**What to fix if it fails:**
- `Connection failed` / `Failed to spawn subprocess` — check your `engine.entry` command; run it manually first
- `Invalid JSON response` — your bridge is printing non-JSON to stdout; redirect debug output to stderr
- `observation_space.shape does not match` — number of `mappings:` entries doesn't equal `shape:`
- `Reward formula evaluation failed` — state paths in formula don't exist in returned state
- `Terminated: True` on step 1 — `reset()` isn't actually starting a fresh game

---

## 8. Phase 2 — Balance Testing

Balance testing trains an RL agent to play your game, then evaluates it across many episodes and checks whether the trained agent performs meaningfully better than random play.

This is a two-step process: **train**, then **evaluate**.

### 8a. Training an Agent

```bash
ugt train --config ugt.config.yaml --profile aggro
```

This runs PPO (or DQN/A2C if configured) for `total_timesteps` steps and saves the model to `models/ppo_aggro_final.zip`.

**Config settings that matter:**

```yaml
training:
  seed: 42               # Reproducibility seed — same seed → same training run
  algorithm: "PPO"       # PPO is the best default; DQN for single-env; A2C for speed
  total_timesteps: 200000  # More steps = more learning, but diminishing returns
  parallel_envs: 1        # >1 uses SubprocVecEnv for faster data collection
  checkpoint_freq: 20000  # Saves intermediate models every N steps
```

**How long to train:**
- Simple games (3–5 actions, clear reward signal): 50,000–100,000 steps
- Medium games (10–15 actions, sparse reward): 200,000–500,000 steps
- Complex games: 1M+ steps, may require reward shaping

**Training one profile per play style:**

```bash
ugt train --config ugt.config.yaml --profile aggro
ugt train --config ugt.config.yaml --profile eco
```

Monitor training with TensorBoard:

```bash
ugt dashboard --logdir ./logs
# opens http://localhost:6006 — watch the "ep_rew_mean" curve
```

A healthy training curve shows `ep_rew_mean` rising over time and eventually plateauing. A flat or oscillating curve that never improves is an early warning of a poor reward signal or action space design.

---

### 8b. Running Evaluation

```bash
ugt evaluate \
  --config ugt.config.yaml \
  --model models/ppo_aggro_final \
  --profile aggro \
  --episodes 100
```

This runs two passes:
1. **Trained policy:** 100 episodes with the saved model (deterministic/greedy)
2. **Random baseline:** 100 episodes with random action selection

Then it compares them and writes a JSON report to `results/`.

**For stability testing across seeds:**

```bash
ugt evaluate \
  --config ugt.config.yaml \
  --model models/ppo_aggro_final \
  --profile aggro \
  --episodes 100 \
  --seed-band 3
```

This runs evaluation with seeds 42, 43, 44 and produces a combined stability report showing how consistent the results are across different random conditions.

---

### 8c. Reading the Results

The evaluation writes `results/{profile}_eval_summary.json` (or `results/INVALID_{profile}_eval_summary.json` if collapse is detected). Key fields:

```json
{
  "evaluation_seed": 42,
  "collapse_detected": false,
  "collapse_reasons": [],

  "outcomes": {
    "wins": 34,
    "losses": 66,
    "win_rate": "34.00%"
  },

  "confidence_intervals": {
    "win_rate_95ci":     { "low": 0.2490, "high": 0.4392 },
    "reward_mean_95ci":  { "low": 120.4,  "high": 185.2  }
  },

  "reward_stats": {
    "mean":   152.3,
    "std":    88.1
  },

  "action_entropy": 0.7842,

  "random_baseline": {
    "mean_reward": -45.2,
    "win_rate": "4.00%",
    "wins": 4
  }
}
```

**How to interpret:**

| Field | What it means | Healthy sign |
|-------|--------------|--------------|
| `win_rate` | % of episodes the agent won | Higher than random; depends on game difficulty |
| `win_rate_95ci` | Where the true win rate probably lies | Interval doesn't cross random baseline's win rate |
| `reward_stats.std` | Variance across episodes | > 0 (zero means collapsed policy) |
| `action_entropy` | How spread the agent's choices are (0=one action only, 1=perfectly varied) | > 0.4 for most games |
| `random_baseline.mean_reward` | What random play scores | Trained mean should be clearly above this |
| `random_baseline.win_rate` | How often random play wins | Trained win rate should be clearly above this |

**Comparing profiles for balance:**

Run evaluation for each profile and compare win rates. If `aggro` wins 60% and `eco` wins 5%, the game heavily favors aggressive play — that's a balance signal. Ideal balance: no single profile dominates, or they're competitive within a reasonable margin (±10–15%) on the same game.

---

### 8d. Interpreting Collapse Detection

If UGT prints `COLLAPSE DETECTED` and writes `INVALID_*.json`, the trained policy failed to learn. The report names the reason:

**`zero_variance`** — Every episode returned the exact same reward. The agent is stuck in a deterministic loop, possibly because all actions lead to the same state (e.g., illegal action no-ops dominate).
- Fix: Check that at least some actions have different effects. Add a print to your bridge to verify actions are actually changing state.

**`not_above_random`** — The trained agent performs no better than random play.
- Fix: Check your reward formula. Is it rewarding the right things? Does the win_bonus significantly outweigh the per-step formula noise? Try training longer. Try a simpler observation space first.

**`low_entropy`** — The agent uses only 1–2 actions across all episodes.
- Fix: Check that other actions are legal and have meaningful effects. The agent is ignoring actions because they produce no reward signal — either they're no-ops or they're being penalized. Check your formula for biases against certain actions.

**General rule:** A collapsed result is not failure of UGT — it is information about your game's bridge or reward design. Fix the underlying cause before re-running.

---

### 8e. Seed-Band Stability

The seed-band report (from `--seed-band 3`) adds:

```json
{
  "seed_band_stability": {
    "seeds_tested": 3,
    "seeds": [42, 43, 44],
    "win_rate_mean": 34.00,
    "win_rate_std":   2.45,
    "reward_mean_mean": 152.3,
    "reward_mean_std":   8.1,
    "collapse_detected_any": false,
    "collapse_count": 0
  }
}
```

**A low `win_rate_std` (< 5%) means the result is stable** — the win rate is consistent across seeds, which means it's measuring something real about the game, not a lucky/unlucky random outcome. A high `win_rate_std` (> 15%) means the result is noisy and you need more episodes or more seeds.

---

## 9. Phase 3 — Playtest (LLM Player)

`ugt playtest` runs an Anthropic-powered agent through your game. Unlike the scripted verifier, the LLM player reads the game state and reasons about what to do next — it can find bugs that no scripted test would look for, because it plays like a real player would.

### 9a. Writing a Strategy Guide

Create `strategy-guide.md` alongside your config. This is the single most important input: a 1–3 page document that teaches the LLM how your game works.

Include:
- **Win condition** — exactly what state causes the game to end in victory
- **Core loop** — what a competent player does on a typical turn
- **Action vocabulary** — what each action does, when to use it
- **What broken looks like** — describe observable symptoms of bugs (credits unchanged after purchase, screen not changing, etc.)

See `examples/mock-game/strategy-guide.md` for a working example.

### 9b. Running `ugt playtest`

```bash
# Requires: pip install 'ugt[playtest]' and ANTHROPIC_API_KEY
export ANTHROPIC_API_KEY=sk-ant-...

cd examples/your-game/
ugt playtest --config ugt.config.yaml --strategy-guide strategy-guide.md
# Options:
#   --max-actions 100    number of LLM actions to take (default: 100)
#   --output path.json   custom output path (default: results/playtest-report.json)
```

**Cost note:** Each action is one Anthropic API call (claude-opus-4-8, ~512 tokens output). 100 actions ≈ 50K tokens ≈ $0.75 at current pricing. For a first run, use `--max-actions 30` to verify it's working.

### 9c. Reading the Playtest Report

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

## 10. Frontend UI Testing (Browser Games)

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
ugt smoke-test --config ugt.config.yaml --profile aggro
```

The smoke test drives 5 random actions through the browser and confirms the hooks are wired correctly. Watch both terminals: your game server's logs will show exactly which requests UGT is triggering.

**Step 4: Run random-play UI stress test:**

There is no dedicated "UI stress test" command — use `evaluate` with a random or lightly-trained model and a high episode count. Because the trained policy is deterministic, it will repeat similar action sequences. For broader coverage, evaluate with a model that was trained for fewer steps (or use the random baseline component, which runs automatically):

```bash
ugt evaluate \
  --config ugt.config.yaml \
  --model models/ppo_aggro_final \
  --profile aggro \
  --episodes 200
```

The random baseline (which runs automatically alongside the trained eval) is especially valuable here — it exercises many different action sequences and is more likely to find soft-locks or crashes than the trained policy's narrow repertoire.

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

## 11. Configuration Reference

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

reward_profiles:
  profile_name:
    formula: "state.player.credits * 0.01"   # AST-safe expression
    win_bonus: 500          # Added to reward on win
    loss_penalty: 100       # Subtracted from reward on loss

training:
  seed: 42                  # Reproducibility seed (int)
  algorithm: "PPO"          # PPO | DQN | A2C
  total_timesteps: 200000
  parallel_envs: 1          # >1 requires SubprocVecEnv-compatible bridge
  checkpoint_freq: 20000    # Save checkpoint every N steps (optional)
```

---

## 12. Troubleshooting

### Bridge hangs on reset / step

Your bridge is not flushing stdout. Add `flush=True` to every `print()` call, or call `sys.stdout.flush()` after writing.

### "Invalid JSON response"

Something is printing to stdout before (or instead of) your JSON. Common culprits: import-time print statements, framework startup banners, Python warnings. Redirect everything non-JSON to stderr.

### Agent always picks the same action

This is the `low_entropy` collapse signal. Most likely causes:
1. Most actions are no-ops in your bridge (illegal states) — the agent learned that only 1–2 actions do anything.
2. Your reward formula heavily penalizes certain actions even when they're valid.
3. Not enough training steps — add `total_timesteps`.

### Win rate is 0% but game is winnable

The agent hasn't learned to win. Possible causes:
1. The `win_bonus` is too small relative to per-step formula rewards — the agent doesn't care about winning.
2. The win condition requires a long sequence of correct actions and the agent hasn't explored it. Try training longer or adding intermediate reward shaping.
3. Your bridge's `terminated` flag is not correctly returning `True` when the game ends.

### Smoke test passes but training diverges / plateaus immediately

The observation space is missing a key piece of information the agent needs to make decisions. Ask: what does a skilled human player watch that your observation space doesn't include? Add those fields.

### "INVALID_" prefix on eval report

See Section 7d. The three collapse signals are: zero reward variance, not better than random, low action entropy. Each has a specific fix.

### Browser: game doesn't mount / __GET_STATE__ not found

UGT waits up to 10 seconds for `window.__GET_STATE__` to exist. If your game takes longer to initialize, the hook registration is in a component that mounts after a delay. Move it to the earliest possible lifecycle point, or add an explicit wait before registering hooks.

### Reproducibility: two runs produce different results

Check that your bridge reads `UGT_SEED` from the environment. Check that there's no `Math.random()` or `random.random()` call in your bridge that isn't seeded by `UGT_SEED`. Check that `training.seed` is set in your config.
