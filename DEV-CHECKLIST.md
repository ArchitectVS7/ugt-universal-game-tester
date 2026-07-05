# UGT Development Checklist

This file tracks the development and testing status of the UGT *framework* itself.
It is the authoritative record of what is built, what is scaffolded, and what is future work.

> **2026-07-04 note:** the "three-phase" model below (verify → RL train/eval → LLM playtest) still describes the
> framework code that exists, but the SpacerQuest *direction* has changed — RL-as-balance is demoted to a random
> exploit-hunter and both agent tiers now drive the **real game server**, not the `sim_bridge` reimplementation.
> Read `PLAN-FORWARD.md` and the memory note `architecture-pivot-real-server` for the current plan. The items
> below remain accurate as a record of the framework's own features.

---

## Phase A — Honest Evaluation (COMPLETE)

- [x] **A1** Collapse detection in `evaluator.py` — emits `COLLAPSE DETECTED`, prefixes `INVALID_`
- [x] **A1** Random-policy baseline (50 episodes) for comparison
- [x] **A2** Seed pinning — `set_random_seed(seed)` in trainer, `UGT_SEED` env var to subprocess bridge
- [x] **A2** Warzones bridge deterministic seeds (`base_seed + episode_count`)
- [x] **A2** SpacerQuest bridge — removed dead `Math.random()` block
- [x] **A3** Wilson 95% CI for win-rate, bootstrap CI for reward mean
- [x] **A3** `--seed-band N` CLI flag for cross-seed stability testing
- [x] **A3** Normalized Shannon entropy (`action_entropy`) in eval report
- [x] Seed added to all example `ugt.config.yaml` files and `DEFAULT_CONFIG_TEMPLATE`

**Verification commands:**
```bash
cd examples/mock-game
ugt smoke-test --config ugt.config.yaml
ugt evaluate --config ugt.config.yaml --profile aggro --model models/ppo_aggro_final --episodes 20
# Expected: INVALID_ prefix if model is collapsed; collapse_detected: true in JSON
```

---

## Phase B — Three-Phase Tiered System (THIS RELEASE)

### Documentation and Architecture
- [x] `AGENT-PLAYTEST-FRAMEWORK.md` — full engineering spec for game-specific harnesses
- [x] `UGT-USER-MANUAL.md` — three-phase overview section added
- [x] `DEV-CHECKLIST.md` — this file
- [x] CLI help text reordered: verify → smoke-test → train → evaluate → playtest → dashboard
- [x] `DEFAULT_CONFIG_TEMPLATE` three-phase comment block added

### Phase 1 — `ugt verify` (IMPLEMENTED for simulation games)
- [x] `ugt/utils/formula_evaluator.py` — extended with comparison (`>`, `<`, `==`, etc.) and boolean (`and`, `or`, `not`) operators
- [x] `ugt/utils/formula_evaluator.py` — `evaluate()` accepts `extra_context` for `before`/`after` state references
- [x] `ugt/utils/feature_map.py` — YAML loader, `Feature` dataclass, `FeatureMap` class with priority sorting and action name→ID resolution
- [x] `ugt/core/verifier.py` — Phase 1 runner: drives adapter directly, evaluates assertions, produces `coverage-report.json`
- [x] `examples/mock-game/feature-map.yaml` — working 6-feature map for the mock game
- [x] `ugt/cli.py` — `verify` subcommand + `handle_verify()` handler

**Verification commands:**
```bash
cd examples/mock-game
ugt verify --config ugt.config.yaml --feature-map feature-map.yaml
# Expected: results/coverage-report.json created
# Expected: economy.invest_increases_credits → PASSED
# Expected: game.win_condition → NOT_REACHED (credits won't reach 450 in one run without investing)
```

### Phase 2 — `ugt train/evaluate` (unchanged, existing)
- [x] No regressions from Phase B changes (Phase A work preserved)

**Verification commands:**
```bash
cd examples/mock-game
ugt smoke-test --config ugt.config.yaml
ugt evaluate --config ugt.config.yaml --profile aggro --model models/ppo_aggro_final
```

