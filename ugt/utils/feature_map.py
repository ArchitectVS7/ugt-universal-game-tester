import yaml
from dataclasses import dataclass, field

PRIORITY_ORDER = {"critical": 0, "major": 1, "minor": 2}


class FeatureMapError(Exception):
    pass


@dataclass
class Feature:
    id: str
    description: str
    action_names: list        # action names as strings, e.g. ["invest_credits"]
    assertions: list          # assertion expressions, e.g. ["state.player.credits > before.player.credits"]
    priority: str             # "critical" | "major" | "minor"
    precondition: str         # optional expression checked before execution; None if absent
    rng_controlled: bool      # True if this feature requires an RNG seam


class FeatureMap:
    """
    Loads and validates a feature-map.yaml file.

    Feature maps define the testable behaviors of a game at the action-name level.
    Each feature names one or more actions (by name, as defined in ugt.config.yaml),
    an optional precondition expression, and one or more assertion expressions that
    must hold after the actions are executed.

    Action names map to integer action IDs at verify-time via action_ids_for_feature().
    This is a simulation-game-first design; browser press_key flows are a future extension.
    """

    def __init__(self, filepath: str):
        self.filepath = filepath
        self._features = []
        self._load()

    def _load(self):
        try:
            with open(self.filepath) as f:
                data = yaml.safe_load(f)
        except FileNotFoundError:
            raise FeatureMapError(
                f"Feature map not found: '{self.filepath}'\n"
                "Create one with 'features:' entries alongside your ugt.config.yaml."
            )
        except yaml.YAMLError as e:
            raise FeatureMapError(f"Failed to parse feature map '{self.filepath}': {e}")

        if not isinstance(data, dict):
            raise FeatureMapError(f"Feature map must be a YAML mapping, got: {type(data).__name__}")

        raw_features = data.get("features", [])
        if not isinstance(raw_features, list):
            raise FeatureMapError("'features' must be a list of feature entries")

        for i, entry in enumerate(raw_features):
            feature = self._parse_feature(entry, index=i)
            self._features.append(feature)

        # Sort by priority (critical first) then by original definition order
        self._features.sort(key=lambda f: (PRIORITY_ORDER.get(f.priority, 99), raw_features.index(
            next(e for e in raw_features if e.get("id") == f.id)
        )))

    def _parse_feature(self, entry: dict, index: int) -> Feature:
        if not isinstance(entry, dict):
            raise FeatureMapError(f"Feature at index {index} must be a mapping, got: {type(entry).__name__}")

        feature_id = entry.get("id")
        if not feature_id:
            raise FeatureMapError(f"Feature at index {index} is missing required field 'id'")

        description = entry.get("description", "")

        # action: scalar string or list of strings
        raw_action = entry.get("action")
        if raw_action is None:
            raise FeatureMapError(f"Feature '{feature_id}' is missing required field 'action'")
        if isinstance(raw_action, str):
            action_names = [raw_action]
        elif isinstance(raw_action, list):
            action_names = raw_action
        else:
            raise FeatureMapError(f"Feature '{feature_id}': 'action' must be a string or list, got {type(raw_action).__name__}")

        # assertion: scalar string or list of strings
        raw_assertion = entry.get("assertion")
        if raw_assertion is None:
            raise FeatureMapError(f"Feature '{feature_id}' is missing required field 'assertion'")
        if isinstance(raw_assertion, str):
            assertions = [raw_assertion]
        elif isinstance(raw_assertion, list):
            assertions = raw_assertion
        else:
            raise FeatureMapError(f"Feature '{feature_id}': 'assertion' must be a string or list")

        priority = entry.get("priority", "minor")
        if priority not in PRIORITY_ORDER:
            raise FeatureMapError(
                f"Feature '{feature_id}': unknown priority '{priority}'. "
                f"Must be one of: {list(PRIORITY_ORDER.keys())}"
            )

        precondition = entry.get("precondition", None)
        rng_controlled = bool(entry.get("rng_controlled", False))

        return Feature(
            id=feature_id,
            description=description,
            action_names=action_names,
            assertions=assertions,
            priority=priority,
            precondition=precondition,
            rng_controlled=rng_controlled,
        )

    @property
    def features(self) -> list:
        """All features sorted by priority (critical first) then definition order."""
        return list(self._features)

    def action_ids_for_feature(self, feature: Feature, config) -> list:
        """
        Resolve feature action names to integer IDs using the config's action_space.

        config.action_mappings is {0: {"name": "wait"}, 1: {"name": "invest_credits"}, ...}
        We invert it to {"wait": 0, "invest_credits": 1, ...} for lookup.

        Raises FeatureMapError if any action name is not found in the config.
        """
        name_to_id = {}
        for action_id, action_def in config.action_mappings.items():
            if isinstance(action_def, dict):
                name = action_def.get("name", str(action_id))
            else:
                name = str(action_def)
            name_to_id[name] = int(action_id)

        result = []
        for name in feature.action_names:
            if name not in name_to_id:
                available = list(name_to_id.keys())
                raise FeatureMapError(
                    f"Feature '{feature.id}': action '{name}' not found in config action_space. "
                    f"Available actions: {available}"
                )
            result.append(name_to_id[name])
        return result
