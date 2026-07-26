#!/usr/bin/env python3
"""Rung 1 (spike) — the raw JSON-lines protocol, with no UGT adapter involved.

    python3 examples/escape-room/integration/spike_escape_room.py

Spawns `node ../game/src/bridge.js` and talks to its stdin/stdout directly. The
point is to pin down what the game ACTUALLY does on the wire before anything is
built on top of it.

Two of this bridge's known defects live at exactly this layer and are invisible
to every tier above it (the game's own T-006 notes record both):

  * readline emits every line already buffered from a single write, so lines
    after `close` were still being answered until a `closed` latch was added;
  * closing the readline interface does NOT end the process while the parent's
    stdin pipe stays open — which is exactly how `SubprocessAdapter` runs it.
    Its `close()` then does a blocking, un-timed read, so every UGT run would
    have wedged forever.

Both are regression-checked below, and the second is checked the way the bug
actually happened: our stdin pipe is deliberately left OPEN.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
for _p in (HERE, REPO):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ugt.core.trial import GateRunner  # noqa: E402

BRIDGE = os.path.abspath(os.path.join(HERE, "..", "game", "src", "bridge.js"))
CONFIG = os.path.join(HERE, "ugt.config.yaml")

# The PRD's state shape — exactly these six keys, no more.
STATE_KEYS = {"current_room", "inventory", "flags",
              "moves_taken", "rooms_visited", "escaped"}

gate = GateRunner()


def check(ok: bool, label: str, detail: str = "") -> bool:
    """Adapter to GateRunner's (name, ok, detail) order, so call sites read naturally."""
    return gate.ck(label, ok, detail)


