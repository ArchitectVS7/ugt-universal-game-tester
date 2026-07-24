"""
Foraging Run — a tiny, fully deterministic demo game engine.

Genre: turn-based survival micro-roguelike. It exists only to demonstrate UGT's
current methodology end-to-end (see this folder's README.md). It is NOT wired to
any real product; it is the whole game, in one file.

Two properties make it a faithful stand-in for a real engine-first integration:

  1. **It is the single source of truth for the rules.** Nothing outside this
     file knows how foraging or travel works. The harness (harness.py) and the
     adapter (harness_adapter.py) are pure transport — they move JSON, they never
     re-implement a rule. That is UGT rule M1 ("drive the real game, never a
     re-implementation") made concrete: the failure this whole example replaces
     was a bridge that slowly grew its own copy of the game's logic.

  2. **Its randomness lives IN the state (`rng_counter`), seeded once.** Every
     roll is `hash(seed, rng_counter)`, and `rng_counter` is part of the state
     dict. There is no wall-clock, no global RNG. So (seed + action sequence)
     fully determines every future state — which is exactly what lets R3 assert
     byte-identical same-seed replay. A real engine earns its determinism the
     same way (RNG-in-state, per-turn replay hashes).
"""
from __future__ import annotations

import hashlib
import json

HP_MAX = 10
DEST = 4          # reach this location (with hp > 0) to win
MAX_DAY = 12      # surviving past this day without arriving is a loss

# Action ids — mirrored in ugt.config.yaml's action_space and invariants.py.
ACTIONS = {
    0: "wait",       # safe no-op — always legal, never changes anything
    1: "forage",     # gather supplies; small chance of a scrape (-1 hp)
    2: "rest",       # spend 1 supply to recover 2 hp
    3: "travel",     # spend 2 supplies to advance one location; risk of ambush
    4: "trade",      # spend 2 coins for 3 supplies
    5: "end_day",    # advance the day; 1 supply of upkeep; resolves win/loss
}


def _fresh_state() -> dict:
    return {
        "day": 1,
        "hp": HP_MAX,
        "supplies": 6,
        "coins": 3,
        "location": 0,
        "rng_counter": 0,   # RNG-in-state: the ONLY source of variability
        "won": False,
        "lost": False,
        "log": "New expedition. Reach location %d before day %d." % (DEST, MAX_DAY),
    }


class ForagingRun:
    """The game. `seed` + the sequence of `act()` ids fully determines everything."""

    def __init__(self, seed: str = "0"):
        self.seed = str(seed)
        self.state = _fresh_state()

    # ── deterministic RNG, advanced by the counter that lives in the state ────
    def _roll(self, n: int) -> int:
        """Return an int in [0, n), derived purely from (seed, rng_counter)."""
        key = f"{self.seed}:{self.state['rng_counter']}".encode()
        self.state["rng_counter"] += 1
        return int.from_bytes(hashlib.sha256(key).digest()[:8], "big") % n

    def _clamp(self) -> None:
        self.state["hp"] = max(0, min(HP_MAX, self.state["hp"]))
        self.state["supplies"] = max(0, self.state["supplies"])
        self.state["coins"] = max(0, self.state["coins"])

    def _resolve_terminal(self) -> None:
        s = self.state
        if s["won"] or s["lost"]:
            return
        if s["location"] >= DEST and s["hp"] > 0:
            s["won"] = True
            s["log"] = "Arrived at location %d alive — expedition complete." % DEST
        elif s["hp"] <= 0:
            s["lost"] = True
            s["log"] = "Ran out of health. Expedition lost."
        elif s["day"] > MAX_DAY:
            s["lost"] = True
            s["log"] = "Ran out of days before arriving. Expedition lost."

    # ── the one entry point that mutates state ───────────────────────────────
    def act(self, action_id: int) -> None:
        s = self.state

        # Terminal is sticky: once the run is over, every action is a no-op.
        if s["won"] or s["lost"]:
            s["log"] = "Expedition already over; no action taken."
            return

        name = ACTIONS.get(action_id)

        if name == "wait":
            s["log"] = "Waited."

        elif name == "forage":
            gain = self._roll(4) + 1                      # +1..+4 supplies
            s["supplies"] += gain
            scrape = self._roll(4) == 0                   # 25% minor mishap
            if scrape:
                s["hp"] -= 1
                s["log"] = "Foraged +%d supplies but took a scrape (-1 hp)." % gain
            else:
                s["log"] = "Foraged +%d supplies." % gain

        elif name == "rest":
            if s["supplies"] >= 1:
                s["supplies"] -= 1
                s["hp"] += 2
                s["log"] = "Rested (-1 supply, +2 hp)."
            else:
                s["log"] = "No supplies to rest with."

        elif name == "travel":
            if s["supplies"] >= 2:
                s["supplies"] -= 2
                s["location"] += 1
                ambush = self._roll(3) == 0               # 33% ambush
                if ambush:
                    s["hp"] -= 2
                    s["log"] = "Travelled to location %d — ambushed (-2 hp)." % s["location"]
                else:
                    s["log"] = "Travelled to location %d." % s["location"]
            else:
                s["log"] = "Not enough supplies to travel (need 2)."

        elif name == "trade":
            if s["coins"] >= 2:
                s["coins"] -= 2
                s["supplies"] += 3
                s["log"] = "Traded 2 coins for 3 supplies."
            else:
                s["log"] = "Not enough coins to trade (need 2)."

        elif name == "end_day":
            s["day"] += 1
            s["supplies"] -= 1                            # daily upkeep
            if s["supplies"] < 0:
                s["supplies"] = 0
                s["hp"] -= 2                              # starvation
                s["log"] = "Day %d — no supplies, went hungry (-2 hp)." % s["day"]
            else:
                s["log"] = "Day %d began (-1 supply upkeep)." % s["day"]

        else:
            s["log"] = "Unknown action id %r; ignored." % (action_id,)

        self._clamp()
        self._resolve_terminal()

    # ── read-only helpers the harness uses ───────────────────────────────────
    def snapshot(self) -> dict:
        return dict(self.state)

    def terminated(self) -> bool:
        return bool(self.state["won"] or self.state["lost"])

    def legal_actions(self) -> list[int]:
        # Every action is always legal here; contextual ones simply no-op with a
        # log line (never crash). A real game would prune this per-state.
        return list(ACTIONS.keys())

    def state_hash(self) -> str:
        """Canonical hash of the FULL state — the per-step replay hash R3 compares."""
        blob = json.dumps(self.state, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()[:16]
