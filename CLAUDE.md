# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Start here

**Read `PLAN-FORWARD.md` before doing anything else in this repo.** It has the current direction, the
"four next steps," and links to memory notes with the full protocol/history. The core lesson learned the hard
way: **the tester must drive the real running game, never a re-implementation of it.** The original SpacerQuest
integration used a headless `sim_bridge.ts` that slowly became a partial copy of the game (no combat, broken
upgrades) — every RL agent trained against it learned the wrong game. All current SpacerQuest work drives the
**real `spacerquest-web` server** (a sibling repo at `../SpacerQuest/spacerquest-web`, not inside this repo)
over Socket.IO (screens/combat) + HTTP (auth/navigation), never the retired bridge.

Other key docs, in rough reading order for a new game integration:
- `PLAYTEST-DESIGN.md` — design spec for the LLM balance-playtester tier
- `UGT-USER-MANUAL.md` — onboarding a new game + methodology
- `archive/` — superseded docs (old Gate-1 RL spec, early rosy walkthrough, the pre-consolidation
  `ASSESSMENT-AND-FIX-ROADMAP.md`/`AGENT-PLAYTEST-FRAMEWORK.md`/`DEV-CHECKLIST.md`); do not treat as current
  plans — `archive/README.md` says why each was archived and where its still-useful content went

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
2. **Exploit-hunter (`ugt/core/exploit_hunter.py`)** — robustness tier, current SpacerQuest focus. Drives
   random/heuristic *real* actions through an adapter and asserts game invariants after every step (no negative
   fuel, no stuck screens, no soft-lock, no crash). Needs no reward engineering — this is what RL/random search
   is actually good at. Findings are structured (`Finding`/`HuntReport`), deduped, and meant to be read, not
   just counted — a failed check is data, not noise.
3. **LLM playtester (`ugt/core/playtester.py`, `ugt playtest`)** — balance/strategy tier. An LLM (Anthropic or
   Ollama) reads live text/terminal state and plays via `press_key`/`type_text`, producing
   `results/playtest-report.json`. Competence beats volume here — this is the tier that judges "is the game
   good?", not "does it crash?". Spec: `PLAYTEST-DESIGN.md`. Not yet wired to `engine.type: "real_server"` —
   see `PLAN-FORWARD.md` Phase 2.

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

### SpacerQuest integration specifically (`integrations/spacerquest/`)

```bash
# 1. Infra
open -a Docker
cd "../SpacerQuest/spacerquest-web" && docker compose up -d db redis   # Postgres :5454, Redis :6380

# 2. Start the real game server headless, against the UGT DB
NODE_ENV=test PORT=3005 \
  DATABASE_URL='postgresql://spacerquest:spacerquest@localhost:5454/spacerquest_ugt' \
  JWT_SECRET='<from .env.ugt>' REDIS_URL='redis://localhost:6380' UGT_TRAINING=1 \
  npx tsx src/app/index.ts

# 3. From this repo root, drive it (no pytest — these ARE the tests):
python3 integrations/spacerquest/spike_realclient.py           # protocol spike, 7/7 checks
python3 integrations/spacerquest/smoke_realclient_adapter.py   # adapter through BaseAdapter contract
python3 integrations/spacerquest/verify_dod.py                 # Phase-0 definition-of-done, full trade+combat loop
python3 integrations/spacerquest/run_exploit_hunter.py [episodes] [steps]   # Phase-1 robustness run
```

There is no `ugt.config.yaml`-driven CLI path for the exploit-hunter yet — these are standalone scripts that
construct a minimal config shim (`_Cfg`) and call `RealClientAdapter`/`ExploitHunter` directly.

## Verification & running things

Since there's no test suite, "does this work" means actually exercising it end-to-end:
- Framework changes affecting `simulation`/`browser` engines → run against `examples/mock-game/` (see
  `archive/DEV-CHECKLIST.md` for the exact expected-output sequence across all three phases — still-accurate
  record of framework behavior, just archived for its stale phase numbering).
- Changes to `RealClientAdapter` or the exploit-hunter → requires the live SpacerQuest server running (see
  above); run `verify_dod.py` and/or `run_exploit_hunter.py` and read the PASS/FAIL output, don't assume.
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
