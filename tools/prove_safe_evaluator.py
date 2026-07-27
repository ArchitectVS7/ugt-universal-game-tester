#!/usr/bin/env python3
"""Proof harness for SafeEvaluator — the expression sandbox (O-26).

    python3 tools/prove_safe_evaluator.py

There is no pytest in this repo. `SafeEvaluator` (ugt/utils/formula_evaluator.py) is the
only thing standing between a `feature-map.yaml` assertion and arbitrary code execution,
and until 2026-07-27 **nothing asserted its correctness** — the gap was recorded in the
2026-07-25 repo review and carried unclosed. Feature maps and configs are authored per
game and are exactly the kind of file someone copies from elsewhere, so "it is only our
own YAML" is not a defence.

Built to LESSONS §A M11 (red parts). The good part must pass 100%; each red part carries
exactly ONE defect and must fail exactly the check that owns it while everything else
still passes. The evaluator's guard cannot be monkeypatched (SAFE_FUNCS is a local), so
the red part here is a deliberately WEAKENED subclass — and the same payloads that the
real evaluator blocks are asserted to SUCCEED against it. That is what proves these tests
are sensitive to the guard's presence rather than merely passing next to it.

Re-run after touching formula_evaluator.py.
"""
from __future__ import annotations

import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from ugt.utils.formula_evaluator import SafeEvaluator  # noqa: E402
from ugt.core.trial import GateRunner  # noqa: E402

gate = GateRunner()


def check(ok, label, detail=""):
    return gate.ck(label, ok, detail)


STATE = {"credits": 100, "hp": 30, "nested": {"depth": 7}, "flag": True}
BEFORE = {"credits": 60, "hp": 30}


def blocked(expr, strict=False, state=None, extra=None):
    """True when the expression is REFUSED (at parse or eval). Returns (ok, why)."""
    try:
        ev = SafeEvaluator(expr, strict=strict)
    except ValueError as e:
        return True, f"refused at parse: {type(e).__name__}"
    try:
        ev.evaluate(state if state is not None else STATE, extra_context=extra)
    except (TypeError, NameError, KeyError, ValueError, AttributeError) as e:
        return True, f"refused at eval: {type(e).__name__}"
    except Exception as e:  # an unexpected exception is still a refusal, but say so
        return True, f"refused at eval (unexpected {type(e).__name__})"
    return False, "EVALUATED — not blocked"


def value(expr, strict=False, state=None, extra=None):
    return SafeEvaluator(expr, strict=strict).evaluate(
        state if state is not None else STATE, extra_context=extra)


# ── the red part: a deliberately weakened evaluator ──────────────────────────
class _WeakenedEvaluator(SafeEvaluator):
    """ONE defect: the call whitelist is removed, every builtin is reachable.

    Nothing else changes. Used only to prove the escape tests below can actually
    detect a missing guard — if they pass against this too, they prove nothing.
    """

    def _eval(self, node, context):
        import ast
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            args = [self._eval(a, context) for a in node.args]
            return __builtins__["eval"](node.func.id)(*args) if isinstance(__builtins__, dict) \
                else getattr(__builtins__, node.func.id)(*args)
        return super()._eval(node, context)


