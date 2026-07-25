import argparse
import json
import subprocess
import sys
import os
import webbrowser
import yaml
from ugt.utils.config_parser import UgtConfig, ConfigError
from ugt.core.env import UniversalGameEnv
from ugt.core.trainer import train_agent
from ugt.core.evaluator import evaluate_agent

DEFAULT_CONFIG_TEMPLATE = """# UGT Configuration File
#
# Three-Tier Testing Model — run these in order:
#   Tier 1:  ugt verify    -- is the game correct?     (requires feature-map.yaml)
#   Tier 2:  exploit-hunter -- does it break?           (run via verify_round3.py in your integration)
#   Tier 3:  ugt playtest  -- does it feel right?      (LLM balance/strategy judge, requires ANTHROPIC_API_KEY)
#
# Start with: ugt smoke-test   to verify bridge connectivity, then ugt verify.
# Optional: ugt train / ugt evaluate for RL analysis (legacy path — see PLAN-FORWARD.md).

project:
  name: "MyGame"
  version: "1.0.0"

engine:
  type: "simulation" # Options: browser | simulation
  entry: "./sim_game.py" # Shell command to start game simulator
  reset_command: "" # optional reset override command

# Game state fields UGT reads (used by all three tiers)
observation_space:
  type: "box"
  shape: 4
  mappings:
    - path: "player.credits"
      min: 0
      max: 100000
    - path: "player.ap"
      min: 0
      max: 100
    - path: "enemy.credits"
      min: 0
      max: 100000
    - path: "turns_elapsed"
      min: 0
      max: 1000

# Actions UGT can send to your game (used by all three tiers)
action_space:
  type: "discrete"
  size: 3
  actions:
    0: { name: "wait" }
    1: { name: "invest_credits" }
    2: { name: "end_turn" }

# Reward profiles — used by the optional RL training path (ugt train / ugt evaluate)
reward_profiles:
  aggro:
    formula: "(state.player.credits * 0.01) - (state.turns_elapsed * 0.1)"
    win_bonus: 100
    loss_penalty: 50
  eco:
    formula: "(state.player.credits * 0.05) - (state.turns_elapsed * 0.01)"
    win_bonus: 200
    loss_penalty: 100

training:
  seed: 42  # Reproducibility seed (change per experiment)
  algorithm: "PPO"  # Options: PPO | DQN | A2C
  total_timesteps: 500000
  parallel_envs: 4  # Number of parallel simulation instances
  checkpoint_freq: 50000  # Save checkpoints every N timesteps

# Recommended next steps after setup:
#   ugt verify --config ugt.config.yaml --feature-map feature-map.yaml   # Tier 1
#   ugt playtest --config ugt.config.yaml --strategy-guide strategy-guide.md  # Tier 3
#
# Optional RL path (legacy):
#   ugt train --config ugt.config.yaml --profile aggro
#   ugt evaluate --config ugt.config.yaml --model ./models/ppo_aggro_final --episodes 100
#   ugt dashboard --logdir ./logs
"""

def handle_init():
    filepath = "ugt.config.yaml"
    if os.path.exists(filepath):
        print(f"[!] Config file '{filepath}' already exists in this directory.")
        return
    
    with open(filepath, "w") as f:
        f.write(DEFAULT_CONFIG_TEMPLATE)
    print(f"[+] Initialized template configuration in: {os.path.abspath(filepath)}")

