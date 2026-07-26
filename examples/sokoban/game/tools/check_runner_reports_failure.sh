#!/usr/bin/env bash
# Negative control for tests/run_tests.gd.
#
# A hand-written test runner is only trustworthy if it can actually go red, so
# this script injects a guaranteed-failing test into res://tests/, runs the
# runner, and requires BOTH:
#   1. a non-zero exit code, and
#   2. a `FAIL ... <the injected test> ...` line in the output
#      (proving it went red for the injected reason, not because the run
#      crashed or discovered nothing).
#
# The temp file is removed by an EXIT trap installed BEFORE it is written, so
# the working tree is left clean whether this script passes or fails.
#
# Usage: tools/check_runner_reports_failure.sh   (runnable from any cwd)
#        GODOT=/path/to/godot tools/check_runner_reports_failure.sh

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GODOT="${GODOT:-godot4}"

if ! command -v "$GODOT" >/dev/null 2>&1; then
	echo "ERROR: '$GODOT' not found on PATH. Install Godot 4.x, or set GODOT=<path>." >&2
	exit 1
fi

TMP_NAME="test_zz_negative_control_tmp"
TMP_TEST="$PROJECT_DIR/tests/$TMP_NAME.gd"

# Installed before the file exists: cleanup must run on every exit path.
# The .uid sidecar is removed too — this repo tracks .uid files, so a stray one
# would leave `git status --porcelain` non-empty.
trap 'rm -f "$TMP_TEST" "$TMP_TEST.uid"' EXIT

if [ -e "$TMP_TEST" ]; then
	echo "ERROR: $TMP_TEST already exists; refusing to overwrite." >&2
	exit 1
fi

cat >"$TMP_TEST" <<'GDSCRIPT'
extends "res://tests/assertions.gd"
## Temporary file written by tools/check_runner_reports_failure.sh.
## If you are reading this in a committed tree, that script did not clean up.


func test_negative_control_must_fail() -> void:
	assert_eq(1, 2, "negative control must fail")
GDSCRIPT

set +e
out="$("$GODOT" --headless --path "$PROJECT_DIR" -s res://tests/run_tests.gd 2>&1)"
rc=$?
set -e

if [ "$rc" -eq 0 ]; then
	echo "$out"
	echo "FAILED: runner exited 0 with a failing test present — it cannot report failure." >&2
	exit 1
fi

if ! printf '%s\n' "$out" | grep -q "^FAIL $TMP_NAME\.gd::test_negative_control_must_fail "; then
	echo "$out"
	echo "FAILED: runner exited $rc but printed no FAIL line for the injected test." >&2
	exit 1
fi

echo "OK: runner exited $rc and reported the injected failing test."
exit 0
