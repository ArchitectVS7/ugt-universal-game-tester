#!/bin/bash
# Start a simple local HTTP server for the browser game example.
# Usage: ./serve.sh
echo "[*] Serving browser-game example at http://localhost:8080"
python3 -m http.server 8080 --directory "$(dirname "$0")"
