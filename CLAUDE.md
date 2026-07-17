# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Start here

**Read `PLAN-FORWARD.md` before doing anything else in this repo.** It has the current direction (the
trial-ladder methodology, the five completed game integrations, the next steps) and links to the memory notes
with full history. The core lesson learned the hard way: **the tester must drive the real running game, never
a re-implementation of it.** The original SpacerQuest integration used a headless `sim_bridge.ts` that slowly
became a partial copy of the game (no combat, broken upgrades) — every RL agent trained against it learned the
wrong game. Every integration since drives the real game (live server, real browser, or the game's own
subprocess harness). SpacerQuest itself is **ON HOLD** (the game is being redesigned); its integration is
archived at `integrations/spacerquest_old/`.

Other key docs, in rough reading order for a new game integration:
- `UGT-USER-MANUAL.md` — onboarding a new game + methodology (including the trial ladder)
- `PLAYTEST-DESIGN.md` — design spec for the LLM balance-playtester tier
- `integrations/<game>/HANDOFF.md` — per-integration resume-here doorway (RESULTS.md = findings log)
- `archive/` — superseded docs (old Gate-1 RL spec, early rosy walkthrough, the pre-consolidation
  `ASSESSMENT-AND-FIX-ROADMAP.md`/`AGENT-PLAYTEST-FRAMEWORK.md`/`DEV-CHECKLIST.md`, the SpacerQuest-era
  `PLAN-FORWARD-spacerquest.md`); do not treat as current plans — `archive/README.md` says why each was
  archived and where its still-useful content went

## What this is

UGT (Universal Game Tester) is a pip-installable Python framework (`pip install -e .`, console script `ugt`)
that drives arbitrary games with autonomous agents to find bugs, probe balance, and validate behavior. It is
game-agnostic: game-specific knowledge lives entirely in a project's `ugt.config.yaml` (+ optional
`feature-map.yaml` / `strategy-guide.md`), never hardcoded into the framework.

There is no unit test suite (no pytest/unittest anywhere). Correctness is validated by actually running the
CLI/adapters against a live game — see "Verification & running things" below.

## Three testing tiers (current model)

1. **`ugt verify`** — correctness. Drives the adapter directly against a `feature-map.yaml` (assertions on
   state deltas), produces `results/coverage-report.json`. Implemented for `simulation`/`browser` engines.
2. **Exploit-hunter (`ugt/core/exploit_hunter.py`)** — robustness tier; R3 of the trial ladder, run to
   completion against all five integrated games. Drives random/heuristic *real* actions through an adapter and
   asserts game invariants after every step (no negative resources, no stuck screens, no soft-lock, no crash),
   plus same-seed replay determinism. Needs no reward engineering — this is what RL/random search is actually
   good at. Findings are structured (`Finding`/`HuntReport`), deduped, and meant to be read, not just counted —
   a failed check is data, not noise.
3. **LLM playtester (`ugt/core/playtester.py`, `ugt playtest`)** — balance/strategy tier. An LLM (Anthropic or
   Ollama) reads live text/terminal state and plays via `press_key`/`type_text`, producing
   `results/playtest-report.json`. Competence beats volume here — this is the tier that judges "is the game
   good?", not "does it crash?". Spec: `PLAYTEST-DESIGN.md`. Supports `browser`/`simulation`/`real_server`
   engines; ran in anger against SpacerQuest (drove the Gate-C balance verdict). Currently credit-gated;
   pending for tarot-war/NEXUS/DDD (DDD needs a structured-JSON drive mode — see `PLAN-FORWARD.md`).

The rounds of tiers 1–2 are standardized as the **trial ladder** (spike → smoke → R1 playability → R2 full
spine → R3 exploit-hunter); the game-agnostic scaffold is `ugt/core/trial.py` (`GateRunner`, `InvariantSuite`,
`first_divergence`), with everything game-specific in `integrations/<game>/`.

