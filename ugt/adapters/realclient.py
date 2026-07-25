"""
RealClientAdapter — drives a LIVE game server (Socket.IO + HTTP), engine.type "real_server".

This module is a TRANSPORT SKELETON. It handles:
  - optional server lifecycle (spawn via server_cmd, or attach to a running server)
  - Socket.IO authentication + screen:request / screen:input roundtrip
  - HTTP request helpers (_http_post, _auth_header)
  - BaseAdapter interface: connect / reset / step / close / press_key / type_text / get_terminal_text

What you must implement per-integration (subclass or monkey-patch before use):

  _read_state(self) -> dict
      Map your game's API response into the nested obs dict your config's
      observation_space.mappings paths expect. Called by reset() and step().

  ACTION_HANDLERS (class-level dict)
      Map action names (strings from your config's action_space) to handler
      functions with signature handler(adapter_self) -> info_dict.
      Unmapped actions raise NotImplementedError — intentional (no fabricated game logic).

Verified server protocol assumptions (adjust per game):
  - dev-login: GET /auth/dev-login -> 302 with ?token= query param
  - reset:     POST <reset_endpoint> -> character is re-initialised server-side
  - screens:   Socket.IO events "screen:request" / "screen:input" -> "screen:render"
  - an unknown screen id SILENTLY falls back to main-menu (watch for this drift)
  - screen:request emits two identical renders; drain with a short quiet window
  - a menu key that navigates returns {nextScreen: <id>} not content -> follow it
"""
from __future__ import annotations

import os
import subprocess
import threading
import time

import requests
import socketio

from ugt.adapters.base import BaseAdapter

DEFAULTS = {
    "base_url": "http://127.0.0.1:3005",
    "main_menu_screen": "main-menu",
    "reset_endpoint": "/auth/dev-setup-character",
    "connect_timeout": 10.0,
    "render_quiet_period": 0.4,
    "server_boot_timeout": 30.0,
}


