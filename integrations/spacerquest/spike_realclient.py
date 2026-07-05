#!/usr/bin/env python3
"""
Phase 0 / Step 0 spike: headless real-client for the LIVE spacerquest-web server.

This is the reconstituted, committed version of the 2026-07-04 spike that de-risked
the "play the game with the game" pivot (see memory note `architecture-pivot-real-server`).
It proves the whole real-client path round-trips headlessly:

    dev-login  ->  JWT
    dev-setup-character  ->  clean playable episode reset  (this is the Phase-0 reset primitive)
    Socket.IO authenticate  ->  {success: true}
    screen:request / screen:input  ->  screen:render (ANSI terminal text, for the LLM tier)
    GET /api/character  ->  structured state (for the RL / exploit-hunter obs)

It deliberately contains NO game logic (no travel/fuel/price math): everything is read
from, or driven through, the real server. That constraint is the whole point of the pivot.

Structured as a small `RealClient` so Step 1 can lift it into `ugt/adapters/realclient.py`
almost verbatim.

Prereqs (see PLAN-FORWARD.md "How to resume"):
  - Docker infra up:  Postgres :5454, Redis :6380
  - Server up on :3005:
      env $(grep -v '^#' .env.ugt | grep -v '^$' | xargs) UGT_TRAINING=1 \
        npx tsx src/app/index.ts        # run from SpacerQuest/spacerquest-web

Run:
    python3 integrations/spacerquest/spike_realclient.py

Exit code 0 + "SPIKE PASSED" means the real-client path is healthy and reproducible.
"""
from __future__ import annotations

import sys
import threading

import requests
import socketio

BASE_URL = "http://127.0.0.1:3005"
MAIN_MENU_SCREEN = "main-menu"   # screen ids are lowercase-kebab; unknown ids SILENTLY
                                 # fall back to 'main-menu' server-side (a real footgun).
MENU_KEY = "S"                   # 'S' -> Shipyard; a menu key returns nextScreen, not content
EXPECTED_NEXT = "shipyard"       # what pressing 'S' should transition to
CONNECT_TIMEOUT = 10.0           # seconds
RENDER_QUIET_PERIOD = 0.4        # wait this long for extra screen:render events before settling

# Real navigation protocol (verified against the live server, 2026-07-05):
#   screen:request {screen}        -> emits TWO identical {output} renders (dedupe: take last)
#   screen:input   {screen, input} -> emits ONE {output:'\x1b[2J\x1b[H', nextScreen:'<id>'}
#                                     i.e. a menu key returns a CLEAR + a transition target,
#                                     NOT the destination content.
#   client then screen:request {nextScreen} to load the destination.
# This is the contract Step 1's adapter action-map must implement.


