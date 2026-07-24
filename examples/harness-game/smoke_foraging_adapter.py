#!/usr/bin/env python3
"""
Ladder rung 2 — SMOKE. The same round-trip as the spike, but through UGT's
BaseAdapter contract (connect / reset / step / close) instead of the raw wire.

Run from the repo root:
    python3 examples/harness-game/smoke_foraging_adapter.py
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..")))

from ugt.core.trial import GateRunner  # noqa: E402
from harness_adapter import HarnessAdapter  # noqa: E402


def main() -> int:
    print("SMOKE — Foraging Run through BaseAdapter\n")
    gate = GateRunner()
    adapter = HarnessAdapter(seed="smoke")

    pid = adapter.connect()
    gate.ck("connect() returns a live pid", isinstance(pid, dict) and "pid" in pid)

    st = adapter.reset()
    gate.ck("reset() returns a state dict",
            isinstance(st, dict) and "hp" in st and "location" in st)
    gate.ck("reset() state is non-terminal", not (st["won"] or st["lost"]))
    gate.ck("reset() seeds a one-element hash stream", len(adapter.hash_stream) == 1)

    after, term, trunc, info = adapter.step(1)  # forage
    gate.ck("step() returns the (state, terminated, truncated, info) 4-tuple",
            isinstance(after, dict) and isinstance(term, bool)
            and isinstance(trunc, bool) and isinstance(info, dict))
    gate.ck("step info carries command/action/result/stateHash",
            all(k in info for k in ("command", "action", "result", "stateHash")),
            f"info keys={sorted(info)}")
    gate.ck("hash stream grew by one after a step", len(adapter.hash_stream) == 2)
    gate.ck("_read_state() returns the latest state (hunter recovery hook)",
            adapter._read_state() == after)

    # Per-episode seed wiring: a second bare reset must produce a DIFFERENT run
    # once randomness is exercised (the initial pre-roll state is identical).
    adapter.reset()
    _, _, _, info_a = adapter.step(1)
    adapter.reset()
    _, _, _, info_b = adapter.step(1)
    gate.ck("consecutive bare resets give distinct episodes (per-episode seed)",
            info_a["stateHash"] != info_b["stateHash"],
            f"{info_a['stateHash']} vs {info_b['stateHash']}")

    adapter.close()
    gate.ck("close() tears down cleanly", adapter.process is None)

    return gate.finish("SMOKE", "Adapter honors the BaseAdapter contract.")


if __name__ == "__main__":
    sys.exit(main())