def handle_smoke_test(config_path, profile_name):
    try:
        config = UgtConfig(config_path)
    except ConfigError as e:
        print(f"[-] Config validation failed: {e}")
        sys.exit(1)

    print(f"[*] Starting connection smoke test for project: {config.project_name}")
    try:
        env = UniversalGameEnv(config, profile_name)
        obs, info = env.reset()
        print(f"[+] Connection established! Initial observation vector: {obs}")
        
        print("[*] Running 5 steps with random action commands to verify action space and state mapping...")
        for i in range(5):
            action = env.action_space.sample()
            obs, reward, done, truncated, info = env.step(action)
            print(f"  [Step {i+1}] Action ID: {action} | Obs: {obs} | Reward: {reward:.2f} | Terminated: {done}")
            if done or truncated:
                print("  [*] Environment triggered reset indicator. Resetting...")
                obs, info = env.reset()
        
        env.close()
        print("[+] Smoke test passed successfully! Adapter communication and state mappings are fully operational.")
    except Exception as e:
        print(f"[-] Smoke test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

def _run_seed_band(config, model_path, profile_name, num_episodes, n_seeds):
    """Run evaluate_agent() N times with consecutive seeds and report stability metrics."""
    import numpy as np

    base_seed = config.data.get("training", {}).get("seed", 42)
    project_dir = os.path.dirname(os.path.abspath(config.filepath))
    results_dir = os.path.join(project_dir, "results")
    os.makedirs(results_dir, exist_ok=True)

    seed_results = []
    for i in range(n_seeds):
        seed = base_seed + i
        config.data.setdefault("training", {})["seed"] = seed
        print(f"\n{'='*50}\n[*] Seed band run {i+1}/{n_seeds}  (seed={seed})\n{'='*50}")
        summary = evaluate_agent(config, model_path, profile_name, num_episodes=num_episodes)
        seed_results.append(summary)
        individual_path = os.path.join(results_dir, f"{profile_name}_{seed}_eval.json")
        with open(individual_path, "w") as f:
            json.dump(summary, f, indent=2)
        print(f"[+] Seed {seed} result saved: {individual_path}")

    win_rates = [float(r["outcomes"]["win_rate"].rstrip("%")) for r in seed_results]
    reward_means = [r["reward_stats"]["mean"] for r in seed_results]
    collapse_flags = [r.get("collapse_detected", False) for r in seed_results]

    stability = {
        "seeds_tested": n_seeds,
        "base_seed": base_seed,
        "seeds": list(range(base_seed, base_seed + n_seeds)),
        "win_rate_mean": round(float(np.mean(win_rates)), 2),
        "win_rate_std": round(float(np.std(win_rates)), 2),
        "reward_mean_mean": round(float(np.mean(reward_means)), 2),
        "reward_mean_std": round(float(np.std(reward_means)), 2),
        "collapse_detected_any": any(collapse_flags),
        "collapse_count": sum(collapse_flags),
    }

    combined = {"seed_band_stability": stability, "individual_runs": seed_results}
    combined_path = os.path.join(results_dir, f"{profile_name}_eval_summary.json")
    with open(combined_path, "w") as f:
        json.dump(combined, f, indent=2)

    print(f"\n{'='*65}")
    print(f"[+] SEED BAND COMPLETE — {n_seeds} runs")
    print(f"[+] Win rate:    {stability['win_rate_mean']:.2f}% ± {stability['win_rate_std']:.2f}%")
    print(f"[+] Reward mean: {stability['reward_mean_mean']:.2f} ± {stability['reward_mean_std']:.2f}")
    if stability["collapse_detected_any"]:
        print(f"[!] WARNING: {stability['collapse_count']}/{n_seeds} seeds triggered COLLAPSE DETECTED")
    print(f"[+] Combined report: {combined_path}")
    print("=" * 65)


def handle_verify(config_path, feature_map_path, max_turns, output):
    from ugt.utils.feature_map import FeatureMap, FeatureMapError
    from ugt.core.verifier import verify_game
    try:
        config = UgtConfig(config_path)
    except ConfigError as e:
        print(f"[-] Config error: {e}")
        sys.exit(1)
    try:
        feature_map = FeatureMap(feature_map_path)
    except FeatureMapError as e:
        print(f"[-] Feature map error: {e}")
        sys.exit(1)
    try:
        verify_game(config, feature_map, max_turns=max_turns, output_path=output)
    except Exception as e:
        print(f"[-] Verify failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def handle_playtest(config_path, strategy_guide_path, max_actions, output, provider="anthropic",
                    model=None, runs=1):
    from ugt.core.playtester import playtest_game
    # Load a repo-local .env so ANTHROPIC_API_KEY (anthropic provider) is picked up
    # without the caller having to export it. Optional dep — the [playtest] extra
    # pulls it in; if absent, fall back to the ambient environment.
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    try:
        config = UgtConfig(config_path)
    except ConfigError as e:
        print(f"[-] Config error: {e}")
        sys.exit(1)
    try:
        with open(strategy_guide_path) as f:
            guide = f.read()
    except FileNotFoundError:
        print(f"[-] Strategy guide not found: '{strategy_guide_path}'")
        print("    Create a strategy-guide.md describing the game rules and win condition.")
        sys.exit(1)
    try:
        playtest_game(config, guide, max_actions=max_actions, output_path=output,
                      provider=provider, model=model, runs=runs)
    except (ImportError, RuntimeError) as e:
        print(f"[-] {e}")
        sys.exit(1)
    except Exception as e:
        print(f"[-] Playtest failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Universal Game Tester (UGT) CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # init
    subparsers.add_parser("init", help="Initialize a template ugt.config.yaml in the current directory")

    # verify (Phase 1)
    verify_parser = subparsers.add_parser(
        "verify",
        help="[Tier 1] Test game correctness against a feature map — run this first",
    )
    verify_parser.add_argument("--config", default="ugt.config.yaml", help="Path to ugt.config.yaml")
    verify_parser.add_argument(
        "--feature-map", default="feature-map.yaml", dest="feature_map",
        help="Path to feature-map.yaml (default: feature-map.yaml alongside config)"
    )
    verify_parser.add_argument("--max-turns", type=int, default=50, dest="max_turns",
                               help="Maximum turns to drive the game (default: 50)")
    verify_parser.add_argument("--output", default=None,
                               help="Output path for coverage-report.json (default: results/coverage-report.json)")

    # smoke-test
    smoke_parser = subparsers.add_parser("smoke-test", help="Quick bridge connectivity check — 5 random steps")
    smoke_parser.add_argument("--config", default="ugt.config.yaml", help="Path to ugt.config.yaml")
    smoke_parser.add_argument("--profile", default="aggro", help="Reward profile to test")

    # train (Phase 2a)
    train_parser = subparsers.add_parser("train", help="Train an RL agent (legacy optional path — use 'ugt playtest' for balance/strategy judgment)")
    train_parser.add_argument("--config", default="ugt.config.yaml", help="Path to ugt.config.yaml")
    train_parser.add_argument("--profile", default="aggro", help="Reward profile to train with")

    # evaluate (Phase 2b)
    eval_parser = subparsers.add_parser("evaluate", help="Evaluate a trained RL agent (legacy optional path — use 'ugt playtest' for balance/strategy judgment)")
    eval_parser.add_argument("--config", default="ugt.config.yaml", help="Path to ugt.config.yaml")
    eval_parser.add_argument("--profile", default="aggro", help="Reward profile to evaluate with")
    eval_parser.add_argument("--model", required=True, help="Path to trained model file (e.g. ./models/ppo_aggro_final)")
    eval_parser.add_argument("--episodes", type=int, default=50, help="Number of episodes to evaluate")
    eval_parser.add_argument(
        "--seed-band",
        type=int,
        default=1,
        dest="seed_band",
        help="Run evaluate N times over seeds [base, base+1, ..., base+N-1] for stability testing. Default=1 (single run).",
    )

    # playtest (Phase 3)
    playtest_parser = subparsers.add_parser(
        "playtest",
        help="[Tier 3] LLM-powered balance/strategy playtest — requires ANTHROPIC_API_KEY",
    )
    playtest_parser.add_argument("--config", default="ugt.config.yaml", help="Path to ugt.config.yaml")
    playtest_parser.add_argument(
        "--strategy-guide", default="strategy-guide.md", dest="strategy_guide",
        help="Path to strategy-guide.md (default: strategy-guide.md alongside config)"
    )
    playtest_parser.add_argument("--max-actions", type=int, default=100, dest="max_actions",
                                 help="Maximum LLM actions to take (default: 100)")
    playtest_parser.add_argument("--output", default=None,
                                 help="Output path for playtest-report.json (default: results/playtest-report.json)")
    playtest_parser.add_argument(
        "--provider", default="anthropic", choices=["anthropic", "ollama"],
        help="LLM provider: 'anthropic' (requires ANTHROPIC_API_KEY) or 'ollama' (local, no key needed)"
    )
    playtest_parser.add_argument(
        "--model", default=None,
        help="Model name override (e.g. 'gemma4:26b' for ollama, 'claude-opus-4-8' for anthropic)"
    )
    playtest_parser.add_argument(
        "--runs", type=int, default=1,
        help="Independent playtest runs (each starts from a fresh reset). runs>1 writes "
             "per-run playtest-run-{i}.json plus an aggregate playtest-summary.json with "
             "mean/std/95%%-CI per summary metric (default: 1)"
    )

    # dashboard
    dash_parser = subparsers.add_parser("dashboard", help="Launch TensorBoard to view training metrics")
    dash_parser.add_argument("--logdir", default="./logs", help="Path to TensorBoard log directory")
    dash_parser.add_argument("--port", type=int, default=6006, help="Port for TensorBoard server")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == "init":
        handle_init()
    elif args.command == "verify":
        handle_verify(args.config, args.feature_map, args.max_turns, args.output)
    elif args.command == "smoke-test":
        handle_smoke_test(args.config, args.profile)
    elif args.command == "playtest":
        handle_playtest(args.config, args.strategy_guide, args.max_actions, args.output,
                        provider=args.provider, model=args.model, runs=args.runs)
    elif args.command == "train":
        try:
            config = UgtConfig(args.config)
            train_agent(config, args.profile)
        except Exception as e:
            print(f"[-] Training initialization failed: {e}")
            sys.exit(1)
    elif args.command == "evaluate":
        try:
            config = UgtConfig(args.config)
            if args.seed_band <= 1:
                evaluate_agent(config, args.model, args.profile, num_episodes=args.episodes)
            else:
                _run_seed_band(config, args.model, args.profile, args.episodes, args.seed_band)
        except Exception as e:
            print(f"[-] Evaluation failed: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
    elif args.command == "dashboard":
        logdir = os.path.abspath(args.logdir)
        if not os.path.isdir(logdir):
            print(f"[-] Log directory not found: {logdir}")
            print("    Run 'ugt train' first to generate training logs.")
            sys.exit(1)
        try:
            import tensorboard  # noqa: F401
        except ImportError:
            print("[-] TensorBoard is not installed. Install it with: pip install tensorboard")
            sys.exit(1)
        print(f"[*] Launching TensorBoard on port {args.port} for logs in: {logdir}")
        print(f"[*] Open http://localhost:{args.port} in your browser.")
        try:
            webbrowser.open(f"http://localhost:{args.port}")
        except Exception:
            pass
        try:
            subprocess.run(
                [sys.executable, "-m", "tensorboard", "--logdir", logdir, "--port", str(args.port)],
                check=True,
            )
        except KeyboardInterrupt:
            print("\n[*] TensorBoard stopped.")
        except subprocess.CalledProcessError as e:
            print(f"[-] TensorBoard failed: {e}")
            sys.exit(1)

if __name__ == "__main__":
    main()
