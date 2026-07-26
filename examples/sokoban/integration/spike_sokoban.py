#!/usr/bin/env python3
"""Rung 1 — raw TCP protocol round-trip against the real headless Godot bridge.

    python3 examples/sokoban/integration/spike_sokoban.py

No adapter class: this proves the wire itself before anything is built on it.
It spawns its own bridge and reaps it, so it runs on a cold machine with no
Godot already going — and it refuses to attach to a port that was already open,
because a green run against a stale build is worse than a red one.
"""
from __future__ import annotations

import json
import os
import socket
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
for _p in (HERE, REPO):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ugt.core.trial import GateRunner  # noqa: E402
from bridge_process import bridge, connect_with_retry, listening_pid  # noqa: E402

STATE_KEYS = {
    "level_index", "player_x", "player_y", "boxes_on_target",
    "boxes_total", "moves_taken", "level_solved", "all_levels_solved",
    "grid",
}

gate = GateRunner()


def check(ok: bool, label: str, detail: str = "") -> bool:
    """Adapter to GateRunner's (name, ok, detail) order, so call sites read naturally."""
    return gate.ck(label, ok, detail)


class Wire:
    """Newline-delimited JSON over a socket, with its own read buffer.

    The buffer matters: TCP gives no message framing, so one recv can carry half
    a message or two whole ones. Anything that assumes recv==message works right
    up until it doesn't.
    """

    def __init__(self, port: int) -> None:
        # One connection, retried on refusal — the bridge serves a single client,
        # so nothing here may dial the port speculatively.
        self.sock = connect_with_retry(port, timeout=15)
        self.buf = b""

    def send(self, obj: dict) -> None:
        self.sock.sendall((json.dumps(obj) + "\n").encode())

    def recv(self) -> dict:
        while b"\n" not in self.buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("bridge closed the connection mid-message")
            self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        return json.loads(line.decode())

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def main() -> int:
    print("Sokoban spike — raw TCP against the real bridge\n")
    print("  -- lifecycle --")

    with bridge() as port:
        spawned_pid = listening_pid(port)
        check(bool(spawned_pid), "the bridge we spawned is the process listening",
              f"port {port}, pid {spawned_pid or 'unknown'}")

        w = Wire(port)
        try:
            print("\n  -- reset --")
            w.send({"command": "reset"})
            r = w.recv()
            check(isinstance(r, dict) and set(r) == {"state"},
                  "reset returns exactly {'state': {...}}", f"keys={sorted(r)}")
            s0 = r.get("state", {})
            check(set(s0) == STATE_KEYS, "state carries exactly the PRD's 9 keys",
                  f"missing={sorted(STATE_KEYS - set(s0))} extra={sorted(set(s0) - STATE_KEYS)}")
            check(s0.get("moves_taken") == 0 and s0.get("level_index") == 0,
                  "a fresh reset starts at level 0 with 0 moves",
                  f"level_index={s0.get('level_index')} moves_taken={s0.get('moves_taken')}")
            check(s0.get("boxes_total", 0) > 0, "level 1 actually has boxes",
                  f"boxes_total={s0.get('boxes_total')}")

            grid = s0.get("grid")
            check(isinstance(grid, list) and grid
                  and all(isinstance(row, str) for row in grid),
                  "grid is a non-empty list of row strings",
                  f"{len(grid) if isinstance(grid, list) else 'n/a'} rows")
            if isinstance(grid, list):
                marks = sum(row.count("@") + row.count("+") for row in grid if isinstance(row, str))
                check(marks == 1, "the grid shows exactly one player marker",
                      f"found {marks}")

            print("\n  -- step --")
            w.send({"command": "step", "action_id": 0})
            r = w.recv()
            check(set(r) == {"state", "terminated", "truncated", "info"},
                  "step returns the PRD's 4-key envelope", f"keys={sorted(r)}")
            check(isinstance(r.get("terminated"), bool) and isinstance(r.get("truncated"), bool),
                  "terminated/truncated are booleans")

            print("\n  -- refusals are inert --")
            w.send({"command": "step", "action_id": 99})
            before = r["state"]
            after = w.recv()["state"]
            check(after == before, "an out-of-range action_id changes nothing at all",
                  f"moves {before['moves_taken']} -> {after['moves_taken']}")

            w.send({"command": "nonsense"})
            r_bad = w.recv()
            check(isinstance(r_bad, dict) and r_bad != {},
                  "an unknown command still gets an answer (never a hang)",
                  f"keys={sorted(r_bad)}")

            print("\n  -- reload (action 4) --")
            w.send({"command": "step", "action_id": 4})
            r_reload = w.recv()
            check(set(r_reload) == {"state", "terminated", "truncated", "info"},
                  "reload is an ordinary step reply, not a special shape",
                  f"keys={sorted(r_reload)}")
            check(r_reload.get("state") == s0,
                  "action 4 rewinds to the exact level-start state",
                  f"moves_taken back to {r_reload.get('state', {}).get('moves_taken')}")

            print("\n  -- framing --")
            # One message, deliberately split across two writes: the bridge must
            # buffer across polls rather than assume one read is one message.
            msg = json.dumps({"command": "step", "action_id": 1}) + "\n"
            w.sock.sendall(msg[:6].encode())
            import time as _t
            _t.sleep(0.25)
            w.sock.sendall(msg[6:].encode())
            r_split = w.recv()
            check("state" in r_split, "a message split across two writes still parses",
                  f"keys={sorted(r_split)}")

            print("\n  -- determinism --")
            w.send({"command": "reset"})
            base = w.recv()["state"]
            seq = [2, 0, 2, 0]
            first = []
            for a in seq:
                w.send({"command": "step", "action_id": a})
                first.append(w.recv()["state"])
            w.send({"command": "reset"})
            again = w.recv()["state"]
            second = []
            for a in seq:
                w.send({"command": "step", "action_id": a})
                second.append(w.recv()["state"])
            check(base == again, "reset returns to an identical starting state")
            check(first == second, "same actions after reset replay identically",
                  f"{len(seq)} steps compared")
            check(len({json.dumps(s, sort_keys=True) for s in first}) > 1,
                  "the determinism proof is NON-VACUOUS (state actually moved)",
                  f"{len({json.dumps(s, sort_keys=True) for s in first})} distinct states")

            print("\n  -- close --")
            w.send({"command": "close"})
            w.sock.settimeout(10)
            try:
                trailing = w.sock.recv(4096)
            except socket.timeout:
                trailing = b"<timeout>"
            check(trailing == b"", "close hangs up with no reply (EOF)",
                  f"got {trailing!r}")
        finally:
            w.close()

    return gate.finish("SPIKE", "The raw bridge contract holds: exact message shapes, inert refusals, cross-write framing, "
        "and deterministic replay. Safe to build the adapter on it.")


if __name__ == "__main__":
    sys.exit(main())
