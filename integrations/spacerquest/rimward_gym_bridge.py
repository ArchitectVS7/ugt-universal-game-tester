#!/usr/bin/env python3
"""
Rimward Gym bridge — the transport shim that lets UGT's OWN machinery (the
SubprocessAdapter behind `ugt smoke-test` / `ugt verify` / `ugt train` /
`ugt evaluate`) drive the REAL Rimward engine through the T-1003 stdio protocol
(SpacerQuest `packages/sim/dist/protocol-stdio.js`).

  UGT SubprocessAdapter  ──Gym wire──▶  THIS BRIDGE  ──Rimward wire──▶  node protocol-stdio.js

Gym wire (spoken on THIS process's stdin/stdout, one JSON per line):
    {"command":"reset"}                  -> {"state": {...}}
    {"command":"step","action_id":N}     -> {"state":..., "terminated":..., "truncated":..., "info":...}
    {"command":"close"}                  -> {"ok": true} (and exit)

Rimward wire (spoken to the spawned node subprocess — see SpacerQuest
packages/sim/PROTOCOL.md):
    new-game / reset / start-day / legal-actions / apply-action / end-day

Like every UGT adapter (the ddd_harness lesson), this bridge contains NO game
logic. Every action id is STRUCTURAL: it selects among the LegalActionSpecs the
engine's own `legal-actions` enumerator advertised, filling each parameter from
the domain the spec itself declares. The bridge never invents an action, never
consults rules/content, and never sends anything the game did not offer — so an
`ActionBlocked` coming back from a bridge-formed action is a REAL parity defect
(counted in `blockedFromLegal`, which must stay 0).

Episode shape (for the RL/eval phases, which need episodic play):
  * terminated  — Tour One resolved (the engine's own era leaves TOUR_ONE);
                  `victory` = resolved with the Guild marker paid off (debt 0).
  * truncated   — day cap reached (UGT_MAX_DAYS, default 45).
  * Each reset() re-seeds deterministically: seed = UGT_SEED + episode_index,
    so episodes vary but a same-seed re-run reproduces the whole stream.

Action evidence: set SPACERQUEST_UGT_LOG to a file path and the bridge appends
one JSON line per applied action (episode, step, day, action, blocked, events) —
the auditable "UGT actions logged" trail for T-1604.

Env vars: SPACERQUEST_STDIO_BIN (built protocol bin), UGT_SEED (base seed, set
by UGT's SubprocessAdapter from training.seed), UGT_MAX_DAYS, UGT_MAX_ACTIONS_PER_DAY.
"""
from __future__ import annotations

import json
import os
import random
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
UGT_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
DEFAULT_BIN = os.path.join(
    UGT_ROOT, "..", "SpacerQuest", "packages", "sim", "dist", "protocol-stdio.js"
)
BIN = os.environ.get("SPACERQUEST_STDIO_BIN", DEFAULT_BIN)
BASE_SEED = int(os.environ.get("UGT_SEED", "42"))
MAX_DAYS = int(os.environ.get("UGT_MAX_DAYS", "45"))
MAX_ACTIONS_PER_DAY = int(os.environ.get("UGT_MAX_ACTIONS_PER_DAY", "30"))
LOG_PATH = os.environ.get("SPACERQUEST_UGT_LOG", "")