Historically there was also an RL train/evaluate path (`ugt train`/`ugt evaluate`, PPO/DQN/A2C via
stable-baselines3) used as a balance oracle — this was demoted after a well-documented collapse (see
`archive/ASSESSMENT-AND-FIX-ROADMAP.md` and the archived Gate-1 spec). The CLI commands still exist and work
against `simulation`/`browser` engines, but RL-as-balance-judgment is not the current direction for
`real_server` games.

## Architecture

```
Global CLI: ugt (ugt/cli.py)
  init | verify | smoke-test | train | evaluate | playtest | dashboard
        │
        ▼
UniversalGameEnv (ugt/core/env.py) — Gymnasium env; dynamic obs/action spaces from
  ugt.config.yaml; safe-AST reward formulas (ugt/utils/formula_evaluator.py)
        │
        ▼  picks one adapter by config `engine.type`
   ┌────────────────┬───────────────────┬─────────────────────────┐
   │ PlaywrightAdapter │ SubprocessAdapter │ RealClientAdapter      │
   │ engine.type=      │ engine.type=      │ engine.type=           │
   │ "browser"         │ "simulation"      │ "real_server"          │
   │ Drives a browser  │ JSON over stdin/  │ Socket.IO (screens/    │
   │ game via window   │ stdout to a       │ combat) + HTTP (auth,  │
   │ .__GET_STATE__ /  │ headless sim      │ navigation) against a  │
   │ __SEND_ACTION__   │ process           │ REAL running server —  │
   │                   │                   │ current SpacerQuest    │
   │                   │                   │ direction              │
   └────────────────┴───────────────────┴─────────────────────────┘
```

All adapters implement `ugt/adapters/base.py::BaseAdapter`: `connect()`, `reset() -> state dict`,
`step(action_id) -> (state, terminated, truncated, info)`, `close()`, plus optional
`press_key`/`type_text`/`get_terminal_text` for UI-driving tiers (playtest, exploit-hunter transport).

Three further adapters live alongside those three but are constructed directly by their integration's ladder
scripts rather than registered under an `engine.type` in `env.py`: `nexus_http.py` (NexusHttpAdapter — plain
HTTP against NEXUS's live Next.js test routes), `ddd_harness.py` (DddHarnessAdapter — JSON-lines subprocess
harness around DDD's deterministic engine), and `nexus_dominion_harness.py` (NexusDominionHarnessAdapter —
JSON-lines subprocess harness around Nexus Dominion's pure-TS cycle engine; composes per-cycle order lists
from structural state reads).

**`RealClientAdapter` (`ugt/adapters/realclient.py`) contains NO game logic** — it is a thin transport layer
(screen navigation, key input, HTTP calls) plus an `ACTION_HANDLERS` registry mapping config action names to
handler methods that compose those primitives. An action id not yet in `ACTION_HANDLERS` raises
`NotImplementedError` naming the action — the adapter deliberately does not fabricate behavior for unmapped
actions. This is the discipline that prevents repeating the `sim_bridge.ts` drift.

Config-driven pieces (`ugt/utils/config_parser.py::UgtConfig`):
- `observation_space.mappings` — dot-separated paths into the state dict → flat obs vector (with optional
  `sum`/`mean`/`min`/`max`/`count` aggregators for list fields)
- `action_space.actions` — discrete action id → name; `training.action_subset` lets an RL policy see only a
  restricted subset of real action ids (index-to-real-id remap happens in `env.py`)
- `reward_profiles.<name>.formula` — a safe-AST expression (`ugt/utils/formula_evaluator.py`) evaluated against
  `state` and `before` (previous state), plus `win_bonus`/`loss_penalty` on episode end

`engine.type: "real_server"` is the only type where `engine.entry` is optional (it uses `base_url`/`server_cmd`
instead of a subprocess entrypoint).

## Common commands

