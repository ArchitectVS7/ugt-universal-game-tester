#!/usr/bin/env python3
"""Committed negative test for the PC-6 ordering predicate in verify_round2.

Feeds SYNTHETIC event lists to `rewards_settle_before_end` — no game, no wire —
to prove the guard actually catches an out-of-order stream (the vacuous boolean
check it replaced could not). Run: python3 integrations/pond/pc6_ordering_selftest.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from verify_round2 import rewards_settle_before_end  # noqa: E402


def main() -> int:
    fails = []

    # 1. THE guard: run_ended BEFORE run_rewards_due must FAIL.
    ok, r, e = rewards_settle_before_end(
        [{"signal": "run_ended"}, {"signal": "run_rewards_due"}])
    if ok:
        fails.append(f"out-of-order stream wrongly PASSED (r={r} e={e})")

    # 2. Correct order must PASS, with r strictly before e.
    ok, r, e = rewards_settle_before_end(
        [{"signal": "run_rewards_due"}, {"signal": "run_ended"}])
    if not (ok and r is not None and e is not None and r < e):
        fails.append(f"in-order stream wrongly FAILED (ok={ok} r={r} e={e})")

    # 3. Realistic interleaved batch: rewards then other signals then end -> PASS.
    ok, _, _ = rewards_settle_before_end(
        ["player_died", "run_rewards_due", "evidence_unlocked", "run_ended"])
    if not ok:
        fails.append("interleaved in-order stream wrongly FAILED")

    # 4. Missing run_rewards_due must FAIL (never vacuously green).
    ok, r, _ = rewards_settle_before_end([{"signal": "run_ended"}])
    if ok or r is not None:
        fails.append("stream with no run_rewards_due wrongly PASSED")

    if fails:
        print("PC-6 ordering self-test FAILED:")
        for f in fails:
            print(f"  * {f}")
        return 1
    print("PC-6 ordering self-test PASSED (4/4 cases).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