class RealClientAdapter(BaseAdapter):
    """Generic Socket.IO + HTTP adapter for live game servers.

    Subclass this for your game and implement _read_state() and ACTION_HANDLERS.
    See module docstring for the protocol contract.
    """

    # ── Per-integration extension points ──────────────────────────────────────

    ACTION_HANDLERS: dict = {}
    """Map action name -> handler(self) -> info dict. Populated by each integration."""

    def _read_state(self) -> dict:
        """Return the current game state as the nested dict your feature-map paths address.

        Override this in your integration. Typical pattern:
          payload = self.get_json("/api/your-state-endpoint")
          return {"player": {"credits": payload["credits"], ...}, ...}
        """
        raise NotImplementedError(
            "_read_state() must be implemented per-integration. "
            "Map your game's API response to the obs dict your config paths expect. "
            "See ugt/adapters/realclient.py module docstring for the pattern."
        )

    # ── Constructor ───────────────────────────────────────────────────────────

    def __init__(self, config=None):
        super().__init__(config)
        eng = {}
        if config is not None:
            try:
                eng = config.data.get("engine", {}) or {}
            except AttributeError:
                eng = {}
        self.base_url = eng.get("base_url", DEFAULTS["base_url"]).rstrip("/")
        self.main_menu = eng.get("main_menu_screen", DEFAULTS["main_menu_screen"])
        self.reset_endpoint = eng.get("reset_endpoint", DEFAULTS["reset_endpoint"])
        self.connect_timeout = float(eng.get("connect_timeout", DEFAULTS["connect_timeout"]))
        self.render_quiet = float(eng.get("render_quiet_period", DEFAULTS["render_quiet_period"]))

        # Optional server lifecycle: if server_cmd is set, spawn and manage it;
        # otherwise attach to an already-running server at base_url.
        self.server_cmd = eng.get("server_cmd")
        self.server_cwd = eng.get("server_cwd")
        self.server_env_file = eng.get("server_env_file")
        self.server_boot_timeout = float(eng.get("server_boot_timeout", DEFAULTS["server_boot_timeout"]))

        # action_id -> action name mapping, from config.
        self._action_names = {}
        if config is not None:
            try:
                for k, v in (config.action_mappings or {}).items():
                    self._action_names[int(k)] = v.get("name") if isinstance(v, dict) else str(v)
            except Exception:
                self._action_names = {}

        # transport / lifecycle state
        self.token = None
        self.sio = None
        self._server_proc = None
        self._we_spawned_server = False
        self._turn = 0
        self._authed = threading.Event()
        self._auth_ok = False
        self._last_render = None
        self._render_evt = threading.Event()
        self._last_terminal = ""
        # Transport bookkeeping — not game logic: the screen the next input targets.
        self._current_screen = self.main_menu
        self._last_input_meta = None

    # ── BaseAdapter lifecycle ─────────────────────────────────────────────────

    def connect(self):
        if self.server_cmd:
            self._spawn_server()
        self._wait_for_server()
        self._dev_login()
        self._connect_socket()

    def reset(self):
        """Episode reset via the game's dev endpoint; returns the initial observation."""
        r = requests.post(f"{self.base_url}{self.reset_endpoint}",
                          headers=self._auth_header(), timeout=10)
        r.raise_for_status()
        self._turn = 0
        self._last_terminal = self.screen_request(self.main_menu).get("output", "")
        return self._read_state()

    def step(self, action_id):
        """Execute an action. Returns (state, terminated, truncated, info).

        Dispatches through ACTION_HANDLERS. Unmapped actions raise NotImplementedError
        — the adapter does not fabricate game logic.
        """
        self._turn += 1
        name = self._action_names.get(int(action_id), f"action_{action_id}")
        handler = self.ACTION_HANDLERS.get(name)
        if handler is None:
            raise NotImplementedError(
                f"action '{name}' (id {action_id}) is not mapped — add it to ACTION_HANDLERS. "
                f"Transport primitives available: screen_request / screen_input / "
                f"press_menu_key / press_key / type_text / _http_post."
            )
        info = handler(self) or {}
        state = self._read_state()
        terminated = bool(info.get("terminated", False))
        truncated = bool(info.get("truncated", False))
        return state, terminated, truncated, info

    def close(self):
        try:
            if self.sio is not None and self.sio.connected:
                self.sio.disconnect()
        except Exception:
            pass
        self.sio = None
        if self._we_spawned_server and self._server_proc is not None:
            if self._server_proc.poll() is None:
                self._server_proc.terminate()
                try:
                    self._server_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._server_proc.kill()
            self._server_proc = None

    # ── BaseAdapter optional UI actions ──────────────────────────────────────

    def press_key(self, key: str) -> None:
        self._input_follow(self._current_screen, key)

    def type_text(self, text: str, press_enter: bool = True) -> None:
        self._input_follow(self._current_screen, text)

    def get_terminal_text(self, chars: int = 600) -> str:
        return self._last_terminal[-chars:] if self._last_terminal else ""

    # ── Transport: HTTP ───────────────────────────────────────────────────────

    def _auth_header(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    def _dev_login(self) -> str:
        """GET /auth/dev-login, extract Bearer token from redirect Location header."""
        r = requests.get(f"{self.base_url}/auth/dev-login", allow_redirects=False, timeout=10)
        loc = r.headers.get("location", "")
        if "token=" not in loc:
            raise RuntimeError(f"dev-login returned no token; status={r.status_code} loc={loc!r}")
        self.token = loc.split("token=", 1)[1]
        return self.token

    def get_json(self, path: str) -> dict:
        """GET a JSON endpoint with the current auth token."""
        r = requests.get(f"{self.base_url}{path}", headers=self._auth_header(), timeout=10)
        r.raise_for_status()
        return r.json()

    def _http_post(self, path: str, body: dict | None = None):
        r = requests.post(f"{self.base_url}{path}", headers=self._auth_header(),
                          json=(body or {}), timeout=15)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {"raw": r.text}

    # ── Transport: Socket.IO screens ──────────────────────────────────────────

    def _connect_socket(self):
        self.sio = socketio.Client(reconnection=False, logger=False, engineio_logger=False)

        @self.sio.on("authenticated")
        def _on_auth(data):
            self._auth_ok = bool(data.get("success"))
            self._authed.set()

        @self.sio.on("screen:render")
        def _on_render(data):
            self._last_render = data
            self._render_evt.set()

        self.sio.connect(self.base_url, wait_timeout=self.connect_timeout)
        self._authed.clear()
        self.sio.emit("authenticate", {"token": self.token})
        if not self._authed.wait(timeout=self.connect_timeout):
            raise RuntimeError("timed out waiting for 'authenticated'")
        if not self._auth_ok:
            raise RuntimeError("server rejected authentication")

    def screen_request(self, screen: str) -> dict:
        resp = self._roundtrip("screen:request", {"screen": screen})
        self._current_screen = resp.get("nextScreen") or screen
        return resp

    def screen_input(self, screen: str, key: str) -> dict:
        return self._roundtrip("screen:input", {"screen": screen, "input": key})

    def press_menu_key(self, key: str, from_screen: str | None = None) -> dict:
        """Press a menu key and auto-follow its nextScreen to load real content."""
        src = from_screen or self.main_menu
        resp = self.screen_input(src, key)
        nxt = resp.get("nextScreen")
        self._last_input_meta = {"screen": src, "input": key, "had_next": bool(nxt)}
        if nxt:
            dest = self.screen_request(nxt)
        else:
            dest = resp
            self._current_screen = src
        self._last_terminal = dest.get("output", "")
        return dest

    def _roundtrip(self, event: str, payload: dict) -> dict:
        # One request/input can emit multiple screen:render events (request emits two identical;
        # some inputs emit a clear then content). Wait for the first, drain trailing renders for a
        # short quiet period, return the LAST settled dict (preserves `nextScreen`).
        if self.sio is None:
            raise RuntimeError("socket not connected — call connect() first")
        self._render_evt.clear()
        self._last_render = None
        self.sio.emit(event, payload)
        if not self._render_evt.wait(timeout=self.connect_timeout):
            raise RuntimeError(f"timed out waiting for 'screen:render' after {event}")
        last = self._last_render
        while True:
            self._render_evt.clear()
            if not self._render_evt.wait(timeout=self.render_quiet):
                break
            last = self._last_render
        return last or {}

    def _input_follow(self, screen: str, key: str):
        """screen:input on `screen`; if it returns a nextScreen, request it."""
        resp = self.screen_input(screen, key)
        nxt = resp.get("nextScreen")
        self._last_input_meta = {"screen": screen, "input": key, "had_next": bool(nxt)}
        if nxt:
            out = self.screen_request(nxt).get("output", "")
            self._last_terminal = out
            return nxt, out
        self._last_terminal = resp.get("output", "")
        self._current_screen = screen
        return screen, resp.get("output", "")

    def _goto_main(self):
        self._last_terminal = self.screen_request(self.main_menu).get("output", "")

    # ── Server lifecycle ──────────────────────────────────────────────────────

    def _spawn_server(self):
        env = os.environ.copy()
        if self.server_env_file and self.server_cwd:
            env_path = os.path.join(self.server_cwd, self.server_env_file)
            if os.path.exists(env_path):
                with open(env_path) as fh:
                    for line in fh:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, val = line.split("=", 1)
                            env[key.strip()] = val.strip()
        self._server_proc = subprocess.Popen(
            self.server_cmd.split(),
            cwd=self.server_cwd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._we_spawned_server = True

    def _wait_for_server(self):
        """Poll until the server answers dev-login, or time out."""
        deadline = time.monotonic() + self.server_boot_timeout
        last_err = None
        while time.monotonic() < deadline:
            try:
                requests.get(f"{self.base_url}/auth/dev-login", allow_redirects=False, timeout=2)
                return
            except Exception as e:
                last_err = e
                time.sleep(0.5)
        raise RuntimeError(f"server at {self.base_url} not ready within "
                           f"{self.server_boot_timeout}s: {last_err}")
