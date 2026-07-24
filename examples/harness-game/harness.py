#!/usr/bin/env python3
"""
JSON-lines harness around the Foraging Run engine.

This is the "engine-first subprocess contract" the recent UGT integrations use:
the game engine runs in its own process and speaks newline-delimited JSON on
stdin/stdout. The Python adapter (harness_adapter.py) spawns THIS file and talks
to it exactly the way the real harness adapters spawn a Node or Godot process.

Protocol (one JSON object per line, one response per request):

  → {"op": "create", "seed": "s", "config": {...}}
  ← {"ok": true, "state": {...}, "stateHash": "…", "legal": [ids], "terminated": false}

  → {"op": "act", "action_id": 3}
  ← {"ok": true, "state": {...}, "terminated": bool, "truncated": false,
     "stateHash": "…", "legal": [ids], "result": {"ok": true, "action": "travel"}}

  → {"op": "close"}    (process exits 0)

Discipline that keeps the wire honest (UGT rule O2 / the "test over the wire"
lesson M8): stdout carries ONLY protocol JSON — every diagnostic goes to stderr —
and each response is flushed immediately so the caller never blocks. The engine,
not the harness, owns all rules; this file only marshals JSON to and from it.
"""
from __future__ import annotations

import json
import sys

from engine import ACTIONS, ForagingRun


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _view(game: ForagingRun, result: dict | None = None) -> dict:
    return {
        "ok": True,
        "state": game.snapshot(),
        "terminated": game.terminated(),
        "truncated": False,
        "stateHash": game.state_hash(),
        "legal": game.legal_actions(),
        "result": result or {"ok": True},
    }


def main() -> int:
    game: ForagingRun | None = None

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as exc:
            _emit({"ok": False, "error": f"bad JSON: {exc}"})
            continue

        op = msg.get("op")

        if op == "create":
            game = ForagingRun(seed=str(msg.get("seed", "0")))
            _emit(_view(game))

        elif op == "act":
            if game is None:
                _emit({"ok": False, "error": "act before create"})
                continue
            action_id = msg.get("action_id")
            if not isinstance(action_id, int) or action_id not in ACTIONS:
                _emit({"ok": False, "error": f"illegal action_id {action_id!r}"})
                continue
            game.act(action_id)
            _emit(_view(game, result={"ok": True, "action": ACTIONS[action_id]}))

        elif op == "close":
            return 0

        else:
            _emit({"ok": False, "error": f"unknown op {op!r}"})

    return 0


if __name__ == "__main__":
    sys.exit(main())
