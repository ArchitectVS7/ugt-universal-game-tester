"""GodotTcpAdapter — transport only, for a headless Godot game over a TCP socket.

Constructed directly by this integration's ladder scripts, NOT dispatched by
`ugt/core/env.py` (its `ugt.config.yaml` declares `engine.type: custom`) — which
is the contract for engines no built-in adapter fits.

**This file contains no game rules.** It opens a socket, writes a JSON line,
reads a JSON line, and hands back what the game said. Whether a move is legal,
whether a box can be pushed, when a level is solved — all of that lives in
`../game/scripts/board.gd` and is never mirrored, cached, or second-guessed
here. That discipline is the whole point (UGT rule M1): an adapter that starts
deciding outcomes stops testing the game and starts testing itself.

Lifecycle is owned, not assumed: `connect()` spawns the bridge via
`bridge_process.bridge()` and `close()` reaps it, so no rung needs a human to
start a server first.
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

from bridge_process import bridge, connect_with_retry  # noqa: E402
from ugt.adapters.base import BaseAdapter  # noqa: E402

HOST = "127.0.0.1"


class GodotTcpAdapter(BaseAdapter):
    def __init__(self, config=None, port: int | None = None, timeout: float = 20.0):
        super().__init__(config)
        self._requested_port = port
        self.timeout = timeout
        self._ctx = None
        self.port: int | None = None
        self.sock: socket.socket | None = None
        self._buf = b""
        self._screen: list = []

    # ── lifecycle ────────────────────────────────────────────────────────────

    def connect(self):
        if self.sock is not None:
            return
        self._ctx = bridge(port=self._requested_port)
        self.port = self._ctx.__enter__()
        # connect_with_retry, not a bare create_connection: the bridge serves one
        # client at a time, so the first dial can land before it is accepting.
        self.sock = connect_with_retry(self.port, timeout=self.timeout)
        self._buf = b""

    def close(self):
        if self.sock is not None:
            try:
                # Best-effort polite hangup; the bridge answers `close` with EOF.
                self._send({"command": "close"})
            except OSError:
                pass
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None
        if self._ctx is not None:
            try:
                self._ctx.__exit__(None, None, None)
            finally:
                self._ctx = None
                self.port = None

    # ── wire ─────────────────────────────────────────────────────────────────

    def _send(self, obj: dict) -> None:
        if self.sock is None:
            raise RuntimeError("adapter is not connected — call connect() first")
        self.sock.sendall((json.dumps(obj) + "\n").encode())

    def _recv(self) -> dict:
        # TCP has no message framing: a read may return a partial message or
        # several. Buffer until a newline rather than assuming recv == message.
        assert self.sock is not None
        while b"\n" not in self._buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("bridge closed the connection mid-message")
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        return json.loads(line.decode())

    def _request(self, obj: dict) -> dict:
        self._send(obj)
        return self._recv()

    # ── BaseAdapter ──────────────────────────────────────────────────────────

    def reset(self):
        if self.sock is None:
            self.connect()
        reply = self._request({"command": "reset"})
        if "state" not in reply:
            raise RuntimeError(f"reset: bridge replied without a state: {reply!r}")
        self._remember_screen(reply["state"])
        return reply["state"]

    def step(self, action_id):
        if self.sock is None:
            raise RuntimeError("step() called before connect()")
        reply = self._request({"command": "step", "action_id": int(action_id)})
        if "state" not in reply:
            raise RuntimeError(f"step({action_id}): bridge replied without a state: {reply!r}")
        self._remember_screen(reply["state"])
        return (
            reply["state"],
            bool(reply.get("terminated", False)),
            bool(reply.get("truncated", False)),
            reply.get("info", {}) or {},
        )

    # ── the screen, for UI-driving tiers (playtest) ───────────────────────────

    def _remember_screen(self, state) -> None:
        """Keep the last `grid` the GAME sent, verbatim.

        Storing a reply is not modelling the game: nothing here is derived,
        merged or recomputed, and if the bridge stops sending `grid` this goes
        back to empty rather than reconstructing a board from the scalars.
        """
        rows = state.get("grid") if isinstance(state, dict) else None
        self._screen = list(rows) if isinstance(rows, list) else []

    def get_terminal_text(self, chars: int = 600) -> str:
        """The board as a player sees it — the game's own row render, joined.

        `board.gd::render_rows()` draws these rows and `main.gd` paints exactly
        them for the human; the only thing that happens here is `"\\n".join`, so
        the machine player reads the same screen rather than a projection of it.

        The game emits no prose anywhere — `main.tscn` is ColorRects with no
        Label, no font and no message line — so this board IS the entire
        player-facing text channel. An empty return means the wire stopped
        sending `grid`, which is a defect, not a quiet genre difference; the
        playtest driver asserts the channel is live and non-vacuous before a run.
        """
        text = "\n".join(self._screen)
        return text[-chars:] if chars and chars > 0 else text

    # ── crash-recovery hook used by InvariantFuzzer ────────────────────────────

    def _read_state(self) -> dict:
        """Re-read state without applying an action.

        The hunter calls this to recover after a step raises. There is no
        read-only opcode in the protocol, so this issues a deliberately
        out-of-range action_id — which the bridge treats as a no-op that still
        returns current state (proven inert by the spike, and asserted again by
        R2's no-op checks). It is a read, not a rule.
        """
        reply = self._request({"command": "step", "action_id": -1})
        return reply.get("state", {})
