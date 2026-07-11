"""
DddHarnessAdapter — drives the REAL DDD deterministic engine through its
JSON-lines subprocess harness (packages/harness/bin/harness.mjs), never a
re-implementation (the sim_bridge lesson).

DDD is a two-player deterministic dueling card game. Its engine is a
zero-dependency, RNG-in-state simulation; the harness wraps it as a line
protocol — one JSON request per line in, one response per line out, in order:

  {"op":"create",...}  -> a fresh match (matchId m1,m2,…), two PlayerViews, hash
  {"op":"legal",...}   -> the legal Actions for one seat
  {"op":"act",...}     -> apply one Action -> events + updated views + hash, OR a
                          RULES_ERROR ({ok:false,applied:false,...}, hash unchanged)
  {"op":"replay",...}  -> re-simulate the recorded action log, verify determinism

Like every UGT adapter this contains NO game logic — it is a transport layer that
(a) spawns/speaks to the harness and (b) chooses which LEGAL action to send for a
given action id. It never fabricates an effect: every state fact is read back from
the harness views. The engine is authoritative; the adapter only picks moves from
the legal list the harness returns, and NEVER concedes.

Two seats, one process: DDD is turn-simultaneous with a MULLIGAN step then repeated
SELECTION steps. The adapter figures out which seat the engine is waiting on
(`_pending_seat`) and drives that seat, so a single stream of `step()` calls walks
a whole match to a terminal result (WIN/DRAW) or the maxTurns cap.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import subprocess

from ugt.adapters.base import BaseAdapter

DEFAULTS = {
    "harness_entry": "/Users/vs7/Dev/Games/DDD/packages/harness/bin/harness.mjs",
    "node_bin": "node",
    "decks": ["bb_competitive", "sw_competitive"],
    "format": "COMPETITIVE",
    "enabledWaves": {"stanceEcho": True, "chainsPredictions": False},
    "maxTurns": 50,
    "seed": "ddd-r1",
}

# id -> name default, if the config doesn't carry action_mappings.
_DEFAULT_ACTION_NAMES = {
    0: "commit_first",
    1: "commit_random",
    2: "pass",
    3: "mulligan_keep",
    4: "mulligan_full",
}


class DddHarnessAdapter(BaseAdapter):
    """Transport-only handle on the running DDD harness. Contains NO game logic."""

    def __init__(self, config=None):
        super().__init__(config)
        eng = {}
        if config is not None:
            try:
                eng = config.data.get("engine", {}) or {}
            except AttributeError:
                eng = {}

        self.harness_entry = str(
            os.environ.get("DDD_HARNESS_PATH")
            or eng.get("harness_entry")
            or DEFAULTS["harness_entry"]
        )
        self.node_bin = str(eng.get("node_bin", DEFAULTS["node_bin"]))
        # Default cwd = the DDD repo root inferred from the harness path
        # (…/DDD/packages/harness/bin/harness.mjs -> …/DDD). @ddd/engine resolves
        # from there.
        inferred_cwd = os.path.abspath(
            os.path.join(os.path.dirname(self.harness_entry), "..", "..", "..")
        )
        self.harness_cwd = str(
            os.environ.get("DDD_HARNESS_CWD")
            or eng.get("harness_cwd")
            or inferred_cwd
        )
        self.decks = list(eng.get("decks", DEFAULTS["decks"]))
        self.match_format = str(eng.get("format", DEFAULTS["format"]))
        self.enabled_waves = dict(eng.get("enabledWaves", DEFAULTS["enabledWaves"]))
        self.max_turns = int(eng.get("maxTurns", DEFAULTS["maxTurns"]))
        self.seed = str(eng.get("seed", DEFAULTS["seed"]))

        # action_id -> action name (from config, else the 5-name default).
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
        self._create_id = 0
        self._match_id = None
        self._rng = random.Random(0)
        self._views = None
        self._applied_actions = []
        self._hash_stream = []
        self._step_count = 0

    # ── public read-only attributes (mirrors nexus/warzones shape) ───────────
    @property
    def hash_stream(self):
        return self._hash_stream

    @property
    def applied_actions(self):
        return self._applied_actions

    @property
    def step_count(self):
        return self._step_count

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
                f"Failed to spawn DDD harness {cmd!r} (cwd={self.harness_cwd!r}): {e}"
            ) from e

        if self.process.poll() is not None:
            err = self._drain_stderr()
            raise RuntimeError(
                f"DDD harness exited immediately (code {self.process.returncode}). "
                f"Stderr: {err or '<empty>'} — check node >=24 and that @ddd/engine "
                f"resolves from cwd {self.harness_cwd!r}."
            )
        return {"pid": self.process.pid}

    def reset(self, seed=None):
        """Create a fresh match on `seed` and return the normalized initial state."""
        if self.process is None or self.process.poll() is not None:
            self.connect()

        seed_str = str(seed if seed is not None else self.seed)
        resp = self._request({
            "op": "create",
            "config": {
                "decks": self.decks,
                "format": self.match_format,
                "enabledWaves": self.enabled_waves,
                "maxTurns": self.max_turns,
            },
            "seed": seed_str,
        })
        if not resp.get("ok"):
            raise RuntimeError(f"DDD harness create failed: {resp!r}")

        self._match_id = resp.get("matchId")
        # Deterministic policy RNG re-seeded from the same seed string, so a
        # same-seed re-run replays the adapter's own action choices byte-identically.
        digest = hashlib.sha256(seed_str.encode()).digest()[:8]
        self._rng = random.Random(int.from_bytes(digest, "big"))
        self._views = resp["views"]
        self._applied_actions = []
        self._hash_stream = [resp["stateHash"]]
        self._step_count = 0
        return self._normalize(resp["stateHash"])

    def step(self, action_id):
        """Drive the pending seat with the move mapped to `action_id`.

        Returns (state, terminated, truncated, info). If the match has already
        ended, returns the cached terminal state with terminated=True.
        """
        seat = self._pending_seat()
        if seat is None:
            after = self._read_state()
            return after, True, False, {
                "command": "act",
                "action": None,
                "seat": None,
                "stateHash": self._hash_stream[-1] if self._hash_stream else None,
                "result": {"ok": True, "terminal": True},
                "legalCount": 0,
            }

        actions, _lhash = self._legal(seat)
        action = self._select(action_id, actions)

        resp = self._request({
            "op": "act",
            "matchId": self._match_id,
            "action": action,
        })

        if resp.get("ok") is False:
            # Canary: for ids 0-4 the adapter only ever sends a LEGAL action, so a
            # RULES_ERROR here should never happen. Surface it in info without
            # mutating cached views; the invariant sweep will flag it.
            after = self._read_state()
            return after, False, False, {
                "command": "act",
                "action": action,
                "seat": seat,
                "stateHash": resp.get("stateHash"),
                "result": {**resp, "legalCount": len(actions)},
                "legalCount": len(actions),
            }

        self._views = resp["views"]
        self._applied_actions.append(action)
        self._hash_stream.append(resp["stateHash"])
        self._step_count += 1

        after = self._normalize(resp["stateHash"])
        terminated = after["resultKind"] != "ONGOING"
        truncated = False
        info = {
            "command": "act",
            "action": action,
            "seat": seat,
            "stateHash": resp["stateHash"],
            "result": {**resp, "legalCount": len(actions)},
            "legalCount": len(actions),
        }
        return after, terminated, truncated, info

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
        """Send one op line, read exactly one response line (in-order protocol).

        Assigns a monotonically increasing request id. Raises on EOF (drains
        stderr) or an id desync.
        """
        if self.process is None or self.process.poll() is not None:
            err = self._drain_stderr()
            raise RuntimeError(f"DDD harness is not running. Stderr: {err or '<empty>'}")

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
                raise RuntimeError(f"harness returned non-JSON line {line!r}: {e}") from e
            resp_id = resp.get("id")
            if resp_id is not None and resp_id != req_id:
                raise RuntimeError(
                    f"harness id desync: sent id={req_id} got id={resp_id} ({resp!r})"
                )
            return resp

    def _drain_stderr(self) -> str:
        if self.process is None or self.process.stderr is None:
            return ""
        try:
            return self.process.stderr.read() or ""
        except Exception:
            return ""

    def _legal(self, seat: int):
        """Return (legal_actions, stateHash) for `seat`."""
        resp = self._request({
            "op": "legal",
            "matchId": self._match_id,
            "player": int(seat),
        })
        if not resp.get("ok"):
            raise RuntimeError(f"DDD harness legal failed for seat {seat}: {resp!r}")
        return resp.get("actions", []), resp.get("stateHash")

    def replay_current(self) -> dict:
        """Ask the harness to re-simulate the recorded action log and verify it."""
        return self._request({"op": "replay", "matchId": self._match_id})

    # ── seat / action selection (transport policy, NOT game logic) ───────────
    def _pending_seat(self):
        """Which seat the engine is waiting on, or None if the match has ended.

        MULLIGAN  -> first seat that has not used its mulligan.
        SELECTION -> first seat that has not committed.
        else      -> defensive fallback: the seat whose legal list has a
                     non-CONCEDE action. Always verify the chosen seat actually
                     has a non-CONCEDE action; otherwise try the other seat.
        """
        views = self._views
        if views is None:
            return None
        if views[0].get("result", {}).get("kind") != "ONGOING":
            return None

        phase = views[0].get("phase")
        candidate = None
        if phase == "MULLIGAN":
            for s in (0, 1):
                if views[s]["me"].get("mulliganUsed") is False:
                    candidate = s
                    break
        elif phase == "SELECTION":
            for s in (0, 1):
                if views[s]["me"].get("committedSelection") is None:
                    candidate = s
                    break

        if candidate is not None and self._has_non_concede(candidate):
            return candidate
        # Defensive fallback (unexpected phase, or the phase heuristic pointed at a
        # seat with nothing but CONCEDE): pick whichever seat can actually act.
        for s in (0, 1):
            if self._has_non_concede(s):
                return s
        return candidate

    def _has_non_concede(self, seat: int) -> bool:
        actions, _ = self._legal(seat)
        return any(a.get("t") != "CONCEDE" for a in actions)

    def _select(self, action_id: int, actions: list) -> dict:
        """Choose a LEGAL action for `action_id`, NEVER CONCEDE, never illegal.

        Preferred class per id; if that class is absent in the current legal set,
        fall back to another non-CONCEDE action (rng for the random id, first for
        the deterministic ids). Only ever returns a member of `actions`.
        """
        pool = [a for a in actions if a.get("t") != "CONCEDE"]
        if not pool:
            # Degenerate: the only legal move is CONCEDE. The adapter refuses to
            # concede; fall back to the raw list so step() still sends something
            # legal (in practice this branch is unreachable in normal DDD play).
            pool = list(actions)

        aid = int(action_id)
        name = self._action_names.get(aid, _DEFAULT_ACTION_NAMES.get(aid, "commit_random"))

        commit_sel = [a for a in pool if a.get("t") == "COMMIT_SELECTION"]
        commit_pass = [a for a in pool if a.get("t") == "COMMIT_PASS"]
        mull_keep = [a for a in pool
                     if a.get("t") == "MULLIGAN" and a.get("full") is False]
        mull_full = [a for a in pool
                     if a.get("t") == "MULLIGAN" and a.get("full") is True]

        # commit_random is the only stochastic id.
        if name == "commit_random":
            return self._rng.choice(commit_sel) if commit_sel else self._rng.choice(pool)
        if name == "commit_first":
            return commit_sel[0] if commit_sel else pool[0]
        if name == "pass":
            return commit_pass[0] if commit_pass else pool[0]
        if name == "mulligan_keep":
            return mull_keep[0] if mull_keep else pool[0]
        if name == "mulligan_full":
            return mull_full[0] if mull_full else pool[0]
        # Unknown id name -> first legal non-CONCEDE (deterministic).
        return pool[0]

    # ── observation ──────────────────────────────────────────────────────────
    def _read_state(self) -> dict:
        """Normalized view of the CACHED state (no re-send). Named EXACTLY
        `_read_state` — ExploitHunter probes for it by name during crash
        recovery."""
        last_hash = self._hash_stream[-1] if self._hash_stream else None
        return self._normalize(last_hash)

    def _normalize(self, state_hash) -> dict:
        views = self._views or [{}, {}]
        v0 = views[0] if len(views) > 0 else {}
        v1 = views[1] if len(views) > 1 else {}
        result = v0.get("result", {"kind": "ONGOING"})
        return {
            "turn": v0.get("turn"),
            "phase": v0.get("phase"),
            "result": result,
            "resultKind": result.get("kind", "ONGOING"),
            "stateHash": state_hash,
            "pendingSeat": self._pending_seat_from(views),
            "p0": self._seat(v0.get("me", {})),
            "p1": self._seat(v1.get("me", {})),
        }

    @staticmethod
    def _seat(me: dict) -> dict:
        committed = me.get("committedSelection") or {}
        kind = committed.get("kind") if isinstance(committed, dict) else None
        return {
            "hp": me.get("hp"),
            "focus": me.get("focus"),
            "stance": me.get("stance"),
            "handCount": len(me.get("hand", []) or []),
            "deckCount": me.get("deckCount"),
            "graveyardCount": len(me.get("graveyard", []) or []),
            "committedKind": kind,
            "committedCard": 1 if kind == "CARD" else 0,
            "hasCommitted": me.get("committedSelection") is not None,
            "mulliganUsed": me.get("mulliganUsed"),
            "shieldPool": me.get("shieldPool"),
        }

    @staticmethod
    def _pending_seat_from(views) -> int | None:
        """Pure (no request) pending-seat read for _normalize, from the cached
        views only. Mirrors the MULLIGAN/SELECTION phase heuristic; the defensive
        legal-probing fallback lives in _pending_seat()."""
        if not views:
            return None
        if views[0].get("result", {}).get("kind") != "ONGOING":
            return None
        phase = views[0].get("phase")
        if phase == "MULLIGAN":
            for s in (0, 1):
                if views[s].get("me", {}).get("mulliganUsed") is False:
                    return s
        elif phase == "SELECTION":
            for s in (0, 1):
                if views[s].get("me", {}).get("committedSelection") is None:
                    return s
        return None
