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
SRC = os.path.abspath(os.path.join(HERE, "..", "game", "src"))


class ServeError(RuntimeError):
    pass


def _newest(path: str, exts=(".js", ".jsx", ".css")) -> tuple[float, str]:
    """(mtime, path) of the most recently modified matching file under `path`."""
    best = (0.0, "")
    for root, _dirs, files in os.walk(path):
        for f in files:
            if f.endswith(exts):
                p = os.path.join(root, f)
                m = os.path.getmtime(p)
                if m > best[0]:
                    best = (m, p)
    return best


def assert_bundle_is_fresh() -> None:
    """Refuse to serve a `dist/` older than `src/`.

    The whole ladder drives the BUILT bundle, so a stale `dist` means every rung
    certifies code that is not the code in the repo — and it does it in green,
    which is the dangerous part. This is `LESSONS.md` O1 ("verify the LISTENING
    PID is the process you spawned") one layer up: same class of mistake, stale
    ARTIFACT instead of stale process.

    Found the hard way on 2026-07-26: the D18 depth fix changed STARTING_FS to 8
    and the whole ladder re-ran green against a bundle still playing at 12,
    reporting `12v12` in its own PASS line.
    """
    src_m, src_p = _newest(SRC)
    dist_m, _ = _newest(DIST)
    if src_m > dist_m:
        raise ServeError(
            f"dist/ is STALE — {os.path.relpath(src_p, SRC)} is newer than the built bundle.\n"
            f"    The ladder drives dist/, so this run would certify code you are not shipping.\n"
            f"    Rebuild first:  cd examples/dice/game && npm run build"
        )


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
    assert_bundle_is_fresh()
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
