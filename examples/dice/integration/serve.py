#!/usr/bin/env python3
"""Serve the built Dice Duel bundle for the browser adapter.

    python3 serve.py [--port 8080]

Serves `../game/dist`, which Vite produces via `npm run build` in `../game`.
That directory is gitignored, so on a fresh clone you must build first:

    cd ../game && npm install && npm run build

Adapted from `examples/browser-game/serve.py`. Two differences, both because
this one serves a *built* bundle rather than a checked-in page: it fails loudly
when `dist/` is missing (instead of serving a 404 that looks like a game bug to
the adapter), and it exits cleanly on SIGINT/SIGTERM so a ladder script can
spawn and reap it.
"""
from __future__ import annotations

import argparse
import functools
import http.server
import os
import signal
import sys

DIST = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "game", "dist")
)


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    """Same behaviour, without one stderr line per asset request."""

    def log_message(self, fmt, *args):  # noqa: A003 - stdlib signature
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--verbose", action="store_true", help="log every request")
    args = ap.parse_args()

    if not os.path.isdir(DIST) or not os.path.exists(os.path.join(DIST, "index.html")):
        print(
            f"[-] No built bundle at {DIST}\n"
            f"    Build it first:  cd ../game && npm install && npm run build",
            file=sys.stderr,
        )
        return 1

    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler if args.verbose else QuietHandler,
        directory=DIST,
    )
    httpd = http.server.ThreadingHTTPServer(("", args.port), handler)

    def stop(_signum, _frame):
        # shutdown() from a handler would deadlock serve_forever on this thread.
        httpd.server_close()
        sys.exit(0)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    print(f"[*] Serving Dice Duel at http://localhost:{args.port}  (from {DIST})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
