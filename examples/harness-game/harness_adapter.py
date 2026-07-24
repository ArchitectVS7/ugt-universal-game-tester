"""
HarnessAdapter — a transport-only BaseAdapter for the Foraging Run harness.

This is the whole point of the example. Compare it to the retired anti-pattern it
replaces (a bridge that grew its own copy of the game's rules): there is NOT ONE
game rule in this file. It spawns harness.py, writes a JSON request, reads a JSON
response, and hands the state straight back. Foraging, travel, win/loss — all of
it lives in engine.py, reached only over the wire. That is UGT rule M1 in code.

It implements the BaseAdapter contract the whole framework speaks:
`connect` / `reset` / `step` / `close`, plus `_read_state` so the ExploitHunter
can recover after a crash. `reset()` derives a per-episode seed so the hunter's
bare `reset()` between episodes yields distinct runs, while a same-seed re-run of
a given episode reproduces it byte-for-byte (see reset() docstring).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

from ugt.adapters.base import BaseAdapter

from engine import ACTIONS

_HERE = os.path.dirname(os.path.abspath(__file__))
_HARNESS = os.path.join(_HERE, "harness.py")


class HarnessAdapter(BaseAdapter):
    def __init__(self, config: dict | None = None, seed: str = "0"):
        super().__init__(config or {})
        self.seed = str(seed)
        self.python_bin = sys.executable
        self.process: subprocess.Popen | None = None
        self._reset_count = 0
        self._last_state: dict = {}
        self._hash_stream: list[str] = []

    # ── lifecycle ────────────────────────────────────────────────────────────
    def connect(self) -> dict:
        """Spawn the harness process and confirm it is alive."""
        try:
            self.process = subprocess.Popen(
                [self.python_bin, _HARNESS],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,            # line-buffered
                cwd=_HERE,            # so harness.py's `import engine` resolves
                env=os.environ.copy(),
            )
        except Exception as exc:
            raise RuntimeError(f"failed to spawn harness {_HARNESS!r}: {exc}") from exc

        if self.process.poll() is not None:
            err = (self.process.stderr.read() if self.process.stderr else "") or "<empty>"
            raise RuntimeError(f"harness exited immediately ({self.process.returncode}); stderr: {err}")
        return {"pid": self.process.pid}

    def reset(self, seed=None) -> dict:
        """Create a fresh run and return its initial state.

        A BARE reset() (no seed) derives a distinct per-episode seed
        "<self.seed>#<n>" from a reset counter, because ExploitHunter.run() resets
        with no arguments between episodes — a fixed seed there would replay the
        SAME run every episode. This stays fully deterministic: a fresh adapter
        always starts at n=0, so a same-seed re-run of episode k reproduces it
        byte-for-byte.
        """
        if self.process is None or self.process.poll() is not None:
            self.connect()

        seed_str = str(seed) if seed is not None else f"{self.seed}#{self._reset_count}"
        self._reset_count += 1

        resp = self._request({"op": "create", "seed": seed_str, "config": {}})
        if not resp.get("ok"):
            raise RuntimeError(f"harness create failed: {resp!r}")
        self._last_state = resp["state"]
        self._hash_stream = [resp["stateHash"]]
        return self._last_state

    def step(self, action_id):
        """Send one action over the wire; return (state, terminated, truncated, info)."""
        resp = self._request({"op": "act", "action_id": int(action_id)})
        if not resp.get("ok"):
            # A harness-level rejection is DATA, not a crash — surface it in info.
            after = self._last_state
            return after, after.get("won") or after.get("lost"), False, {
                "command": "act", "action": None, "error": resp.get("error"),
                "result": {"ok": False}, "stateHash": self._hash_stream[-1],
            }

        after = resp["state"]
        self._last_state = after
        self._hash_stream.append(resp["stateHash"])
        info = {
            "command": "act",
            "action": ACTIONS.get(int(action_id)),
            "result": resp.get("result", {"ok": True}),
            "stateHash": resp["stateHash"],
            "legal": resp.get("legal", []),
        }
        return after, bool(resp["terminated"]), bool(resp.get("truncated", False)), info

    def close(self) -> None:
        if self.process is None:
            return
        try:
            if self.process.stdin:
                try:
                    self._write({"op": "close"})
                except Exception:
                    pass
                self.process.stdin.close()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
        finally:
            self.process = None

    # ── helpers ──────────────────────────────────────────────────────────────
    def _read_state(self) -> dict:
        """Last known state — used by ExploitHunter to recover after a crash."""
        return self._last_state

    @property
    def hash_stream(self) -> list[str]:
        """Per-step replay hashes since the last reset (R3 determinism compare)."""
        return list(self._hash_stream)

    @staticmethod
    def action_name(action_id: int) -> str:
        return ACTIONS.get(int(action_id), str(action_id))

    def _write(self, obj: dict) -> None:
        assert self.process and self.process.stdin
        self.process.stdin.write(json.dumps(obj, separators=(",", ":")) + "\n")
        self.process.stdin.flush()

    def _request(self, obj: dict) -> dict:
        if self.process is None or self.process.poll() is not None:
            raise RuntimeError("harness process is not running")
        self._write(obj)
        line = self.process.stdout.readline() if self.process.stdout else ""
        if not line:
            err = (self.process.stderr.read() if self.process.stderr else "") or "<empty>"
            raise RuntimeError(f"harness produced no response; stderr: {err}")
        return json.loads(line)
