#!/usr/bin/env python3
"""Committed negative test for the same-seed determinism predicate in verify_round10.

Feeds SYNTHETIC trajectory pairs to `trajectories_match` — no game, no browser — to
prove the guard catches the empty/empty vacuous pass (plus divergence and length
mismatch) that the OLD inline `same_len and divergence is None` boolean waved through.

This is the L-001 regression artifact (style: integrations/pond/pc6_ordering_selftest.py).
Run: python3 integrations/warzones/determinism_selftest.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from verify_round10 import trajectories_match  # noqa: E402


def _old_inline_predicate(first: list, second: list) -> bool:
    """The exact boolean the fix replaced (verify_round10.py before L-001):
        same_len = len(first) == len(second)
        divergence = next((i for i,(x,y) in enumerate(zip(first,second)) if x!=y), None)
        pass = same_len and divergence is None
    Kept here ONLY to demonstrate it green-lit the empty/empty case."""
    same_len = len(first) == len(second)
    divergence = next((i for i, (x, y) in enumerate(zip(first, second)) if x != y), None)
    return same_len and divergence is None


def main() -> int:
    fails = []

    # 1. THE guard: two EMPTY trajectories must FAIL (nothing was driven/compared).
    ok, detail = trajectories_match([], [])
    if ok:
        fails.append(f"empty/empty wrongly PASSED (detail={detail!r})")
    # ...and prove the OLD inline predicate would have PASSED it — the vacuity closed.
    if not _old_inline_predicate([], []):
        fails.append("harness bug: the old inline predicate did NOT pass empty/empty, "
                     "so this regression proves nothing — re-check _old_inline_predicate")

    # 2. Identical NON-EMPTY trajectories must PASS.
    a = [(3, 1, 100), (4, 1, 100), (1, 2, 90)]
    ok, _ = trajectories_match(a, list(a))
    if not ok:
        fails.append("identical non-empty pair wrongly FAILED")

    # 3. Diverging pair must FAIL, reporting the TRUE first-divergence index.
    b = [(3, 1, 100), (4, 1, 100), (5, 2, 90)]  # differs from `a` at index 2
    ok, detail = trajectories_match(a, b)
    if ok or "step 2" not in detail:
        fails.append(f"diverging pair: expected FAIL naming step 2, got ok={ok} detail={detail!r}")

    # 4. Unequal-length pair must FAIL.
    ok, detail = trajectories_match(a, a[:2])
    if ok or "length differs" not in detail:
        fails.append(f"unequal-length pair wrongly PASSED/mis-detailed (ok={ok} detail={detail!r})")

    # 5. One-empty/one-nonempty must FAIL (both orientations).
    for pair in (([], a), (a, [])):
        ok, _ = trajectories_match(*pair)
        if ok:
            fails.append(f"half-empty pair wrongly PASSED (lengths {len(pair[0])},{len(pair[1])})")

    if fails:
        print("Warzones determinism self-test FAILED:")
        for f in fails:
            print(f"  * {f}")
        return 1
    print("Warzones determinism self-test PASSED (6/6 cases).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
