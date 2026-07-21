#!/usr/bin/env python3
"""Committed negative test for the SCRIPT ERROR stderr scan in verify_round2.

Feeds SYNTHETIC stderr blobs to `scan_stderr` — no game, no wire — to prove the
scan actually flags a real `SCRIPT ERROR` line (the R2 finally-block check would
otherwise be self-attested). Case 1 is THE guard the acceptance criterion asks
for: a synthetic blob containing `SCRIPT ERROR` fed through the predicate R2
uses, asserting it fails (i.e. is flagged). The whitelist is imported from R1
here too, re-proving the single-source requirement.

Run: python3 integrations/pond/stderr_scan_selftest.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from verify_round2 import scan_stderr  # noqa: E402
from verify_round1 import STDERR_WHITELIST  # noqa: E402


def main() -> int:
    fails = []
    cases = 0

    # 1. THE guard: a real SCRIPT ERROR line MUST be flagged. This is the
    #    committed proof that a SCRIPT ERROR blob feeds through the R2 predicate
    #    and fails the scan.
    cases += 1
    real = "SCRIPT ERROR: Invalid call. Nonexistent function 'foo' in base 'Node'."
    flagged = scan_stderr([real], STDERR_WHITELIST)
    if flagged != [real]:
        fails.append(f"real SCRIPT ERROR was NOT flagged: {flagged!r}")

    # 2. A Parse Error line MUST be flagged too.
    cases += 1
    parse = "Parse Error: Identifier 'bar' not declared in the current scope."
    if scan_stderr([parse], STDERR_WHITELIST) != [parse]:
        fails.append("Parse Error line was NOT flagged")

    # 3. A whitelisted teardown line carrying BOTH 'SCRIPT ERROR' and a
    #    whitelist token MUST NOT be flagged — proves the IMPORTED whitelist
    #    actually suppresses forked-addon teardown noise.
    cases += 1
    teardown = ("SCRIPT ERROR: Method failed. at: wait_to_finish "
                "(res://addons/BulletUpHell/BuHSpawner.gd:812)")
    if scan_stderr([teardown], STDERR_WHITELIST) != []:
        fails.append("whitelisted teardown line was wrongly flagged")

    # 4. Clean / warning lines yield [] (never vacuously green, never noisy).
    cases += 1
    clean = ["ready",
             "WARNING: ObjectDB instances were leaked at exit.",
             "Godot Engine v4.7.1.stable"]
    if scan_stderr(clean, STDERR_WHITELIST) != []:
        fails.append("clean/warning lines were wrongly flagged")

    # 5. Mixed blob: one real error among noise -> exactly that one flagged.
    cases += 1
    mixed = ["ready", teardown, real, "WARNING: leaked"]
    if scan_stderr(mixed, STDERR_WHITELIST) != [real]:
        fails.append("mixed blob did not isolate the single real error")

    if fails:
        print("stderr-scan self-test FAILED:")
        for f in fails:
            print(f"  * {f}")
        return 1
    print(f"stderr-scan self-test PASSED ({cases}/{cases} cases).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
