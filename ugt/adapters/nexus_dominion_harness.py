"""
NexusDominionHarnessAdapter — drives the REAL Nexus Dominion engine through its
JSON-lines subprocess harness (harness/ugt-harness.mjs in the game repo), never
a re-implementation (the sim_bridge lesson).

Nexus Dominion is a single-player space-empire "digital boardgame": the player
plus 99 bot empires across 250 systems, advanced one atomic `processCycle` per
committed order list. The harness wraps the pure TS engine as a line protocol —
one JSON request per line in, one response per line out, in order:

  {"op":"create",...}  -> a fresh campaign (campaignId c1,c2,...), summary, hash
  {"op":"commit",...}  -> apply one cycle's order list -> report + summary + hash
                          (committed:false + error on a Tier-1 atomic abort)
  {"op":"state",...}   -> summary (+ full serialized state on full:true)
  {"op":"save"/"load"} -> round-trip through the game's own state serializer

Like every UGT adapter this contains NO game logic — it is a transport layer
that (a) spawns/speaks to the harness and (b) composes ORDERS for a given
action id from structural reads of the game's own state (ownership, adjacency,
registries). It never simulates an effect: every state fact is read back from
the harness. Orders the engine refuses are refused silently by the engine (its
real contract — a switch/`break`, no error events); the adapter relays exactly
what happened and invents nothing.

The game has NO terminal win/loss state by design (achievements are milestones,
not endings), so `terminated` is always False and episodes end by `max_cycles`
truncation.

stateHash (computed game-side) normalizes campaign id/timestamps — the only
nondeterministic GameState fields — so same-seed campaigns hash identically.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import subprocess

from ugt.adapters.base import BaseAdapter

DEFAULTS = {
    # No baked-in default: set engine.harness_entry in the config or the
    # NEXUS_DOMINION_HARNESS_PATH env var (path to the game's ugt-harness.mjs).
    "harness_entry": "",
    "node_bin": "node",
    # PRD defaults: 250 systems / 10 sectors / 100 empires. Ladder scripts may
    # shrink for speed; the harness refuses a missing seed (never defaults it).
    "galaxy": {"totalSystems": 250, "sectorCount": 10, "systemsPerSector": 25,
               "empireCount": 100},
    "seed": 20260716,
    "max_cycles": 50,
    "tutorial": False,
}

# ── Content vocabularies (config-level constants, like DDD's deck names).
# These mirror string-literal unions/registries in the game source; the engine
# remains the authority — an id it does not know is simply refused (silently).
UNIT_TYPES = ["fighter", "cruiser", "orbital-platform", "bombardment-ship",
              "infantry", "heavy-armor", "dreadnought"]
INSTALLATION_TYPES = ["trade-hub", "agricultural-station", "mining-complex",
                      "fuel-extraction", "population-centre", "cultural-institute"]
PACT_TYPES = ["stillness-accord", "star-covenant"]  # the two the handler accepts
DOCTRINE_PATHS = ["war-machine", "fortress", "commerce"]
SPECIALIZATIONS = ["shock-troops", "siege-engines", "shield-arrays",
                   "minefield-networks", "trade-monopoly", "mercenary-contracts"]
COVERT_OPS = ["reconnaissance", "steal-military-plans", "steal-credits",
              "sabotage-production", "steal-research", "sabotage-infrastructure",
              "incite-rebellion", "recruit-defectors"]
BLACK_REGISTER_ITEMS = ["empire-dossier", "covenant-map", "advance-signals"]
TRADE_RESOURCES = ["food", "ore", "fuelCells"]

# id -> action name. MUST stay in lockstep with
# the integration's ugt.config.yaml and `_orders_for` below.
_DEFAULT_ACTION_NAMES = {
    0: "pass",                    # commit an empty order list
    1: "claim_adjacent",          # claim-system: unclaimed adjacent to owned
    2: "build_unit_first",        # build-unit: first unit type in the registry
    3: "build_unit_random",       # build-unit: random unit type
    4: "build_installation",      # build-installation: random type, owned system
    5: "build_wormhole",          # build-wormhole: random non-home target
    6: "trade_buy",               # trade buy: random resource, qty 1-5
    7: "trade_sell",              # trade sell: random resource, qty 1-5
    8: "research",                # research (consumes accrued researchPoints)
    9: "select_doctrine",         # select-doctrine: random of the 3 paths
    10: "select_specialization",  # select-specialization: spec of chosen path
    11: "propose_pact",           # propose-pact: random bot, random pact type
    12: "break_pact",             # break-pact: first pact involving the player
    13: "fund_syndicate",         # fund-syndicate: 100 credits
    14: "purchase_black_register",  # purchase-black-register: first item
    15: "launch_covert_op",       # launch-covert-op: random bot + op type
    16: "attack_adjacent",        # attack: enemy system adjacent to owned, own units
    17: "move_fleet",             # move-fleet: player fleet -> adjacent system
    18: "probe_unknown_type",     # deliberately unknown order type
    19: "probe_malformed",        # claim-system with no details
}

# Ids that deliberately send something the engine should refuse/ignore. step()
# marks these with info["probe"]=True so invariants don't misread the expected
# outcome as a defect — and so a probe that visibly APPLIES is caught loudly.
PROBE_ACTION_NAMES = frozenset({"probe_unknown_type", "probe_malformed"})


def decode_tagged(node):
    """Decode the game's own tagged save encoding (Map/Set) into plain Python.

    {"__t":"Map","e":[[k,v],...]} -> dict, {"__t":"Set","v":[...]} -> list.
    Pure transport-level decoding of serializeGameState output — no game logic.
    """
    if isinstance(node, dict):
        tag = node.get("__t")
        if tag == "Map" and isinstance(node.get("e"), list):
            return {k: decode_tagged(v) for k, v in node["e"]}
        if tag == "Set" and isinstance(node.get("v"), list):
            return [decode_tagged(v) for v in node["v"]]
        return {k: decode_tagged(v) for k, v in node.items()}
    if isinstance(node, list):
        return [decode_tagged(v) for v in node]
    return node


class NexusDominionHarnessAdapter(BaseAdapter):
    """Transport-only handle on the running harness. Contains NO game logic."""

    def __init__(self, config=None):
        super().__init__(config)
        eng = {}
        if config is not None:
            try:
                eng = config.data.get("engine", {}) or {}
            except AttributeError:
                eng = {}

        self.harness_entry = str(
            os.environ.get("NEXUS_DOMINION_HARNESS_PATH")
            or eng.get("harness_entry")
            or DEFAULTS["harness_entry"]
        )
        if not self.harness_entry:
            raise ValueError(
                "No harness entrypoint: set engine.harness_entry in the config or "
                "the NEXUS_DOMINION_HARNESS_PATH env var (path to the game's "
                "ugt-harness.mjs)."
            )
        self.node_bin = str(eng.get("node_bin", DEFAULTS["node_bin"]))
        # Default cwd = the game repo root inferred from the harness path
        # (…/nexus-dominion/harness/ugt-harness.mjs -> …/nexus-dominion).
        inferred_cwd = os.path.abspath(
            os.path.join(os.path.dirname(self.harness_entry), "..")
        )
        self.harness_cwd = str(
            os.environ.get("NEXUS_DOMINION_HARNESS_CWD")
            or eng.get("harness_cwd")
            or inferred_cwd
        )
        self.galaxy = dict(eng.get("galaxy", DEFAULTS["galaxy"]))
        self.seed = eng.get("seed", DEFAULTS["seed"])
        self.max_cycles = int(eng.get("max_cycles", DEFAULTS["max_cycles"]))
        self.tutorial = bool(eng.get("tutorial", DEFAULTS["tutorial"]))

        # action_id -> action name (from config, else the default table).
        self._action_names = dict(_DEFAULT_ACTION_NAMES)
        if config is not None:
            try:
                mapped = {}
                for k, v in (config.action_mappings or {}).items():
                    mapped[int(k)] = v.get("name") if isinstance(v, dict) else str(v)
                if mapped:
                    self._action_names = mapped
            except Exception:
                self._action_names = dict(_DEFAULT_ACTION_NAMES)

        self.process = None
        self._req_id = 0
        self._campaign_id = None
        self._rng = random.Random(0)
        self._g = None            # decoded full GameState (refreshed per commit)
        self._summary = None      # last summary the harness returned
        self._hash_stream = []
        self._step_count = 0
        self._reset_count = 0

    # ── public read-only attributes (mirrors ddd/nexus shape) ────────────────
    @property
    def hash_stream(self):
        return self._hash_stream

    @property
    def step_count(self):
        return self._step_count

    @property
    def game_state(self):
        """The decoded full GameState as last read from the harness (the game's
        own serialized form, Map/Set-decoded). Read-only; gates use this for
        invariants. The adapter itself only does structural reads on it."""
        return self._g

    @property
    def campaign_id(self):
        return self._campaign_id

    # ── BaseAdapter lifecycle ────────────────────────────────────────────────
    def connect(self):
        """Spawn the harness subprocess and confirm it is alive."""
        cmd = [self.node_bin, self.harness_entry]
        try:
            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,  # line buffered
                cwd=self.harness_cwd,
                env=os.environ.copy(),
            )
        except Exception as e:
            raise RuntimeError(
                f"Failed to spawn harness {cmd!r} (cwd={self.harness_cwd!r}): {e}"
            ) from e
        if self.process.poll() is not None:
            err = self._drain_stderr()
            raise RuntimeError(
                f"harness exited immediately (code {self.process.returncode}). "
                f"Stderr: {err or '<empty>'} — check node >=24."
            )
        return {"pid": self.process.pid}

    def reset(self, seed=None):
        """Create a fresh campaign and return the normalized initial state.

        A BARE `reset()` derives a distinct per-episode seed base+reset_count,
        because ExploitHunter.run resets with no arguments between episodes — a
        fixed seed there would replay the SAME campaign every episode. Fully
        deterministic: a fresh adapter always starts at reset_count=0.
        """
        if self.process is None or self.process.poll() is not None:
            self.connect()

        if seed is None:
            seed_num = int(self.seed) + self._reset_count
        else:
            seed_num = int(seed)
        self._reset_count += 1

        resp = self._request({
            "op": "create",
            "config": {"seed": seed_num, **self.galaxy},
            "name": f"UGT {seed_num}",
            "tutorial": self.tutorial,
        })
        if not resp.get("ok"):
            raise RuntimeError(f"harness create failed: {resp!r}")

        self._campaign_id = resp["campaignId"]
        digest = hashlib.sha256(str(seed_num).encode()).digest()[:8]
        self._rng = random.Random(int.from_bytes(digest, "big"))
        self._summary = resp["summary"]
        self._hash_stream = [resp["stateHash"]]
        self._step_count = 0
        self._refresh_full_state()
        return self._read_state()

    def step(self, action_id):
        """Commit one cycle carrying the order(s) mapped to `action_id`.

        Returns (state, terminated, truncated, info). terminated is always
        False (the game has no terminal state); truncated fires at max_cycles.
        """
        name = self.action_name(action_id)
        is_probe = name in PROBE_ACTION_NAMES
        orders = self._orders_for(name)
        hash_before = self._hash_stream[-1] if self._hash_stream else None

        resp = self._request({
            "op": "commit",
            "campaignId": self._campaign_id,
            "actions": orders,
        })
        if not resp.get("ok"):
            raise RuntimeError(f"harness commit failed: {resp!r}")

        committed = resp.get("committed") is True
        if committed:
            self._summary = resp["summary"]
            self._hash_stream.append(resp["stateHash"])
            self._step_count += 1
            self._refresh_full_state()

        state = self._read_state()
        cycle = state.get("cycle", 0)
        truncated = cycle >= self.max_cycles
        info = {
            "command": "commit",
            "actionName": name,
            "orders": orders,
            "probe": is_probe,
            "committed": committed,
            "error": resp.get("error"),
            "hashBefore": hash_before,
            "stateHash": resp.get("stateHash"),
            "reckoningOccurred": (resp.get("report") or {}).get("reckoningOccurred"),
            "events": (resp.get("report") or {}).get("events") or [],
            "result": {"ok": resp.get("ok"), "committed": committed,
                       "error": resp.get("error"), "probe": is_probe,
                       "actionName": name, "hashBefore": hash_before},
        }
        return state, False, truncated, info

    def close(self):
        if self.process is not None:
            try:
                if self.process.stdin:
                    self.process.stdin.close()
            except Exception:
                pass
            if self.process.poll() is None:
                try:
                    self.process.terminate()
                    self.process.wait(timeout=2)
                except Exception:
                    try:
                        self.process.kill()
                    except Exception:
                        pass
            self.process = None

    # ── harness transport ────────────────────────────────────────────────────
    def _request(self, op: dict) -> dict:
        """Send one op line, read exactly one response line (in-order protocol)."""
        if self.process is None or self.process.poll() is not None:
            err = self._drain_stderr()
            raise RuntimeError(f"harness is not running. Stderr: {err or '<empty>'}")

        self._req_id += 1
        req_id = self._req_id
        op = dict(op)
        op["id"] = req_id

        self.process.stdin.write(json.dumps(op) + "\n")
        self.process.stdin.flush()

        while True:
            line = self.process.stdout.readline()
            if line == "":
                err = self._drain_stderr()
                raise RuntimeError(f"harness exited: {err or '<empty>'}")
            line = line.strip()
            if not line:
                continue
            try:
                resp = json.loads(line)
            except json.JSONDecodeError as e:
                raise RuntimeError(f"harness returned non-JSON line: {e}") from e
            resp_id = resp.get("id")
            if resp_id is not None and resp_id != req_id:
                raise RuntimeError(
                    f"harness id desync: sent id={req_id} got id={resp_id}"
                )
            return resp

    def _drain_stderr(self) -> str:
        if self.process is None or self.process.stderr is None:
            return ""
        try:
            return self.process.stderr.read() or ""
        except Exception:
            return ""

    def send_raw(self, op: dict) -> dict:
        """Send an ARBITRARY op verbatim and return the raw response.

        The refusal-probe channel for gates (R3): malformed configs, unknown
        campaigns, raw order lists the step() vocabulary would never compose.
        Does NOT advance the adapter's cached state — callers that commit
        through this must refresh via resync().
        """
        return self._request(op)

    def resync(self):
        """Re-read summary + full state after out-of-band send_raw commits."""
        resp = self._request({"op": "state", "campaignId": self._campaign_id})
        if resp.get("ok"):
            self._summary = resp["summary"]
            if resp.get("stateHash") and (
                not self._hash_stream or self._hash_stream[-1] != resp["stateHash"]
            ):
                self._hash_stream.append(resp["stateHash"])
        self._refresh_full_state()
        return self._read_state()

    def save_payload(self) -> dict:
        """The game's own save payload (state via serializeGameState + the
        caller-owned accumulators). For save/load-continue divergence gates."""
        resp = self._request({"op": "save", "campaignId": self._campaign_id})
        if not resp.get("ok"):
            raise RuntimeError(f"harness save failed: {resp!r}")
        return resp["payload"]

    def load_payload(self, payload: dict) -> dict:
        """Load a save payload as a NEW campaign and point the adapter at it."""
        resp = self._request({"op": "load", "payload": payload})
        if not resp.get("ok"):
            raise RuntimeError(f"harness load failed: {resp!r}")
        self._campaign_id = resp["campaignId"]
        self._summary = resp["summary"]
        self._hash_stream.append(resp["stateHash"])
        self._refresh_full_state()
        return self._read_state()

    def _refresh_full_state(self):
        resp = self._request({
            "op": "state", "campaignId": self._campaign_id, "full": True,
        })
        if not resp.get("ok"):
            raise RuntimeError(f"harness state failed: {resp!r}")
        self._g = decode_tagged(resp["state"])
        self._summary = resp["summary"]

    # ── order composition (structural reads, NOT game logic) ────────────────
    def action_name(self, action_id: int) -> str:
        return self._action_names.get(
            int(action_id), _DEFAULT_ACTION_NAMES.get(int(action_id), "pass")
        )

    # Structural readers over the decoded state. Ownership/adjacency are FACTS
    # read from the game's own state, not rules the adapter enforces.
    def _player_id(self):
        return self._g["playerEmpireId"]

    def _player(self):
        return self._g["empires"][self._player_id()]

    def _systems(self):
        return self._g["galaxy"]["systems"]

    def _owned_system_ids(self):
        return list(self._player().get("systemIds") or [])

    def _adjacent_ids(self, of_ids):
        adj = []
        systems = self._systems()
        for sid in of_ids:
            sys_ = systems.get(sid)
            if sys_:
                adj.extend(sys_.get("adjacentSystemIds") or [])
        return adj

    def _player_fleets(self):
        pid = self._player_id()
        return {fid: f for fid, f in (self._g.get("fleets") or {}).items()
                if f.get("ownerId") == pid}

    def _player_unit_ids(self):
        ids = []
        for f in self._player_fleets().values():
            ids.extend(f.get("unitIds") or [])
        return ids

    def _bot_ids(self):
        return list((self._g.get("bots") or {}).keys())

    def _orders_for(self, name: str) -> list:
        """Compose the order list for an action name. Every order is built from
        structural reads of the live state; when no candidate exists the order
        is still sent with a best-effort target — the ENGINE decides (its
        silent-refusal contract is part of what the trial observes)."""
        rng = self._rng
        if name == "pass":
            return []
        if name == "probe_unknown_type":
            return [{"type": "warp-ten", "details": {"factor": 10}}]
        if name == "probe_malformed":
            return [{"type": "claim-system"}]  # no details at all

        if name == "claim_adjacent":
            systems = self._systems()
            owned = set(self._owned_system_ids())
            candidates = [sid for sid in self._adjacent_ids(owned)
                          if sid in systems and systems[sid].get("owner") is None]
            if not candidates:
                candidates = [sid for sid, s in systems.items()
                              if s.get("owner") is None]
            target = rng.choice(sorted(set(candidates))) if candidates else "sys-none"
            return [{"type": "claim-system", "details": {"systemId": target}}]

        if name == "build_unit_first":
            reg = list((self._g.get("unitTypes") or {}).keys()) or UNIT_TYPES
            return [{"type": "build-unit", "details": {"unitTypeId": reg[0]}}]
        if name == "build_unit_random":
            reg = list((self._g.get("unitTypes") or {}).keys()) or UNIT_TYPES
            return [{"type": "build-unit", "details": {"unitTypeId": rng.choice(reg)}}]

        if name == "build_installation":
            owned = self._owned_system_ids()
            target = rng.choice(owned) if owned else "sys-none"
            return [{"type": "build-installation",
                     "details": {"installationType": rng.choice(INSTALLATION_TYPES),
                                 "systemId": target}}]

        if name == "build_wormhole":
            systems = sorted(self._systems().keys())
            home = self._player().get("homeSystemId")
            candidates = [s for s in systems if s != home]
            target = rng.choice(candidates) if candidates else "sys-none"
            return [{"type": "build-wormhole", "details": {"targetSystemId": target}}]

        if name == "trade_buy":
            return [{"type": "trade",
                     "details": {"resource": rng.choice(TRADE_RESOURCES),
                                 "quantity": rng.randint(1, 5),
                                 "direction": "buy"}}]
        if name == "trade_sell":
            return [{"type": "trade",
                     "details": {"resource": rng.choice(TRADE_RESOURCES),
                                 "quantity": rng.randint(1, 5),
                                 "direction": "sell"}}]

        if name == "research":
            return [{"type": "research", "details": {}}]

        if name == "select_doctrine":
            return [{"type": "select-doctrine",
                     "details": {"pathId": rng.choice(DOCTRINE_PATHS)}}]
        if name == "select_specialization":
            return [{"type": "select-specialization",
                     "details": {"specId": rng.choice(SPECIALIZATIONS)}}]

        if name == "propose_pact":
            bots = self._bot_ids()
            target = rng.choice(sorted(bots)) if bots else "empire-none"
            return [{"type": "propose-pact",
                     "details": {"targetId": target,
                                 "type": rng.choice(PACT_TYPES)}}]

        if name == "break_pact":
            pid = self._player_id()
            pacts = self._g.get("diplomacy", {}).get("pacts") or {}
            mine = [pk for pk, p in sorted(pacts.items())
                    if pid in (p.get("members") or [p.get("proposerId"),
                                                    p.get("targetId")])]
            target = mine[0] if mine else "pact-none"
            return [{"type": "break-pact", "details": {"pactId": target}}]

        if name == "fund_syndicate":
            return [{"type": "fund-syndicate", "details": {"amount": 100}}]

        if name == "purchase_black_register":
            return [{"type": "purchase-black-register",
                     "details": {"itemId": BLACK_REGISTER_ITEMS[0]}}]

        if name == "launch_covert_op":
            bots = self._bot_ids()
            target = rng.choice(sorted(bots)) if bots else "empire-none"
            return [{"type": "launch-covert-op",
                     "details": {"targetId": target,
                                 "opType": rng.choice(COVERT_OPS)}}]

        if name == "attack_adjacent":
            systems = self._systems()
            pid = self._player_id()
            owned = set(self._owned_system_ids())
            enemy_adjacent = sorted({
                sid for sid in self._adjacent_ids(owned)
                if sid in systems and systems[sid].get("owner")
                and systems[sid].get("owner") != pid
            })
            target = rng.choice(enemy_adjacent) if enemy_adjacent else "sys-none"
            return [{"type": "attack",
                     "details": {"targetSystemId": target,
                                 "unitIds": self._player_unit_ids()}}]

        if name == "move_fleet":
            fleets = self._player_fleets()
            if not fleets:
                return [{"type": "move-fleet",
                         "details": {"fleetId": "fleet-none",
                                     "targetSystemId": "sys-none"}}]
            fid = sorted(fleets.keys())[0]
            loc = fleets[fid].get("locationSystemId")
            systems = self._systems()
            adjacent = (systems.get(loc, {}).get("adjacentSystemIds") or [])
            target = rng.choice(sorted(adjacent)) if adjacent else loc
            return [{"type": "move-fleet",
                     "details": {"fleetId": fid, "targetSystemId": target}}]

        # Unknown id name -> pass (deterministic).
        return []

    # ── observation ──────────────────────────────────────────────────────────
    def _read_state(self) -> dict:
        """Normalized view of the CACHED summary (no re-send). Named EXACTLY
        `_read_state` — ExploitHunter probes for it by name in crash recovery."""
        s = self._summary or {}
        player = s.get("player") or {}
        flat = {
            "cycle": s.get("cycle", 0),
            "confluence": s.get("confluence", 0),
            "cyclesUntilReckoning": s.get("cyclesUntilReckoning", 0),
            "empireCount": s.get("empireCount", 0),
            "botCount": s.get("botCount", 0),
            "systemCount": s.get("systemCount", 0),
            "unclaimedSystems": s.get("unclaimedSystems", 0),
            "playerTier": s.get("playerTier"),
            "pactCount": s.get("pactCount", 0),
            "coalitionCount": s.get("coalitionCount", 0),
            "playerAchievements": s.get("playerAchievements") or [],
            "totalAchievements": s.get("totalAchievements", 0),
            "syndicateController": s.get("syndicateController"),
            "market": s.get("market") or {},
            "powerHistoryLengths": s.get("powerHistoryLengths") or {},
            "stateHash": self._hash_stream[-1] if self._hash_stream else None,
        }
        for key, val in player.items():
            flat[f"player_{key}"] = val
        return flat
