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
    # Every wave key MUST be present and explicit. enabledWaves lives inside the
    # hashed GameState, so an omitted key is not a default — it is a different
    # game (and a match the engine's own `replay` op will refuse as a
    # MALFORMED_RECORD). All three on = the config apps/ladder and apps/play ship.
    "enabledWaves": {"stanceEcho": True, "chainsPredictions": True, "typeTriangle": True},
    "maxTurns": 50,
    "seed": "ddd-r1",
}

# The exact wave key set the engine requires (engine WAVE_KEYS, matchRecord.ts).
WAVE_KEYS = ("stanceEcho", "chainsPredictions", "typeTriangle")

# id -> name default, if the config doesn't carry action_mappings. MUST stay in
# lockstep with integrations/ddd/ugt.config.yaml (UgtConfig enforces
# size == len(actions)) and with `_select` below.
#
# Every id is STRUCTURAL: it selects among the actions the HARNESS itself
# enumerated (and, for targets, among the candidates the harness's own `targets`
# op returned). None of them consults card costs, rules, or content — the adapter
# has no game knowledge and must never grow any (the sim_bridge lesson).
_DEFAULT_ACTION_NAMES = {
    0: "commit_first",           # first legal COMMIT_SELECTION (deterministic)
    1: "commit_random",          # a random legal COMMIT_SELECTION (adapter RNG)
    2: "commit_last",            # last legal COMMIT_SELECTION (deterministic)
    3: "commit_with_targets",    # a commit whose `targets` op offers candidates; FILL them
    4: "commit_no_targets",      # a commit, targets left [] (the pre-`targets`-op control)
    5: "commit_with_prediction", # a commit carrying prediction != null (RARE + chainsPredictions)
    6: "commit_modal",           # a commit carrying modeIndex != null (modal card)
    7: "pass",                   # COMMIT_PASS (legal only when nothing is affordable)
    8: "mulligan_keep",          # MULLIGAN full:false
    9: "mulligan_full",          # MULLIGAN full:true
    10: "concede",               # CONCEDE — the ONLY route to a CONCESSION result
    11: "probe_illegal",         # deliberately ILLEGAL action -> expect RULES_ERROR + inert
    12: "probe_garbage",         # malformed action object -> expect refusal + inert
}

# Ids that deliberately send something the engine must REFUSE. `step` marks these
# with info["probe"]=True so `inv_no_error_on_legal` does not misread an expected
# refusal as a defect — and so a probe that is silently APPLIED is caught loudly.
PROBE_ACTION_NAMES = frozenset({"probe_illegal", "probe_garbage"})

