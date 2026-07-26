#!/usr/bin/env python3
"""End-to-end wire check for the Sokoban Mini UGT bridge (T-008).

WHAT THIS PROVES
================
The PRD's "Acceptance criteria" section, checked through the REAL TCP wire
rather than in-process:

  * all 3 bundled levels are solvable — the committed
    `levels/solutions.json` sequences are replayed as `step` commands and
    must drive the game to `all_levels_solved: true` (with `terminated`
    mirroring it, as the PRD requires);
  * "same level + same action sequence from `reset` reproduces identical
    state" — two `reset` + replay passes must produce BYTE-IDENTICAL
    response lines.

`tests/run_tests.gd` already covers the rules and the bridge's protocol
dispatch in-process. This script is the layer above that: a separate OS
process, a real socket, real JSON serialization. It is deliberately the same
shape as a UGT ladder run — connect to the game you did not compile, speak its
documented protocol, and assert its own acceptance criteria from the outside.
That is the whole point of the example, so this file is repo-tracked and
maintained, not a throwaway.

TWO CONTRACTS IT LEANS ON (read these before editing)
=====================================================
1. ONE `recv()` IS NOT ONE MESSAGE. The bridge buffers incoming bytes across
   `_process()` polls and splits on "\\n"; a correct client must do the mirror
   image on the way back. `BridgeClient.read_line()` below is that buffer.
   Never assume a single `recv()` returned exactly one complete reply.
2. LAZY LEVEL ADVANCE (`scripts/board.gd::try_move`). A solved level advances
   at the START of the next move, and that move is then applied in the NEW
   level. That is precisely what lets the three per-level sequences be
   concatenated with NO filler move between them — do not insert a spacer
   step, it would desynchronise every following action.

A third contract shapes the determinism phase: `reset_level()` KEEPS
`level_index`. A `reset` retries the level being played; it does not restart
the game. So after the acceptance replay the board sits on level 3, and this
script reads the level out of the `reset` reply rather than assuming level 0.

USAGE
=====
    python3 tools/tcp_smoke_check.py                # launch a bridge, check, shut it down
    python3 tools/tcp_smoke_check.py --attach       # use a bridge that is already running
    python3 tools/tcp_smoke_check.py --launch --port 18910
    GODOT=/path/to/godot python3 tools/tcp_smoke_check.py

Runnable from any working directory. Python standard library only — no pip
install, no network fetch, nothing vendored (the same "no third-party
dependency" discipline the GDScript test runner is held to).

EXIT CODES
==========
    0   every check passed
    1   a check FAILED (the game/bridge disagreed with the PRD)
    2   environment or usage problem (no bridge to attach to, no `godot4`,
        unusable `levels/solutions.json`, port already in use)
    3   unexpected internal error
    130 interrupted (Ctrl-C)

Failures are reported as one readable line on stderr, never a traceback. Pass
`--traceback` when you actually want the stack for debugging.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

# Resolved from this file, so the script works from any cwd (same ergonomics as
# the sibling tools/check_runner_reports_failure.sh).
PROJECT_DIR = Path(__file__).resolve().parent.parent
SOLUTIONS_PATH = PROJECT_DIR / "levels" / "solutions.json"

# Play order. The ACTIONS come from solutions.json; only the order is here.
LEVEL_NAMES = ("level_01", "level_02", "level_03")

# PRD "State shape" — asserted as a SET, so an added or renamed key is a
# failure rather than something a subset check would wave through.
STATE_KEYS = frozenset(
    {
        "level_index",
        "player_x",
        "player_y",
        "boxes_on_target",
        "boxes_total",
        "moves_taken",
        "level_solved",
        "all_levels_solved",
    }
)
STATE_INT_KEYS = frozenset(
    {"level_index", "player_x", "player_y", "boxes_on_target", "boxes_total", "moves_taken"}
)
STATE_BOOL_KEYS = frozenset({"level_solved", "all_levels_solved"})

# PRD: reset replies with the state ALONE; step adds exactly these three.
RESET_KEYS = frozenset({"state"})
STEP_KEYS = frozenset({"state", "terminated", "truncated", "info"})

# PRD "UGT hooks required". The bridge hardcodes the host.
HOST = "127.0.0.1"
DEFAULT_PORT = 8910

# `ugt_bridge.gd`'s READY_MESSAGE, minus the host/port it formats in. That
# constant is documented as stable FOR THIS SCRIPT — keep the two in sync.
READY_SUBSTRING = "UGT bridge listening on"

# Valid PRD action ids: 0=up, 1=down, 2=left, 3=right.
ACTION_IDS = frozenset({0, 1, 2, 3})

# The project path can contain spaces (it does, in this repo), so every command
# line printed for a human to copy is quoted.
QUOTED_PROJECT_DIR = shlex.quote(str(PROJECT_DIR))


class SmokeCheckError(Exception):
    """Environment / usage problem — exit 2. Not the game's fault."""