# ---------------------------------------------------------------------------
# Action vocabulary — MUST stay in lockstep with integrations/spacerquest/
# ugt.config.yaml action_space. Every id resolves to a spec the engine's own
# legal-actions enumerator advertised (or a rollover/Wait the wire allows);
# ids whose preferred class is absent fall back to the first legal spec, so the
# whole vocabulary stays driveable in every state and can never go illegal.
# ---------------------------------------------------------------------------
ACTION_NAMES = {
    0: "wait",              # bare Wait (canWait) — a no-op tick; forced rollover past the per-day cap
    1: "first_legal",       # first advertised spec, first value of every domain (deterministic)
    2: "random_legal",      # random spec, random params (seeded bridge RNG) — the fuzz id
    3: "travel_random",     # Travel to a random advertised destination
    4: "travel_contract",   # Travel; prefer the carried contract's destination IF advertised
    5: "buy_fuel_max",      # Trade/buy-fuel at the advertised max amount
    6: "sign_contract",     # Trade/sign-contract, first advertised board index
    7: "haggle",            # Trade/haggle, first advertised un-haggled index
    8: "pay_debt",          # Trade/pay-debt at the advertised domain minimum (die-free)
    9: "forfeit_cargo",     # Trade/forfeit-cargo — the T-1604 escape hatch
    10: "explore",          # Explore (die + fuel gated by the enumerator)
    11: "shipyard_repair",  # Shipyard/repair, repairMode 'all'
    12: "shipyard_buy",     # first non-repair Shipyard spec (component/pods/special)
    13: "visit_hangout",    # VisitHangout, first venue/params
    14: "crew_hire",        # Crew/hire, first advertised role
    15: "storylet_first",   # first eligible storylet choice
    16: "combat_talk",      # Combat, stance 'talk' if advertised
    17: "combat_run",       # Combat, stance 'run' if advertised
    18: "combat_fight",     # Combat, stance 'fight' if advertised
    19: "end_day",          # force the day-loop rollover (end-day + start-day)
}


