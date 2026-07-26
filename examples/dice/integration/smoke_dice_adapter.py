#!/usr/bin/env python3
"""Rung 2 (smoke) — the same round-trip, through UGT's BaseAdapter contract.

    python3 examples/dice/integration/smoke_dice_adapter.py

The spike proved the page's hooks. This proves `PlaywrightAdapter` speaks to
them correctly — including the places where the adapter's assumptions and this
game's hooks do not line up.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
for _p in (HERE, REPO):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from serve_process import adapter_for, served_bundle  # noqa: E402
from ugt.core.trial import GateRunner  # noqa: E402

STATE_KEYS = {"player", "enemy", "round_number", "battle_over", "winner"}

gate = GateRunner()


def main() -> int:
    print("Dice smoke — the BaseAdapter contract\n")

    with served_bundle() as port:
        ad = adapter_for(port)
        ad.connect()
        try:
            s = ad.reset()
            gate.ck("reset() returns the normalized 5-key state dict",
                    isinstance(s, dict) and set(s) == STATE_KEYS,
                    f"round={s.get('round_number')} "
                    f"{s['player']['force_strength']}v{s['enemy']['force_strength']}")

            shapes_ok, prev, moved = True, s, False
            for a in (0, 3, 6, 1, 5):
                out = ad.step(a)
                if not (isinstance(out, tuple) and len(out) == 4
                        and isinstance(out[0], dict) and isinstance(out[1], bool)
                        and isinstance(out[2], bool) and isinstance(out[3], dict)):
                    shapes_ok = False
                    break
                if out[0] != prev:
                    moved = True
                prev = out[0]
            gate.ck("5 step() calls each return (dict, bool, bool, dict)", shapes_ok)
            gate.ck("state actually advanced (not a dead wire)", moved,
                    f"round_number={prev.get('round_number')}")

            gate.ck("reset() mid-session returns to a fresh battle",
                    ad.reset()["round_number"] == 0)

            # ---- the adapter's blind spot, asserted rather than assumed --------
            # PlaywrightAdapter takes its "legacy mode" path for this game: the
            # hooks return a bare state, so it reads lifecycle fields off the state
            # dict via state.pop("terminated", False). Dice reports `battle_over`,
            # not `terminated`, so the adapter NEVER sees the battle end.
            ad.reset()
            term_seen, last = False, None
            for _ in range(13):
                last, terminated, _tr, _i = ad.step(0)
                term_seen = term_seen or terminated
                if last["battle_over"]:
                    break
            gate.ck("the battle really did conclude", bool(last["battle_over"]),
                    f"round {last['round_number']}, winner={last['winner']!r}")
            gate.ck("...but the adapter reported terminated=False throughout (known gap)",
                    term_seen is False,
                    "state.battle_over is the real signal; `terminated` is never sent")
            gate.finding(
                "PlaywrightAdapter never observes termination for this game. It reads "
                "state.pop('terminated'), and the hooks expose `battle_over` instead, so "
                "every step reports terminated=False even after the battle ends. Harmless "
                "here because a concluded battle is inert (asserted in R1/R2), but any "
                "episode-driven tier will run full-length episodes into a dead battle. "
                "Adding `terminated` to the hook payload would be a one-line game fix."
            )

            gate.ck("a concluded battle is inert through the adapter too",
                    ad.step(0)[0] == last and ad.step(6)[0] == last,
                    "two more actions after battle_over changed nothing")
        finally:
            ad.close()

        # One more adapter, to prove the rung leaves nothing behind.
        ad2 = adapter_for(port)
        ad2.connect()
        ok2 = isinstance(ad2.reset(), dict)
        ad2.close()
        gate.ck("a second adapter can connect and clean up independently", ok2)

    return gate.finish(
        "SMOKE",
        "PlaywrightAdapter honours the BaseAdapter contract against the real page, and the "
        "one place its assumptions diverge from this game's hooks is now asserted rather "
        "than discovered later.",
    )


if __name__ == "__main__":
    sys.exit(main())
