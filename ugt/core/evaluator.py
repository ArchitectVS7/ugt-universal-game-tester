import os
import json
import time
import logging
from collections import Counter
import numpy as np
from stable_baselines3 import PPO, DQN, A2C
from ugt.core.env import UniversalGameEnv

ALGORITHM_MAP = {
    "PPO": PPO,
    "DQN": DQN,
    "A2C": A2C,
}


def _normalized_entropy(counter, num_actions):
    """Normalized Shannon entropy [0, 1]. 0=single action always, 1=perfectly uniform."""
    if num_actions <= 1:
        return 0.0
    total = sum(counter.values())
    if total == 0:
        return 0.0
    h = 0.0
    for count in counter.values():
        if count > 0:
            p = count / total
            h -= p * np.log2(p)
    return round(h / np.log2(num_actions), 4)


def _wilson_ci(k, n, z=1.96):
    """Wilson score 95% CI for a proportion. Returns {"low": ..., "high": ...} in [0, 1]."""
    if n == 0:
        return {"low": 0.0, "high": 0.0}
    center = (k + z * z / 2) / (n + z * z)
    margin = z * ((k * (n - k) / n + z * z / 4) ** 0.5) / (n + z * z)
    return {
        "low": round(max(0.0, center - margin), 4),
        "high": round(min(1.0, center + margin), 4),
    }


def _bootstrap_mean_ci(arr, n_resamples=1000, seed=42):
    """Bootstrap 95% CI for the mean. Uses isolated RandomState — does not affect global np.random."""
    if len(arr) == 0:
        return {"low": 0.0, "high": 0.0}
    rng = np.random.RandomState(seed)
    boot_means = np.array([
        rng.choice(arr, size=len(arr), replace=True).mean()
        for _ in range(n_resamples)
    ])
    return {
        "low": round(float(np.percentile(boot_means, 2.5)), 2),
        "high": round(float(np.percentile(boot_means, 97.5)), 2),
    }


