# UGT — Universal Game Tester

UGT is a pip-installable Python framework (`pip install -e .`, console script `ugt`) that drives **arbitrary
games** with autonomous agents to find bugs, probe balance, and validate behavior. It is game-agnostic:
game-specific knowledge lives entirely in a project's `ugt.config.yaml` (+ optional `feature-map.yaml` /
`strategy-guide.md`) — never hardcoded into the framework itself.

The core discipline behind everything here: **the tester must drive the real running game, never a
re-implementation of it.** Every adapter either talks to the game's own live process (subprocess harness,
real HTTP/WebSocket server) or drives its real UI (headless browser). See `PLAN-FORWARD.md` for the full
story of why that rule exists.

## What it does — three testing tiers

1. **`ugt verify`** — correctness. Drives an adapter directly against a `feature-map.yaml` (assertions on
   state deltas), producing `results/coverage-report.json`.
2. **Exploit-hunter** — robustness. Drives random/heuristic *real* actions through an adapter and asserts
   game invariants after every step (no negative resources, no stuck screens, no soft-lock, no crash), plus
   same-seed replay determinism. No reward engineering needed — this is what random/heuristic search is
   actually good at.
3. **LLM playtester (`ugt playtest`)** — balance/strategy. An LLM reads live text/terminal state (or a
   structured legal-action list) and plays via `press_key`/`type_text`/legal-action selection, producing
   `results/playtest-report.json`. This is the tier that judges "is the game good?", not "does it crash?".

These three tiers are run in a standardized sequence per game integration — the **trial ladder**: spike
(raw protocol round-trip) → smoke (same path through the framework's adapter contract) → R1 playability →
R2 full content spine → R3 exploit-hunter + determinism. See `integrations/README.md` for how every game
in this repo has actually scored against that ladder.

There is also an older RL train/evaluate path (`ugt train` / `ugt evaluate`, PPO/DQN/A2C via
stable-baselines3), still functional against `simulation`/`browser` engines, but demoted as a
balance-judgment tool in favor of the LLM playtester — see `PLAN-FORWARD.md` for why.

## Install

```bash
pip install -e .                  # core framework
pip install -e ".[dashboard]"     # + tensorboard (for `ugt dashboard`)
pip install -e ".[playtest]"      # + anthropic SDK (for `ugt playtest`)
pip install -e ".[realclient]"    # + requests/python-socketio/websocket-client (for real_server adapter)
```

## Quickstart — wiring up a new game

Run these from your game project directory, next to a `ugt.config.yaml`:

```bash
ugt init                                                        # scaffold ugt.config.yaml
ugt smoke-test --config ugt.config.yaml --profile aggro         # 5 random steps, verify wiring
ugt verify --config ugt.config.yaml --feature-map feature-map.yaml --max-turns 50
ugt train --config ugt.config.yaml --profile aggro
ugt evaluate --config ugt.config.yaml --model ./models/ppo_aggro_final --episodes 1000
ugt playtest --config ugt.config.yaml --strategy-guide strategy-guide.md --max-actions 100 \
  [--provider anthropic|ollama] [--model <name>]
ugt dashboard --logdir ./logs                                   # TensorBoard
```

Full onboarding walkthrough (how to write your `ugt.config.yaml`, pick an `engine.type`, and run the trial
ladder against your own game): **`UGT-USER-MANUAL.md`**.

## Architecture, in one paragraph

A Gymnasium environment (`ugt/core/env.py`) builds observation/action spaces dynamically from your
`ugt.config.yaml` and picks one of three adapters by `engine.type`: `browser` (Playwright, drives a real
web game through `window.__GET_STATE__`/`__SEND_ACTION__` hooks the game itself exposes), `simulation`
(JSON over stdin/stdout to a subprocess harness the game exposes), or `real_server` (Socket.IO + HTTP
against a live running server). A few integrations use additional purpose-built adapters (plain HTTP,
JSON-lines subprocess harnesses) constructed directly by that integration's trial-ladder scripts rather
than through `engine.type`. Every adapter is transport-only — it maps declared action ids to real UI/API
calls and never reimplements game logic; an action not yet wired raises `NotImplementedError` rather than
fabricating behavior.

## Where to go next

- **`PLAN-FORWARD.md`** — current direction: what's been proven, what's next, links to full history.
- **`LESSONS.md`** — the canonical cross-game lessons registry: core methodology, the mandatory LLM-playtest
  pre-flight information-integrity audit (read before any balance batch), and operational discipline. Read
  this before any test run.
- **`UGT-USER-MANUAL.md`** — onboarding a new game, including the trial-ladder methodology in depth.
- **`PLAYTEST-DESIGN.md`** — design spec for the LLM balance-playtester tier.
- **`integrations/README.md`** — the index of every game this framework has actually been run against,
  with real pass counts and headline findings.
- **`Dev/`** — ideation, lessons learned, superseded design docs, and other historical/retrospective
  material (start at `Dev/README.md`).

This README is deliberately framework-level and game-agnostic. For "how does UGT do against game X",
follow the link above into `integrations/`.
