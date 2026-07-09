"""
NexusHttpAdapter — drives the LIVE nexus-world-builder Next.js game over plain HTTP.

NEXUS is a terminal-hacking RPG. Unlike the Socket.IO SpacerQuest bridge, its whole
observable surface is three JSON test routes exposed by the running Next.js server
(apps/game), so this adapter is pure `requests` — no websocket, no browser:

  POST /api/test/bootstrap-player   -> create a throwaway player            (connect/warm)
  POST /api/test/reset-episode      -> re-pin player to a deterministic seed (reset)
  POST /api/test/closed-alpha       -> execute ONE game command -> CommandResult (step)
  GET  /api/test/player-state       -> full observable state                 (_read_state)

Like every UGT real-server adapter this contains NO game logic — it is a transport
layer that (a) carries navigation state the game route deliberately does NOT persist
and (b) composes command strings from real state. It never re-implements a command's
effect; it reads the effect back from player-state.

STATELESS-NAV CONTRACT (the one non-obvious thing — plan R3): the closed-alpha route
reads `currentServerId`/`currentPath` from the REQUEST and never writes them to the
Player row (player-state.currentServerId stays null). So this adapter must carry that
nav state across steps itself: after each command it copies any
`CommandResult.stateChanges.currentServerId` / `.currentPath` forward into the next
request. `connect <ip>` is what surfaces a real server id; `disconnect` clears it
(the route emits `currentServerId: undefined`, which JSON drops, so we mirror the
clear locally when the command is a disconnect).

R0 / NX-P0-1: a `fresh` reset leaves the whole hacking surface locked behind the
tutorial gate, so this adapter resets with `baseline: "post_tutorial"` by default
(configurable via engine.baseline) — the game-side reset route was extended to seed a
just-past-tutorial player. See integrations/nexus/README.md.
"""
from __future__ import annotations

import os
import random

import requests

from ugt.adapters.base import BaseAdapter

DEFAULTS = {
    "base_url": "http://127.0.0.1:3100",
    "connect_timeout": 60.0,
    "request_timeout": 30.0,
    "episode_seed": "ugt-nexus-seed",
    "difficulty": "normal",
    "baseline": "post_tutorial",
    "step_cap": 1000,
}