class RimwardWire:
    """Line-delimited JSON over the spawned node protocol bin. Transport only."""

    def __init__(self, bin_path: str):
        self.proc = subprocess.Popen(
            ["node", bin_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    def send(self, req: dict) -> dict:
        assert self.proc.stdin and self.proc.stdout
        self.proc.stdin.write(json.dumps(req) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            err = self.proc.stderr.read() if self.proc.stderr else ""
            raise RuntimeError(f"Rimward wire closed unexpectedly. stderr: {err}")
        return json.loads(line.strip())

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except Exception:
            pass
        self.proc.terminate()
        try:
            self.proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.proc.kill()


class Bridge:
    def __init__(self) -> None:
        self.wire = RimwardWire(BIN)
        self.episode = -1
        self.rng = random.Random(BASE_SEED)
        self.summary: dict = {}
        self.steps_this_day = 0
        self.actions_applied = 0
        self.blocked_from_legal = 0
        self.protocol_errors = 0
        self.log_file = open(LOG_PATH, "a") if LOG_PATH else None

    # ── Rimward wire helpers ────────────────────────────────────────────────
    def _summary_of(self, resp: dict) -> dict:
        if resp.get("type") in ("state-summary", "action-result"):
            return resp["summary"]
        raise RuntimeError(f"unexpected Rimward response: {json.dumps(resp)[:200]}")

    def _legal(self) -> dict:
        resp = self.wire.send({"type": "legal-actions"})
        if resp.get("type") != "legal-actions":
            raise RuntimeError(f"unexpected legal-actions response: {json.dumps(resp)[:200]}")
        return resp["legalActions"]

    def _rollover(self) -> None:
        """DAY -> end-day -> DAWN -> start-day -> next DAY."""
        if self.summary.get("phase") == "DAY":
            self.summary = self._summary_of(self.wire.send({"type": "end-day"}))
        if self.summary.get("phase") == "DAWN":
            self.summary = self._summary_of(self.wire.send({"type": "start-day"}))
        self.steps_this_day = 0

    # ── Gym surface ────────────────────────────────────────────────────────
    def reset(self) -> dict:
        self.episode += 1
        seed = BASE_SEED + self.episode
        self.rng = random.Random(seed)
        self.steps_this_day = 0
        self.actions_applied = 0
        self.blocked_from_legal = 0
        self.protocol_errors = 0
        self.summary = self._summary_of(self.wire.send({"type": "reset", "seed": seed}))
        if self.summary.get("phase") == "DAWN":
            self.summary = self._summary_of(self.wire.send({"type": "start-day"}))
        return self._state()

    def step(self, action_id: int) -> tuple[dict, bool, bool, dict]:
        name = ACTION_NAMES.get(int(action_id), "first_legal")
        info: dict = {"command": "step", "actionName": name}

        if self.summary.get("phase") != "DAY":
            # Defensive: land back on a playable DAY before acting.
            self._rollover()

        forced_end = name == "end_day" or self.steps_this_day >= MAX_ACTIONS_PER_DAY
        if not forced_end:
            legal = self._legal()
            action = self._select(name, legal)
            if action is None:
                forced_end = True  # nothing actionable — the only move is end-day
            else:
                resp = self.wire.send({"type": "apply-action", "action": action})
                self.steps_this_day += 1
                if resp.get("type") == "action-result":
                    self.summary = resp["summary"]
                    events = [e.get("type") for e in resp.get("events", [])]
                    blocked = "ActionBlocked" in events
                    if blocked:
                        # The bridge only ever forms actions from the advertised
                        # legal list, so ANY block here is a parity defect.
                        self.blocked_from_legal += 1
                    self.actions_applied += 1
                    info.update({"action": action, "events": events, "blocked": blocked})
                    self._log(name, action, events, blocked)
                else:
                    # error response to a legal-list-derived action = protocol defect.
                    self.protocol_errors += 1
                    info.update({"action": action, "error": resp})
                    self._log(name, action, ["<error>"], False, error=resp)

        if forced_end:
            day_before = self.summary.get("day", 0)
            self._rollover()
            info.update({"rolledOver": True, "dayBefore": day_before})

        state = self._state()
        terminated = bool(state["eraVeteran"])  # Tour One resolved — the engine's own era gate
        truncated = not terminated and state["day"] > MAX_DAYS
        return state, terminated, truncated, info

    # ── structural action selection (no game logic) ─────────────────────────
    def _spec(self, legal: dict, type_: str, action: str | None = None):
        for spec in legal.get("actions", []):
            if spec.get("type") == type_ and (action is None or spec.get("action") == action):
                return spec
        return None

    def _fill(self, spec: dict, strategy: str = "first", prefer: dict | None = None) -> dict:
        """Form a PlayerAction from a spec: fixed discriminants + one value per
        parameter domain. Values come ONLY from the domains the spec declares."""
        action: dict = {"type": spec["type"]}
        for key in ("action", "storyletId", "choiceId"):
            if key in spec:
                action[key] = spec[key]
        for pkey, pspec in spec.get("params", {}).items():
            kind = pspec["kind"]
            if kind in ("die-index", "system-id", "contract-index", "enum"):
                choices = pspec.get("choices", [])
                if not choices:
                    continue
                if prefer and pkey in prefer and prefer[pkey] in choices:
                    action[pkey] = prefer[pkey]
                elif strategy == "random":
                    action[pkey] = self.rng.choice(choices)
                else:
                    action[pkey] = choices[0]
            elif kind == "int":
                if strategy == "max":
                    action[pkey] = pspec["max"]
                elif strategy == "random":
                    action[pkey] = self.rng.randint(pspec["min"], pspec["max"])
                else:
                    action[pkey] = pspec["min"]
            elif kind == "fixed":
                action[pkey] = pspec["value"]
        return action

    def _select(self, name: str, legal: dict) -> dict | None:
        specs = legal.get("actions", [])
        if name == "wait":
            if legal.get("canWait"):
                return {"type": "Wait"}
            return None
        if not specs:
            return None

        if name == "first_legal":
            return self._fill(specs[0])
        if name == "random_legal":
            return self._fill(self.rng.choice(specs), strategy="random")

        spec = None
        strategy = "first"
        prefer: dict | None = None
        if name == "travel_random":
            spec, strategy = self._spec(legal, "Travel"), "random"
        elif name == "travel_contract":
            spec = self._spec(legal, "Travel")
            contract = self.summary.get("activeContract")
            if contract:
                # Prefer the destination the ENGINE reported for the carried
                # contract, if (and only if) the enumerator advertises it.
                prefer = {"destinationId": contract.get("destination")}
        elif name == "buy_fuel_max":
            spec, strategy = self._spec(legal, "Trade", "buy-fuel"), "max"
        elif name == "sign_contract":
            spec = self._spec(legal, "Trade", "sign-contract")
        elif name == "haggle":
            spec = self._spec(legal, "Trade", "haggle")
        elif name == "pay_debt":
            spec = self._spec(legal, "Trade", "pay-debt")
        elif name == "forfeit_cargo":
            spec = self._spec(legal, "Trade", "forfeit-cargo")
        elif name == "explore":
            spec = self._spec(legal, "Explore")
        elif name == "shipyard_repair":
            spec = self._spec(legal, "Shipyard", "repair")
            prefer = {"repairMode": "all"}
        elif name == "shipyard_buy":
            spec = next(
                (s for s in specs if s.get("type") == "Shipyard" and s.get("action") != "repair"),
                None,
            )
        elif name == "visit_hangout":
            spec = self._spec(legal, "VisitHangout")
        elif name == "crew_hire":
            spec = self._spec(legal, "Crew", "hire")
        elif name == "storylet_first":
            spec = next((s for s in specs if s.get("type") == "Storylet"), None)
        elif name in ("combat_talk", "combat_run", "combat_fight"):
            spec = self._spec(legal, "Combat")
            prefer = {"stance": name.split("_", 1)[1]}

        if spec is None:
            spec = specs[0]  # fallback: stay legal, keep the id driveable
        return self._fill(spec, strategy=strategy, prefer=prefer)

    # ── observation / logging ───────────────────────────────────────────────
    def _state(self) -> dict:
        s = self.summary
        contract = s.get("activeContract")
        encounter = s.get("encounter")
        return {
            "day": s.get("day", 0),
            "phaseDay": 1 if s.get("phase") == "DAY" else 0,
            "eraVeteran": 0 if s.get("era") == "TOUR_ONE" else 1,
            "credits": s.get("credits", 0),
            "debt": s.get("debt", 0),
            "debtDueDay": s.get("debtDueDay", 0),
            "fuel": s.get("fuel", 0),
            "maxFuel": s.get("maxFuel", 0),
            "systemId": s.get("systemId", 0),
            "diceLeft": len(s.get("diceRemaining", [])),
            "rerollsRemaining": s.get("rerollsRemaining", 0),
            "crewCount": len(s.get("crew", [])),
            "crewCapacity": s.get("crewCapacity", 0),
            "portCount": len(s.get("ports", [])),
            "hasContract": 1 if contract else 0,
            "contractPayment": (contract or {}).get("payment", 0),
            "contractDestination": (contract or {}).get("destination", -1),
            "inEncounter": 1 if encounter else 0,
            "encounterTier": (encounter or {}).get("tier", 0),
            "enemyHull": (encounter or {}).get("enemyHull", 0),
            "boardCount": len(s.get("manifestBoard", [])),
            "localFuelPrice": s.get("localFuelPrice", 0),
            "storyletCount": len(s.get("eligibleStorylets", [])),
            "deedCount": s.get("deedCount", 0),
            "fragmentCount": s.get("fragmentCount", 0),
            "poiCount": s.get("poiCount", 0),
            "successionCount": s.get("successionCount", 0),
            "actionsApplied": self.actions_applied,
            "blockedFromLegal": self.blocked_from_legal,
            "protocolErrors": self.protocol_errors,
            # Tour One resolved with the Guild marker fully paid = the win.
            "victory": s.get("era") != "TOUR_ONE" and s.get("debt", 0) == 0,
        }

    def _log(self, name, action, events, blocked, error=None) -> None:
        if not self.log_file:
            return
        entry = {
            "episode": self.episode,
            "n": self.actions_applied,
            "day": self.summary.get("day"),
            "actionName": name,
            "action": action,
            "events": events,
            "blocked": blocked,
            "credits": self.summary.get("credits"),
            "debt": self.summary.get("debt"),
            "fuel": self.summary.get("fuel"),
        }
        if error is not None:
            entry["error"] = error
        self.log_file.write(json.dumps(entry) + "\n")
        self.log_file.flush()

    def close(self) -> None:
        if self.log_file:
            self.log_file.close()
        self.wire.close()


def main() -> int:
    if not os.path.exists(BIN):
        print(json.dumps({"error": f"protocol bin not found: {BIN}"}), flush=True)
        return 1
    bridge = Bridge()
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            req = json.loads(line)
            cmd = req.get("command")
            if cmd == "reset":
                state = bridge.reset()
                print(json.dumps({"state": state}), flush=True)
            elif cmd == "step":
                state, terminated, truncated, info = bridge.step(req.get("action_id", 0))
                print(
                    json.dumps(
                        {
                            "state": state,
                            "terminated": terminated,
                            "truncated": truncated,
                            "info": info,
                        }
                    ),
                    flush=True,
                )
            elif cmd == "close":
                print(json.dumps({"ok": True}), flush=True)
                break
            else:
                print(json.dumps({"error": f"unknown command: {cmd}"}), flush=True)
    finally:
        bridge.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
