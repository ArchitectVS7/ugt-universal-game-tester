import logging
import gymnasium as gym
import numpy as np
from gymnasium import spaces
from ugt.adapters.playwright import PlaywrightAdapter
from ugt.adapters.subprocess import SubprocessAdapter
from ugt.utils.formula_evaluator import evaluate_reward_formula

def get_value_by_path(nested_dict, path, aggregator=None):
    """Safely traverse a nested dictionary using a dot-separated path."""
    current = nested_dict
    for part in path.split('.'):
        if isinstance(current, dict):
            current = current.get(part, 0)
        else:
            return 0
            
    if aggregator and isinstance(current, list):
        if aggregator == "count":
            return len(current)
        numeric = [x for x in current if isinstance(x, (int, float))]
        if not numeric:
            return 0
        if aggregator == "sum":
            return float(sum(numeric))
        elif aggregator == "mean":
            return float(sum(numeric) / len(numeric))
        elif aggregator == "min":
            return float(min(numeric))
        elif aggregator == "max":
            return float(max(numeric))
    
    # If the retrieved value is not a float/int, return 0
    if not isinstance(current, (int, float)):
        return 0
    return float(current)

class UniversalGameEnv(gym.Env):
    """
    Universal Gymnasium Environment dynamically driven by a ugt.config.yaml file.
    Translates raw JSON game state and declarative rewards into a standard Gymnasium loop.
    """
    spec = None

    def __init__(self, config, profile_name):
        super().__init__()
        self.config = config
        self.profile_name = profile_name
        self.profile = self.config.get_reward_profile(profile_name)

        # Setup spaces dynamically.
        # Gate 1: if training.action_subset is set, the RL agent sees only those real
        # action IDs. Its policy indexes 0..N-1; step() remaps to the real game action.
        self.action_subset = None
        training_cfg = getattr(config, "data", {}).get("training", {})
        subset = training_cfg.get("action_subset") if training_cfg else None
        if subset:
            self.action_subset = list(subset)
            self.action_space = spaces.Discrete(len(self.action_subset))
        else:
            self.action_space = spaces.Discrete(self.config.action_size)
        
        # Build observation limits
        obs_min = []
        obs_max = []
        for mapping in self.config.obs_mappings:
            obs_min.append(mapping.get("min", -np.inf))
            obs_max.append(mapping.get("max", np.inf))
            
        self.observation_space = spaces.Box(
            low=np.array(obs_min, dtype=np.float32),
            high=np.array(obs_max, dtype=np.float32),
            dtype=np.float32
        )

        # Initialize Adapter
        if self.config.engine_type == "browser":
            self.adapter = PlaywrightAdapter(self.config)
        elif self.config.engine_type == "simulation":
            self.adapter = SubprocessAdapter(self.config)
        elif self.config.engine_type == "real_server":
            from ugt.adapters.realclient import RealClientAdapter
            self.adapter = RealClientAdapter(self.config)
        else:
            raise ValueError(f"Unknown engine type: {self.config.engine_type}")

        self.adapter.connect()
        self.raw_state = {}
        self.prev_raw_state = {}  # Previous state for delta-based reward formulas

    def _map_state_to_obs(self, raw_state):
        """Translate raw nested JSON dict into a flat numpy observation vector."""
        obs = []
        for mapping in self.config.obs_mappings:
            path = mapping["path"]
            agg = mapping.get("aggregator")
            val = get_value_by_path(raw_state, path, aggregator=agg)
            obs.append(val)
        return np.array(obs, dtype=np.float32)

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.prev_raw_state = {}
        self.raw_state = self.adapter.reset()
        obs = self._map_state_to_obs(self.raw_state)
        info = self.raw_state.get("info", {})
        return obs, info

    def step(self, action):
        # Gate 1: translate the agent's subset index into the real game action id.
        real_action = self.action_subset[int(action)] if self.action_subset else int(action)
        prev_state = self.raw_state
        next_state, terminated, truncated, info = self.adapter.step(real_action)
        self.prev_raw_state = prev_state
        self.raw_state = next_state

        # Translate state to flat numerical observation vector
        obs = self._map_state_to_obs(next_state)

        # Dynamically calculate reward. Pass prev_state as "before" so formulas can
        # express deltas: (state.character.score - before.character.score) * 10
        reward = 0.0
        formula = self.profile.get("formula")
        if formula:
            try:
                reward = float(evaluate_reward_formula(
                    formula, next_state, extra_context={"before": prev_state}
                ))
            except Exception as e:
                logging.warning(
                    "Reward formula evaluation failed (falling back to 0.0). "
                    "Formula: '%s' | Error: %s | State keys: %s",
                    formula, e, list(next_state.keys()) if isinstance(next_state, dict) else type(next_state)
                )
                reward = 0.0

        # Apply endgame victory/loss bonuses
        if terminated:
            is_win = next_state.get("victory", False)
            if is_win:
                reward += float(self.profile.get("win_bonus", 0))
            else:
                reward -= float(self.profile.get("loss_penalty", 0))

        return obs, reward, terminated, truncated, info

    def close(self):
        self.adapter.close()
