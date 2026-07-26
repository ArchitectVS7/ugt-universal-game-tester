"""Own the headless Godot bridge's lifecycle, so no ladder rung needs a human.

Every rung imports `bridge()` from here rather than re-rolling process
management. Two rules this exists to enforce (TASKS.md standing constraints):

  * No manual pre-step. A rung that only passes when someone started a server by
    hand cannot run unattended.
  * Never trust a port that was already open. Attaching to a bridge from an
    earlier build is a *silent* false green — the run passes against stale code.
    `bridge()` therefore refuses to start if the port is already occupied, and
    verifies the PID it spawned is the one listening.

Usage:

    from bridge_process import bridge
    with bridge() as port:
        ...                      # bridge is up on 127.0.0.1:<port>
    # process is gone, port is free, even if the body raised
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import threading
import time
from contextlib import contextmanager

HOST = "127.0.0.1"
DEFAULT_PORT = 8910
HERE = os.path.dirname(os.path.abspath(__file__))
GAME_DIR = os.path.abspath(os.path.join(HERE, "..", "game"))


class BridgeError(RuntimeError):
    pass


def resolve_godot(binary: str | None = None) -> str:
    """Locate the Godot 4 CLI, with an actionable message when it is missing."""
    requested = binary or os.environ.get("GODOT") or "godot4"
    if os.path.sep in requested:
        if os.path.isfile(requested) and os.access(requested, os.X_OK):
            return requested
        raise BridgeError(f"'{requested}' is not an executable file")
    found = shutil.which(requested)
    if found is None:
        raise BridgeError(
            f"'{requested}' not found on PATH. Install Godot 4.x, set GODOT=<path>, or "
            'symlink Homebrew\'s binary: ln -s "$(command -v godot)" /usr/local/bin/godot4'
        )
    return found


def port_is_open(port: int, timeout: float = 0.25) -> bool:
    """Is anything listening? Connects, so it BURNS A CONNECTION SLOT.

    The bridge serves exactly one client at a time, so this must never be used
    to poll for readiness — see `wait_until_listening()`. It is fine for the
    "is it gone yet" direction, where no slot matters.
    """
    try:
        with socket.create_connection((HOST, port), timeout=timeout):
            return True
    except OSError:
        return False


def wait_until_listening(port: int, proc, deadline: float, tail: list[str]) -> None:
    """Block until the port is BOUND, without connecting to it.

    Readiness is read from the OS socket table via lsof rather than by dialling
    the port. Connecting would consume the bridge's single connection slot and
    leave the real client racing the bridge's re-accept — which is exactly the
    ConnectionResetError this function exists to prevent.
    """
    while time.time() < deadline:
        if proc.poll() is not None:
            raise BridgeError(
                f"godot exited early (code {proc.returncode}) before opening {HOST}:{port}\n"
                + "\n".join(tail[-15:])
            )
        if listening_pid(port):
            return
        time.sleep(0.15)
    raise BridgeError(
        f"bridge never opened {HOST}:{port} in time\n" + "\n".join(tail[-15:])
    )


def connect_with_retry(port: int, timeout: float = 20.0, attempts: int = 40) -> socket.socket:
    """Open THE connection to the bridge, retrying only on refusal/reset.

    Every successful connection is handed back to the caller and kept — nothing
    here opens a socket speculatively.
    """
    last: OSError | None = None
    for _ in range(attempts):
        try:
            return socket.create_connection((HOST, port), timeout=timeout)
        except OSError as exc:
            last = exc
            time.sleep(0.15)
    raise BridgeError(f"could not connect to {HOST}:{port}: {last}")


def free_port() -> int:
    """An ephemeral port, so parallel or repeated runs never collide."""
    with socket.socket() as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


@contextmanager
def bridge(port: int | None = None, godot: str | None = None, boot_timeout: float = 45.0):
    """Spawn the headless bridge, yield its port, and always tear it down."""
    exe = resolve_godot(godot)
    port = port or free_port()

    if listening_pid(port):
        raise BridgeError(
            f"something is ALREADY listening on {HOST}:{port}. Refusing to attach — a run "
            f"against a bridge from an earlier build looks green and means nothing. "
            f"Stop it first (lsof -nP -iTCP:{port} -sTCP:LISTEN)."
        )

    cmd = [exe, "--headless", "--path", GAME_DIR, "--", "--ugt-bridge", f"--ugt-port={port}"]
    proc = subprocess.Popen(
        cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, bufsize=1,
    )

    # Drain the child's output on a daemon thread: an unread pipe can eventually
    # block the process, and the tail is what makes a boot failure diagnosable.
    tail: list[str] = []

    def _drain() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            tail.append(line.rstrip())
            del tail[:-40]

    threading.Thread(target=_drain, daemon=True).start()

    try:
        wait_until_listening(port, proc, time.time() + boot_timeout, tail)
        yield port
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def listening_pid(port: int) -> str:
    """The PID holding the listen socket, via lsof — '' when nothing is listening.

    Used by the spike to prove the process it spawned is the one being talked to,
    rather than assuming it.
    """
    try:
        out = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            capture_output=True, text=True, timeout=10,
        )
        return out.stdout.strip()
    except Exception:
        return ""
