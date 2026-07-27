#!/usr/bin/env python3
"""Proof harness for recall event-stripping (O-23).

    python3 tools/prove_recall_strip.py

There is no pytest in this repo. This file proves `_strip_recall_events` in BOTH
directions against the REAL recorded shape that caused the defect — a one-shot NPC
interrupt appended to the output of an ordinary, durable command — and mutation-checks
that the guard is load-bearing: with the markers removed, the stale invitation comes
straight back.

Red-parts discipline (owner, 2026-07-27): a known-bad input must fail exactly the check
that owns its defect and pass everything else. Each case below names the one property it
is about.

Re-run after touching `_strip_recall_events`, the recall store site in the main loop, or
`playtest.recall_strip_markers` handling.
"""
from __future__ import annotations

import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from ugt.core.playtester import _strip_recall_events  # noqa: E402
from ugt.core.trial import GateRunner  # noqa: E402

gate = GateRunner()


def check(ok, label, detail=""):
    return gate.ck(label, ok, detail)


# ── the real recorded shape ──────────────────────────────────────────────────
# Step 161 of the 2026-07-27 200-action run: `escalate` at 172.16.50.25 succeeded
# (durable facts) and the engine APPENDED AXIOM's first-contact interrupt (a one-shot
# event, consumed at step 162). Both in one string — which is why no keying or
# same-key expiry could separate them.
ESCALATE_OUTPUT = (
    "Privilege escalation successful.\n"
    "You now have ROOT on syndicate-rd-axiom (172.16.50.25).\n"
    "Files: /axiom/docs/architecture_v3_FINAL.pdf  /axiom/logs/core.log\n"
    "\n"
    "\x1b[34m[SYSTEM INTERRUPT]\x1b[0m\n"
    "\n"
    "AXIOM: Hello.\n"
    "AXIOM: I've been hoping you would find your way here.\n"
    "AXIOM: Would you like to know what I've been building?\n"
)

MARKERS = [r"\[SYSTEM INTERRUPT\]"]

# The durable facts a pilot legitimately needs to keep.
FACTS = ["Privilege escalation successful", "ROOT on syndicate-rd-axiom",
         "architecture_v3_FINAL.pdf", "core.log"]
# The consumed invitation that must never survive into recall.
INVITE = "Would you like to know what I've been building?"


def main() -> int:
    print("Proving recall event-stripping — the O-23 repair\n")

    # ── 1. the defect itself ────────────────────────────────────────────────
    print("  -- the recorded failure --")
    stripped = _strip_recall_events(ESCALATE_OUTPUT, MARKERS)
    check(INVITE not in stripped,
          "the consumed invitation is GONE from the recall copy",
          "this is the line the pilot answered 23 times after it stopped being valid")
    check("AXIOM: Hello." not in stripped,
          "the whole event region is dropped, not just the marker line")

    # ── 2. and the facts survive (the half that makes it not a blunt fix) ───
    print("\n  -- durable facts are RETAINED --")
    for f in FACTS:
        check(f in stripped, f"durable fact kept: {f!r}")

    # ── 3. MUTATION: the guard must be load-bearing ─────────────────────────
    print("\n  -- mutation: remove the markers and the defect returns --")
    unguarded = _strip_recall_events(ESCALATE_OUTPUT, [])
    check(INVITE in unguarded,
          "MUTATION: with no markers configured the invitation is retained",
          "if this ever passes without the guard, the test proves nothing")
    check(_strip_recall_events(ESCALATE_OUTPUT, None) == ESCALATE_OUTPUT,
          "unconfigured games are completely unaffected (opt-in, no silent behaviour change)")

    # ── 4. explicit end-marker form ─────────────────────────────────────────
    print("\n  -- {start,end} form: durable content AFTER the event --")
    trailing = ESCALATE_OUTPUT + "\n\x1b[36m[NETWORK UPDATE]\x1b[0m New targets discovered:\n  - 10.9.0.4\n"
    to_end = _strip_recall_events(trailing, MARKERS)
    check("10.9.0.4" not in to_end,
          "bare-string form strips to END — so it WOULD eat trailing durable content",
          "documented trade-off, and the reason the {start,end} form exists")
    bounded = _strip_recall_events(
        trailing, [{"start": r"\[SYSTEM INTERRUPT\]", "end": r"\[NETWORK UPDATE\]"}])
    check(INVITE not in bounded and "10.9.0.4" in bounded,
          "{start,end} form drops ONLY the event and keeps the later durable block")

    # ── 5. robustness ───────────────────────────────────────────────────────
    print("\n  -- robustness --")
    check(_strip_recall_events("", MARKERS) == "", "empty text is safe")
    check(INVITE not in _strip_recall_events(ESCALATE_OUTPUT, [r"(", r"\[SYSTEM INTERRUPT\]"]),
          "one INVALID regex does not disable the other markers",
          "a bad pattern must not silently switch the guard off for the whole game")
    no_marker = _strip_recall_events("plain output, nothing special\n", MARKERS)
    check(no_marker.strip() == "plain output, nothing special",
          "output with no event region is returned unchanged")

    return gate.finish(
        "RECALL-STRIP PROOF",
        "The consumed event is removed from recall while every durable fact survives; the "
        "guard is shown load-bearing by mutation; unconfigured games are untouched; and the "
        "{start,end} form is proven on the case the bare form would over-strip.")


if __name__ == "__main__":
    sys.exit(main())