class CheckFailure(SmokeCheckError):
    """An assertion about the running game failed — exit 1."""


# ---------------------------------------------------------------------------
# Check bookkeeping
# ---------------------------------------------------------------------------


class Checker:
    """Counts assertions and fails fast.

    Fail-fast is deliberate: once the wire state has diverged from what the
    solution expects, every later assertion is noise. The FIRST failure is the
    informative one.
    """

    def __init__(self, verbose: bool = False) -> None:
        self.count = 0
        self.verbose = verbose

    def check(self, condition: bool, detail: str) -> None:
        self.count += 1
        if not condition:
            raise CheckFailure(detail)

    def ok(self, label: str) -> None:
        print(f"ok   {label}")

    def trace(self, label: str) -> None:
        if self.verbose:
            print(f"     {label}")


# ---------------------------------------------------------------------------
# Wire client — the mirror of the bridge's own framing
# ---------------------------------------------------------------------------


class BridgeClient:
    """Newline-delimited JSON over a blocking TCP socket."""

    def __init__(self, sock: socket.socket, checker: Checker) -> None:
        self._sock = sock
        self._buf = b""
        self._checker = checker
        self.context = "startup"

    def send(self, message: dict) -> None:
        payload = (json.dumps(message) + "\n").encode("utf-8")
        try:
            self._sock.sendall(payload)
        except socket.timeout as exc:
            raise SmokeCheckError(f"timed out sending to the bridge ({self.context})") from exc
        except OSError as exc:
            raise SmokeCheckError(
                f"failed to send to the bridge ({self.context}): {exc}"
            ) from exc

    def read_line(self) -> bytes:
        """One COMPLETE reply line, buffering across reads.

        A reply can arrive split across several `recv()` calls, and two replies
        can arrive in one. Splitting the buffer on b"\\n" is the whole answer.
        """
        while b"\n" not in self._buf:
            try:
                chunk = self._sock.recv(4096)
            except socket.timeout as exc:
                raise SmokeCheckError(
                    f"timed out waiting for a reply from the bridge ({self.context})"
                ) from exc
            except OSError as exc:
                raise SmokeCheckError(
                    f"lost the connection to the bridge ({self.context}): {exc}"
                ) from exc
            if not chunk:
                raise SmokeCheckError(
                    f"bridge closed the connection while a reply was expected ({self.context})"
                )
            self._buf += chunk
        line, _, self._buf = self._buf.partition(b"\n")
        return line

    def request(self, message: dict) -> tuple[bytes, dict]:
        """Send one message and return (raw reply line, parsed reply).

        The RAW bytes are returned too because the determinism phase compares
        bytes, which is a strictly stronger claim than comparing dicts.
        """
        self.send(message)
        raw = self.read_line()
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CheckFailure(
                f"bridge sent a non-JSON reply ({self.context}): {raw[:200]!r} ({exc})"
            ) from exc
        self._checker.check(
            isinstance(parsed, dict),
            f"bridge reply was not a JSON object ({self.context}): {raw[:200]!r}",
        )
        self._checker.check(
            "error" not in parsed,
            f"bridge returned an error ({self.context}): {parsed.get('error')!r}",
        )
        return raw, parsed

    def expect_eof(self) -> None:
        """After `close` the bridge sends NOTHING and hangs up — assert exactly that."""
        if self._buf:
            raise CheckFailure(
                f"bridge replied to `close`, which the PRD defines as no-reply: {self._buf[:200]!r}"
            )
        try:
            trailing = self._sock.recv(4096)
        except socket.timeout as exc:
            raise CheckFailure(
                "bridge did not close the connection after `close` (timed out waiting for EOF)"
            ) from exc
        except ConnectionResetError:
            # A reset is a hang-up too; the process is gone, which is the point.
            return
        except OSError as exc:
            raise SmokeCheckError(f"error while waiting for the bridge to hang up: {exc}") from exc
        if trailing:
            raise CheckFailure(
                f"bridge replied to `close`, which the PRD defines as no-reply: {trailing[:200]!r}"
            )


