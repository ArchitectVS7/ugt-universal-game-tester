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

    def reset_seeded(self, seed) -> dict:
        """Start a fresh episode on an EXPLICIT seed; return the initial state.

        Same contract as `reset()` in every respect except that the game's RNG
        seed is chosen by the caller rather than by the game.

        **Why this is a separate method rather than `reset(seed=None)`:** the
        default `reset()` is what the playtest loop calls between episodes, and
        the documented browser hook — `window.__RESET_GAME__()` — takes no
        arguments. A game whose reset defaults to "replay the current seed" then
        hands the tier N copies of one match: the run reports N episodes, the
        aggregate reports an N-sized denominator, and the sample size is 1.
        Measured on a browser dice game, where two consecutive "different"
        battles shared 10 of their first 12 (action, state-delta) pairs. It is
        completely invisible in the output. (`LESSONS.md` §B P9.)

        **An adapter that cannot control the seed MUST raise, never silently
        ignore the argument.** Silent ignoring reproduces the exact bug above
        while *looking* fixed, which is strictly worse than not having the
        feature — the same discipline as an unmapped action raising
        `NotImplementedError` rather than fabricating behaviour (`LESSONS.md`
        M1). Callers that request seeding and get a refusal must fail closed.

        Note that a raise is necessary but not sufficient: a JS hook silently
        IGNORES extra arguments, so a browser adapter can forward a seed to a
        game that does nothing with it and no exception is raised anywhere.
        Any caller relying on seed variety must additionally PROVE it — reset on
        two different seeds and assert the resulting episodes differ (O2).
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support reset_seeded() — it cannot "
            f"control the game's RNG seed, so every episode it produces replays "
            f"the same one. Do not treat its episodes as independent samples."
        )
