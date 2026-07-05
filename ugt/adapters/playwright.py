from playwright.sync_api import sync_playwright
from ugt.adapters.base import BaseAdapter

class PlaywrightAdapter(BaseAdapter):
    """
    Adapter for browser-based games (React, Phaser, Vue, etc.).
    Uses Playwright to spin up a browser, inject actions, and read state.

    Games must expose these global JS hooks:
      - window.__GET_STATE__()       → Returns game state as a JSON object
      - window.__SEND_ACTION__(id)   → Executes action, returns {state, terminated, truncated, info}
      - window.__RESET_GAME__()      → (Optional) Soft-resets without page reload
    """
    def __init__(self, config):
        super().__init__(config)
        self.playwright = None
        self.browser = None
        self.page = None
        self.step_delay_ms = getattr(config, '_step_delay_ms', None)
        if self.step_delay_ms is None:
            self.step_delay_ms = config.data.get("engine", {}).get("step_delay_ms", 50)

    def connect(self):
        self.playwright = sync_playwright().start()
        # Launch headless browser
        self.browser = self.playwright.chromium.launch(headless=True)
        self.page = self.browser.new_page()

        # Navigate to target game page
        url = self.config.engine_entry
        try:
            self.page.goto(url)
            # Wait for game to actually mount by checking for the state hook
            self.page.wait_for_function(
                "typeof window.__GET_STATE__ === 'function'",
                timeout=10000
            )
        except Exception as e:
            self.close()
            raise RuntimeError(f"Playwright failed to navigate to '{url}' or game did not mount __GET_STATE__: {e}")

    def reset(self):
        if not self.page:
            self.connect()

        try:
            # Check for a soft reset function first (avoids ~15s page reload)
            has_soft_reset = self.page.evaluate("() => typeof window.__RESET_GAME__ === 'function'")
            if has_soft_reset:
                self.page.evaluate("window.__RESET_GAME__()")
                # Wait for reset to complete — state function should be available
                self.page.wait_for_function(
                    "typeof window.__GET_STATE__ === 'function'",
                    timeout=5000
                )
            else:
                # Fall back to page reload
                reset_cmd = self.config.engine_reset_command
                if reset_cmd and reset_cmd != "page.reload()":
                    self.page.evaluate(reset_cmd)
                else:
                    self.page.reload()
                # Wait for game to re-mount
                self.page.wait_for_function(
                    "typeof window.__GET_STATE__ === 'function'",
                    timeout=10000
                )

            # Retrieve initial state
            return self._get_game_state()
        except Exception as e:
            raise RuntimeError(f"Error resetting browser game environment: {e}")

    def _get_game_state(self):
        """Extract game state via the standard __GET_STATE__ endpoint."""
        has_state_fn = self.page.evaluate("() => typeof window.__GET_STATE__ === 'function'")
        if not has_state_fn:
            raise RuntimeError("Missing required global JS hook: window.__GET_STATE__")

        state = self.page.evaluate("window.__GET_STATE__()")
        if not isinstance(state, dict):
            raise TypeError(f"window.__GET_STATE__() must return a JSON object/dict, got {type(state)}")
        return state

    def step(self, action_id):
        """
        Execute an action via __SEND_ACTION__.

        The JS hook should return a structured response:
          {state: {...}, terminated: bool, truncated: bool, info: {...}}

        If it returns only a state dict (legacy mode), lifecycle fields are
        extracted from the state itself as a fallback.
        """
        has_send_fn = self.page.evaluate("() => typeof window.__SEND_ACTION__ === 'function'")
        if not has_send_fn:
            raise RuntimeError("Missing required global JS hook: window.__SEND_ACTION__")

        try:
            # Trigger action in browser — expect structured response
            response = self.page.evaluate(f"window.__SEND_ACTION__({int(action_id)})")

            # Wait for step processing using adaptive strategy:
            # 1. Check if game sets a __STEP_COMPLETE__ flag
            # 2. Fall back to configured step_delay_ms
            try:
                self.page.wait_for_function(
                    "window.__STEP_COMPLETE__ === true",
                    timeout=self.step_delay_ms
                )
                # Clear the flag for next step
                self.page.evaluate("window.__STEP_COMPLETE__ = false")
            except Exception:
                # Game doesn't use __STEP_COMPLETE__ — the step_delay_ms timeout
                # already provided the necessary wait
                pass

            # Handle structured response (preferred) vs raw state (legacy)
            if isinstance(response, dict) and "state" in response:
                state = response["state"]
                terminated = response.get("terminated", False)
                truncated = response.get("truncated", False)
                info = response.get("info", {})
            else:
                # Legacy mode: read state fresh, extract lifecycle from state dict
                state = self._get_game_state()
                terminated = state.pop("terminated", False)
                truncated = state.pop("truncated", False)
                info = state.pop("info", {})

            return state, terminated, truncated, info
        except Exception as e:
            raise RuntimeError(f"Error executing action {action_id} in browser: {e}")

    def press_key(self, key: str) -> None:
        """Send a single keypress to the browser page (e.g. 'T', 'Enter', 'Escape')."""
        if not self.page:
            raise RuntimeError("press_key() called before connect()")
        self.page.keyboard.press(key)

    def type_text(self, text: str, press_enter: bool = True) -> None:
        """Type a string into the browser, optionally followed by Enter."""
        if not self.page:
            raise RuntimeError("type_text() called before connect()")
        self.page.keyboard.type(text)
        if press_enter:
            self.page.keyboard.press("Enter")

    def get_terminal_text(self, chars: int = 600) -> str:
        """
        Return the last `chars` characters of the game's terminal output.

        Games can expose a `window.__GET_TERMINAL_TEXT__()` hook for best results.
        Falls back to extracting innerText from common terminal element selectors
        (.xterm-rows, #terminal, [data-terminal]).
        """
        if not self.page:
            return ""
        try:
            text = self.page.evaluate(
                "() => { "
                "  if (typeof window.__GET_TERMINAL_TEXT__ === 'function') "
                "    return window.__GET_TERMINAL_TEXT__(); "
                "  const el = document.querySelector('.xterm-rows, #terminal, [data-terminal]'); "
                "  return el ? el.innerText : ''; "
                "}"
            )
            return (text or "")[-chars:]
        except Exception:
            return ""

    def close(self):
        if self.page:
            self.page.close()
            self.page = None
        if self.browser:
            self.browser.close()
            self.browser = None
        if self.playwright:
            self.playwright.stop()
            self.playwright = None
