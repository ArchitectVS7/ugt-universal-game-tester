"""
Trial-ladder scaffold — the game-agnostic skeleton shared by every per-game
verify_round{1,2,3}.py script (the R1 "one loop" / R2 "full spine" / R3
"exploit-hunter walk" ladder documented in UGT-USER-MANUAL.md).

Extracted from the fourth game trial's ladder scripts, where the same three
pieces were duplicated verbatim across rounds — and, before that, across the
two browser-game trials that preceded it:

  * GateRunner       — the [PASS]/[FAIL] check accumulator, [FINDING] registry,
                       and the "ROUND N MET — p/t" footer with its exit code.
  * InvariantSuite   — a registry of per-command predicates
                       (before, after, command, result) -> str | None, runnable
                       as a sweep after every command AND wrappable to the
                       ExploitHunter's (before, action_id, info, after, ctx)
                       invariant signature for the R3 tier.
  * first_divergence — the determinism-replay compare (index of the first
                       differing element between two same-length streams).

Everything game-specific — the predicates themselves, state normalization,
probes, policies — stays in the game's integrations/<game>/ files. This module
holds only the harness shape. A failed check is DATA: findings print inline,
fail the gate, and are fixed upstream in the game, never tolerated here.
"""
from __future__ import annotations

from typing import Callable, Optional

# A per-command invariant predicate: returns a human-readable violation string,
# or None when the invariant holds. Nothing in a predicate may re-implement
# game logic — every check reads observable state back and compares.
CommandPredicate = Callable[[dict, dict, str, dict], Optional[str]]


class GateRunner:
    """Accumulates a round's checks + findings and prints the standard gate.

    Usage (matching every verify_roundN.py):

        gate = GateRunner()
        gate.ck("thing holds", ok, "detail")     # prints [PASS]/[FAIL]
        gate.finding("bug to fix upstream")       # prints [FINDING]
        return gate.finish("ROUND 1", "…met message…")
    """

    def __init__(self) -> None:
        self.checks: list[tuple[str, bool, str]] = []
        self.findings: list[str] = []

    def ck(self, name: str, ok: bool, detail: str = "") -> bool:
        ok = bool(ok)
        self.checks.append((name, ok, detail))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}"
              + (f"  — {detail}" if detail else ""))
        return ok

    def finding(self, text: str) -> None:
        self.findings.append(text)
        print(f"  [FINDING] {text}")

    @property
    def passed(self) -> int:
        return sum(1 for _, ok, _ in self.checks if ok)

    @property
    def total(self) -> int:
        return len(self.checks)

    def finish(self, label: str, met_msg: str,
               not_met_msg: str = "Fix the failures above and re-run.") -> int:
        """Print the findings block + the MET/NOT-MET footer; return the exit
        code (0 only when EVERY check passed — the gate is fail-closed)."""
        print(f"\n{'=' * 70}")
        if self.findings:
            print("FINDINGS (bugs/anomalies in the game, to fix upstream):")
            for i, f in enumerate(self.findings, 1):
                print(f"  {i}. {f}")
            print()
        if self.passed == self.total:
            print(f"{label} MET — {self.passed}/{self.total} checks. {met_msg}")
            return 0
        print(f"{label} NOT MET — {self.passed}/{self.total} checks passed. "
              f"{not_met_msg}")
        return 1


class InvariantSuite:
    """A game's per-command invariant predicates, runnable in both tiers.

    R1/R2 (scripted rounds) call `check_command` after every command; R3 hands
    the same predicates to the ExploitHunter via `to_hunter_invariants` — one
    definition, both signatures, so the tiers can never drift apart.
    """

    def __init__(self, predicates: list[CommandPredicate]) -> None:
        self.predicates = list(predicates)

    def check_command(self, before: dict, after: dict, command: str,
                      result: dict) -> list[str]:
        """Run every predicate for one command; return the violation strings
        (empty when all hold)."""
        violations = []
        for pred in self.predicates:
            msg = pred(before, after, command, result)
            if msg:
                violations.append(msg)
        return violations

    def to_hunter_invariants(self) -> list:
        """Wrap each predicate to the ExploitHunter's
        (before, action_id, info, after, ctx) signature, preserving its name
        and docstring for the hunter's finding reports."""
        from ugt.core.exploit_hunter import Invariant  # avoid import cycles
        return [Invariant(pred.__name__, _wrap_for_hunter(pred),
                          pred.__doc__ or "")
                for pred in self.predicates]


def _wrap_for_hunter(pred: CommandPredicate):
    def check(before, action_id, info, after, ctx):
        return pred(before, after, info.get("command", ""),
                    info.get("result") or {})
    check.__name__ = pred.__name__
    return check


def first_divergence(a, b) -> Optional[int]:
    """Index of the first differing element between two streams (zip
    semantics), or None when they match element-for-element. Compare lengths
    separately — a shared prefix with different lengths returns None here."""
    return next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), None)
