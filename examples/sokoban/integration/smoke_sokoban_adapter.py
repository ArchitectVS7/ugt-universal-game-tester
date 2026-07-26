#!/usr/bin/env python3
"""Rung 2 — the same round-trip as the spike, but through the BaseAdapter contract.

    python3 examples/sokoban/integration/smoke_sokoban_adapter.py

The spike proved the wire. This proves `GodotTcpAdapter` honours
connect/reset/step/close and cleans up after itself.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from bridge_process import port_is_open  # noqa: E402
from godot_tcp_adapter import GodotTcpAdapter  # noqa: E402

STATE_KEYS = {
    "level_index", "player_x", "player_y", "boxes_on_target",
    "boxes_total", "moves_taken", "level_solved", "all_levels_solved",
}

checks: list[tuple[bool, str, str]] = []


def check(ok, label, detail=""):
    checks.append((bool(ok), label, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  — {detail}" if detail else ""))


def main() -> int:
    print("Sokoban smoke — the BaseAdapter contract\n")

    ad = GodotTcpAdapter()
    ad.connect()
    port = ad.port
    check(port is not None and port_is_open(port),
          "connect() spawns a live bridge and connects", f"port={port}")

    s = ad.reset()
    check(isinstance(s, dict) and set(s) == STATE_KEYS,
          "reset() returns the normalized 8-key state dict",
          f"level_index={s.get('level_index')} boxes={s.get('boxes_on_target')}/{s.get('boxes_total')}")

    shapes_ok, moved = True, False
    prev = s
    for a in (0, 1, 2, 3, 2, 0):
        out = ad.step(a)
        if not (isinstance(out, tuple) and len(out) == 4
                and isinstance(out[0], dict) and isinstance(out[1], bool)
                and isinstance(out[2], bool) and isinstance(out[3], dict)):
            shapes_ok = False
            break
        if out[0] != prev:
            moved = True
        prev = out[0]
    check(shapes_ok, "6 step() calls each return (dict, bool, bool, dict)")
    check(moved, "at least one step actually changed state (not a dead wire)",
          f"moves_taken={prev.get('moves_taken')}")

    rs = ad._read_state()
    check(isinstance(rs, dict) and set(rs) == STATE_KEYS,
          "_read_state() returns state without applying an action (hunter recovery hook)",
          f"moves_taken={rs.get('moves_taken')}")

    s2 = ad.reset()
    check(s2["moves_taken"] == 0 and s2["level_index"] == 0,
          "reset() mid-session returns to a fresh level 0")

    ad.close()
    check(ad.sock is None and ad.port is None, "close() clears adapter state")
    check(not port_is_open(port), "close() reaped the bridge — the port is free again",
          f"port={port}")

    # Connecting a second time must work: the ladder builds one adapter per rung.
    ad2 = GodotTcpAdapter()
    ad2.connect()
    ok2 = isinstance(ad2.reset(), dict)
    p2 = ad2.port
    ad2.close()
    check(ok2 and not port_is_open(p2),
          "a second adapter can connect and clean up independently", f"port={p2}")

    passed = sum(1 for ok, _, _ in checks if ok)
    total = len(checks)
    print("\n" + "=" * 70)
    if passed == total:
        print(f"SMOKE MET — {passed}/{total} checks. GodotTcpAdapter honours the BaseAdapter "
              f"contract and owns the bridge's lifecycle cleanly.")
        return 0
    print(f"SMOKE NOT MET — {passed}/{total} checks.")
    for ok, label, detail in checks:
        if not ok:
            print(f"  FAILED: {label}  {detail}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
