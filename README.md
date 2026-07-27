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
2. **Invariant-fuzzer** — robustness. Drives random/heuristic *real* actions through an adapter and asserts
   game invariants after every step (no negative resources, no stuck screens, no soft-lock, no crash), plus
   same-seed replay determinism. No reward engineering needed — this is what random/heuristic search is
   actually good at.
3. **LLM playtester (`ugt playtest`)** — balance/strategy. An LLM reads live text/terminal state (or a
   structured legal-action list) and plays via `press_key`/`type_text`/legal-action selection, producing
   `results/playtest-report.json`; costs approximately **$0.75 per 100 actions** with claude-haiku-4-5 ($1/$5 per MTok, as of July 2026), or **$3–4 per 100 actions** with claude-opus-4-8 ($5/$25 per MTok, as of July 2026) — both figures include input context growth across the run. This is the tier that judges "is the game good?", not "does it crash?".

These three tiers are run in a standardized sequence per game integration — the **trial ladder**: spike
(raw protocol round-trip) → smoke (same path through the framework's adapter contract) → R1 playability →
R2 full content spine → R3 invariant-fuzzer + determinism. Each integration lives in its own
`integrations/<game>/` directory (a self-contained set of ladder scripts + a findings log).

**`sokoban/` is a complete worked example of that whole ladder** — a small deterministic Godot
game driven engine-first over a TCP socket, with all five rungs runnable in one command. Its sibling
`dice/` and `escape-room/` show the same methodology through the two built-in engines
(browser and simulation). Start there to see it end to end.

## Install

```bash
pip install -e .                  # core (numpy + gymnasium + pyyaml — no heavy deps)
pip install -e ".[browser]"       # + Playwright headless browser (for engine.type: browser)
playwright install chromium       # required after [browser] install — downloads browser binaries
pip install -e ".[playtest]"      # + anthropic SDK (for ugt playtest)
```

## Quickstart — wiring up a new game

Run these from your game project directory, next to a `ugt.config.yaml`:

```bash
ugt init                                                        # scaffold ugt.config.yaml
ugt smoke-test --config ugt.config.yaml                         # 5 random steps, verify wiring
ugt verify --config ugt.config.yaml --feature-map feature-map.yaml --max-turns 50
ugt playtest --config ugt.config.yaml --strategy-guide strategy-guide.md --max-actions 100 \
  [--provider anthropic|ollama] [--model <name>]
```

Full onboarding walkthrough (how to write your `ugt.config.yaml`, pick an `engine.type`, and run the trial
ladder against your own game): **`UGT-USER-MANUAL.md`**.

## Running it conversationally (how this is actually used, in practice)

UGT ships as a CLI (`ugt verify`, `ugt playtest`, …) and the Orchestrator ships as two Claude Code skills
(`/tasklist`, `/orchestrate`). Both are built to be *driven*, not typed at length — in practice, almost
nobody runs the raw commands above by hand. The normal workflow is a Claude Code session (terminal, IDE
extension, or Claude Code on the web): you describe the outcome, and the agent scaffolds configs, runs the
CLI commands, reads the output, and reports back. You don't need to memorize a flag to use this.

The examples below span two axes — how much you spell out (simple → complex) and how much work is in
flight (one run → many) — for both halves of the repo. Type any of these into a Claude Code session opened
in your game's or integration's directory.

**UGT — testing an existing integration**

| | One run | Several in flight |
|---|---|---|
| **Simple** | "Run a smoke test against this game and tell me if the adapter wiring is broken." | "Run the invariant-fuzzer three times with different seeds and tell me if any found an invariant violation." |
| **Complex** | "Prepare UGT for this repository — scaffold `ugt.config.yaml` if one doesn't exist, write a `feature-map.yaml` from the game's design doc, then run the trial ladder through R2 and give me the coverage report." | "Playtest this game 5 times with claude-haiku-4-5 and 5 times with claude-opus-4-8, then tell me whether the two models actually disagree on whether the economy is balanced." |

**Orchestrator — building or extending a game/integration**

| | One list | Several lists |
|---|---|---|
| **Simple** | "/tasklist Add a settings screen to this app." · "Pick up where TASKS.md left off and keep going until it's dry." | "/orchestrate all" against each of the three sample-game integrations in turn, one after another. |
| **Complex** | "Based on the current open items in PLAN-FORWARD.md, author a TASKS.md compatible with `/orchestrate`, with milestones grouped by feature area and a human UAT checkpoint at the end of each milestone." | "Author three separate TASKS.md files — one per module: auth, billing, notifications — each independently orchestratable, then run `/orchestrate` on all three back to back and stop at the first BLOCKED gate." |

## Architecture, in one paragraph

A Gymnasium environment (`ugt/core/env.py`) builds observation/action spaces dynamically from your
`ugt.config.yaml` and picks an adapter by `engine.type`: `browser` (Playwright, drives a real
web game through `window.__GET_STATE__`/`__SEND_ACTION__` hooks the game itself exposes) or `simulation`
(JSON over stdin/stdout to a subprocess harness the game exposes). Games that fit neither declare
`engine.type: custom` and supply their own purpose-built adapter (plain HTTP, a TCP socket, a JSON-lines
subprocess harness), constructed directly by that integration's trial-ladder scripts rather than
dispatched by `env.py` — see `sokoban/integration/`. Every adapter is transport-only — it maps declared action ids to real UI/API
calls and never reimplements game logic; an action not yet wired raises `NotImplementedError` rather than
fabricating behavior.

## Where to go next

- **The sample games** — three worked examples, each pairing a game built from a PRD with the UGT
  integration that tests it, one per transport: **dice** (React → `browser`), **escape-room**
  (Node → `simulation`), and **sokoban** (Godot → a hand-written `custom` adapter). Each is its **own
  repository**, published alongside UGT rather than bundled inside it — because in real use a game owns its
  repository and the harness lives in that project's `integration/` directory, which is exactly the shape
  these demonstrate. Take the ones you want; skip them entirely if you only want the tester.
  **`sokoban/integration/` is the fastest way to see the full trial ladder** — all five rungs runnable in one
  command. R3 (the invariant-fuzzer) is qualitatively different from R1: it runs random walks and re-checks
  invariants after *every* step, catching states no scripted test can enumerate; the same-seed replay then
  certifies the engine is deterministic. Start there.
- **`PLAN-FORWARD.md`** — current direction: what's been proven, what's next, links to full history.
- **`LESSONS.md`** — the canonical cross-game lessons registry: core methodology, the mandatory LLM-playtest
  pre-flight information-integrity audit (read before any balance batch), and operational discipline. Read
  this before any test run.
- **`UGT-USER-MANUAL.md`** — onboarding a new game, including the trial-ladder methodology in depth.
- **`UGT-REFERENCE.md`** — the lookup half of the manual: the bridge/adapter contract, every
  `ugt.config.yaml` key, and troubleshooting. Search it; don't read it.
- **`PLAYTEST-DESIGN.md`** — design spec for the LLM balance-playtester tier.
This README, and the four docs above it, are deliberately framework-level and game-agnostic. The concrete
per-game integrations (which specific games have been run and how they scored) live under `integrations/`,
and the historical/retrospective design docs live under `Dev/` — both are kept internal.

The `Orchestrator/` directory is a bonus Claude Code build-loop tool bundled with the repo — it is not part of the UGT framework (see `Orchestrator/README.md`).