class Wire:
    """Newline-delimited JSON over the child's stdin/stdout pipes.

    Reads are done on a background thread with a deadline, because the failure
    mode this spike exists to catch is a HANG — and a hang asserted with a
    blocking read is a test that never reports.
    """

    def __init__(self) -> None:
        self.proc = subprocess.Popen(
            ["node", BRIDGE],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )

    def send_raw(self, text: str) -> None:
        self.proc.stdin.write(text)
        self.proc.stdin.flush()

    def send(self, obj: dict) -> None:
        self.send_raw(json.dumps(obj) + "\n")

    def readline(self, timeout: float = 10.0):
        """One line, or None on timeout/EOF. Never blocks past `timeout`."""
        box: list = []

        def pull():
            box.append(self.proc.stdout.readline())

        t = threading.Thread(target=pull, daemon=True)
        t.start()
        t.join(timeout)
        if t.is_alive():
            return None            # hung
        line = box[0] if box else ""
        return None if line == "" else line   # "" is EOF

    def recv(self, timeout: float = 10.0):
        line = self.readline(timeout)
        return None if line is None else json.loads(line)

    def kill(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
        try:
            self.proc.stdin.close()
        except OSError:
            pass


def main() -> int:
    print("Escape Room spike — raw JSON-lines against the real bridge\n")

    if not os.path.exists(BRIDGE):
        print(f"  bridge not found: {BRIDGE}")
        return 2

    # ── the action table the config is generated from ────────────────────────
    print("  -- action table (`--actions`) --")
    dump = subprocess.run(["node", BRIDGE, "--actions"],
                          capture_output=True, text=True, timeout=30)
    check(dump.returncode == 0, "`--actions` exits 0", f"rc={dump.returncode}")
    try:
        table = json.loads(dump.stdout)
    except json.JSONDecodeError as exc:
        table = []
        check(False, "`--actions` emits parseable JSON", str(exc))
    check(isinstance(table, list) and len(table) > 0,
          "`--actions` emits a non-empty list", f"{len(table)} actions")

    # The config claims to be GENERATED from this table. If it has drifted, every
    # rung above this one is testing the wrong ids under the right names.
    import yaml
    cfg = yaml.safe_load(open(CONFIG))
    declared = {int(k): v["name"] for k, v in cfg["action_space"]["actions"].items()}

    # The table names itself — `{verb, arg, name}` per entry. Compare against the
    # game's own `name`, never against a name this script reconstructs: a
    # reconstruction that drifts from the game would fail this check for the
    # wrong reason (it did, on the first run of this spike).
    actual = {i: e["name"] for i, e in enumerate(table)}
    check(declared == actual,
          "ugt.config.yaml's 41 ids match the game's own action table exactly",
          f"declared {len(declared)}, actual {len(actual)}"
          + ("" if declared == actual else
             f"; first mismatch at {next(i for i in sorted(set(declared) | set(actual)) if declared.get(i) != actual.get(i))}"))
    check(cfg["action_space"]["size"] == len(table),
          "the declared action_space size matches the table length",
          f"size={cfg['action_space']['size']} table={len(table)}")

    w = Wire()
    try:
        # ── reset ────────────────────────────────────────────────────────────
        print("\n  -- reset --")
        w.send({"command": "reset"})
        r = w.recv()
        check(isinstance(r, dict) and set(r) == {"state"},
              "reset returns exactly {'state': {...}}",
              f"keys={sorted(r) if isinstance(r, dict) else r}")
        s0 = (r or {}).get("state", {})
        check(set(s0) == STATE_KEYS, "state carries exactly the PRD's 6 keys",
              f"missing={sorted(STATE_KEYS - set(s0))} extra={sorted(set(s0) - STATE_KEYS)}")
        check(s0.get("moves_taken") == 0 and s0.get("escaped") is False,
              "a fresh reset starts at 0 moves, not escaped",
              f"moves={s0.get('moves_taken')} escaped={s0.get('escaped')}")
        check(isinstance(s0.get("flags"), dict) and len(s0["flags"]) > 0,
              "the flag universe is present from the first state (stable key set)",
              f"{len(s0.get('flags') or {})} flags")
        check(all(v is False for v in (s0.get("flags") or {}).values()),
              "every flag starts False")

        # ── step ─────────────────────────────────────────────────────────────
        print("\n  -- step --")
        w.send({"command": "step", "action_id": 0})   # go_north — a real move
        r = w.recv()
        check(isinstance(r, dict) and set(r) == {"state", "terminated", "truncated", "info"},
              "step returns the PRD's 4-key envelope",
              f"keys={sorted(r) if isinstance(r, dict) else r}")
        check(isinstance(r.get("terminated"), bool) and isinstance(r.get("truncated"), bool),
              "terminated/truncated are booleans")
        check(r.get("info") == {}, "info is exactly {}", f"info={r.get('info')}")
        check(r["state"]["moves_taken"] == 1 and r["state"]["current_room"] != s0["current_room"],
              "a legal move advances moves_taken and changes room",
              f"{s0['current_room']} -> {r['state']['current_room']}")

        # ── refusals are completely inert ────────────────────────────────────
        # This is the contract dice's spike found the other two games diverge on:
        # escape-room returns state unchanged where dice throws a RangeError.
        print("\n  -- invalid action ids are inert --")
        before = r["state"]
        bad_ids = [-1, 41, 999, None, "north", 1.5, True]
        inert, offender = True, None
        for bad in bad_ids:
            w.send({"command": "step", "action_id": bad})
            got = w.recv()
            if got is None or got.get("state") != before:
                inert, offender = False, bad
                break
        check(inert, f"all {len(bad_ids)} invalid action_ids leave state byte-identical",
              f"tried {bad_ids}" if inert else f"first offender: {offender!r}")

        w.send({"command": "step"})   # action_id missing entirely
        got = w.recv()
        check(got is not None and got.get("state") == before,
              "a step with NO action_id is inert rather than a crash")

        # An in-context refusal is the engine's, and consumes nothing at all —
        # not even moves_taken. The feature map's F1/F5 assertions rest on this.
        w.send({"command": "step", "action_id": 39})   # use_key_skeleton, not held
        got = w.recv()
        check(got is not None and got.get("state") == before,
              "an in-fiction refusal consumes NOTHING, not even moves_taken",
              f"moves stayed {before['moves_taken']}")

        # ── protocol robustness ──────────────────────────────────────────────
        print("\n  -- protocol robustness --")
        w.send({"command": "nonsense"})
        r_bad = w.recv()
        check(isinstance(r_bad, dict) and "error" in r_bad and "state" not in r_bad,
              "an unknown command answers {'error': ...} with NO state key",
              f"keys={sorted(r_bad) if isinstance(r_bad, dict) else r_bad}")

        w.send_raw("\n   \n")                      # blank lines
        w.send({"command": "step", "action_id": 4})  # look
        r_after_blank = w.recv()
        check(r_after_blank is not None and "state" in r_after_blank,
              "blank lines are skipped, not answered (no phantom reply)")

        w.send_raw("{not json at all}\n")
        w.send({"command": "step", "action_id": 4})
        r_after_garbage = w.recv()
        check(r_after_garbage is not None and "state" in r_after_garbage,
              "garbage is reported on stderr and does NOT desync the stdout stream")

        # ── framing: two messages in ONE write ───────────────────────────────
        print("\n  -- framing --")
        two = (json.dumps({"command": "step", "action_id": 4}) + "\n"
               + json.dumps({"command": "step", "action_id": 5}) + "\n")
        w.send_raw(two)
        a1, a2 = w.recv(), w.recv()
        check(a1 is not None and a2 is not None and "state" in a1 and "state" in a2,
              "two messages in a single write get two separate replies")

        # One message split across two writes.
        msg = json.dumps({"command": "step", "action_id": 4}) + "\n"
        w.send_raw(msg[:9])
        w.send_raw(msg[9:])
        r_split = w.recv()
        check(r_split is not None and "state" in r_split,
              "a message split across two writes still parses")

        # ── determinism ──────────────────────────────────────────────────────
        print("\n  -- determinism --")
        seq = [0, 4, 2, 14, 5]
        w.send({"command": "reset"})
        base = w.recv()["state"]
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
        check(base == again, "reset mid-session returns to an identical start state")
        check(first == second, "the same sequence after reset replays identically",
              f"{len(seq)} steps compared")
        distinct = len({json.dumps(s, sort_keys=True) for s in first})
        check(distinct > 1, "the determinism proof is NON-VACUOUS (state actually moved)",
              f"{distinct} distinct states over {len(first)} steps")
    finally:
        pass

    # ── close: the two regressions ───────────────────────────────────────────
    # Deliberately on a FRESH process, and our stdin pipe is left OPEN, because
    # that is the exact condition under which the wedge bug appeared.
    print("\n  -- close (regression: must not wedge) --")
    w.kill()
    w2 = Wire()
    try:
        w2.send({"command": "reset"})
        w2.recv()
        # Both lines in ONE write: `close` first, then a step that must be ignored.
        w2.send_raw(json.dumps({"command": "close"}) + "\n"
                    + json.dumps({"command": "step", "action_id": 0}) + "\n")
        trailing = w2.readline(timeout=10)
        check(trailing is None,
              "close writes no reply and the line buffered after it is NOT answered",
              "EOF" if trailing is None else f"got {trailing!r}")
        try:
            rc = w2.proc.wait(timeout=10)
            exited = True
        except subprocess.TimeoutExpired:
            rc, exited = None, False
        check(exited, "the process EXITS on close while the parent's stdin stays open",
              f"exit code {rc}" if exited else "STILL RUNNING after 10s — the wedge is back")
        check(rc == 0, "close exits cleanly (code 0)", f"rc={rc}")
    finally:
        w2.kill()

    return gate.finish(
        "SPIKE",
        "The raw bridge contract holds: exact message shapes, inert refusals, robust framing, "
        "deterministic replay, and a close that neither answers nor wedges. Safe to build on.")


if __name__ == "__main__":
    sys.exit(main())
