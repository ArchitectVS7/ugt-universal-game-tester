# Gate 1 — Learnability Smoke Test (Executable Spec)

> **Question this answers:** *Can PPO beat a random policy on the simplest reachable version of
> SpacerQuest?* If yes, the RL tier is worth scaling. If no, the universal-RL thesis is falsified for this
> game class and you pivot (see `PLAN-FORWARD.md` → Fallback path). **Do not run full training until this
> passes.** Cost: minutes, single profile, ~100k steps — vs. the hour × 5 profiles that currently produces
> guaranteed `INVALID_` results.
>
> Context / why: memory note `rootcause-rl-collapse`. This spec removes 3 of the 4 root causes cheaply.
> (The 4th, verify≠train, is orthogonal and handled in Gate 2.)

---

## Design in one sentence

Give the agent **only the ~6 actions of the trade loop**, make a **positive terminal actually reachable**,
then **require it to beat the random baseline by a margin** before the tier is declared operational.

This attacks root causes #1 (unreachable win), #2 (inaction-optimal reward), and #3 (coverage-inflated
action space) simultaneously. Dynamic action masking (a bigger change) is intentionally deferred to Gate 2.

---

## Success criteria (the gate — all four must hold)

Evaluate the Gate-1 model with `ugt evaluate` (trader profile, ≥ 50 episodes). PASS requires **all**:

1. **Beats random:** `trained_mean_reward > random_mean_reward + max(0.25·|random_mean|, 1.0)`
   (stricter than the current 5% flag; a real margin, not noise).
2. **Not collapsed:** `collapse_detected == false` — i.e. normalized action entropy > 0.2 and reward std > 0.
3. **Reaches the goal:** `win_rate > 0%` against the *lowered* train-mode threshold (proves the agent can
   actually complete the objective, not just accrue shaped reward).
4. **Uses the loop:** action distribution shows real use of `accept_cargo` **and** `navigate_cargo_dest`
   (not just `buy_fuel`/`end_turn`) — confirms it learned the *combo*, the thing that was unlearnable before.

FAIL = any of the above missing after a fair attempt (see "If it fails" below).

---

## Changes required (4 edits, all small)

### Edit 1 — Add a trainable action subset (config)
`integrations/spacerquest/ugt.config.yaml`, under `training:` add:
```yaml
training:
  seed: 42
  algorithm: "PPO"
  total_timesteps: 100000          # Gate 1: small. NOT 500000.
  parallel_envs: 1
  checkpoint_freq: 25000
  # Gate 1: RL sees ONLY these real action IDs. Order defines the agent's 0..N-1 index.
  action_subset: [4, 6, 2, 7, 8, 14]
  # 4=buy_fuel 6=accept_cargo 2=navigate_cargo_dest 7=deliver_cargo 8=upgrade_cheapest 14=end_turn
```
Keep the full 40-action block for the verifier — do not delete it.

### Edit 2 — Honor the subset in the env (remap index → real action id)
`ugt/core/env.py`:
- In `__init__` (near line 52), read the subset and size the space to it:
  ```python
  self.action_subset = None
  training_cfg = getattr(config, "data", {}).get("training", {})
  subset = training_cfg.get("action_subset")
  if subset:
      self.action_subset = list(subset)
      self.action_space = spaces.Discrete(len(self.action_subset))
  else:
      self.action_space = spaces.Discrete(self.config.action_size)
  ```
- In `step()` (near line 97), translate the agent's index to the real game action before the adapter call:
  ```python
  def step(self, action):
      real_action = self.action_subset[int(action)] if self.action_subset else int(action)
      prev_state = self.raw_state
      next_state, terminated, truncated, info = self.adapter.step(real_action)
      ...
  ```
This makes **both** the trained policy and the random baseline sample only the 6 subset actions —
a fair, and much stronger, comparison. No evaluator changes needed for the subset to take effect.

