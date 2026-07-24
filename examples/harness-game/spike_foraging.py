#!/usr/bin/env python3
"""
Ladder rung 1 — SPIKE. Prove the raw JSON-lines protocol round-trips headlessly,
BEFORE any adapter is involved. Talks to harness.py directly over pipes.

Run from the repo root:
    python3 examples/harness-game/spike_foraging.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)  # so the ugt.core import path AND local files resolve
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..")))

from ugt.core.trial import GateRunner  # noqa: E402


class RawHarness:
    """Minimal direct pipe client — no UGT adapter, just the wire."""

    def __init__(self):
        self.p = subprocess.Popen(
            [sys.executable, os.path.join(_HERE, "harness.py")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1, cwd=_HERE,
        )

    def req(self, obj: dict) -> dict:
        self.p.stdin.write(json.dumps(obj) + "\n")
        self.p.stdin.flush()
        return json.loads(self.p.stdout.readline())

    def close(self):
        try:
            self.p.stdin.write(json.dumps({"op": "close"}) + "\n")
            self.p.stdin.flush()
            self.p.wait(timeout=2)
        except Exception:
            self.p.kill()


def state_after(seed: str, actions: list[int]) -> list[str]:
    """Return the hash stream produced by a fresh harness for a fixed script."""
    h = RawHarness()
    stream = [h.req({"op": "create", "seed": seed})["stateHash"]]
    for a in actions:
        stream.append(h.req({"op": "act", "action_id": a})["stateHash"])
    h.close()
    return stream


def main() -> int:
    print("SPIKE — Foraging Run raw JSON-lines protocol\n")
    gate = GateRunner()
    h = RawHarness()

    # create
    created = h.req({"op": "create", "seed": "spike"})
    gate.ck("create returns ok", created.get("ok") is True)
    st = created.get("state", {})
    gate.ck("initial state has all expected keys",
            all(k in st for k in ("day", "hp", "supplies", "coins", "location",
                                  "rng_counter", "won", "lost")),
            f"keys={sorted(st)}")
    gate.ck("create is non-terminal", created.get("terminated") is False)
    gate.ck("create exposes a legal-action list", isinstance(created.get("legal"), list)
            and len(created["legal"]) > 0)
    gate.ck("create exposes a stateHash", bool(created.get("stateHash")))

    # act — a real state change advances the hash
    h0 = created["stateHash"]
    acted = h.req({"op": "act", "action_id": 1})  # forage
    gate.ck("act(forage) returns ok", acted.get("ok") is True)
    gate.ck("act echoes the action name", acted.get("result", {}).get("action") == "forage",
            f"result={acted.get('result')}")
    gate.ck("a real change advances the stateHash", acted.get("stateHash") != h0)
    gate.ck("act reports terminated/truncated flags",
            "terminated" in acted and "truncated" in acted)

    # bad inputs are refused, not crashed (refusal != inertness)
    bad = h.req({"op": "act", "action_id": 99})
    gate.ck("illegal action_id is refused with ok:false", bad.get("ok") is False,
            f"resp={bad}")
    unk = h.req({"op": "frobnicate"})
    gate.ck("unknown op is refused with ok:false", unk.get("ok") is False)
    h.close()

    # protocol-level determinism: same seed + same script → identical hash stream
    script = [1, 1, 3, 5, 2, 3, 5]
    a = state_after("det", script)
    b = state_after("det", script)
    gate.ck("same-seed replay is byte-identical at protocol level", a == b,
            f"len={len(a)}")
    c = state_after("different", script)
    gate.ck("a different seed produces a different stream", a != c)

    return gate.finish("SPIKE", "Raw protocol round-trips; safe to build the adapter on it.")


if __name__ == "__main__":
    sys.exit(main())
