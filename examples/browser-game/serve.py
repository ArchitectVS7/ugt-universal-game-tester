#!/usr/bin/env python3
"""Start a simple local HTTP server for the browser game example.
Usage: python3 serve.py
"""
import functools
import http.server
import os

DIRECTORY = os.path.dirname(os.path.abspath(__file__))


def main():
    print("[*] Serving browser-game example at http://localhost:8080")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=DIRECTORY)
    with http.server.ThreadingHTTPServer(("", 8080), handler) as httpd:
        httpd.serve_forever()


if __name__ == "__main__":
    main()
