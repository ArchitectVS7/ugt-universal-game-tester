#!/usr/bin/env python3
"""Rung 1 (spike) — the raw `window` hook contract, with no UGT adapter involved.

    python3 examples/dice/integration/spike_dice.py

Playwright loads the built page and calls the three hooks directly. The point is
to pin down what the game ACTUALLY does before anything is built on top of it —
this repo keeps finding gaps between a PRD and its wire, and a spike is the
cheapest place to find them.

Spawns and reaps its own server on an ephemeral port; needs nothing running.
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

from serve_process import served_bundle  # noqa: E402
from ugt.core.trial import GateRunner  # noqa: E402

STATE_KEYS = {"player", "enemy", "round_number", "battle_over", "winner"}
SIDE_KEYS = {"force_strength", "bonus_dice"}
HOOKS = ("__GET_STATE__", "__SEND_ACTION__", "__RESET__", "__RESET_GAME__")

gate = GateRunner()


def main() -> int:
    print("Dice spike — the raw window hook contract\n")

    from playwright.sync_api import sync_playwright

    with served_bundle() as port:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://localhost:{port}/index.html")
            page.wait_for_function("typeof window.__GET_STATE__ === 'function'", timeout=10000)

            print("  -- hooks --")
            missing = [h for h in HOOKS
                       if not page.evaluate(f"typeof window.{h} === 'function'")]
            gate.ck("all four documented hooks are present and callable",
                    not missing, f"missing={missing}" if missing else ", ".join(HOOKS))

            print("\n  -- __GET_STATE__ --")
            s0 = page.evaluate("window.__GET_STATE__()")
            gate.ck("state carries exactly the PRD's 5 top-level keys",
                    set(s0) == STATE_KEYS,
                    f"missing={sorted(STATE_KEYS - set(s0))} extra={sorted(set(s0) - STATE_KEYS)}")
            gate.ck("each side carries exactly force_strength and bonus_dice",
                    set(s0["player"]) == SIDE_KEYS and set(s0["enemy"]) == SIDE_KEYS,
                    f"player={sorted(s0['player'])}")
            gate.ck("a fresh page starts at round 0, 20/20, undecided",
                    s0["round_number"] == 0 and s0["battle_over"] is False
                    and s0["winner"] is None
                    and s0["player"]["force_strength"] == 20
                    and s0["enemy"]["force_strength"] == 20,
                    json.dumps(s0["player"]) + " vs " + json.dumps(s0["enemy"]))
            gate.ck("__GET_STATE__ is a pure read (calling it twice changes nothing)",
                    page.evaluate("window.__GET_STATE__()") == s0)

            print("\n  -- __SEND_ACTION__ --")
            env = page.evaluate("window.__SEND_ACTION__(0)")
            gate.ck("returns the structured {state, terminated, truncated, info} envelope",
                    isinstance(env, dict)
                    and set(env) == {"state", "terminated", "truncated", "info"},
                    f"keys={sorted(env)}")
            r = env["state"]
            gate.ck("the enveloped state is the same 5-key projection",
                    set(r) == STATE_KEYS, f"keys={sorted(r)}")
            gate.ck("terminated mirrors battle_over (so a driver can see the end)",
                    env["terminated"] == r["battle_over"],
                    f"terminated={env['terminated']} battle_over={r['battle_over']}")
            gate.ck("one action resolves exactly one round",
                    r["round_number"] == s0["round_number"] + 1,
                    f"round {s0['round_number']} -> {r['round_number']}")
            gate.ck("what it returns matches what __GET_STATE__ then reports",
                    r == page.evaluate("window.__GET_STATE__()"))
            gate.ck("an all-attack round actually damages the enemy",
                    r["enemy"]["force_strength"] < s0["enemy"]["force_strength"],
                    f"enemy {s0['enemy']['force_strength']} -> {r['enemy']['force_strength']}")

            print("\n  -- illegal input --")
            # This game REJECTS LOUDLY rather than absorbing bad input: engine.js
            # validates the preset index and throws instead of coercing. Worth
            # knowing, because the repo's other two examples answer this question
            # the opposite way (escape-room and sokoban both treat an unknown
            # action id as an inert no-op that still returns state). It is a
            # deliberate call (ugtHooks.js D16, "loud, not coerced") that never
            # made it into PRD.md.
            #
            # What actually matters for a tester is not which of the two it does,
            # but that it does it CLEANLY — a throw part-way through resolving a
            # round could leave the battle half-updated. It does not.
            before = page.evaluate("window.__GET_STATE__()")
            threw, mutated = [], []
            for bad in ("-1", "7", "999", "null", "'x'", "1.5", "undefined"):
                try:
                    page.evaluate(f"window.__SEND_ACTION__({bad})")
                except Exception:
                    threw.append(bad)
                if page.evaluate("window.__GET_STATE__()") != before:
                    mutated.append(bad)
            gate.ck("every ill-typed / out-of-range action id is rejected",
                    len(threw) == 7, f"threw on: {', '.join(threw)}")
            gate.ck("a rejected action mutates NOTHING (no half-resolved round)",
                    not mutated,
                    "state identical after all 7" if not mutated else f"mutated by: {mutated}")
            healthy = page.evaluate("window.__SEND_ACTION__(0)")["state"]
            gate.ck("the game is still usable after being fed garbage",
                    healthy["round_number"] == before["round_number"] + 1,
                    f"round advanced {before['round_number']} -> {healthy['round_number']}")
            gate.finding(
                "__SEND_ACTION__ THROWS on an out-of-range or ill-typed action id, where "
                "escape-room and sokoban both return current state unchanged. State is not "
                "corrupted either way, so this is a contract divergence rather than a bug, and "
                "it IS deliberate — ugtHooks.js D16 says a contract violation should be loud, "
                "not coerced. The gap is that the decision lives in a code comment and never "
                "reached PRD.md, so a black-box client has to discover by experiment that it "
                "must try/except this game and not the other two. Worth settling one way "
                "across all three examples and writing it down where clients will look."
            )

            print("\n  -- __RESET__ --")
            page.evaluate("window.__SEND_ACTION__(0)")
            fresh = page.evaluate("window.__RESET__()")
            fresh = fresh if isinstance(fresh, dict) else page.evaluate("window.__GET_STATE__()")
            gate.ck("__RESET__() returns to a fresh battle",
                    fresh["round_number"] == 0 and fresh["battle_over"] is False)
            gate.ck("__RESET_GAME__ is an alias for the same thing (the adapter uses it)",
                    (page.evaluate("window.__SEND_ACTION__(0)") is not None)
                    and (page.evaluate("window.__RESET_GAME__()") or
                         page.evaluate("window.__GET_STATE__()"))["round_number"] == 0)

            print("\n  -- seeding --")
            # The whole reason a scripted rung can do what the feature map cannot:
            # it can choose a seed. `engine.reset_command` is ignored for any game
            # exposing __RESET_GAME__, so config-level seeding is not available.
            def battle(seed, action=0, rounds=13):
                page.evaluate(f"window.__RESET__({json.dumps(seed)})")
                last = page.evaluate("window.__GET_STATE__()")
                for _ in range(rounds):
                    last = page.evaluate(f"window.__SEND_ACTION__({action})")["state"]
                    if last["battle_over"]:
                        break
                return last

            a1, a2 = battle("dice-duel"), battle("dice-duel")
            gate.ck("same seed + same actions replays identically",
                    a1 == a2, f"round {a1['round_number']}, winner={a1['winner']!r}")
            other = battle(0)
            gate.ck("a DIFFERENT seed gives a different battle (seeding really works)",
                    other != a1,
                    f"'dice-duel' -> {a1['winner']!r} @r{a1['round_number']}, "
                    f"0 -> {other['winner']!r} @r{other['round_number']}")

            print("\n  -- console --")
            gate.ck("no uncaught page errors during the whole spike",
                    not errors, "; ".join(errors[:2]))

            browser.close()

    return gate.finish(
        "SPIKE",
        "The raw hook contract holds: exact state shape, one action per round, illegal "
        "input rejected without corrupting state, reset and seeding both real, and no page "
        "errors. Safe to build on.",
    )


if __name__ == "__main__":
    sys.exit(main())