def evaluate_agent(config, model_path, profile_name, num_episodes=50):
    """
    Runs statistical E2E evaluation sweeps using a frozen trained model policy.
    Collects rich game telemetry and saves reports for game balance analysis.

    Includes collapse detection (A1): runs a random-policy baseline and checks
    reward variance, action entropy, and whether the trained policy is meaningfully
    above random. Marks the report INVALID_ if collapse is detected.
    """
    project_dir = os.path.dirname(os.path.abspath(config.filepath))
    results_dir = os.path.join(project_dir, "results")
    os.makedirs(results_dir, exist_ok=True)

    # Determine algorithm from model path or config
    algo_name = config.data.get("training", {}).get("algorithm", "PPO")
    algo_cls = ALGORITHM_MAP.get(algo_name, PPO)

    # A2: Read seed for reproducible evaluation
    seed = config.data.get("training", {}).get("seed", 42)
    np.random.seed(seed)

    print(f"[*] Loading {algo_name} model from: {model_path}")
    model = algo_cls.load(model_path)

    # Load VecNormalize obs stats if present. The policy was trained on normalized
    # observations, so it MUST see normalized obs at eval or it acts on garbage inputs.
    # Rewards are left RAW (we sum the raw env reward) so the beat-random comparison stays fair.
    obs_normalizer = None
    vecnorm_path = os.path.join(
        os.path.dirname(model_path),
        f"{algo_name.lower()}_{profile_name}_vecnormalize.pkl",
    )
    if os.path.exists(vecnorm_path):
        try:
            import pickle
            with open(vecnorm_path, "rb") as f:
                obs_normalizer = pickle.load(f)
            print(f"[*] Loaded VecNormalize obs stats from: {vecnorm_path}")
        except Exception as e:
            logging.warning("Failed to load VecNormalize stats (%s). Evaluating on raw obs.", e)

    print(f"[*] Initializing environment for {num_episodes} evaluation episodes (seed={seed})...")
    env = UniversalGameEnv(config, profile_name)

    # Gate 1: the policy emits subset indices 0..N-1, not real game action IDs.
    # Remap the index through env.action_subset before naming, or the action
    # distribution mislabels (e.g. index 1 -> full-table "navigate_cheap_fuel"
    # instead of the real subset[1] action). Gate-1 criterion #4 depends on this.
    _action_subset = getattr(env, "action_subset", None)

    def _resolve_action_name(policy_idx):
        real_id = _action_subset[policy_idx] if _action_subset else policy_idx
        name = config.action_mappings.get(real_id, config.action_mappings.get(str(real_id), {}))
        if isinstance(name, dict):
            name = name.get("name", str(real_id))
        return name

    wins = 0
    losses = 0
    total_steps = 0
    all_rewards = []
    all_step_counts = []
    action_counter = Counter()
    episode_details = []

    start_time = time.time()

    obs, info = env.reset(seed=seed)

    for ep in range(num_episodes):
        done = False
        truncated = False
        steps = 0
        ep_reward = 0.0
        ep_actions = Counter()

        while not done and not truncated:
            model_obs = obs_normalizer.normalize_obs(obs) if obs_normalizer is not None else obs
            action, _ = model.predict(model_obs, deterministic=True)
            action_int = int(action)
            obs, reward, done, truncated, info = env.step(action_int)
            ep_reward += reward
            steps += 1
            ep_actions[action_int] += 1
            action_counter[action_int] += 1

        total_steps += steps
        all_rewards.append(ep_reward)
        all_step_counts.append(steps)

        # Detect victory: check multiple common keys for robustness
        is_win = _detect_victory(env.raw_state, info, config)

        if is_win:
            wins += 1
            outcome = "Win"
        else:
            losses += 1
            outcome = "Loss"

        # Map policy indices (remapped through the subset) to action names.
        action_dist = {}
        for action_id, count in ep_actions.items():
            action_dist[_resolve_action_name(action_id)] = count

        # Record rich telemetry
        telemetry = {
            "episode": ep + 1,
            "outcome": outcome,
            "reward": round(float(ep_reward), 2),
            "steps": steps,
            "action_distribution": action_dist,
            "game_telemetry": env.raw_state.get("telemetry", {}),
        }
        episode_details.append(telemetry)
        print(f"[Episode {ep+1}/{num_episodes}] {outcome} | Steps: {steps} | Reward: {ep_reward:.2f}")
        obs, info = env.reset()

    duration = time.time() - start_time

    # === A1: Random policy baseline for collapse detection ===
    print(f"\n[*] Running {num_episodes}-episode random baseline for collapse detection...")
    rand_wins = 0
    rand_rewards = []
    rand_action_counter = Counter()

    np.random.seed(seed + 1)
    obs, info = env.reset(seed=seed + 1)

    for ep in range(num_episodes):
        done = False
        truncated = False
        ep_reward = 0.0
        while not done and not truncated:
            action = int(env.action_space.sample())
            obs, reward, done, truncated, info = env.step(action)
            ep_reward += reward
            rand_action_counter[action] += 1
        rand_rewards.append(ep_reward)
        if _detect_victory(env.raw_state, info, config):
            rand_wins += 1
        obs, info = env.reset()
        print(f"  [Baseline {ep+1}/{num_episodes}] Reward: {ep_reward:.2f}")

    rand_rewards_arr = np.array(rand_rewards) if rand_rewards else np.array([0.0])
    rand_mean = float(rand_rewards_arr.mean())
    rand_win_rate = (rand_wins / num_episodes) * 100 if num_episodes > 0 else 0

    # === Compute stats ===
    win_rate = (wins / num_episodes) * 100 if num_episodes > 0 else 0
    rewards_arr = np.array(all_rewards) if all_rewards else np.array([0.0])
    steps_arr = np.array(all_step_counts) if all_step_counts else np.array([0])
    trained_mean = float(rewards_arr.mean())
    num_actions = env.action_space.n

    # A3: Entropy and confidence intervals
    normalized_h = _normalized_entropy(action_counter, num_actions)
    win_rate_ci = _wilson_ci(wins, num_episodes)
    reward_mean_ci = _bootstrap_mean_ci(rewards_arr, n_resamples=1000, seed=seed)

    # === A1: Collapse detection ===
    collapse_reasons = []

    if rewards_arr.std() < 0.01:
        collapse_reasons.append(
            f"zero_variance: reward std={rewards_arr.std():.4f} < 0.01 "
            f"({num_episodes} episodes produced identical rewards)"
        )

    # Sign-aware "not above random" check.
    # For rand=-789: threshold = -789 + 39.46 = -749.75 (trained must be less negative to pass)
    # For rand=+100: threshold = 100 + 5 = 105 (trained must exceed by >5%)
    not_above_threshold = rand_mean + abs(rand_mean) * 0.05
    if trained_mean <= not_above_threshold:
        collapse_reasons.append(
            f"not_above_random: trained_mean={trained_mean:.2f} <= "
            f"threshold={not_above_threshold:.2f} "
            f"(random_mean={rand_mean:.2f}, margin=5% of |rand|)"
        )

    if normalized_h < 0.2:
        collapse_reasons.append(
            f"low_entropy: normalized_entropy={normalized_h:.4f} < 0.2 "
            f"(agent used only {len(action_counter)}/{num_actions} actions)"
        )

    collapse_detected = len(collapse_reasons) > 0

    if collapse_detected:
        print("\n" + "=" * 65)
        print("  !! COLLAPSE DETECTED — EVALUATION RESULT IS LIKELY INVALID !!")
        print("  Reasons:")
        for r in collapse_reasons:
            print(f"    - {r}")
        print("  The report will be prefixed INVALID_ and flagged in JSON.")
        print("=" * 65 + "\n")

    # Build action distribution maps (policy indices remapped through the subset)
    aggregate_actions = {}
    for action_id, count in action_counter.items():
        aggregate_actions[_resolve_action_name(action_id)] = count

    rand_aggregate_actions = {}
    for action_id, count in rand_action_counter.items():
        rand_aggregate_actions[_resolve_action_name(action_id)] = count

    # Compile statistical report (backward-compatible — all original keys preserved)
    summary = {
        "project": config.project_name,
        "profile": profile_name,
        "model": model_path,
        "algorithm": algo_name,
        "total_episodes": num_episodes,
        "evaluation_seed": seed,
        "collapse_detected": collapse_detected,
        "collapse_reasons": collapse_reasons,
        "outcomes": {
            "wins": wins,
            "losses": losses,
            "win_rate": f"{win_rate:.2f}%",
        },
        "confidence_intervals": {
            "win_rate_95ci": win_rate_ci,
            "reward_mean_95ci": reward_mean_ci,
        },
        "reward_stats": {
            "mean": round(trained_mean, 2),
            "median": round(float(np.median(rewards_arr)), 2),
            "std": round(float(rewards_arr.std()), 2),
            "min": round(float(rewards_arr.min()), 2),
            "max": round(float(rewards_arr.max()), 2),
        },
        "action_entropy": normalized_h,
        "step_stats": {
            "mean": round(float(steps_arr.mean()), 1),
            "median": round(float(np.median(steps_arr)), 1),
            "min": int(steps_arr.min()),
            "max": int(steps_arr.max()),
        },
        "action_distribution": aggregate_actions,
        "random_baseline": {
            "mean_reward": round(rand_mean, 2),
            "win_rate": f"{rand_win_rate:.2f}%",
            "wins": rand_wins,
            "action_distribution": rand_aggregate_actions,
        },
        "evaluation_duration_seconds": round(duration, 1),
        "episodes": episode_details,
    }

    # A1: Prefix filename with INVALID_ if collapse detected
    report_filename = f"{'INVALID_' if collapse_detected else ''}{profile_name}_eval_summary.json"
    report_path = os.path.join(results_dir, report_filename)

    with open(report_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\n[+] Evaluation complete!")
    print(f"[+] Win Rate: {win_rate:.2f}% ({wins}/{num_episodes})  "
          f"CI: [{win_rate_ci['low']:.4f}, {win_rate_ci['high']:.4f}]")
    print(f"[+] Reward: mean={trained_mean:.2f}  std={rewards_arr.std():.2f}  "
          f"CI: [{reward_mean_ci['low']:.2f}, {reward_mean_ci['high']:.2f}]")
    print(f"[+] Action entropy (normalized): {normalized_h:.4f}")
    print(f"[+] Random baseline: mean={rand_mean:.2f}  win_rate={rand_win_rate:.2f}%")
    print(f"[+] Action Distribution: {aggregate_actions}")
    print(f"[+] Detailed report saved to: {report_path}")

    env.close()
    return summary


def _detect_victory(raw_state, info, config):
    """
    Detect victory using multiple strategies for robustness:
    1. Custom victory_key from config
    2. Standard 'victory' field in state
    3. 'is_win' / 'player_won' in state
    4. 'victory' / 'is_win' / 'player_won' in info dict
    """
    # Check for custom victory key in config
    victory_key = config.data.get("evaluation", {}).get("victory_key", None)
    if victory_key and isinstance(raw_state, dict):
        val = raw_state.get(victory_key)
        if val is not None:
            return bool(val)

    # Standard state-level checks
    if isinstance(raw_state, dict):
        for key in ("victory", "is_win", "player_won"):
            val = raw_state.get(key)
            if val is not None:
                return bool(val)

    # Info dict checks
    if isinstance(info, dict):
        for key in ("victory", "is_win", "player_won"):
            val = info.get(key)
            if val is not None:
                return bool(val)

    return False
