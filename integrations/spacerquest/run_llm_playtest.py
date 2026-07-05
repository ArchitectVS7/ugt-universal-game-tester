#!/usr/bin/env python3
"""
Phase 2 — LLM balance playtest against the LIVE SpacerQuest server, with the
exploit-hunter's invariants running as machine checks alongside LLM play.

The LLM (balance tier) answers "is the game good?"; the invariants (robustness tier)
keep watching "does the game break?" during the same run. Violations land in the
report's `invariant_violations` (machine-checked), separate from the LLM's own
`potential_bugs` (player-suspected).

Requires the live server on :3005 (for balance runs start it with CLASSIC_MODE=false
so end_turn actually advances the day — see PLAN-FORWARD.md). Run:

    python3 integrations/spacerquest/run_llm_playtest.py [runs] [max_actions] [provider] [model]

Defaults: 1 run x 30 actions, provider=anthropic, model=provider default.
Reports land in integrations/spacerquest/results/ (playtest-summary.json + per-run files
when runs > 1, playtest-report.json for a single run).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(__file__))  # so run_exploit_hunter is importable

from ugt.core.exploit_hunter import Invariant
from ugt.core.playtester import playtest_game
from ugt.utils.config_parser import UgtConfig
from run_exploit_hunter import INVARIANTS_BASE, make_inv_screen_nonempty

CONFIG = os.path.join(os.path.dirname(__file__), "ugt.realserver.config.yaml")
GUIDE = os.path.join(os.path.dirname(__file__), "strategy-guide.md")


def inv_combat_stall(b, aid, info, a, ctx):
    """Action-independent combat-stall check (the exploit-hunter's version keys on the
    attack ACTION ID from the old config; LLM play also attacks via press_key, so here
    we watch the state instead: in_combat persisting with battle counters frozen)."""
    ch_b, ch_a = b["character"], a["character"]
    frozen = (ch_a["battles_won"] == ch_b["battles_won"]
              and ch_a["battles_lost"] == ch_b["battles_lost"])
    if ch_a["in_combat"] and ch_b["in_combat"] and frozen:
        ctx["stall"] = ctx.get("stall", 0) + 1
        if ctx["stall"] > 25:
            return (f"in_combat for {ctx['stall']} consecutive actions with battle "
                    f"counters frozen (combat stall / soft-lock)")
    else:
        ctx["stall"] = 0


def build_invariants(adapter):
    """Reuse the Phase-1 invariant set; swap the id-keyed softlock check for the
    state-keyed one (this config re-keys action ids, and LLMs also act via press_key)."""
    base = [inv for inv in INVARIANTS_BASE if inv.name != "combat_softlock"]
    return base + [
        Invariant("combat_stall", inv_combat_stall,
                  "combat must progress: counters move or combat ends"),
        make_inv_screen_nonempty(adapter),
    ]


def main() -> int:
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    max_actions = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    provider = sys.argv[3] if len(sys.argv) > 3 else "anthropic"
    model = sys.argv[4] if len(sys.argv) > 4 else None

    config = UgtConfig(CONFIG)
    with open(GUIDE) as f:
        guide = f.read()

    report = playtest_game(
        config, guide,
        max_actions=max_actions,
        provider=provider,
        model=model,
        runs=runs,
        invariants=build_invariants,
    )

    # Non-zero exit if the batch produced hard failures (machine-checked only —
    # LLM-flagged potential_bugs are triage input, not an automatic failure).
    if runs > 1:
        violations = report["aggregate"]["invariant_violations_total"]
    else:
        violations = len(report.get("invariant_violations", []))
    if violations:
        print(f"\n[!!] {violations} invariant violation(s) — read the report before trusting balance numbers.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