### Phase 3 — `ugt playtest` (SCAFFOLDED)
- [x] `ugt/adapters/base.py` — optional `press_key()`, `type_text()`, `get_terminal_text()` methods
- [x] `ugt/adapters/playwright.py` — implements `press_key()`, `type_text()`, `get_terminal_text()` using `self.page.keyboard`
- [x] `ugt/core/playtester.py` — LLM player scaffold: Anthropic tool_use, action schema, bug flagging, `playtest-report.json`
- [x] `examples/mock-game/strategy-guide.md` — strategy guide for mock-game LLM player
- [x] `ugt/cli.py` — `playtest` subcommand + `handle_playtest()` handler
- [x] `setup.py` — `[playtest]` optional extra (`anthropic>=0.25.0`)

**Verification commands:**
```bash
cd examples/mock-game
export ANTHROPIC_API_KEY=sk-ant-...
pip install 'ugt[playtest]'
ugt playtest --config ugt.config.yaml --strategy-guide strategy-guide.md --max-actions 20
# Expected: results/playtest-report.json created with action_log entries
```

---

## Future Work (Not Yet Implemented)

### Phase 1 Extensions
- [ ] **Browser feature map** — `press_key` / `type_text` action syntax in `feature-map.yaml`
      for browser games (requires screen detection + `waitForScreen` in Python verifier)
- [ ] **Screen detection** — `detect_screen()` implemented in `PlaywrightAdapter` using pattern matching
- [ ] **`waitForScreen()`** — polling equivalent in Python (Playwright `wait_for_function` wrapper)
- [ ] **RNG seam testing** — `rng_controlled: true` features exercised via injectable RNG
- [ ] **SpacerQuest feature map** — full 26-feature map for SpacerQuest
- [ ] **Warzones feature map** — feature map for the Warzones simulation

### Phase 3 Extensions
- [ ] **Browser screen detection in playtest loop** — replace `# TODO: browser screen detection` stubs
- [ ] **`waitForScreen` after `press_key`** — verify expected screen appeared before continuing
- [ ] **Coverage integration** — playtest agent reads `coverage-report.json` to drive toward untested features
- [ ] **Recovery protocol** — on 3 consecutive `diagnose` actions, reset to known state

### Architecture Extensions
- [ ] **Desktop adapter** (Adapter 3) — `pyautogui` or Anthropic computer-use API for any desktop game
      (mouse/keyboard/controller input; screenshot capture as state)
- [ ] **HTML report output** — generate `coverage-report.html` from JSON for human-readable review
- [ ] **`ugt init --with-feature-map`** — generate a starter `feature-map.yaml` alongside `ugt.config.yaml`

---

## Test Commands — Full Suite

Run all three phases end-to-end on the mock-game example:

```bash
cd examples/mock-game

# Connectivity
ugt smoke-test --config ugt.config.yaml

# Phase 1: Correctness
ugt verify --config ugt.config.yaml --feature-map feature-map.yaml

# Phase 2: Balance (uses pre-trained model)
ugt evaluate --config ugt.config.yaml --profile aggro --model models/ppo_aggro_final --episodes 20

# Phase 3: LLM Playtest (requires API key)
export ANTHROPIC_API_KEY=...
ugt playtest --config ugt.config.yaml --strategy-guide strategy-guide.md --max-actions 30

# Help ordering check
ugt --help
# verify must appear before smoke-test; playtest must appear after evaluate

# Assertion evaluator unit check
python -c "
from ugt.utils.formula_evaluator import SafeEvaluator
e = SafeEvaluator('state.x > before.x')
assert e.evaluate({'x': 10}, extra_context={'before': {'x': 5}}) == True
e2 = SafeEvaluator('state.x > before.x and state.y == 0')
assert e2.evaluate({'x': 10, 'y': 0}, extra_context={'before': {'x': 5}}) == True
print('Assertion evaluator: OK')
"
```
