from abc import ABC, abstractmethod

class BaseAdapter(ABC):
    """
    Abstract Base Class for Game Adapters in Universal Game Tester (UGT).
    Adapters act as the bridge between UGT and different game platforms/simulators.
    """
    def __init__(self, config):
        self.config = config

    @abstractmethod
    def connect(self):
        """Establish connection with the game (e.g., launch browser or start subprocess)."""
        pass

    @abstractmethod
    def reset(self):
        """
        Reset the game environment.
        Returns:
            dict: The initial game state data.
        """
        pass

    @abstractmethod
    def step(self, action_id):
        """
        Execute an action in the game.
        Args:
            action_id (int): The ID of the action to execute.
        Returns:
            tuple: (state_dict, terminated, truncated, info)
        """
        pass

    @abstractmethod
    def close(self):
        """Teardown connections and cleanup resources."""
        pass

    # ── Optional UI-action methods ───────────────────────────────────────────
    # Adapters that support direct keyboard input implement these.
    # The default raises NotImplementedError so callers know when they're
    # reaching into a capability the adapter doesn't have.

    def press_key(self, key: str) -> None:
        """Send a single keypress to the game UI (e.g. 'T', 'Enter', 'Escape')."""
        raise NotImplementedError(f"{type(self).__name__} does not support press_key()")

    def type_text(self, text: str, press_enter: bool = True) -> None:
        """Type a string into the game UI, optionally followed by Enter."""
        raise NotImplementedError(f"{type(self).__name__} does not support type_text()")

    def get_terminal_text(self, chars: int = 600) -> str:
        """Return the last `chars` characters of visible terminal/game output.
        Returns empty string for adapters that cannot expose raw text output."""
        return ""