```bash
# Install (editable) from repo root
pip install -e .
pip install -e ".[dashboard]"    # + tensorboard
pip install -e ".[playtest]"     # + anthropic SDK, for `ugt playtest`
pip install -e ".[realclient]"   # + requests/python-socketio/websocket-client, for real_server adapter

# Per-game-project workflow (run from the game project directory, next to ugt.config.yaml)
ugt init                                                        # scaffold ugt.config.yaml
ugt smoke-test --config ugt.config.yaml --profile aggro         # 5 random steps, verify wiring
ugt verify --config ugt.config.yaml --feature-map feature-map.yaml --max-turns 50
ugt train --config ugt.config.yaml --profile aggro
ugt evaluate --config ugt.config.yaml --model ./models/ppo_aggro_final --episodes 1000 [--seed-band N]
ugt playtest --config ugt.config.yaml --strategy-guide strategy-guide.md --max-actions 100 \
  [--provider anthropic|ollama] [--model <name>]
ugt dashboard --logdir ./logs                                   # TensorBoard
```

### Per-game integrations (`integrations/<game>/`)

Each integration is a self-contained trial-ladder directory: `HANDOFF.md` (resume here — includes how to
start that game's server, if any), `README.md` (how to run), `RESULTS.md` (commit-traceable findings log),
plus the ladder scripts. Run them from this repo root (no pytest — these ARE the tests):

```bash
# The general shape (script names vary slightly per game — see its README):
python3 integrations/<game>/spike_<game>.py        # raw protocol round-trip
python3 integrations/<game>/smoke_<game>_adapter.py # same path through BaseAdapter
python3 integrations/<game>/verify_round1.py       # R1: playability gate (one full loop + invariants)
python3 integrations/<game>/verify_round2.py       # R2: full spine (every mode to a real outcome)
python3 integrations/<game>/verify_round3.py       # R3: exploit-hunter + same-seed replay determinism

# DDD needs no server (the adapter spawns its JSON-lines harness); the full ladder is:
for s in spike_ddd smoke_ddd_adapter verify_round1 verify_round2 verify_round3; do
  python3 integrations/ddd/$s.py || break
done
```

Current integrations: `ddd` and `nexus-dominion` (subprocess harness), `nexus` (live HTTP), `tarot-war` and
`warzones` (browser), `spacerquest_old` (Socket.IO+HTTP real server — **archived**, game on hold; its
infra/run commands are in `archive/PLAN-FORWARD-spacerquest.md`).

There is no `ugt.config.yaml`-driven CLI path for the ladder yet — the scripts construct a minimal config
shim and call the adapter/`ExploitHunter`/`ugt/core/trial.py` pieces directly.

## Verification & running things

Since there's no test suite, "does this work" means actually exercising it end-to-end:
- Framework changes affecting `simulation`/`browser` engines → run against `examples/mock-game/` (see
  `archive/DEV-CHECKLIST.md` for the exact expected-output sequence across all three phases — still-accurate
  record of framework behavior, just archived for its stale phase numbering).
- Changes to `ugt/core/trial.py`, `exploit_hunter.py`, or an adapter → re-run a completed ladder against the
  live game and read the PASS/FAIL output, don't assume. Cheapest full re-run: the DDD ladder (no server to
  start — see above). This is how the `trial.py` extraction itself was validated (exact NEXUS ladder re-run).
- After starting any game server, verify the LISTENING PID is the process you spawned
  (`lsof -nP -iTCP:<port> -sTCP:LISTEN`) — a stale server once silently absorbed an entire campaign.
- A one-off assertion-evaluator sanity check is documented at the bottom of `archive/DEV-CHECKLIST.md`.

## Conventions specific to this repo

- **Never reimplement game logic in an adapter.** If an action isn't mapped, let it raise
  `NotImplementedError` rather than inventing behavior — this is the exact failure mode (`sim_bridge.ts`) the
  project pivoted away from.
- **Dual validation.** Work here validates two things at once: that UGT can test/learn a game, and the game
  itself. Surfacing a real game bug mid-test is a success of the process, not a distraction — expect to
  sometimes pause and fix the game (e.g. `/api/character` was extended to expose win/loss/bank/jail state that
  was previously invisible to the black-box tester).
- **A failed check is data.** Invariant violations, crashes, and negative RL results get recorded (in
  `PLAN-FORWARD.md` "Findings" and in memory notes), not silently discarded or waved off as flaky.
- **Reward design:** reward realized profit/outcome deltas, not raw activity counters (e.g. trip count) —
  profiles should differ by weighting, not by hiding actions from the agent.
