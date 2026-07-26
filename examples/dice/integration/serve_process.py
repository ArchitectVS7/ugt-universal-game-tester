"""Own the static server's lifecycle, so no rung needs a human to start one.

Every ladder rung imports `served_bundle()` rather than re-rolling process
management. Two rules it enforces (the same ones sokoban's bridge_process.py
enforces, for the same reasons):

  * No manual pre-step. A rung that only passes when someone already ran
    `serve.py` cannot run unattended.
  * Never silently reuse someone else's server. The port is EPHEMERAL, so a
    stale server squatting :8080 from an earlier build can never be mistaken
    for the bundle under test — a green run against the wrong build is worse
    than a red one.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from contextlib import contextmanager

HERE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.abspath(os.path.join(HERE, "..", "game", "dist"))


class ServeError(RuntimeError):
    pass


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def served_bundle(port: int | None = None, boot_timeout: float = 20.0):
    """Spawn serve.py on an ephemeral port; guarantee it dies with us."""
    if not os.path.exists(os.path.join(DIST, "index.html")):
        raise ServeError(
            f"no built bundle at {DIST}\n"
            f"    build it first:  cd examples/dice/game && npm install && npm run build"
        )
    port = port or free_port()
    proc = subprocess.Popen(
        [sys.executable, os.path.join(HERE, "serve.py"), "--port", str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
    )
    try:
        deadline = time.time() + boot_timeout
        while time.time() < deadline:
            if proc.poll() is not None:
                raise ServeError(f"serve.py exited early: {(proc.stderr.read() or '').strip()}")
            try:
                # Unlike sokoban's single-client bridge, an HTTP server is happy to
                # be probed — a throwaway connection here costs nothing.
                with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            raise ServeError(f"serve.py never accepted a connection on :{port}")
        yield port
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def adapter_for(port: int):
    """A PlaywrightAdapter pointed at our ephemeral port."""
    repo = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
    if repo not in sys.path:
        sys.path.insert(0, repo)
    from ugt.adapters.playwright import PlaywrightAdapter
    from ugt.utils.config_parser import UgtConfig

    cfg = UgtConfig(os.path.join(HERE, "ugt.config.yaml"))
    cfg.data["engine"]["entry"] = f"http://localhost:{port}/index.html"
    return PlaywrightAdapter(cfg)
