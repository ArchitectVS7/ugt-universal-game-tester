import gymnasium as gym
import numpy as np
from gymnasium import spaces
from ugt.adapters.playwright import PlaywrightAdapter
from ugt.adapters.subprocess import SubprocessAdapter

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
    Translates raw JSON game state into a standard Gymnasium observation/action loop.
    Used by `ugt smoke-test` for a quick wiring check — reward is always 0.0 since
    nothing in UGT's three testing tiers consumes it (verify/exploit-hunter/playtest
    all drive an adapter directly, not this env).
    """
    spec = None

    def __init__(self, config):
        super().__init__()
        self.config = config
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
        elif self.config.engine_type == "custom":
            raise ValueError(
                "engine.type 'custom' has no adapter to dispatch — the integration builds "
                "its own adapter and calls it directly, so it cannot go through this env. "
                "Import your adapter in your ladder scripts instead "
                "(see examples/sokoban/integration)."
            )
        else:
            raise ValueError(f"Unknown engine type: {self.config.engine_type}")

        self.adapter.connect()
        self.raw_state = {}

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
        self.raw_state = self.adapter.reset()
        obs = self._map_state_to_obs(self.raw_state)
        info = self.raw_state.get("info", {})
        return obs, info

    def step(self, action):
        next_state, terminated, truncated, info = self.adapter.step(int(action))
        self.raw_state = next_state

        # Translate state to flat numerical observation vector
        obs = self._map_state_to_obs(next_state)

        return obs, 0.0, terminated, truncated, info

    def close(self):
        self.adapter.close()
