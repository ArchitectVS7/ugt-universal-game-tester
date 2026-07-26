#!/usr/bin/env python3
"""Rung 2 (smoke) — the same round-trip, through UGT's BaseAdapter contract.

    python3 examples/escape-room/integration/smoke_escape_room_adapter.py

The spike proved the wire. This proves `SubprocessAdapter` speaks to it
correctly — including the places where the adapter's assumptions and this game
do not line up.

**Why this rung exists when `ugt smoke-test` already passes.** `ugt smoke-test`
sends 5 UNIFORM-RANDOM action ids, and in this game only 6 of the 41 actions do
anything from the start room (the other 35 are refusals, which by design mutate
nothing at all). So P(all five steps inert) is (35/41)^5 ~= 45%: nearly half of
all `ugt smoke-test` runs print "fully operational" having proved only that the
pipe is open. Measured, not modelled — three consecutive runs on 2026-07-26
produced a frozen observation vector in two of them.

A rung that cannot tell a working game from a dead one is not a gate. This one
drives KNOWN-GOOD actions and asserts the state actually moved.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
for _p in (HERE, REPO):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from invariants import SUITE  # noqa: E402
from ugt.adapters.subprocess import SubprocessAdapter  # noqa: E402
from ugt.core.trial import GateRunner  # noqa: E402
from ugt.utils.config_parser import UgtConfig  # noqa: E402

CONFIG = os.path.join(HERE, "ugt.config.yaml")
STATE_KEYS = {"current_room", "inventory", "flags",
              "moves_taken", "rooms_visited", "escaped"}

gate = GateRunner()


def check(ok, label, detail=""):
    """Adapter to GateRunner's (name, ok, detail) order, so call sites read naturally."""
    return gate.ck(label, ok, detail)


def main() -> int:
    print("Escape Room smoke — the BaseAdapter contract\n")

    cfg = UgtConfig(CONFIG)
    names = {int(k): v["name"] for k, v in cfg.action_mappings.items()}
    by_name = {v: k for k, v in names.items()}

    ad = SubprocessAdapter(cfg)
    ad.connect()
    check(ad.process is not None and ad.process.poll() is None,
          "connect() spawns a live `node bridge.js` child",
          f"pid={getattr(ad.process, 'pid', None)}")

    s = ad.reset()
    check(isinstance(s, dict) and set(s) == STATE_KEYS,
          "reset() returns the 6-key state dict",
          f"room={s.get('current_room')} moves={s.get('moves_taken')}")

    # ── the non-vacuity gate ─────────────────────────────────────────────────
    # Known-good opening moves, not random ids: go_north, look, go_east,
    # take_lantern, inventory. If ANY of these leaves the game inert, the wire is
    # dead and every rung above this one would be measuring nothing.
    print("\n  -- driven with known-good actions (not random ids) --")
    script = ["go_north", "look", "go_east", "take_lantern", "inventory"]
    shapes_ok, prev, moved_on = True, s, []
    violations: list[str] = []
    for name in script:
        out = ad.step(by_name[name])
        if not (isinstance(out, tuple) and len(out) == 4
                and isinstance(out[0], dict) and isinstance(out[1], bool)
                and isinstance(out[2], bool) and isinstance(out[3], dict)):
            shapes_ok = False
            break
        after = out[0]
        violations += [f"after {name}: {v}"
                       for v in SUITE.check_command(prev, after, name, out[3] or {})]
        if after != prev:
            moved_on.append(name)
        prev = after
    check(shapes_ok, f"{len(script)} step() calls each return (dict, bool, bool, dict)")
    check(len(moved_on) == len(script),
          "EVERY known-good action changed state (not a dead wire)",
          f"{len(moved_on)}/{len(script)} moved: {moved_on}")
    check(prev.get("current_room") == "R03" and "lantern" in (prev.get("inventory") or []),
          "the driven script arrived where the content says it should",
          f"room={prev.get('current_room')} inventory={prev.get('inventory')}")
    check(not violations, f"invariants hold across all {len(script)} commands",
          "" if not violations else "; ".join(violations[:3]))

    # ── the hole this rung was written to close ──────────────────────────────
    # Quantify it rather than assert it away: this is the number that makes the
    # case for driving a script instead of trusting `ugt smoke-test`.
    print("\n  -- how inert is a random step, really? --")
    live = []
    for aid, name in sorted(names.items()):
        probe = SubprocessAdapter(cfg)
        probe.connect()
        b = probe.reset()
        a, _, _, _ = probe.step(aid)
        if a != b:
            live.append(name)
        probe.close()
    frac_inert = 1 - len(live) / len(names)
    check(len(live) > 0, "at least one action is live from the start room",
          f"{len(live)}/{len(names)} live: {live}")
    gate.finding(
        f"`ugt smoke-test` is ~{frac_inert ** 5:.0%} likely to pass on a FROZEN state here: "
        f"only {len(live)}/{len(names)} actions are live from the start room and refusals "
        f"mutate nothing, so 5 uniform-random steps often prove only that the pipe is open. "
        f"This rung drives a known-good script instead. Generalises to any game with a "
        f"large action space and context-gated actions.")

    # ── termination is visible to the adapter ────────────────────────────────
    # Dice's R3 lost ~91% of its budget to a terminal flag the adapter could not
    # see. Here the bridge sets `terminated` itself, so check it end to end
    # rather than assume the two games are alike.
    print("\n  -- termination reaches the adapter --")
    ad2 = SubprocessAdapter(cfg)
    ad2.connect()
    ad2.reset()
    walk = json.load(open(os.path.join(HERE, "..", "game", "content", "walkthrough.json")))
    term = False
    final = {}
    for stepdef in walk:
        arg = stepdef.get("object") or ""
        nm = f"{stepdef['verb']}_{arg}" if arg else stepdef["verb"]
        final, term, _trunc, _info = ad2.step(by_name[nm])
    check(final.get("escaped") is True, "the committed walkthrough reaches escaped",
          f"room={final.get('current_room')} moves={final.get('moves_taken')}")
    check(term is True, "the adapter SEES termination (`terminated` mirrors escaped)",
          f"terminated={term}")
    ad2.close()

    # ── lifecycle ────────────────────────────────────────────────────────────
    print("\n  -- lifecycle --")
    s2 = ad.reset()
    check(s2["moves_taken"] == 0 and s2["escaped"] is False,
          "reset() mid-session returns to a fresh game",
          f"moves={s2['moves_taken']}")

    proc = ad.process
    ad.close()
    check(proc is None or proc.poll() is not None,
          "close() reaps the child process (no orphan `node`)",
          f"exit={None if proc is None else proc.poll()}")

    ad3 = SubprocessAdapter(cfg)
    ad3.connect()
    ok3 = isinstance(ad3.reset(), dict)
    p3 = ad3.process
    ad3.close()
    check(ok3 and (p3 is None or p3.poll() is not None),
          "a second adapter can connect and clean up independently")

    return gate.finish(
        "SMOKE",
        "SubprocessAdapter honours the BaseAdapter contract, sees termination, owns the "
        "child's lifecycle, and — unlike a uniform-random probe — this rung fails when the "
        "game goes inert.")


if __name__ == "__main__":
    sys.exit(main())
