# SpacerQuest UGT Policy Training Plan

> **⚠️ RETIRED — part of the `sim_bridge.ts` cautionary example, not a live plan.** This
> roadmap was written against the retired bridge described in `README.md` in this same
> folder — do not execute it or use it as a template for a new integration. See
> `../../PLAN-FORWARD.md` and `../../Dev/PLAN-FORWARD-spacerquest.md` for the current
> SpacerQuest (Rimward) direction.

This plan outlines the roadmap for training and evaluating reinforcement learning agents (PPO policy) on SpacerQuest v4.0.

---

## 📋 Execution Roadmap

### Step 1: Scale Explorer Policy Training (200,000 Steps)
* **Goal**: Enable the policy to successfully learn mapping loops for traveling to cheap fuel ports and delivering cargo.
* **Command**:
  ```bash
  python3 -u -m ugt.cli train --config examples/spacerquest/ugt.config.yaml --profile explorer
  ```
* **Parameters**:
  * `total_timesteps`: `200000`
  * `parallel_envs`: `1`
  * `checkpoint_freq`: `20000`

### Step 2: Compare with Trader Policy
* **Goal**: Evaluate if direct reward feedback on credits and cargo pod holds yields faster strategy convergence.
* **Command**:
  ```bash
  python3 -u -m ugt.cli train --config examples/spacerquest/ugt.config.yaml --profile trader
  ```

### Step 3: Run Interactive Telemetry Dashboard
* **Goal**: Monitor agent training reward curves, rollout statistics, and learning rate adjustments.
* **Command**:
  ```bash
  python3 -m ugt.cli dashboard --logdir ./logs
  ```

### Step 4: Re-introduce Combat Scenarios
* **Goal**: Train survival, defensive retreat, and offensive combat behaviors once the baseline transport economy is mastered.
* **Action**:
  * Edit `spacerquest-web/.env.ugt` to set `ENCOUNTER_CHANCE=0.3`.
  * Rerun training with either the `explorer` or `trader` profile.