# CONCEDE is filtered out of every selection EXCEPT the explicit `concede` id, so
# a random/heuristic policy can never accidentally throw the match.
_CONCEDE = "CONCEDE"


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
        # Fail LOUD on an under-specified wave set. The engine treats a missing
        # key as `undefined` -> falsy, so an incomplete enabledWaves silently
        # plays a DIFFERENT game (this is how D16's type triangle sat switched
        # off through the whole 2026-07-11 R1 run). Never guess a default here.
        missing = [k for k in WAVE_KEYS if k not in self.enabled_waves]
        unknown = [k for k in self.enabled_waves if k not in WAVE_KEYS]
        if missing or unknown:
            raise ValueError(
                "engine.enabledWaves must name EXACTLY "
                f"{list(WAVE_KEYS)} — missing={missing} unknown={unknown}. "
                "A missing wave key is not a default; it is a different game."
            )
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
        self._reset_count = 0

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

    @property
    def views(self):
        """Both raw PlayerViews as the harness last returned them.

        Read-only. Exposed so a gate script can resolve an action's `instanceId`
        to its `defId` (content coverage) and so the fog-of-war invariant can
        assert the OPPONENT view never carries hidden fields. The adapter itself
        never interprets these — it only relays them.
        """
        return self._views

    def defid_of(self, seat: int, instance_id: int):
        """The `defId` of a card in `seat`'s own hand, or None. Pure view lookup."""
        views = self._views or []
        if seat is None or seat >= len(views):
            return None
        for card in (views[seat].get("me", {}).get("hand") or []):
            if card.get("instanceId") == instance_id:
                return card.get("defId")
        return None

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
        """Create a fresh match on `seed` and return the normalized initial state.

        A BARE `reset()` (no seed) derives a distinct per-episode seed
        `"<self.seed>#<n>"` from a reset counter, because `ExploitHunter.run` resets
        with no arguments between episodes — a fixed seed there would replay the
        SAME match every episode and the whole hunt would be one trajectory wearing
        N hats. This stays fully deterministic: a fresh adapter always starts at
        n=0, so a same-seed re-run of episode k reproduces it byte for byte.
        """
        if self.process is None or self.process.poll() is not None:
            self.connect()

        if seed is None:
            seed_str = f"{self.seed}#{self._reset_count}"
        else:
            seed_str = str(seed)
        self._reset_count += 1
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
        name = self.action_name(action_id)
        is_probe = name in PROBE_ACTION_NAMES
        action = self._select(action_id, actions, seat)
        hash_before = self._hash_stream[-1] if self._hash_stream else None
        # Resolve the card's defId NOW, while it is still in the seat's hand — after
        # the act it has moved out of the view. Content-coverage gates need it.
        committed_defid = (
            self.defid_of(seat, action.get("instanceId"))
            if action.get("t") == "COMMIT_SELECTION" else None
        )

        resp = self._request({
            "op": "act",
            "matchId": self._match_id,
            "action": action,
        })

        if resp.get("ok") is False:
            # For every NON-probe id the adapter only ever sends an action drawn
            # from the harness's own legal list, so a RULES_ERROR here is a real
            # defect (`inv_no_error_on_legal` flags it). For a probe id a refusal
            # is the EXPECTED outcome — info["probe"] tells the invariants which
            # is which. Cached views are not mutated: the state is unchanged.
            after = self._read_state()
            return after, False, False, {
                "command": "act",
                "actionName": name,
                "defIdCommitted": committed_defid,
                "action": action,
                "seat": seat,
                "probe": is_probe,
                "hashBefore": hash_before,
                "stateHash": resp.get("stateHash"),
                "result": {**resp, "legalCount": len(actions), "hashBefore": hash_before,
                           "probe": is_probe, "actionName": name},
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
            "actionName": name,
                "defIdCommitted": committed_defid,
            "action": action,
            "seat": seat,
            # A probe reaching HERE means the engine ACCEPTED an action it should
            # have refused — `inv_probe_refused` turns that into a finding.
            "probe": is_probe,
            "hashBefore": hash_before,
            "stateHash": resp["stateHash"],
            "result": {**resp, "legalCount": len(actions), "hashBefore": hash_before,
                           "probe": is_probe, "actionName": name},
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

    def _targets(self, seat: int, instance_id: int, mode_index):
        """Ask the harness for the graveyard-target requirements of one commit.

        The harness's `legal` op reports EVERY action with `targets: []` (engine
        D-A — zero targets is legal, so the base move is legal, and richer sets
        are enumerated on demand). This op is the on-demand half: without it a
        wire client can play a graveyard-targeting card but never fill it, so the
        effect is permanently inert. Returns the `TargetRequirement` list
        (`[{effectIndex, maxCount, candidates}]`); `[]` = the card takes none.
        """
        resp = self._request({
            "op": "targets",
            "matchId": self._match_id,
            "player": int(seat),
            "instanceId": int(instance_id),
            "modeIndex": mode_index,
        })
        if not resp.get("ok"):
            raise RuntimeError(
                f"DDD harness targets failed (seat={seat} instanceId={instance_id} "
                f"modeIndex={mode_index}): {resp!r}"
            )
        return resp.get("requirements", [])

    def fill_targets(self, seat: int, action: dict) -> dict:
        """Return `action` with `targets` filled from the harness's own candidates.

        Picks up to `maxCount` DISTINCT candidate ids from requirements[0] — the
        contract the engine's `validateTargets` enforces. The GAME decides what is
        eligible; the adapter only relays the answer. Non-commits and cards with
        no requirement come back untouched.
        """
        if action.get("t") != "COMMIT_SELECTION":
            return action
        reqs = self._targets(seat, action["instanceId"], action.get("modeIndex"))
        if not reqs:
            return action
        req = reqs[0]
        candidates = list(req.get("candidates") or [])
        max_count = int(req.get("maxCount", 0))
        if not candidates or max_count <= 0:
            return action
        return {**action, "targets": candidates[:max_count]}

    def send_raw_action(self, action) -> dict:
        """Send an ARBITRARY action verbatim and return the raw `act` response.

        The refusal-probe channel (R3): unlike `step`, this deliberately does NOT
        restrict itself to the harness's legal list, so every RulesError arm can be
        provoked and asserted STATE-INERT. State is advanced only if the engine
        actually applied the action — a probe that unexpectedly applies is a real
        finding, and this method makes that observable rather than silently
        corrupting the run.
        """
        before = self._hash_stream[-1] if self._hash_stream else None
        if isinstance(action, dict):
            # Underscore-prefixed keys are display-only annotations added by
            # legal_actions() (_card/_hand) — never part of the wire action.
            action = {k: v for k, v in action.items() if not k.startswith("_")}
        resp = self._request({
            "op": "act",
            "matchId": self._match_id,
            "action": action,
        })
        if resp.get("ok") and resp.get("applied"):
            self._views = resp["views"]
            self._applied_actions.append(action)
            self._hash_stream.append(resp["stateHash"])
            self._step_count += 1
        resp = {**resp, "hashBefore": before}
        return resp

    def replay_current(self) -> dict:
        """Ask the harness to re-simulate the recorded action log and verify it."""
        return self._request({"op": "replay", "matchId": self._match_id})

    # ── legal-action drive mode (L-002 playtest seam) ─────────────────────────
    # A thin, game-agnostic channel for the LLM playtester: expose the SAME legal
    # list the ladder scripts read via `_legal`, and apply ONE chosen legal action
    # verbatim. Both methods are pure relays composed of existing primitives
    # (`_pending_seat`, `_legal`, `send_raw_action`, `_read_state`) — no rules, no
    # fabricated effects (the sim_bridge discipline this file enforces).
    def legal_actions(self):
        """Legal action objects for the seat the engine is waiting on — the SAME
        list the ladder scripts read via `_legal`, made playable-as-shown for a
        wire client. Returns [] when the match has ended (no pending seat).

        Two enrichments, both relays of the harness's own responses (never
        fabricated):

        - COMMIT_SELECTION actions get `targets` filled via `fill_targets` —
          the engine's `legalActions` always reports `targets: []` and its
          `targets` op is the only way a wire client discovers eligible ids
          (harness router.ts contract). Sending the raw list entry verbatim
          replays the L-007 "targeted cards played blank" wire defect on this
          side of the wire; the exploit-hunter path (`_select`) has always
          filled, this brings `apply_legal` to parity. They also get an
          `_card` annotation: the card's `defId` from the seat's OWN hand view
          (fog-of-war safe — it is the acting player's own hand).
        - MULLIGAN actions get a `_hand` annotation listing the hand's defIds,
          so a mulligan decision can actually be made on card identity.

        Underscore-prefixed keys are display-only for the LLM prompt and are
        stripped by `send_raw_action` before anything reaches the engine."""
        seat = self._pending_seat()
        if seat is None:
            return []
        actions, _ = self._legal(seat)
        views = self._views or []
        hand = (views[seat].get("me", {}).get("hand") or []) if seat < len(views) else []
        hand_defids = [c.get("defId") for c in hand]
        enriched = []
        for action in actions:
            if action.get("t") == "COMMIT_SELECTION":
                action = self.fill_targets(seat, action)
                action = {**action, "_card": self.defid_of(seat, action.get("instanceId"))}
            elif action.get("t") == "MULLIGAN":
                action = {**action, "_hand": hand_defids}
            enriched.append(action)
        return enriched

    def apply_legal(self, action, legal_count=None):
        """Apply ONE legal action object verbatim and return the standard
        (state, terminated, truncated, info) 4-tuple.

        `action` MUST be a member of the list `legal_actions()` returned this step
        (the LLM picks it by index). It is sent verbatim through `send_raw_action`,
        so the engine — never this adapter — decides the outcome; a legal action
        that is unexpectedly refused surfaces as `result.ok is False`, which the DDD
        invariant suite (`inv_no_error_on_legal`) turns into a real finding. `info`
        carries the `command`/`result` shape those invariants read."""
        resp = self.send_raw_action(action)
        after = self._read_state()
        terminated = after.get("resultKind", "ONGOING") != "ONGOING"
        name = action.get("t") if isinstance(action, dict) else str(action)
        result = {
            **resp,
            "legalCount": legal_count or 0,
            "probe": False,
            "actionName": name,
        }
        info = {
            "command": "act",
            "action": action,
            "actionName": name,
            "seat": resp.get("seat"),
            "probe": False,
            "stateHash": after.get("stateHash"),
            "result": result,
            "legalCount": legal_count or 0,
        }
        return after, terminated, False, info

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

    def action_name(self, action_id: int) -> str:
        return self._action_names.get(
            int(action_id), _DEFAULT_ACTION_NAMES.get(int(action_id), "commit_random")
        )

    def _probe_action(self, name: str, seat: int, actions: list) -> dict:
        """Build a deliberately-REFUSABLE action (R3 refusal probes).

        These are the only actions the adapter sends that are not drawn from the
        harness's legal list. They exist so the engine's refusal paths can be
        asserted state-inert — a game that silently ACCEPTS one of these has a
        real defect, and `step` flags it via info["probe"].
        """
        if name == "probe_garbage":
            # Not a member of the Action union at all.
            return {"t": "NOT_AN_ACTION", "player": int(seat)}
        # probe_illegal: a well-formed COMMIT_SELECTION naming a card that cannot
        # be in the seat's hand -> CARD_NOT_IN_HAND (or WRONG_PHASE in MULLIGAN).
        return {
            "t": "COMMIT_SELECTION",
            "player": int(seat),
            "instanceId": 999_999,
            "modeIndex": None,
            "targets": [],
            "prediction": None,
        }

    def _select(self, action_id: int, actions: list, seat: int) -> dict:
        """Choose an action for `action_id`.

        Every non-probe id resolves to a member of `actions` — the harness's OWN
        legal list — so the adapter can never send an illegal move by accident and
        never invents a move the game did not offer. CONCEDE is filtered out of
        every id except the explicit `concede` one, so a stochastic policy cannot
        throw the match by chance. When an id's preferred class is absent in the
        current phase it falls back to another legal non-CONCEDE action, so the
        whole vocabulary stays driveable in every phase.
        """
        aid = int(action_id)
        name = self.action_name(aid)

        if name in PROBE_ACTION_NAMES:
            return self._probe_action(name, seat, actions)

        if name == "concede":
            concedes = [a for a in actions if a.get("t") == _CONCEDE]
            if concedes:
                return concedes[0]
            # No CONCEDE offered (e.g. the match just ended) — fall through.

        pool = [a for a in actions if a.get("t") != _CONCEDE]
        if not pool:
            # Degenerate: the only legal move is CONCEDE. Unreachable in normal
            # DDD play; fall back so step() still sends something legal.
            pool = list(actions)

        commit_sel = [a for a in pool if a.get("t") == "COMMIT_SELECTION"]
        commit_pass = [a for a in pool if a.get("t") == "COMMIT_PASS"]
        mull_keep = [a for a in pool if a.get("t") == "MULLIGAN" and a.get("full") is False]
        mull_full = [a for a in pool if a.get("t") == "MULLIGAN" and a.get("full") is True]

        # commit_random is the only stochastic id.
        if name == "commit_random":
            return self._rng.choice(commit_sel) if commit_sel else self._rng.choice(pool)
        if name == "commit_first":
            return commit_sel[0] if commit_sel else pool[0]
        if name == "commit_last":
            return commit_sel[-1] if commit_sel else pool[-1]
        if name == "commit_no_targets":
            # The pre-`targets`-op control: commit, leave targets []. Keeping this
            # id makes the inert path an explicit, named choice rather than the
            # silent default it used to be.
            return commit_sel[0] if commit_sel else pool[0]
        if name == "commit_with_prediction":
            with_pred = [a for a in commit_sel if a.get("prediction") is not None]
            if with_pred:
                return self._rng.choice(with_pred)
            return commit_sel[0] if commit_sel else pool[0]
        if name == "commit_modal":
            modal = [a for a in commit_sel if a.get("modeIndex") is not None]
            if modal:
                return self._rng.choice(modal)
            return commit_sel[0] if commit_sel else pool[0]
        if name == "commit_with_targets":
            # Ask the GAME which commits actually have candidates, then fill them.
            # Scanning in legal order keeps this deterministic for a given state.
            for cand in commit_sel:
                filled = self.fill_targets(seat, cand)
                if filled.get("targets"):
                    return filled
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
