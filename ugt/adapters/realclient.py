"""
RealClientAdapter — drives a LIVE game server (Socket.IO + HTTP), engine.type "real_server".

This is the Phase-0 real-client adapter: UGT "plays the game with the game" instead of a
shadow reimplementation. It is the productionized lift of a validated protocol spike
against the BBS-style space-trading game it was built for (the game whose bridge
reimplementation drift motivated the M1 rule — see LESSONS.md).

Scope of this module (Phase 0, Step 1 + parts of 2 & 4):
  - server lifecycle (optional spawn/attach) + Socket.IO/HTTP client   [Step 1]
  - reset() via the game's own dev endpoint                            [Step 2]
  - observation reads: /api/character -> structured obs dict           [Step 4, first cut]
  - transport primitives (screen nav, key input, terminal text) the action map will compose

Explicitly NOT in this module:
  - the full action_id -> real-input mapping (trade/combat/upgrade multi-step flows).  [Step 3]
    step() dispatches through a handler registry; unmapped actions raise NotImplementedError
    naming the action, rather than inventing game logic here (that reimplementation drift is
    exactly what the pivot retired).

Verified server protocol (established by the spike, re-verified live):
  - screen ids are lowercase-kebab (`main-menu`); an unknown id SILENTLY falls back to main-menu.
  - screen:request emits TWO identical {output} renders  -> settle to the last.
  - a menu key returns {output:'\\x1b[2J\\x1b[H', nextScreen:'<id>'}, NOT content -> then request nextScreen.
  - bootstrap: GET /auth/dev-login (302 ?token=, creates user if none) ; POST /auth/dev-setup-character resets.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time

import requests
import socketio

from ugt.adapters.base import BaseAdapter

# Rank enum order from prisma/schema.prisma (index == obs `character.rank_index`).
RANK_ORDER = [
    "LIEUTENANT", "COMMANDER", "CAPTAIN", "COMMODORE", "ADMIRAL",
    "TOP_DOG", "GRAND_MUFTI", "MEGA_HERO", "GIGA_HERO",
]

DEFAULTS = {
    "base_url": "http://127.0.0.1:3005",
    "main_menu_screen": "main-menu",
    "connect_timeout": 10.0,
    "render_quiet_period": 0.4,   # window to absorb duplicate/trailing screen:render events
    "server_boot_timeout": 30.0,
}


class RealClientAdapter(BaseAdapter):
    """Transport-agnostic handle on the running game. Contains NO game logic."""

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
        self.connect_timeout = float(eng.get("connect_timeout", DEFAULTS["connect_timeout"]))
        self.render_quiet = float(eng.get("render_quiet_period", DEFAULTS["render_quiet_period"]))

        # Optional server lifecycle: if server_cmd is set we spawn+manage it; else we attach
        # to an already-running server at base_url.
        self.server_cmd = eng.get("server_cmd")            # e.g. "npx tsx src/app/index.ts"
        self.server_cwd = eng.get("server_cwd")            # path to the game's server checkout
        self.server_env_file = eng.get("server_env_file")  # e.g. ".env.ugt" (relative to cwd)
        self.server_boot_timeout = float(eng.get("server_boot_timeout", DEFAULTS["server_boot_timeout"]))

        # action_id -> action name, from config (used to dispatch step()).
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
        self._last_terminal = ""  # cache for get_terminal_text()
        # Free-form navigation state (transport bookkeeping, not game logic):
        # the screen the next press_key/type_text targets. Updated by every
        # screen_request/_input_follow/press_menu_key; reset() lands on main-menu.
        self._current_screen = self.main_menu
        # Metadata about the last input sent — lets callers (LLM playtest log) see which
        # screen a key actually went to (the server silently falls back to main-menu on
        # unknown screen ids, so this is the only drift signal available client-side).
        self._last_input_meta = None

    # ── BaseAdapter lifecycle ────────────────────────────────────────────────
    def connect(self):
        if self.server_cmd:
            self._spawn_server()
        self._wait_for_server()
        self._dev_login()
        self._connect_socket()

    def reset(self):
        """Episode reset via the game's own dev endpoint; returns the initial observation."""
        r = requests.post(f"{self.base_url}/auth/dev-setup-character",
                          headers=self._auth_header(), timeout=10)
        r.raise_for_status()
        self._turn = 0
        # Land on the main menu so every episode starts from a known screen.
        self._last_terminal = self.screen_request(self.main_menu).get("output", "")
        return self._read_state()

    def step(self, action_id):
        """Execute an action. Returns (state, terminated, truncated, info).

        Dispatches through ACTION_HANDLERS. The full trade/combat/upgrade map is Step 3;
        until an action is registered, this raises NotImplementedError naming it — we do
        NOT fabricate game logic in the adapter.
        """
        self._turn += 1
        name = self._action_names.get(int(action_id), f"action_{action_id}")
        handler = self.ACTION_HANDLERS.get(name)
        if handler is None:
            raise NotImplementedError(
                f"action '{name}' (id {action_id}) is not yet mapped to real inputs — "
                f"this is Step 3 (action map). Transport primitives are available: "
                f"screen_request/screen_input/press_menu_key/press_key/type_text."
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
        """Send a single keypress to the CURRENT screen (tracked across inputs)."""
        self._input_follow(self._current_screen, key)

    def type_text(self, text: str, press_enter: bool = True) -> None:
        """Type a string into the current screen. The server treats input as a line, so we
        send the whole string as one screen:input (press_enter is implicit at the protocol)."""
        self._input_follow(self._current_screen, text)

    def get_terminal_text(self, chars: int = 600) -> str:
        """Return the last `chars` of the most recent rendered terminal (for the LLM tier)."""
        return self._last_terminal[-chars:] if self._last_terminal else ""

    # ── Transport: HTTP ──────────────────────────────────────────────────────
    def _auth_header(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    def _dev_login(self) -> str:
        r = requests.get(f"{self.base_url}/auth/dev-login", allow_redirects=False, timeout=10)
        loc = r.headers.get("location", "")
        if "token=" not in loc:
            raise RuntimeError(f"dev-login returned no token; status={r.status_code} loc={loc!r}")
        self.token = loc.split("token=", 1)[1]
        return self.token

    def get_character(self) -> dict:
        r = requests.get(f"{self.base_url}/api/character", headers=self._auth_header(), timeout=10)
        r.raise_for_status()
        return r.json()

    # ── Transport: Socket.IO screens ─────────────────────────────────────────
    def _connect_socket(self):
        self.sio = socketio.Client(reconnection=False, logger=False, engineio_logger=False)

        @self.sio.on("authenticated")
        def _on_auth(data):  # noqa: ANN001
            self._auth_ok = bool(data.get("success"))
            self._authed.set()

        @self.sio.on("screen:render")
        def _on_render(data):  # noqa: ANN001
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
        # Some renders are redirects (reason text + nextScreen, e.g. end-turn when the
        # turn can't end yet). Track where the server says we ARE — without re-requesting,
        # so callers still see the reason text in this response's output.
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

    # ── Observation ──────────────────────────────────────────────────────────
    def _read_state(self) -> dict:
        """Parse /api/character into the nested obs dict the config's feature-map paths expect.

        Every obs field is now sourced from real game state — the /api/character endpoint was
        extended (2026-07-05) to expose win-state, lost-state, bank balance, jail-state, and
        active-combat so a black-box tester is not blind to them. No hardcoded observation values.
        """
        payload = self.get_character()
        c = payload.get("character", {}) or {}
        s = payload.get("ship", {}) or {}
        rank = c.get("rank", "LIEUTENANT")
        rank_index = RANK_ORDER.index(rank) if rank in RANK_ORDER else 0
        credits = int(c.get("creditsHigh", 0)) * 10000 + int(c.get("creditsLow", 0))
        bank_balance = int(c.get("bankHigh", 0)) * 10000 + int(c.get("bankLow", 0))

        state = {
            "character": {
                "credits": credits,
                "score": c.get("score", 0),
                "rank_index": rank_index,
                "current_system": c.get("currentSystem", 0),
                "trip_count": c.get("tripCount", 0),
                "battles_won": c.get("battlesWon", 0),
                "battles_lost": c.get("battlesLost", 0),
                "cargo_pods": c.get("cargoPods", 0),
                "destination": c.get("destination", 0),
                "bank_balance": bank_balance,
                "is_conqueror": int(bool(c.get("isConqueror", False))),
                "in_combat": int(bool(c.get("inCombat", False))),
                "is_lost": int(bool(c.get("isLost", False))),
                # Bonus observability: jail-state (soft-lock signal for the exploit-hunter).
                "in_jail": int(c.get("crimeType") is not None),
            },
            "ship": {
                "fuel": s.get("fuel", 0),
                "hull_strength": s.get("hullStrength", 0),
                "hull_condition": s.get("hullCondition", 0),
                "drive_strength": s.get("driveStrength", 0),
                "weapon_strength": s.get("weaponStrength", 0),
                "shield_strength": s.get("shieldStrength", 0),
                "has_cloaker": int(bool(s.get("hasCloaker", False))),
                "has_auto_repair": int(bool(s.get("hasAutoRepair", False))),
            },
            "turn_number": self._turn,
        }
        return state

    # ── Server lifecycle ─────────────────────────────────────────────────────
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
        """Poll until the server answers (dev-login redirects), or time out."""
        deadline = time.monotonic() + self.server_boot_timeout
        last_err = None
        while time.monotonic() < deadline:
            try:
                requests.get(f"{self.base_url}/auth/dev-login", allow_redirects=False, timeout=2)
                return
            except Exception as e:  # noqa: BLE001
                last_err = e
                time.sleep(0.5)
        raise RuntimeError(f"server at {self.base_url} not ready within "
                          f"{self.server_boot_timeout}s: {last_err}")

    # ── Action-map helpers (drive real screens/HTTP; NO game logic) ──────────
    def _http_post(self, path: str, body: dict | None = None):
        r = requests.post(f"{self.base_url}{path}", headers=self._auth_header(),
                          json=(body or {}), timeout=15)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {"raw": r.text}

    def _input_follow(self, screen: str, key: str):
        """screen:input on `screen`; if it returns a nextScreen, request it. Returns (screen_now, output).
        Keeps `_current_screen` pointed at wherever the input landed us."""
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

    # Shipyard-upgrade component-selection keys (verified in shipyard-upgrade.ts).
    _UPGRADE_KEY = {"hull": "1", "drives": "2", "cabin": "3", "life_support": "4",
                    "weapons": "5", "navigation": "6", "robotics": "7", "shields": "8"}

    def _do_upgrade(self, comp_key: str) -> str:
        self._goto_main()
        self._input_follow(self.main_menu, "S")          # -> shipyard
        self._input_follow("shipyard", "U")              # -> shipyard-upgrade
        # The upgrade result ("... upgraded successfully! (-N cr)") is on the INPUT response's
        # output; the nextScreen then transitions to shipyard. Capture the message before following.
        resp = self.screen_input("shipyard-upgrade", comp_key)
        msg = resp.get("output", "")
        nxt = resp.get("nextScreen")
        if nxt:
            self._last_terminal = self.screen_request(nxt).get("output", "")
        self._goto_main()
        return msg

    # ── Action handlers (name -> handler(self) -> info dict) ─────────────────
    def _act_wait(self):
        """No-op: advance a turn without touching the game."""
        return {"action": "wait"}

    def _act_accept_cargo(self):
        """main-menu T -> traders A -> traders-cargo -> pick manifest 1 -> confirm Y."""
        self._goto_main()
        s, _ = self._input_follow(self.main_menu, "T")   # -> traders
        s, _ = self._input_follow(s, "A")                # -> traders-cargo (renders board)
        s, _ = self._input_follow(s, "1")                # pick manifest 1 -> "Are you sure?"
        s, out = self._input_follow(s, "Y")              # -> traders (signed) or error
        self._goto_main()
        c = self.get_character().get("character", {})
        return {"action": "accept_cargo", "signed": c.get("cargoPods", 0) > 0,
                "destination": c.get("destination", 0), "cargoPods": c.get("cargoPods", 0)}

    def _act_navigate_cargo_dest(self):
        """Launch to the signed cargo destination over HTTP, then arrive (encounter fires;
        delivery is automatic on arrival). Mirrors the real frontend's arrive-over-HTTP."""
        c = self.get_character().get("character", {})
        dest = c.get("destination", 0)
        if not dest:
            return {"action": "navigate_cargo_dest", "skipped": "no signed contract/destination"}
        sc1, launch = self._http_post("/api/navigation/launch", {"destinationSystemId": dest})
        sc2, arrive = self._http_post("/api/navigation/arrive")
        enc = arrive.get("encounter") if isinstance(arrive, dict) else None
        hostile = bool(enc and enc.get("encounter") and not enc.get("friendly"))
        # Reflect the resulting screen for the LLM tier: combat screen if a fight started.
        if hostile:
            self._last_terminal = self.screen_request("combat").get("output", "")
        else:
            self._goto_main()
        return {"action": "navigate_cargo_dest", "launch_status": sc1, "arrive_status": sc2,
                "encounter": bool(enc and enc.get("encounter")), "hostile": hostile,
                "launch_error": launch if sc1 != 200 else None}

    def _act_deliver_cargo(self):
        """Delivery is automatic on arrival at the destination (see navigation.ts arrive).
        As an action this confirms delivery status from real state — no reimplementation."""
        c = self.get_character().get("character", {})
        return {"action": "deliver_cargo", "note": "auto-on-arrival",
                "cargoPods": c.get("cargoPods", 0), "destination": c.get("destination", 0)}

    def _act_buy_fuel(self):
        """main-menu T -> traders B -> traders-buy-fuel -> type a unit amount."""
        units = 100
        self._goto_main()
        s, _ = self._input_follow(self.main_menu, "T")   # -> traders
        s, _ = self._input_follow(s, "B")                # -> traders-buy-fuel
        s, out = self._input_follow(s, str(units))       # buy -> traders
        self._goto_main()
        return {"action": "buy_fuel", "units_requested": units}

    def _act_end_turn(self):
        """main-menu D -> end-turn screen. The screen is a confirm flow (end-turn.ts):
        render asks 'End your turn? [Y]es / [N]o'; Y executes the turn (bot turns run,
        tripCount resets) and shows results; any key then returns to the menu.
        Validation failures render a reason and bounce to main-menu:
          - CLASSIC_MODE=true          -> 'Classic mode — wait for next day'
          - tripCount < DAILY_TRIP_LIMIT -> 'You still have N trip(s) remaining'
        """
        self._goto_main()
        s, out = self._input_follow(self.main_menu, "D")
        low = out.lower()
        if "end your turn?" in low:
            s, results = self._input_follow(s, "Y")   # executes the turn, shows summary
            self._input_follow(s, " ")                # any-key -> back to main-menu
            self._goto_main()
            return {"action": "end_turn", "confirmed": True}
        self._goto_main()
        return {"action": "end_turn", "confirmed": False,
                "classic_mode_noop": "wait for next day" in low,
                "blocked_reason": " ".join(out.split())[:120] or None}

    def _act_upgrade_weapons(self):
        out = self._do_upgrade(self._UPGRADE_KEY["weapons"])
        return {"action": "upgrade_weapons", "ok": "upgraded successfully" in out.lower()}

    def _act_upgrade_shields(self):
        out = self._do_upgrade(self._UPGRADE_KEY["shields"])
        return {"action": "upgrade_shields", "ok": "upgraded successfully" in out.lower()}

    def _act_upgrade_cheapest(self):
        """Upgrade the lowest-strength core component (cheapest to bump). Reads real ship state."""
        s = self.get_character().get("ship", {})
        strengths = {"hull": s.get("hullStrength", 999), "drives": s.get("driveStrength", 999),
                     "weapons": s.get("weaponStrength", 999), "shields": s.get("shieldStrength", 999)}
        comp = min(strengths, key=strengths.get)
        out = self._do_upgrade(self._UPGRADE_KEY[comp])
        return {"action": "upgrade_cheapest", "component": comp,
                "ok": "upgraded successfully" in out.lower()}

    def _act_repair_ship(self):
        """main-menu S -> shipyard R ('[R]epair all damage'; renders result in place).
        Repair cost/validation are the game's own (repairs.ts) — we just press the key."""
        self._goto_main()
        s, _ = self._input_follow(self.main_menu, "S")   # -> shipyard
        s, out = self._input_follow(s, "R")              # repair all (in-place render)
        self._goto_main()
        low = out.lower()
        return {"action": "repair_ship",
                "ok": "repair" in low and "failed" not in low,
                "detail": " ".join(out.split())[:120]}

    def _act_combat_attack(self):
        """Drive the 'combat' SCREEN with 'A' (the stateful path that resolves the encounter)."""
        s, out = self._input_follow("combat", "A")
        c = self.get_character().get("character", {})
        return {"action": "combat_attack", "in_combat": bool(c.get("inCombat")),
                "battles_won": c.get("battlesWon", 0), "battles_lost": c.get("battlesLost", 0)}

    def _act_combat_retreat(self):
        s, out = self._input_follow("combat", "R")
        c = self.get_character().get("character", {})
        return {"action": "combat_retreat", "in_combat": bool(c.get("inCombat"))}

    # name -> handler(self) -> info dict. Covers the training action_subset
    # [4,6,2,7,8,14,10,11,16,17]; other config actions remain unmapped (raise) until needed.
    ACTION_HANDLERS = {
        "wait": _act_wait,
        "buy_fuel": _act_buy_fuel,
        "accept_cargo": _act_accept_cargo,
        "navigate_cargo_dest": _act_navigate_cargo_dest,
        "deliver_cargo": _act_deliver_cargo,
        "upgrade_cheapest": _act_upgrade_cheapest,
        "end_turn": _act_end_turn,
        "combat_attack": _act_combat_attack,
        "combat_retreat": _act_combat_retreat,
        "upgrade_weapons": _act_upgrade_weapons,
        "upgrade_shields": _act_upgrade_shields,
        "repair_ship": _act_repair_ship,
    }
