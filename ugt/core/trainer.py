import os
import logging
from stable_baselines3 import PPO, DQN, A2C
from stable_baselines3.common.vec_env import SubprocVecEnv, DummyVecEnv, VecNormalize
from stable_baselines3.common.callbacks import CheckpointCallback
from ugt.core.env import UniversalGameEnv
from stable_baselines3.common.utils import set_random_seed
from ugt.utils.config_parser import ConfigError

ALGORITHM_MAP = {
    "PPO": PPO,
    "DQN": DQN,
    "A2C": A2C,
}


def _make_env(config, profile_name):
    """Factory function that returns a callable for SubprocVecEnv."""
    def _init():
        return UniversalGameEnv(config, profile_name)
    return _init


def train_agent(config, profile_name):
    """Orchestrates Stable Baselines3 reinforcement learning for a given config and profile."""
    # Ensure models and logs directories exist in the project directory
    project_dir = os.path.dirname(os.path.abspath(config.filepath))
    models_dir = os.path.join(project_dir, "models")
    checkpoint_dir = os.path.join(models_dir, "checkpoints")
    logs_dir = os.path.join(project_dir, "logs")
    os.makedirs(models_dir, exist_ok=True)
    os.makedirs(checkpoint_dir, exist_ok=True)
    os.makedirs(logs_dir, exist_ok=True)

    training_cfg = config.data.get("training", {})
    algo_name = training_cfg.get("algorithm", "PPO")
    total_timesteps = training_cfg.get("total_timesteps", 100000)
    parallel_envs = training_cfg.get("parallel_envs", 1)
    checkpoint_freq = training_cfg.get("checkpoint_freq", None)
    seed = training_cfg.get("seed", 42)

    # Resolve algorithm class
    algo_cls = ALGORITHM_MAP.get(algo_name)
    if not algo_cls:
        raise ConfigError(f"Unsupported algorithm: '{algo_name}'. Supported: {list(ALGORITHM_MAP.keys())}")

    print(f"[*] Initializing Universal Gymnasium Environment for project: {config.project_name}")
    print(f"[*] Engine: {config.engine_type} | Reward Profile: {profile_name}")
    print(f"[*] Algorithm: {algo_name} | Parallel Envs: {parallel_envs} | Timesteps: {total_timesteps}")

    # Create vectorized environment
    if parallel_envs > 1:
        print(f"[*] Launching {parallel_envs} parallel environments via SubprocVecEnv...")
        env = SubprocVecEnv([_make_env(config, profile_name) for _ in range(parallel_envs)])
    else:
        env = DummyVecEnv([_make_env(config, profile_name)])

    # Normalize observations and rewards so PPO's value function can actually fit.
    # Without this the raw reward scale (delivery +200, win +1000, loss -100) diverges the
    # critic (explained_variance stays ~0), which collapses the policy to a single action.
    env = VecNormalize(env, norm_obs=True, norm_reward=True, clip_obs=10.0)

    # Build callbacks
    callbacks = []
    if checkpoint_freq:
        print(f"[*] Periodic checkpoints every {checkpoint_freq} timesteps → {checkpoint_dir}")
        callbacks.append(CheckpointCallback(
            save_freq=max(checkpoint_freq // parallel_envs, 1),
            save_path=checkpoint_dir,
            name_prefix=f"{algo_name.lower()}_{profile_name}",
        ))

    # Check if tensorboard is available for logging
    tb_log = None
    try:
        import tensorboard  # noqa: F401
        tb_log = logs_dir
    except ImportError:
        logging.warning(
            "TensorBoard is not installed. Training will proceed without TensorBoard logging. "
            "Install it with: pip install tensorboard"
        )

    print(f"[*] Starting {algo_name} training for {total_timesteps} timesteps...")
    print(f"[*] Seeding training with seed={seed} (set training.seed in config to change)")
    set_random_seed(seed)

    model = algo_cls(
        "MlpPolicy",
        env,
        seed=seed,
        verbose=1,
        tensorboard_log=tb_log,
    )

    try:
        model.learn(
            total_timesteps=total_timesteps,
            callback=callbacks if callbacks else None,
        )

        # Save final model
        model_filename = f"{algo_name.lower()}_{profile_name}_final"
        model_path = os.path.join(models_dir, model_filename)
        model.save(model_path)
        # Persist normalization stats alongside the model; eval must reuse them so the
        # policy sees in-distribution (normalized) observations.
        vecnorm_path = os.path.join(models_dir, f"{algo_name.lower()}_{profile_name}_vecnormalize.pkl")
        env.save(vecnorm_path)
        print(f"[+] Training completed successfully! Model saved to: {model_path}.zip")
        print(f"[+] VecNormalize stats saved to: {vecnorm_path}")
    except KeyboardInterrupt:
        print("[!] Training interrupted by user. Saving current model checkpoint...")
        model_path = os.path.join(models_dir, f"{algo_name.lower()}_{profile_name}_interrupted")
        model.save(model_path)
    finally:
        env.close()