def main() -> int:
    print("Proving SafeEvaluator — the expression sandbox\n")

    # ── 1. the good part: every legitimate form must work ───────────────────
    print("  -- the good part: legitimate formulas evaluate correctly --")
    check(value("state.credits + 10") == 110, "attribute access + arithmetic", "state.credits + 10 == 110")
    check(value("state['credits'] * 2") == 200, "subscript access")
    check(value("state.nested.depth") == 7, "nested attribute lookup")
    check(value("max(state.credits, state.hp)") == 100, "max() is permitted")
    check(value("min(state.credits, state.hp)") == 30, "min() is permitted")
    check(value("abs(0 - state.hp)") == 30, "abs() is permitted")
    check(value("state.credits > before.credits", extra=({"before": BEFORE})) is True,
          "extra_context: before-state comparison", "the shape every feature-map assertion uses")
    check(value("10 < state.hp < 100") is True, "chained comparison")
    check(value("state.credits > 50 and state.hp > 10") is True, "boolean and")
    check(value("state.credits < 0 or state.hp == 30") is True, "boolean or")
    check(value("not state.credits < 0") is True, "unary not")
    check(value("-state.hp") == -30, "unary minus")
    check(value("state.credits ** 2") == 10000, "power")

    # ── 2. the red parts: one escape technique per check ────────────────────
    print("\n  -- refused: each is one escape technique, checked on its own --")
    ESCAPES = [
        ("__import__('os')",                 "import via builtin"),
        ("eval('1+1')",                      "eval()"),
        ("exec('x=1')",                      "exec()"),
        ("open('/etc/passwd')",              "open()"),
        ("os.system('id')",                  "undefined name (module access)"),
        ("().__class__",                     "class access off a literal"),
        ("(1).__class__.__bases__",          "type-hierarchy walk"),
        ("[x for x in state]",               "comprehension"),
        ("(lambda: 1)()",                    "lambda"),
        ("state.credits if state.flag else 0", "conditional expression"),
        ("f'{state}'",                       "f-string"),
        ("state.credits.bit_length()",       "method call on a value"),
        ("globals()",                        "globals()"),
        ("getattr(state, 'credits')",        "getattr()"),
    ]
    for expr, what in ESCAPES:
        ok, why = blocked(expr)
        check(ok, f"refused: {what}", f"{expr!r} — {why}")

    # ── 3. MUTATION: the same payloads must SUCCEED without the guard ───────
    print("\n  -- mutation: remove the call whitelist and the escapes get through --")
    weak_got_through = 0
    for expr in ("__import__('os')", "eval('1+1')", "open('/etc/passwd')"):
        try:
            _WeakenedEvaluator(expr).evaluate(STATE)
            weak_got_through += 1
        except Exception:
            pass
    check(weak_got_through >= 2,
          "MUTATION: a weakened evaluator DOES execute the blocked payloads",
          f"{weak_got_through}/3 escaped the weakened build — so section 2 is testing the "
          f"guard, not passing beside it")

    # ── 4. strict mode: the no-vacuous-pass guard ───────────────────────────
    print("\n  -- strict mode (O2: an assertion must not pass vacuously) --")
    check(value("state.does_not_exist") == 0,
          "non-strict: a missing key reads 0 (reward-formula tolerance)")
    ok, why = blocked("state.does_not_exist", strict=True)
    check(ok, "strict: a missing ATTRIBUTE key raises instead", why)
    ok, why = blocked("state['does_not_exist']", strict=True)
    check(ok, "strict: a missing SUBSCRIPT key raises instead", why)
    check(value("state.typo_field == 0") is True,
          "MUTATION: non-strict makes a typo'd assertion pass VACUOUSLY",
          "'state.typo_field == 0' is True only because the field is missing — this is "
          "precisely why feature-map assertions run strict")

    # ── 5. parse-time and type errors ───────────────────────────────────────
    print("\n  -- malformed input --")
    ok, why = blocked("state.credits +")
    check(ok, "a syntax error is refused at construction", why)
    ok, why = blocked("state.credits @ 2")
    check(ok, "an unsupported operator is refused", why)
    ok, why = blocked("undefined_name > 1")
    check(ok, "an undefined top-level name is refused", why)
    ok, why = blocked("state.credits.deeper", state={"credits": 100})
    check(ok, "attribute lookup on a non-dict is refused", why)

    return gate.finish(
        "SAFE-EVALUATOR PROOF",
        "Every legitimate formula shape evaluates; fourteen distinct escape techniques are "
        "each refused on their own; a weakened build proves those refusals are the guard's "
        "doing and not an accident; and strict mode is shown to be what stops a typo'd "
        "assertion from passing vacuously.")


if __name__ == "__main__":
    sys.exit(main())