### Edit 3 — Make a positive terminal reachable (bridge)
`integrations/spacerquest/sim_bridge.ts`, line ~886 (and the mirror at line 91 in the initial-state
builder):
```typescript
// was: const isConqueror = state.character.score >= 10000;
const WIN_SCORE = parseInt(process.env.UGT_WIN_SCORE || '10000', 10);
const isConqueror = state.character.score >= WIN_SCORE;
```
Then train Gate 1 with `UGT_WIN_SCORE=100` in the environment. At +2 score/delivery and 2 trips/turn,
score 100 is ~25 turns of competent trading — comfortably inside the 1000-step cap, so a real win_bonus
gradient exists. **This env var does not affect the verifier** (verify tests specific features, not the win
key) and defaults to the real 10000 when unset, so nothing else changes.

### Edit 4 — Point the trader reward at the reachable goal (optional but recommended)
The existing `trader` profile is fine for Gate 1 (credits + trip_count deltas + win_bonus 1000). With the
lowered win threshold the `win_bonus` now actually fires, giving PPO the sparse signal it was missing.
No change strictly required — but if you want a cleaner signal, temporarily bump `win_bonus` to 2000 so the
terminal dominates the shaping noise.

---

## How to run

```bash
cd "integrations/spacerquest"

# 1. Train the Gate-1 model (small, reachable, 6 actions)
UGT_WIN_SCORE=100 ugt train --config ugt.config.yaml --profile trader

# 2. Evaluate it (this runs the random baseline + collapse guard automatically)
UGT_WIN_SCORE=100 ugt evaluate --model ./models/ppo_trader_final.zip \
    --config ugt.config.yaml --profile trader --episodes 50
```
Then read `results/*trader_eval_summary.json` (it will be `INVALID_`-prefixed only if collapse is detected)
and check it against the four success criteria above.

> Keep `UGT_WIN_SCORE` identical for train and eval — a mismatch would evaluate against a different MDP than
> was trained (the same class of bug as verify≠train).

---

## How to interpret

| Observation | Meaning | Action |
|---|---|---|
| All 4 criteria pass | **PPO can learn this game.** RL tier is viable. | Proceed to Gate 2 (scale actions, curriculum up to score 10000, retrain 5 profiles, then balance-eval). |
| Beats random + uses the combo, but win_rate 0 | Learning works; goal still too far. | Lower `UGT_WIN_SCORE` further (50), or raise win_bonus; re-run once. |
| Collapses to `end_turn`/`buy_fuel` again | Even the 6-action reachable version won't bootstrap. | One retry with win_bonus 2000 + `UGT_WIN_SCORE=50`. If still collapsed → **FAIL**. |
| Trained ≈ random | No signal in the reward. | Inspect that delivery actually moves credits/score/trip_count in the bridge for the training config (not just VERIFY_MODE). Then one retry. |

**Attempt budget: 2 retries max.** If it hasn't cleared the gate after tuning win threshold + win_bonus on a
6-action reachable problem, that is a *decisive* negative result — do not enter another retrain loop (that is
the exact circle this whole exercise exists to break).

---

## Decision rule (write the outcome down)

- **PASS** → update memory `rootcause-rl-collapse` and `PLAN-FORWARD.md`: RL tier viable, Gate 2 next.
- **FAIL** → the universal-RL-balance thesis does not hold for sparse-reward menu-economy games like
  SpacerQuest. Execute the **Fallback path** in `PLAN-FORWARD.md`: keep verify + LLM tiers, demote RL to
  exploit-hunting, and update the READMEs to state the scope honestly. This is a real, valuable answer —
  it stops the usage burn and redirects effort to the tiers that work.

---

## What this spec deliberately does NOT do (deferred to Gate 2)
- Dynamic legal-action masking (`info["action_mask"]` / MaskablePPO) — Gate 1 uses a *static* subset.
- Curriculum from score 100 → 10000.
- Bounded-rationality / suboptimal-play evaluation sweep.
- Fixing verify≠train (making the RL env use the verifier's certified starting state).
Keep Gate 1 minimal so the learnability answer is clean and cheap.