# ---------------------------------------------------------------------------
# Phase 0 — the solutions file (before any socket is opened)
# ---------------------------------------------------------------------------


def load_solutions(checker: Checker) -> dict[str, list[int]]:
    """Read and validate `levels/solutions.json`.

    Validated hard on purpose: a missing or empty file must be a loud exit-2
    error, never a silent `{}` that would let this whole script pass
    vacuously by replaying nothing.
    """
    if not SOLUTIONS_PATH.is_file():
        raise SmokeCheckError(
            f"{SOLUTIONS_PATH} not found — the committed level solutions are what this "
            "script replays; nothing can be checked without them."
        )
    try:
        raw = json.loads(SOLUTIONS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SmokeCheckError(f"could not read {SOLUTIONS_PATH}: {exc}") from exc

    if not isinstance(raw, dict):
        raise SmokeCheckError(f"{SOLUTIONS_PATH} must hold a JSON object, got {type(raw).__name__}")
    if set(raw) != set(LEVEL_NAMES):
        raise SmokeCheckError(
            f"{SOLUTIONS_PATH} must hold exactly the keys {', '.join(LEVEL_NAMES)} — "
            f"found: {', '.join(sorted(raw)) or '(none)'}"
        )

    solutions: dict[str, list[int]] = {}
    for name in LEVEL_NAMES:
        actions = raw[name]
        if not isinstance(actions, list) or not actions:
            raise SmokeCheckError(
                f"{SOLUTIONS_PATH}: '{name}' must be a non-empty list of action ids"
            )
        coerced: list[int] = []
        for pos, value in enumerate(actions):
            # JSON has one number type, so a whole number may arrive as a float.
            # A FRACTIONAL value is a real defect, not something to floor away.
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise SmokeCheckError(
                    f"{SOLUTIONS_PATH}: '{name}'[{pos}] is {value!r}, not a number"
                )
            if isinstance(value, float) and value != int(value):
                raise SmokeCheckError(
                    f"{SOLUTIONS_PATH}: '{name}'[{pos}] is {value!r}, not a whole number"
                )
            action = int(value)
            if action not in ACTION_IDS:
                raise SmokeCheckError(
                    f"{SOLUTIONS_PATH}: '{name}'[{pos}] is {action}, outside the PRD's 0..3"
                )
            coerced.append(action)
        solutions[name] = coerced

    total = sum(len(v) for v in solutions.values())
    checker.ok(
        "solutions.json: 3 levels, "
        + " + ".join(str(len(solutions[n])) for n in LEVEL_NAMES)
        + f" = {total} actions"
    )
    return solutions


# ---------------------------------------------------------------------------
# State assertions
# ---------------------------------------------------------------------------


def assert_state_shape(checker: Checker, state: object, context: str) -> dict:
    checker.check(isinstance(state, dict), f"{context}: `state` is not a JSON object: {state!r}")
    assert isinstance(state, dict)  # narrowing only; the check above is the real gate
    checker.check(
        set(state) == STATE_KEYS,
        f"{context}: state keys are {sorted(state)}, PRD requires {sorted(STATE_KEYS)}",
    )
    for key in STATE_INT_KEYS:
        value = state[key]
        # bool is a subclass of int in Python, so exclude it explicitly.
        checker.check(
            isinstance(value, int) and not isinstance(value, bool),
            f"{context}: state['{key}'] should be an int, got {value!r}",
        )
    for key in STATE_BOOL_KEYS:
        checker.check(
            isinstance(state[key], bool),
            f"{context}: state['{key}'] should be a bool, got {state[key]!r}",
        )
    return state


def do_reset(client: BridgeClient, checker: Checker, context: str) -> tuple[bytes, dict]:
    client.context = context
    raw, reply = client.request({"command": "reset"})
    checker.check(
        set(reply) == RESET_KEYS,
        f"{context}: reset reply keys are {sorted(reply)}, PRD requires exactly ['state']",
    )
    state = assert_state_shape(checker, reply["state"], context)
    checker.check(
        state["moves_taken"] == 0,
        f"{context}: reset left moves_taken at {state['moves_taken']}, expected 0",
    )
    checker.check(
        state["all_levels_solved"] is False,
        f"{context}: reset left all_levels_solved true",
    )
    return raw, state


def do_step(
    client: BridgeClient, checker: Checker, action: int, context: str, previous_moves: int
) -> tuple[bytes, dict]:
    client.context = context
    raw, reply = client.request({"command": "step", "action_id": action})
    checker.check(
        set(reply) == STEP_KEYS,
        f"{context}: step reply keys are {sorted(reply)}, PRD requires {sorted(STEP_KEYS)}",
    )
    state = assert_state_shape(checker, reply["state"], context)
    checker.check(
        reply["truncated"] is False,
        f"{context}: truncated is {reply['truncated']!r}, expected false",
    )
    checker.check(reply["info"] == {}, f"{context}: info is {reply['info']!r}, expected {{}}")
    # PRD: "`terminated` mirrors `all_levels_solved`" — checked on the wire, on
    # EVERY step, not just the last one.
    checker.check(
        reply["terminated"] is state["all_levels_solved"],
        f"{context}: terminated={reply['terminated']!r} does not mirror "
        f"all_levels_solved={state['all_levels_solved']!r}",
    )
    checker.check(
        0 <= state["boxes_on_target"] <= state["boxes_total"],
        f"{context}: boxes_on_target={state['boxes_on_target']} outside "
        f"0..{state['boxes_total']}",
    )
    checker.check(
        state["moves_taken"] >= previous_moves,
        f"{context}: moves_taken went backwards, {previous_moves} -> {state['moves_taken']}",
    )
    return raw, state


# ---------------------------------------------------------------------------
# Phase 2 — the acceptance replay
# ---------------------------------------------------------------------------


def replay_all_levels(
    client: BridgeClient, checker: Checker, solutions: dict[str, list[int]]
) -> dict:
    """Replay all three sequences back-to-back and assert the PRD's win state.

    NO filler move is sent between levels: `try_move()` advances a solved level
    at the start of the next move and applies that same move in the new level.
    """
    total_actions = sum(len(solutions[name]) for name in LEVEL_NAMES)
    state: dict = {}
    moves = 0
    for level_index, name in enumerate(LEVEL_NAMES):
        actions = solutions[name]
        for step_index, action in enumerate(actions):
            context = f"{name} step {step_index + 1}/{len(actions)} (action_id={action})"
            _, state = do_step(client, checker, action, context, moves)
            moves = state["moves_taken"]
            checker.trace(
                f"{context} -> ({state['player_x']},{state['player_y']}) "
                f"{state['boxes_on_target']}/{state['boxes_total']} moves={moves}"
            )
        where = f"end of {name}"
        checker.check(
            state["level_index"] == level_index,
            f"{where}: level_index is {state['level_index']}, expected {level_index}",
        )
        checker.check(
            state["level_solved"] is True,
            f"{where}: level_solved is false — the committed solution for {name} "
            f"does not solve it over the wire "
            f"({state['boxes_on_target']}/{state['boxes_total']} boxes on target)",
        )
        checker.check(
            state["boxes_on_target"] == state["boxes_total"],
            f"{where}: {state['boxes_on_target']}/{state['boxes_total']} boxes on target",
        )
        checker.ok(f"{name} solved over the wire in {len(actions)} actions")

    # The headline acceptance criterion.
    checker.check(
        state["all_levels_solved"] is True,
        "after all three solutions all_levels_solved is false — the PRD's acceptance "
        "criterion ('all 3 levels are solvable') does not hold over the wire",
    )
    checker.check(
        state["moves_taken"] == total_actions,
        f"moves_taken is {state['moves_taken']} after {total_actions} actions — every "
        "committed action should be an effective move (a mismatch means a step was "
        "dropped on the wire or a solution contains a no-op)",
    )
    checker.ok(
        f"all_levels_solved=true and terminated=true after {total_actions} actions "
        f"(moves_taken={state['moves_taken']})"
    )
    return state


# ---------------------------------------------------------------------------
# Phase 3 — determinism
# ---------------------------------------------------------------------------


def check_determinism(
    client: BridgeClient, checker: Checker, solutions: dict[str, list[int]]
) -> None:
    """PRD: same level + same sequence from `reset` reproduces identical state.

    Compares the RAW response bytes of two `reset` + replay passes, which is
    literally what "identical state" asks for and strictly stronger than
    comparing parsed dictionaries.

    The level is read out of the first `reset` reply rather than assumed: a
    `reset` retries the CURRENT level, so after the acceptance replay this runs
    against level 3, not level 1.
    """

    def one_pass(tag: str) -> tuple[str, list[bytes]]:
        raw_reset, state = do_reset(client, checker, f"determinism {tag}: reset")
        index = state["level_index"]
        checker.check(
            0 <= index < len(LEVEL_NAMES),
            f"determinism {tag}: reset reported level_index {index}, outside 0..{len(LEVEL_NAMES) - 1}",
        )
        name = LEVEL_NAMES[index]
        lines = [raw_reset]
        moves = 0
        for step_index, action in enumerate(solutions[name]):
            context = f"determinism {tag}: {name} step {step_index + 1} (action_id={action})"
            raw, state = do_step(client, checker, action, context, moves)
            moves = state["moves_taken"]
            lines.append(raw)
        return name, lines

    name_a, first = one_pass("pass 1")
    name_b, second = one_pass("pass 2")
    checker.check(
        name_a == name_b,
        f"determinism: reset moved the board from {name_a} to {name_b} — a reset must "
        "retry the current level, not advance",
    )
    checker.check(
        len(first) == len(second),
        f"determinism: {len(first)} replies in pass 1 vs {len(second)} in pass 2",
    )
    for i, (a, b) in enumerate(zip(first, second)):
        if a != b:
            label = "reset" if i == 0 else f"step {i}"
            raise CheckFailure(
                f"determinism: replies diverge at {label} of the {name_a} replay\n"
                f"  pass 1: {a[:200].decode('utf-8', 'replace')}\n"
                f"  pass 2: {b[:200].decode('utf-8', 'replace')}"
            )
    checker.ok(
        f"determinism: {len(first)} responses byte-identical across two "
        f"reset+replay passes of {name_a}"
    )


# ---------------------------------------------------------------------------
# Connecting / launching
# ---------------------------------------------------------------------------


def try_connect(port: int, timeout: float) -> socket.socket | None:
    """One connection attempt. Returns the live socket, or None if refused.

    The probe socket IS the connection that gets used — the bridge accepts only
    ONE peer at a time, so probing and then reconnecting could race its accept
    loop and get the real connection hung up on.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((HOST, port))
    except (ConnectionRefusedError, socket.timeout, OSError):
        sock.close()
        return None
    return sock


def no_bridge_error(port: int) -> SmokeCheckError:
    return SmokeCheckError(
        f"no bridge is listening on {HOST}:{port}. Start one with:\n"
        f"    godot4 --headless --path {QUOTED_PROJECT_DIR} -- --ugt-bridge --ugt-port={port}\n"
        "  ...or drop --attach and this script will launch and shut down its own."
    )


def resolve_godot(requested: str) -> str:
    if os.path.sep in requested:
        candidate = Path(requested).expanduser()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
        raise SmokeCheckError(f"'{requested}' is not an executable file")
    found = shutil.which(requested)
    if found is None:
        raise SmokeCheckError(
            f"'{requested}' not found on PATH. Install Godot 4.x, set GODOT=<path>, or pass "
            "--godot <path>. (Homebrew installs the binary as 'godot' — symlink it: "
            'ln -s "$(command -v godot)" /usr/local/bin/godot4)'
        )
    return found


class LaunchedBridge:
    """A headless Godot process this script owns, with its output drained.

    The stdout pipe is drained by a daemon thread rather than read inline: a
    pipe nobody reads can eventually block the child, and the captured lines are
    exactly what a startup failure message needs.
    """

    def __init__(self, godot: str, port: int) -> None:
        self.port = port
        self.lines: list[str] = []
        self._lock = threading.Lock()
        cmd = [
            godot,
            "--headless",
            "--path",
            str(PROJECT_DIR),
            "--",
            "--ugt-bridge",
            f"--ugt-port={port}",
        ]
        try:
            self.proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            raise SmokeCheckError(f"could not start '{godot}': {exc}") from exc
        self._reader = threading.Thread(target=self._drain, daemon=True)
        self._reader.start()

    def _drain(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            with self._lock:
                self.lines.append(line.rstrip("\n"))

    def output(self) -> str:
        with self._lock:
            return "\n".join(self.lines) or "(no output)"

    def saw_ready(self) -> bool:
        with self._lock:
            return any(READY_SUBSTRING in line for line in self.lines)

    def wait_ready(self, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.saw_ready():
                return
            if self.proc.poll() is not None:
                raise SmokeCheckError(
                    f"the headless bridge exited with code {self.proc.returncode} before it "
                    f"started listening. Output:\n{self.output()}\n"
                    "  (on a fresh clone, regenerate the import cache first: "
                    f"godot4 --headless --editor --path {QUOTED_PROJECT_DIR} --quit)"
                )
            time.sleep(0.05)
        raise SmokeCheckError(
            f"the headless bridge did not print '{READY_SUBSTRING}' within {timeout:g}s. "
            f"Output:\n{self.output()}"
        )

    def connect(self, timeout: float) -> socket.socket:
        """Connect once the ready line is out; retry briefly for good measure."""
        deadline = time.monotonic() + min(timeout, 10.0)
        while True:
            sock = try_connect(self.port, timeout=2.0)
            if sock is not None:
                return sock
            if self.proc.poll() is not None or time.monotonic() >= deadline:
                raise SmokeCheckError(
                    f"the bridge announced itself on {HOST}:{self.port} but would not accept a "
                    f"connection. Output:\n{self.output()}"
                )
            time.sleep(0.05)

    def wait_exit(self, timeout: float) -> int | None:
        try:
            return self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None

    def kill(self) -> None:
        """Never leave a stray headless Godot behind."""
        if self.proc.poll() is not None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def run(args: argparse.Namespace) -> int:
    checker = Checker(verbose=args.verbose)
    solutions = load_solutions(checker)

    sock: socket.socket | None = None
    bridge: LaunchedBridge | None = None
    attached = False

    try:
        if args.mode in ("auto", "attach"):
            sock = try_connect(args.port, timeout=min(args.timeout, 2.0))
            if sock is not None:
                attached = True
                # LESSONS O-series: never let a process you did not start absorb
                # a run silently. Say so, loudly.
                print(
                    f"NOTE: attached to a bridge already listening on {HOST}:{args.port} — "
                    "this script did not start it."
                )
            elif args.mode == "attach":
                raise no_bridge_error(args.port)

        if sock is None:
            probe = try_connect(args.port, timeout=min(args.timeout, 2.0))
            if probe is not None:
                probe.close()
                raise SmokeCheckError(
                    f"something is already listening on {HOST}:{args.port}; refusing to launch a "
                    "second bridge. Use --attach to drive it, or --port to pick a free port."
                )
            godot = resolve_godot(args.godot)
            print(f"launching: {godot} --headless --path . -- --ugt-bridge --ugt-port={args.port}")
            bridge = LaunchedBridge(godot, args.port)
            bridge.wait_ready(args.timeout)
            sock = bridge.connect(args.timeout)
            checker.ok(f"headless bridge up and listening on {HOST}:{args.port}")

        sock.settimeout(args.timeout)
        client = BridgeClient(sock, checker)

        # --- Phase 1: reset + protocol shape --------------------------------
        _, state = do_reset(client, checker, "initial reset")
        if state["level_index"] != 0:
            raise SmokeCheckError(
                f"the attached bridge is on level {state['level_index'] + 1}; `reset` retries the "
                "current level, it does not restart the game, so the three solution sequences "
                "cannot be replayed against it. Restart the bridge and re-run."
            )
        checker.ok("reset returns exactly {'state': {...}} with the PRD's 8 state keys")

        # --- Phase 2: acceptance replay -------------------------------------
        replay_all_levels(client, checker, solutions)

        # --- Phase 3: determinism -------------------------------------------
        check_determinism(client, checker, solutions)

        # --- Phase 4: clean shutdown (only for a bridge we own) --------------
        if attached:
            print("attach mode: left the bridge running (no 'close' sent).")
        else:
            assert bridge is not None
            client.context = "close"
            client.send({"command": "close"})
            client.expect_eof()
            code = bridge.wait_exit(timeout=10)
            checker.check(
                code == 0,
                "the bridge did not exit cleanly after `close` "
                + (f"(exit code {code})" if code is not None else "(still running)")
                + f". Output:\n{bridge.output()}",
            )
            checker.ok("`close` hung up with no reply and the process exited 0")

        total = sum(len(solutions[n]) for n in LEVEL_NAMES)
        print(
            f"OK: {len(LEVEL_NAMES)}/{len(LEVEL_NAMES)} shipped levels solved over "
            f"{HOST}:{args.port} ({total} moves, all_levels_solved=true, terminated=true); "
            f"determinism verified; {checker.count} checks passed."
        )
        return 0
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        # Attach mode must leave a foreign bridge untouched; a bridge we
        # launched must never be leaked, on any exit path.
        if bridge is not None:
            bridge.kill()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tcp_smoke_check.py",
        description=(
            "Drive the Sokoban Mini UGT bridge over real TCP: replay the committed "
            "solutions for all 3 levels, assert all_levels_solved, and verify determinism."
        ),
        epilog=(
            "exit codes: 0 pass · 1 a check failed · 2 environment/usage problem "
            "(no bridge, no godot4, bad solutions.json) · 3 unexpected error · 130 interrupted"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"bridge TCP port on {HOST} (default: {DEFAULT_PORT}, the PRD's port)",
    )
    parser.add_argument(
        "--godot",
        default=os.environ.get("GODOT", "godot4"),
        help="Godot 4.x binary used in launch mode (default: $GODOT or godot4)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--attach",
        dest="mode",
        action="store_const",
        const="attach",
        help="use a bridge that is already running; never launch one",
    )
    mode.add_argument(
        "--launch",
        dest="mode",
        action="store_const",
        const="launch",
        help="always launch a bridge; fail if the port is already in use",
    )
    parser.set_defaults(mode="auto")
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="seconds to wait for startup and for each socket operation (default: 30)",
    )
    parser.add_argument("--verbose", action="store_true", help="print one line per wire step")
    parser.add_argument(
        "--traceback",
        action="store_true",
        help="re-raise unexpected errors instead of printing one readable line",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.port < 1 or args.port > 65535:
        print(f"ERROR: --port {args.port} is outside 1..65535.", file=sys.stderr)
        return 2
    if args.timeout <= 0:
        print(f"ERROR: --timeout {args.timeout:g} must be positive.", file=sys.stderr)
        return 2
    try:
        return run(args)
    except CheckFailure as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    except SmokeCheckError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("ERROR: interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:  # never spray a traceback at a user
        if args.traceback:
            raise
        print(
            f"ERROR: unexpected failure: {type(exc).__name__}: {exc} "
            "(re-run with --traceback for the stack)",
            file=sys.stderr,
        )
        return 3


if __name__ == "__main__":
    sys.exit(main())
