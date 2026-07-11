import os
import yaml

class ConfigError(Exception):
    pass

class UgtConfig:
    def __init__(self, filepath):
        self.filepath = filepath
        self.data = self._load()
        self._validate()

    def _load(self):
        if not os.path.exists(self.filepath):
            raise ConfigError(f"Config file not found: {self.filepath}")
        try:
            with open(self.filepath, "r") as f:
                return yaml.safe_load(f)
        except Exception as e:
            raise ConfigError(f"Error parsing configuration YAML: {e}")

    def _validate(self):
        # Validate critical sections
        if not isinstance(self.data, dict):
            raise ConfigError("Config data must be a dictionary.")

        if "project" not in self.data or "name" not in self.data["project"]:
            raise ConfigError("Missing required field: project.name")

        if "engine" not in self.data:
            raise ConfigError("Missing required section: engine")
        engine = self.data["engine"]
        if "type" not in engine or engine["type"] not in ["browser", "simulation", "real_server", "ddd"]:
            raise ConfigError("engine.type must be one of 'browser', 'simulation', 'real_server', 'ddd'")
        # real_server drives a running game over HTTP/Socket.IO — it uses base_url/server_cmd,
        # not a sim entrypoint — so engine.entry is not required for it.
        if engine["type"] != "real_server" and "entry" not in engine:
            raise ConfigError("Missing required field: engine.entry")

        if "observation_space" not in self.data:
            raise ConfigError("Missing required section: observation_space")
        obs = self.data["observation_space"]
        if "type" not in obs or obs["type"] != "box":
            raise ConfigError("observation_space.type must be 'box' currently")
        if "shape" not in obs or not isinstance(obs["shape"], int):
            raise ConfigError("observation_space.shape must be an integer")
        if "mappings" not in obs or not isinstance(obs["mappings"], list):
            raise ConfigError("observation_space.mappings must be a list of mappings")

        # Cross-check shape against actual number of mappings
        if obs["shape"] != len(obs["mappings"]):
            raise ConfigError(
                f"observation_space.shape ({obs['shape']}) does not match "
                f"the number of mappings ({len(obs['mappings'])}). These must be equal."
            )

        if "action_space" not in self.data:
            raise ConfigError("Missing required section: action_space")
        act = self.data["action_space"]
        if "type" not in act or act["type"] != "discrete":
            raise ConfigError("action_space.type must be 'discrete' currently")
        if "size" not in act or not isinstance(act["size"], int):
            raise ConfigError("action_space.size must be an integer")

        # Cross-check action size against actual actions defined
        if "actions" in act and isinstance(act["actions"], dict):
            if act["size"] != len(act["actions"]):
                raise ConfigError(
                    f"action_space.size ({act['size']}) does not match "
                    f"the number of defined actions ({len(act['actions'])}). These must be equal."
                )

        if "reward_profiles" not in self.data or not isinstance(self.data["reward_profiles"], dict):
            raise ConfigError("Missing required section: reward_profiles (must be a dictionary)")

        # Validate training section (optional but checked if present)
        training = self.data.get("training", {})
        if training:
            if "parallel_envs" in training:
                pe = training["parallel_envs"]
                if not isinstance(pe, int) or pe < 1:
                    raise ConfigError("training.parallel_envs must be a positive integer")
            if "algorithm" in training:
                algo = training["algorithm"]
                if algo not in ("PPO", "DQN", "A2C"):
                    raise ConfigError(f"training.algorithm must be one of PPO, DQN, A2C (got '{algo}')")
            if "checkpoint_freq" in training:
                cf = training["checkpoint_freq"]
                if not isinstance(cf, int) or cf < 1:
                    raise ConfigError("training.checkpoint_freq must be a positive integer")
            if "seed" in training:
                s = training["seed"]
                if not isinstance(s, int):
                    raise ConfigError("training.seed must be an integer (e.g. seed: 42)")

    @property
    def project_name(self):
        return self.data["project"]["name"]

    @property
    def engine_type(self):
        return self.data["engine"]["type"]

    @property
    def engine_entry(self):
        # Optional for real_server (which uses base_url/server_cmd instead of a sim entry).
        return self.data["engine"].get("entry")

    @property
    def engine_reset_command(self):
        return self.data["engine"].get("reset_command")

    @property
    def obs_shape(self):
        return self.data["observation_space"]["shape"]

    @property
    def obs_mappings(self):
        return self.data["observation_space"]["mappings"]

    @property
    def action_size(self):
        return self.data["action_space"]["size"]

    @property
    def action_mappings(self):
        return self.data["action_space"].get("actions", {})

    @property
    def reward_profiles(self):
        return self.data["reward_profiles"]

    def get_reward_profile(self, name):
        profile = self.reward_profiles.get(name)
        if not profile:
            raise ConfigError(f"Reward profile '{name}' not found in configuration.")
        return profile
