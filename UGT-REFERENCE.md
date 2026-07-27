# UGT — Reference

> **Lookup, not tutorial.** Every exact contract and key, in one place. If you are onboarding a game for
> the first time, start with **[`UGT-USER-MANUAL.md`](UGT-USER-MANUAL.md)** and come here when it sends
> you. Split out of the manual on 2026-07-27.

**Contents:** the bridge/adapter contract · authoring `ugt.config.yaml` · full configuration reference ·
troubleshooting.

---
## 1. Connecting Your Game — The Bridge

The bridge is the only piece of code you write. It wraps your game engine in a standard protocol that UGT understands. Pick the engine type that matches how your game runs:

| Your game... | engine.type | Bridge pattern |
|---|---|---|
| ...is a headless subprocess (Python sim, TypeScript harness, Godot/Unity CLI build) | `simulation` | JSON-lines over stdin/stdout (`SubprocessAdapter`) |
| ...runs in a browser (React, Phaser, Vue, vanilla JS, any web frontend) | `browser` | Headless Chromium via Playwright; your game exposes `window.__GET_STATE__` / `window.__SEND_ACTION__` hooks (`PlaywrightAdapter`) |
| ...is anything else (a live server over HTTP/WebSocket, a TCP bridge into an engine's frame loop) | `custom` | You write a small transport-only `BaseAdapter` subclass; your ladder scripts construct it directly (`env.py` does not dispatch it). See `sokoban/integration/` |

Not sure? **Subprocess is the most portable starting point** — `escape-room/` shows it end-to-end against a real Node game. If your game has a frontend you want to drive through UI interactions, use Browser. Reach for `custom` only when neither transport fits — it costs you a small adapter, but nothing else in the ladder changes.

### 1a. Subprocess Bridge (headless / simulation games)

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

### 1b. Browser Bridge (browser / frontend games)

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

## 2. Teaching UGT the Rules — `ugt.config.yaml`

The config file is the only place you describe your game to UGT. Start with a template:

```bash
ugt init   # creates ugt.config.yaml in the current directory
```

Then fill in the three sections below.

---

### 2a. Observation Space

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

### 2b. Action Space

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

## 3. Configuration Reference

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

## 4. Troubleshooting

### Bridge hangs on reset / step

Your bridge is not flushing stdout. Add `flush=True` to every `print()` call, or call `sys.stdout.flush()` after writing.

### "Invalid JSON response"

Something is printing to stdout before (or instead of) your JSON. Common culprits: import-time print statements, framework startup banners, Python warnings. Redirect everything non-JSON to stderr.

### Browser: game doesn't mount / __GET_STATE__ not found

UGT waits up to 10 seconds for `window.__GET_STATE__` to exist. If your game takes longer to initialize, the hook registration is in a component that mounts after a delay. Move it to the earliest possible lifecycle point, or add an explicit wait before registering hooks.

### Reproducibility: two runs produce different results

Check that your bridge reads `UGT_SEED` from the environment. Check that there's no `Math.random()` or `random.random()` call in your bridge that isn't seeded by `UGT_SEED`.
