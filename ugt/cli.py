import argparse
import sys
import os
from ugt.utils.config_parser import UgtConfig, ConfigError
from ugt.core.env import UniversalGameEnv

DEFAULT_CONFIG_TEMPLATE = """# UGT Configuration File
#
# Three-Tier Testing Model — run these in order:
#   Tier 1:  ugt verify    -- is the game correct?     (requires feature-map.yaml)
#   Tier 2:  exploit-hunter -- does it break?           (run via verify_round3.py in your integration)
#   Tier 3:  ugt playtest  -- does it feel right?      (LLM balance/strategy judge, requires ANTHROPIC_API_KEY)
#
# Start with: ugt smoke-test   to verify bridge connectivity, then ugt verify.

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

# Recommended next steps after setup:
#   ugt smoke-test --config ugt.config.yaml                                   # bridge is alive
#   ugt verify --config ugt.config.yaml --feature-map feature-map.yaml       # Tier 1
#   ugt playtest --config ugt.config.yaml --strategy-guide strategy-guide.md # Tier 3
"""

def handle_init():
    filepath = "ugt.config.yaml"
    if os.path.exists(filepath):
        print(f"[!] Config file '{filepath}' already exists in this directory.")
        return

    with open(filepath, "w") as f:
        f.write(DEFAULT_CONFIG_TEMPLATE)
    print(f"[+] Initialized template configuration in: {os.path.abspath(filepath)}")

def handle_smoke_test(config_path):
    try:
        config = UgtConfig(config_path)
    except ConfigError as e:
        print(f"[-] Config validation failed: {e}")
        sys.exit(1)

    print(f"[*] Starting connection smoke test for project: {config.project_name}")
    try:
        env = UniversalGameEnv(config)
        obs, info = env.reset()
        print(f"[+] Connection established! Initial observation vector: {obs}")

        print("[*] Running 5 steps with random action commands to verify action space and state mapping...")
        for i in range(5):
            action = env.action_space.sample()
            obs, reward, done, truncated, info = env.step(action)
            print(f"  [Step {i+1}] Action ID: {action} | Obs: {obs} | Terminated: {done}")
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

    # verify (Tier 1)
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

    # playtest (Tier 3)
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

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == "init":
        handle_init()
    elif args.command == "verify":
        handle_verify(args.config, args.feature_map, args.max_turns, args.output)
    elif args.command == "smoke-test":
        handle_smoke_test(args.config)
    elif args.command == "playtest":
        handle_playtest(args.config, args.strategy_guide, args.max_actions, args.output,
                        provider=args.provider, model=args.model, runs=args.runs)

if __name__ == "__main__":
    main()
