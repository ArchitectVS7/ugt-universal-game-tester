# Universal Game Tester (UGT)

UGT is a globally installable framework for testing games with autonomous agents. Point it at a game and it
drives that game to find bugs, probe balance, and validate behavior. It is **multi-tier**: correctness
verification, an **RL/random exploit-hunter** (robustness — crashes, soft-locks, exploits), and an **LLM
playtester** (strategy & balance). UGT does two jobs at once — it validates *the game*, and it validates that
*UGT itself* can test the game.

> **⚠️ Start with [`PLAN-FORWARD.md`](PLAN-FORWARD.md).** Core principle learned the hard way: **the tester must
> drive the real running game, never a re-implementation of it.** Early SpacerQuest work used a headless "bridge"
> that drifted into a partial copy of the game (it had no combat) — so agents learned the wrong game. The current
> direction drives the real game server directly. RL as a pure balance oracle was tried and demoted; see
> `PLAN-FORWARD.md` for the honest history (older assessments are in `archive/`).

## Architecture

```
                    ┌─────────────────────────────────┐
                    │     Global CLI: ugt             │
                    │   init | smoke-test | train     │
                    │   evaluate | dashboard          │
                    └──────────┬──────────────────────┘
                               │
                    ┌──────────▼──────────────────────┐
                    │   Core Trainer / Orchestrator    │
                    │   PPO · DQN · A2C via SB3       │
                    │   SubprocVecEnv (parallel)       │
                    └──────────┬──────────────────────┘
                               │
                    ┌──────────▼──────────────────────┐
                    │   Universal Gymnasium Env        │
                    │   Dynamic spaces from YAML       │
                    │   Safe AST reward formulas       │
                    └──────────┬──────────────────────┘
                               │
              ┌────────────────┼────────────────┐
              │                                 │
   ┌──────────▼──────────┐          ┌──────────▼──────────┐
   │  Playwright Bridge  │          │  Subprocess Bridge  │
   │  Browser games      │          │  Headless sims      │
   │  React/Phaser/Vue   │          │  Python/Node/WASM   │
   └─────────────────────┘          └─────────────────────┘
```

## Installation

```bash
cd "/Users/vs7/Dev/Games/_UGT Universal Game Tester"
pip install -e .

# For dashboard support (TensorBoard):
pip install -e ".[dashboard]"
```

## Quick Start

### 1. Initialize a config in your game directory
```bash
ugt init
```
This creates a template `ugt.config.yaml` with documented fields.

### 2. Validate the game connection
```bash
ugt smoke-test --config ugt.config.yaml
```
Runs 5 random steps to verify the adapter can communicate with your game and observations are mapped correctly.

### 3. Train an RL agent
```bash
ugt train --config ugt.config.yaml --profile aggro
```
Models are saved to `./models/` relative to the config file. Checkpoints saved periodically if `checkpoint_freq` is set in config.

### 4. Evaluate game balance
```bash
ugt evaluate --model ./models/ppo_aggro_final --episodes 1000 --config ugt.config.yaml
```
Produces a detailed JSON report in `./results/` with win rates, reward statistics, step counts, and action distributions.

### 5. View training metrics
```bash
ugt dashboard --logdir ./logs
```
Launches TensorBoard against the training log directory.

## CLI Reference

| Command | Description |
|---|---|
| `ugt init` | Create a template `ugt.config.yaml` in the current directory |
| `ugt smoke-test` | Verify game adapter connection and state mapping |
| `ugt train` | Train an RL agent using a reward profile from config |
| `ugt evaluate` | Run N-episode statistical evaluation with a frozen model |
| `ugt dashboard` | Launch TensorBoard to view training metrics |

## Configuration (`ugt.config.yaml`)

Each game project contains a `ugt.config.yaml` that maps game-specific structures into the standardized format the RL framework understands. See the [examples/](examples/) directory for working configurations.

### Key Sections

- **`engine`** — Connection type (`browser` or `simulation`) and entry point
- **`observation_space`** — Maps JSON state fields to numerical observation vectors
- **`action_space`** — Defines the discrete action set
- **`reward_profiles`** — Declarative reward formulas evaluated via safe AST parsing
- **`training`** — Algorithm choice (PPO/DQN/A2C), timesteps, parallelism, checkpointing

## Porting a Game

### Simulation Games (Headless)

1. Write a simulator script that reads JSON commands from stdin and writes JSON responses to stdout
2. Support three commands: `reset`, `step` (with `action_id`), and `close`
3. Create a `ugt.config.yaml` mapping your game's state fields
4. Run `ugt smoke-test` to verify

See [examples/warzones/](examples/warzones/) for a complete reference implementation using the Warzones game engine.

### Browser Games

1. Expose three JS hooks on `window`:
   - `window.__GET_STATE__()` → returns game state as JSON
   - `window.__SEND_ACTION__(actionId)` → executes action, returns `{state, terminated, truncated, info}`
   - `window.__RESET_GAME__()` → (optional) soft-reset without page reload
2. Create a `ugt.config.yaml` with `engine.type: browser`
3. Run `ugt smoke-test` with your game's dev server running

See [examples/browser-game/](examples/browser-game/) for a minimal working example.

## Examples

| Example | Type | Description |
|---|---|---|
| `examples/mock-game/` | Simulation | Minimal Python simulator for testing UGT core |
| `examples/browser-game/` | Browser | HTML/JS game demonstrating the Playwright adapter |
| `examples/warzones/` | Simulation | Full game port — bridges to the Warzones game engine |
