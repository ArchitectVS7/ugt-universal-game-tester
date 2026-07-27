#!/usr/bin/env python3
"""Proof harness for the truncated-reply salvage in `ugt/core/playtester.py`.

    python3 tools/prove_salvage.py

There is no pytest in this repo, and LESSONS §B P15 states the requirement this
file exists to meet: *"A salvage must be able to REFUSE... Prove both directions:
it recovers the real name, and it declines an invented one."* A salvage that only
ever recovers is the coercion P4 forbids, wearing a green light.

Modelled on `tools/prove_seeding.py` / `tools/prove_generic_checks.py`. Re-run
after touching `_salvage_truncated_action` or `_parse_json_action`.
"""
from __future__ import annotations

import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from ugt.core.playtester import (  # noqa: E402
    _parse_json_action,
    _salvage_truncated_action,
)
from ugt.core.trial import GateRunner  # noqa: E402

gate = GateRunner()


def check(ok, label, detail=""):
    return gate.ck(label, ok, detail)


# A reply cut off mid-prose: the decision is complete, the tail is not.
TRUNC_ID = '{"action_type": "action_id", "value": "down", "reasoning": "the crate is at (3,2) so I'
TRUNC_TEXT = ('{"action_type": "type_text", "value": "connect 10.0.0.5", '
              '"reasoning": "the scan listed this host and it is not yet comp')
TRUNC_TEXT_BAD = ('{"action_type": "type_text", "value": "frobnicate the mainframe", '
                  '"reasoning": "I will try someth')

ID_VOCAB = {"down", "up", "left", "right"}
TEXT_VOCAB = {"scan", "connect", "exploit", "cat", "status"}


def main() -> int:
    print("Proving the truncated-reply salvage — both directions, both channels\n")

    # ── action_id channel (the original P15 fix) ────────────────────────────
    print("  -- action_id mode --")
    got = _salvage_truncated_action(TRUNC_ID, ID_VOCAB)
    check(got is not None and got["value"] == "down" and got["action_type"] == "action_id",
          "recovers a DECLARED action name from the prefix",
          f"{got and got['value']!r}")
    check(bool(got and got.get("_salvaged")),
          "marks the turn as salvaged (so a transcript can say so)")
    check(bool(got and "truncated" in got["reasoning"]),
          "says in the reasoning that the reply was cut off (never implies the model said more)")

    invented = TRUNC_ID.replace('"down"', '"teleport"')
    check(_salvage_truncated_action(invented, ID_VOCAB) is None,
          "REFUSES an invented action name (this is the P4 coercion guard)",
          "a hallucinated verb must never be snapped onto a neighbouring id")

    # ── text channel (the gap that made the mechanism inert for text games) ──
    print("\n  -- text mode (command lines, not action names) --")
    # The regression, stated as an assertion rather than prose: the whole command
    # LINE is never a member of the vocabulary, so the action_id rule rejects it.
    check("connect 10.0.0.5" not in TEXT_VOCAB,
          "a command LINE is never in the config vocabulary (why the old rule was inert)")
    check(_salvage_truncated_action(TRUNC_TEXT, TEXT_VOCAB, "action_id") is None,
          "...and under the action_id rule that same reply is DISCARDED",
          "this is the pre-fix behaviour, kept visible so the fix cannot silently regress")

    got = _salvage_truncated_action(TRUNC_TEXT, TEXT_VOCAB, "text")
    check(got is not None and got["value"] == "connect 10.0.0.5"
          and got["action_type"] == "type_text",
          "text mode RECOVERS the whole command line when its VERB is declared",
          f"{got and got['value']!r}")

    check(_salvage_truncated_action(TRUNC_TEXT_BAD, TEXT_VOCAB, "text") is None,
          "text mode REFUSES a line whose verb is not declared",
          "'frobnicate' is not in the vocabulary, so the arguments are not trusted either")

    # Guard the guard: an empty vocabulary must never become a wildcard.
    check(_salvage_truncated_action(TRUNC_TEXT, set(), "text") is None,
          "an EMPTY vocabulary refuses everything (never a wildcard)")

    # ── end-to-end through the parser, incl. the discard marker ─────────────
    print("\n  -- through _parse_json_action --")
    parsed = _parse_json_action(TRUNC_TEXT, TEXT_VOCAB, "text")
    check(parsed.get("action_type") == "type_text" and parsed.get("_salvaged") is True,
          "the parser returns the salvaged action rather than burning the turn")

    parsed = _parse_json_action("I think I should probably look around a bit", TEXT_VOCAB, "text")
    check(parsed.get("action_type") == "wait" and parsed.get("_discarded") is True,
          "an unsalvageable reply is marked DISCARDED, not passed off as a chosen wait",
          "a silent discard is indistinguishable from a deliberate pass (P15)")

    parsed = _parse_json_action("", TEXT_VOCAB, "text")
    check(parsed.get("_discarded") is True, "an empty reply is also counted as discarded")

    parsed = _parse_json_action('{"action_type": "type_text", "value": "scan", '
                                '"reasoning": "recon first", "expected_outcome": "hosts"}',
                                TEXT_VOCAB, "text")
    check(parsed.get("action_type") == "type_text" and not parsed.get("_discarded")
          and not parsed.get("_salvaged"),
          "a COMPLETE reply is untouched — no false salvage, no false discard")

    return gate.finish(
        "SALVAGE PROOF",
        "The salvage recovers a declared decision and refuses an invented one, in "
        "both channels; discarded and salvaged turns are marked so the run can "
        "count what the loop threw away.")


if __name__ == "__main__":
    sys.exit(main())