class NexusHttpAdapter(BaseAdapter):
    """Transport-only handle on the running NEXUS server. Contains NO game logic."""

    def __init__(self, config=None):
        super().__init__(config)
        eng = {}
        if config is not None:
            try:
                eng = config.data.get("engine", {}) or {}
            except AttributeError:
                eng = {}
        self.base_url = str(eng.get("base_url", DEFAULTS["base_url"])).rstrip("/")
        self.api_key = eng.get("api_key") or os.environ.get("TEST_API_KEY")
        self.connect_timeout = float(eng.get("connect_timeout", DEFAULTS["connect_timeout"]))
        self.request_timeout = float(eng.get("request_timeout", DEFAULTS["request_timeout"]))
        self.episode_seed = str(eng.get("episode_seed", DEFAULTS["episode_seed"]))
        self.difficulty = str(eng.get("difficulty", DEFAULTS["difficulty"]))
        self.baseline = str(eng.get("baseline", DEFAULTS["baseline"]))
        self.step_cap = int(eng.get("step_cap", DEFAULTS["step_cap"]))

        # action_id -> action name, from config (used to dispatch step()).
        self._action_names = {}
        if config is not None:
            try:
                for k, v in (config.action_mappings or {}).items():
                    self._action_names[int(k)] = v.get("name") if isinstance(v, dict) else str(v)
            except Exception:
                self._action_names = {}

        self.session = None
        self.player_id = None
        # Navigation bookkeeping the closed-alpha route does NOT persist for us.
        self._cur_server_id = None
        self._cur_path = "/"
        self._last_output = ""
        self._step_count = 0

    # ── BaseAdapter lifecycle ────────────────────────────────────────────────
    def connect(self):
        """Reachability + warm: create a throwaway player through bootstrap-player.

        Raises a clear RuntimeError (naming the likely cause) if the route is
        missing (404 — wrong/stale server) or the key is rejected (401), so a
        campaign never silently runs against the wrong code / an unconfigured key.
        """
        if not self.api_key:
            raise RuntimeError(
                "No API key: set engine.api_key in the config or the TEST_API_KEY env var "
                "(must match the server's TEST_API_KEY)."
            )
        self.session = requests.Session()
        self.session.headers.update({"X-Test-API-Key": self.api_key})

        url = f"{self.base_url}/api/test/bootstrap-player"
        try:
            r = self.session.post(
                url, json={"prefix": "ugt"},
                headers={"Content-Type": "application/json"},
                timeout=self.connect_timeout,
            )
        except requests.RequestException as e:
            raise RuntimeError(f"NEXUS server unreachable at {self.base_url}: {e}") from e

        if r.status_code == 404:
            raise RuntimeError(
                f"bootstrap-player 404 at {url} — the server at {self.base_url} does not expose "
                f"the UGT test routes (stale/wrong build, or NODE_ENV=production). Confirm the "
                f"LISTEN pid is the `next dev` you launched."
            )
        if r.status_code in (401, 503):
            raise RuntimeError(
                f"bootstrap-player {r.status_code} — API key rejected or TEST_API_KEY unset on the "
                f"server. Body: {r.text[:200]}"
            )
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, dict) or "playerId" not in data:
            raise RuntimeError(f"bootstrap-player returned an unexpected shape: {data!r}")
        self.player_id = data["playerId"]
        return data

    def reset(self, seed=None):
        """Re-pin the player to a deterministic episode and return the initial state.

        bootstrap-once (a player persists across episodes; only the episode is reset),
        then POST reset-episode with the configured baseline. Nav bookkeeping is cleared.
        """
        if self.session is None:
            self.connect()
        if self.player_id is None:
            self.connect()

        seed_str = str(seed if seed is not None else self.episode_seed)
        body = {
            "playerId": self.player_id,
            "seed": seed_str,
            "difficulty": self.difficulty,
            "baseline": self.baseline,
        }
        r = self.session.post(
            f"{self.base_url}/api/test/reset-episode", json=body,
            headers={"Content-Type": "application/json"},
            timeout=self.request_timeout,
        )
        r.raise_for_status()
        payload = r.json()
        if not payload.get("ok"):
            raise RuntimeError(f"reset-episode did not return ok: {payload!r}")

        self._cur_server_id = None
        self._cur_path = "/"
        self._last_output = ""
        self._step_count = 0
        return self._read_state()

    def step(self, action_id):
        """Execute the command mapped to `action_id`. Returns (state, term, trunc, info)."""
        name = self._action_names.get(int(action_id), f"action_{action_id}")
        command = self._compose_command(name)
        return self._execute(command)

    def close(self):
        if self.session is not None:
            try:
                self.session.close()
            except Exception:
                pass
        self.session = None

    # ── BaseAdapter optional UI actions ──────────────────────────────────────
    def type_text(self, text: str, press_enter: bool = True) -> None:
        """Drive one raw command string through closed-alpha (playtest/spike path).

        Returns None per the BaseAdapter contract; the resulting CommandResult and
        terminal text are readable via the adapter's last-output / player-state.
        The full (state, term, trunc, info) tuple is available via `type_text_step`.
        """
        self._execute(text)

    def type_text_step(self, command: str):
        """Like type_text but returns the full (state, terminated, truncated, info)
        tuple — the convenient primitive for the Phase-0 verification scripts."""
        return self._execute(command)

    def get_terminal_text(self, chars: int = 600) -> str:
        return self._last_output[-chars:] if self._last_output else ""

    # ── Core command transport ───────────────────────────────────────────────
    def _execute(self, command: str):
        """POST one command to closed-alpha, carry nav state forward, read new state."""
        if self.session is None or self.player_id is None:
            raise RuntimeError("adapter not connected — call connect()/reset() first")

        self._step_count += 1
        body = {
            "playerId": self.player_id,
            "command": command,
            "currentServerId": self._cur_server_id,
            "currentPath": self._cur_path,
        }
        r = self.session.post(
            f"{self.base_url}/api/test/closed-alpha", json=body,
            headers={"Content-Type": "application/json"},
            timeout=self.request_timeout,
        )
        # The route returns JSON even on a handled 500 ({success:false,...}); only a
        # transport-level failure should raise. Surface HTML/5xx explicitly.
        ctype = r.headers.get("Content-Type", "")
        if "application/json" not in ctype:
            raise RuntimeError(
                f"closed-alpha returned non-JSON ({r.status_code} {ctype}) for {command!r}: "
                f"{r.text[:200]}"
            )
        result = r.json()

        # Carry navigation state the route deliberately does not persist (R3).
        changes = result.get("stateChanges") or {}
        if "currentServerId" in changes:
            self._cur_server_id = changes["currentServerId"]
        if "currentPath" in changes:
            self._cur_path = changes["currentPath"]
        # disconnect emits currentServerId:undefined (dropped by JSON) — mirror the clear.
        if command.strip().split(" ", 1)[0].lower() == "disconnect" and result.get("success"):
            self._cur_server_id = None

        self._last_output = result.get("output", "") or ""

        after = self._read_state()
        terminated = bool((after.get("gameStatus") or {}).get("isComplete", False))
        truncated = self._step_count >= self.step_cap
        info = {"command": command, "result": result, "state": after}
        return after, terminated, truncated, info

    # ── Observation ──────────────────────────────────────────────────────────
    def _read_state(self) -> dict:
        """GET player-state -> parsed obs dict (name kept EXACTLY `_read_state`:
        exploit_hunter probes for it by name during crash recovery).

        BigInt fields (xp/credits) arrive as decimal STRINGS — coerce to int here.
        Derive the flat counts the observation_space mappings reference.
        """
        r = self.session.get(
            f"{self.base_url}/api/test/player-state",
            params={"playerId": self.player_id},
            timeout=self.request_timeout,
        )
        r.raise_for_status()
        p = r.json()

        missions = p.get("missions") or []
        compromised = p.get("compromisedServers") or []
        discovered = p.get("discoveredServers") or []

        state = {
            "level": _to_int(p.get("level"), 0),
            "xp": _to_int(p.get("xp"), 0),
            "credits": _to_int(p.get("credits"), 0),
            "rngCounter": _to_int(p.get("rngCounter"), 0),
            "difficulty": p.get("difficulty"),
            "reputation": p.get("reputation") or {},
            "storyFlags": p.get("storyFlags") or [],
            "unlockedCommands": p.get("unlockedCommands") or [],
            "currentServerId": p.get("currentServerId"),
            "discoveredServers": discovered,
            "compromisedServers": compromised,
            "missions": missions,
            "gameStatus": p.get("gameStatus") or {},
            # Derived flat counts for the obs vector.
            "discoveredServersCount": len(discovered),
            "compromisedServersCount": len(compromised),
            "missionsCompletedCount": sum(1 for m in missions if m.get("status") == "completed"),
            "missionsActiveCount": sum(1 for m in missions if m.get("status") == "active"),
        }
        return state

    # ── Command composition (heuristic, from real state; NO game logic) ──────
    # A small fixed Phase-0 command set. Args are filled from live state where a
    # command needs them; a full stochastic policy is R3 (see `policy` below).
    _BARE = {"status", "help", "missions", "scan", "ls", "analyze", "escalate",
             "backdoor", "whoami", "disconnect"}
    _COMMON_VULN = "weak_password"
    _CRACK_TARGET = "/etc/shadow"
    _GENERIC_FILE = "/etc/passwd"
    _FALLBACK_MISSION = "the_breadcrumb"
    _GARBAGE_TOKEN = "zzqq_nx_garble"

    def _compose_command(self, name: str) -> str:
        """Turn an action name into a concrete command string using current state.

        Kept deliberately simple for Phase-0: enough to exercise the surface and
        never fabricate an effect — a command that can't be sensibly filled is
        still sent verbatim and the (honest) refusal is read back from state.
        """
        if name in self._BARE:
            return name
        state = None
        if name in ("connect", "cat", "accept"):
            try:
                state = self._read_state()
            except Exception:
                state = None
        if name == "connect":
            ip = self._pick_connect_target(state)
            return f"connect {ip}" if ip else "connect"
        if name == "exploit":
            return f"exploit {self._COMMON_VULN}"
        if name == "crack":
            return f"crack {self._CRACK_TARGET}"
        if name == "cat":
            return f"cat {self._GENERIC_FILE}"
        if name == "download":
            return f"download {self._GENERIC_FILE}"
        if name == "accept":
            mid = self._pick_mission(state)
            return f"accept {mid}" if mid else f"accept {self._FALLBACK_MISSION}"
        # R3 verbs — simple, stateless defaults. The R3 subclass overrides
        # _compose_command to fill these from live state / probe kinds; these are
        # the base fallbacks so the whole action vocabulary is still driveable
        # through the plain adapter.
        if name == "talk":
            return "talk sp3ctr3"
        if name == "choose":
            return "choose liberation"
        if name == "garbage":
            return self._GARBAGE_TOKEN
        # Unknown action name (e.g. the intentionally-unmapped "action_18"): send
        # it bare (honest — the game will report "Command not found").
        return name

    def _pick_connect_target(self, state):
        """Prefer a discovered server we have not yet compromised; else any discovered."""
        if not state:
            return None
        compromised_ips = {c.get("ipAddress") for c in state.get("compromisedServers", [])}
        discovered = state.get("discoveredServers", [])
        fresh = [ip for ip in discovered if ip not in compromised_ips]
        pool = fresh or discovered
        return pool[0] if pool else None

    def _pick_mission(self, state):
        if not state:
            return None
        for m in state.get("missions", []):
            if m.get("status") == "active":
                return m.get("missionId")
        return None

    # ── Policy stub (R3) ─────────────────────────────────────────────────────
    def policy(self, state, action_ids, rng=None, ctx=None):
        """Placeholder action selector for a later stochastic exploit-hunter run.

        Phase-0 keeps this a uniform random choice over the given action ids; the
        heuristic/weighted policy that biases toward reachable progress is R3.
        """
        rng = rng or random
        return rng.choice(list(action_ids))


def _to_int(value, default=0):
    """Coerce a possibly-string BigInt field to int; fall back on garbage."""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