class RealClient:
    """Thin, transport-agnostic handle on the running game. No game logic lives here."""

    def __init__(self, base_url: str = BASE_URL) -> None:
        self.base_url = base_url
        self.token: str | None = None
        self.sio = socketio.Client(reconnection=False, logger=False, engineio_logger=False)
        self._authed = threading.Event()
        self._auth_ok = False
        self._last_render: dict | None = None
        self._render_evt = threading.Event()

        @self.sio.on("authenticated")
        def _on_authenticated(data):  # noqa: ANN001
            self._auth_ok = bool(data.get("success"))
            self._authed.set()

        @self.sio.on("screen:render")
        def _on_render(data):  # noqa: ANN001
            self._last_render = data
            self._render_evt.set()

    # ── HTTP ────────────────────────────────────────────────────────────────
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    def dev_login(self) -> str:
        """Bootstrap a JWT via the server's own dev endpoint (creates a user if none)."""
        r = requests.get(f"{self.base_url}/auth/dev-login", allow_redirects=False, timeout=10)
        loc = r.headers.get("location", "")
        if "token=" not in loc:
            raise RuntimeError(f"dev-login did not return a token; status={r.status_code} loc={loc!r}")
        self.token = loc.split("token=", 1)[1]
        return self.token

    def reset(self) -> dict:
        """Phase-0 episode reset: bootstrap the character to a clean playable state."""
        r = requests.post(f"{self.base_url}/auth/dev-setup-character", headers=self._headers(), timeout=10)
        r.raise_for_status()
        return r.json()

    def get_character(self) -> dict:
        """Structured observation: character + ship state."""
        r = requests.get(f"{self.base_url}/api/character", headers=self._headers(), timeout=10)
        r.raise_for_status()
        return r.json()

    # ── Socket.IO ───────────────────────────────────────────────────────────
    def connect_and_auth(self) -> None:
        if not self.token:
            raise RuntimeError("call dev_login() before connect_and_auth()")
        self.sio.connect(self.base_url, wait_timeout=CONNECT_TIMEOUT)
        self.sio.emit("authenticate", {"token": self.token})
        if not self._authed.wait(timeout=CONNECT_TIMEOUT):
            raise RuntimeError("timed out waiting for 'authenticated' event")
        if not self._auth_ok:
            raise RuntimeError("server rejected authentication")

    def screen_request(self, screen: str) -> dict:
        """Ask for a screen; return the settled render dict ({output[, nextScreen]})."""
        return self._roundtrip("screen:request", {"screen": screen})

    def screen_input(self, screen: str, key: str) -> dict:
        """Send a keypress to a screen; return the settled render dict.

        For a main-menu navigation key this is a clear + {nextScreen}; follow it with
        screen_request(nextScreen) to load the destination. For an in-place key (e.g. 'X'
        Ship's Stats) it's the content directly, with no nextScreen.
        """
        return self._roundtrip("screen:input", {"screen": screen, "input": key})

    def press_menu_key(self, key: str, from_screen: str = MAIN_MENU_SCREEN) -> dict:
        """Press a menu key and auto-follow its nextScreen to load real content.

        Returns the destination render dict; if there was no transition, the input's own
        render. This is the shape Step 1's action-map will use for menu navigation.
        """
        resp = self.screen_input(from_screen, key)
        nxt = resp.get("nextScreen")
        return self.screen_request(nxt) if nxt else resp

    def _roundtrip(self, event: str, payload: dict) -> dict:
        # One request/input can emit MORE THAN ONE screen:render (a screen:request emits two
        # identical renders; some inputs emit a clear then content). Wait for the first, then
        # drain trailing renders for a brief quiet period and return the LAST settled dict.
        # Returning the dict (not just output) preserves `nextScreen` for navigation.
        self._render_evt.clear()
        self._last_render = None
        self.sio.emit(event, payload)
        if not self._render_evt.wait(timeout=CONNECT_TIMEOUT):
            raise RuntimeError(f"timed out waiting for 'screen:render' after {event}")
        last = self._last_render
        while True:
            self._render_evt.clear()
            if not self._render_evt.wait(timeout=RENDER_QUIET_PERIOD):
                break  # no further render within the quiet period -> settled
            last = self._last_render
        return last or {}

    def close(self) -> None:
        try:
            if self.sio.connected:
                self.sio.disconnect()
        except Exception:
            pass


def main() -> int:
    client = RealClient()
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, ok, detail))
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {name}" + (f"  — {detail}" if detail else ""))

    print(f"Spike: driving live server at {BASE_URL}\n")
    try:
        token = client.dev_login()
        check("dev-login -> JWT", bool(token) and len(token) > 20, f"token len={len(token)}")

        reset = client.reset()
        check("dev-setup-character (episode reset)", reset.get("success") is True, reset.get("message", ""))

        client.connect_and_auth()
        check("Socket.IO authenticate", client._auth_ok, "authenticated={success:true}")

        menu = client.screen_request(MAIN_MENU_SCREEN).get("output", "")
        check("screen:request -> screen:render", "MAIN MENU" in menu, f"{len(menu)} chars; MAIN MENU banner present")

        # Prove REAL navigation: 'S' returns nextScreen='shipyard', which we follow to load it.
        nav_resp = client.screen_input(MAIN_MENU_SCREEN, MENU_KEY)
        check(f"screen:input '{MENU_KEY}' -> nextScreen", nav_resp.get("nextScreen") == EXPECTED_NEXT,
              f"nextScreen={nav_resp.get('nextScreen')!r} (expected {EXPECTED_NEXT!r})")

        dest = client.screen_request(nav_resp.get("nextScreen", "")).get("output", "")
        check("follow nextScreen -> destination screen", len(dest) > 0 and dest != menu,
              f"{len(dest)} chars of a different screen")

        state = client.get_character()
        c = state.get("character", {})
        has_state = all(k in c for k in ("name", "currentSystem", "creditsLow"))
        check("GET /api/character (structured obs)", has_state,
              f"name={c.get('name')} system={c.get('currentSystem')} rank={c.get('rank')}")
    except Exception as exc:  # noqa: BLE001
        check("exception-free run", False, f"{type(exc).__name__}: {exc}")
    finally:
        client.close()

    passed = sum(1 for _, ok, _ in checks if ok)
    total = len(checks)
    print()
    if passed == total and total >= 6:
        print(f"SPIKE PASSED — {passed}/{total} checks. Real-client path is healthy and reproducible.")
        return 0
    print(f"SPIKE FAILED — {passed}/{total} checks passed.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
