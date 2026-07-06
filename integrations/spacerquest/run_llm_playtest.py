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

Honorarium adjustment (SpacerQuest-specific, kept here rather than in the game-agnostic
framework): the `dev-setup-character` baseline every run starts from has score=148,
one point below the COMMANDER rank threshold (150). That means the very first end_turn
of EVERY run fires a guaranteed +20,000cr promotion honorarium, which is larger than the
raw mean credits_gain of the pre-fix campaign and materially pollutes the economy
numbers. Rather than change the game baseline (which would break comparability with
existing reference result sets), we subtract the actual honoraria paid — computed from
`character.rank_index` in baseline_state/final_state — and emit both the raw and
honorarium-adjusted credits_gain side by side. See PLAN-FORWARD.md Gate-C.
"""
from __future__ import annotations

import json
import math
import os
import statistics
import sys

sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(__file__))  # so run_exploit_hunter is importable

from ugt.core.exploit_hunter import Invariant
from ugt.core.playtester import playtest_game
from ugt.utils.config_parser import UgtConfig
from run_exploit_hunter import INVARIANTS_BASE, make_inv_screen_nonempty

CONFIG = os.path.join(os.path.dirname(__file__), "ugt.realserver.config.yaml")
GUIDE = os.path.join(os.path.dirname(__file__), "strategy-guide.md")

# Rank ladder + promotion honoraria, in cr. Source of truth (read-only reference, never
# edited from here): ../SpacerQuest/spacerquest-web/src/game/constants.ts
#   RANK_THRESHOLDS (lines 27-37): LIEUTENANT=0, COMMANDER=150, CAPTAIN=300,
#     COMMODORE=450, ADMIRAL=750, TOP_DOG=1200, GRAND_MUFTI=1650, MEGA_HERO=2250,
#     GIGA_HERO=2700 (score thresholds, in ascending rank_index order 0..8)
#   RANK_HONORARIA (lines 40-50): the cr amount paid the moment a run's rank_index
#     advances into a given rank.
RANK_ORDER = [
    "LIEUTENANT", "COMMANDER", "CAPTAIN", "COMMODORE", "ADMIRAL",
    "TOP_DOG", "GRAND_MUFTI", "MEGA_HERO", "GIGA_HERO",
]
RANK_HONORARIA = [10000, 20000, 30000, 40000, 50000, 80000, 100000, 120000, 150000]
COMMANDER_HONORARIUM = RANK_HONORARIA[RANK_ORDER.index("COMMANDER")]  # 20000


def _rank_index_honorarium(baseline_state, final_state):
    """Best case: sum the RANK_HONORARIA for every rank_index threshold crossed between
    baseline_state and final_state (per-run character.rank_index is directly observable
    in both playtest-report.json and playtest-run-N.json — see ugt.realserver.config.yaml
    playtest.summary_paths, where "promotions" is defined as exactly this delta).
    rank_index 0=LIEUTENANT..8=GIGA_HERO, ascending, matching RANK_ORDER/RANK_HONORARIA
    index-for-index. Returns None if rank_index isn't present (signal unavailable —
    caller should fall back)."""
    try:
        b = baseline_state["character"]["rank_index"]
        f = final_state["character"]["rank_index"]
    except (KeyError, TypeError):
        return None
    if f <= b:
        return 0
    hi = min(f, len(RANK_HONORARIA) - 1)
    return sum(RANK_HONORARIA[i] for i in range(b + 1, hi + 1))


def _fallback_commander_honorarium(baseline_state, final_state):
    """Fallback if rank_index is ever unavailable: charge only the ONE guaranteed
    COMMANDER honorarium (+20,000cr), known to fire on every dev-setup-character run
    because the baseline score (148) sits one point below the 150 COMMANDER threshold.
    This under-counts any promotions beyond COMMANDER, unlike the rank_index path above."""
    try:
        b_score = baseline_state["character"]["score"]
        f_score = final_state["character"]["score"]
    except (KeyError, TypeError):
        return 0
    return COMMANDER_HONORARIUM if b_score < 150 <= f_score else 0


def honorarium_for_run(baseline_state, final_state):
    """Returns (honorarium_cr, method) for one run's baseline/final state dicts."""
    h = _rank_index_honorarium(baseline_state, final_state)
    if h is not None:
        return h, "rank_index"
    return _fallback_commander_honorarium(baseline_state, final_state), "fallback_score_threshold"


def _ci95_stats(values):
    """mean/std/95%-CI in the same shape/formula as playtester._aggregate_runs, so the
    adjusted metric reads consistently next to the framework's own aggregate block."""
    n = len(values)
    mean = statistics.mean(values)
    std = statistics.stdev(values) if n > 1 else 0.0
    half = 1.96 * std / math.sqrt(n) if n > 1 else 0.0
    return {
        "mean": round(mean, 2),
        "std": round(std, 2),
        "ci95": [round(mean - half, 2), round(mean + half, 2)],
        "ci95_half_width": round(half, 2),
        "values": values,
    }


def apply_honorarium_adjustment(report, config, runs):
    """Post-process a playtest_game() report in place: add
    credits_gain_honorarium / _method / _honorarium_adjusted fields (per-run, plus an
    adjusted aggregate when runs > 1), print a summary line, and rewrite the on-disk
    JSON that playtest_game already wrote (playtest-report.json for runs==1,
    playtest-summary.json + each playtest-run-N.json for runs>1) so the adjustment
    survives for anyone reading results/ later."""
    results_dir = os.path.join(os.path.dirname(os.path.abspath(config.filepath)), "results")

    if runs == 1:
        honorarium, method = honorarium_for_run(report["baseline_state"], report["final_state"])
        raw = report["summary"]["credits_gain"]
        adjusted = raw - honorarium
        report["summary"]["credits_gain_honorarium"] = honorarium
        report["summary"]["credits_gain_honorarium_method"] = method
        report["summary"]["credits_gain_honorarium_adjusted"] = adjusted

        out = os.path.join(results_dir, "playtest-report.json")
        with open(out, "w") as f:
            json.dump(report, f, indent=2, default=str)

        print(f"[+] credits_gain (honorarium-adjusted): {adjusted} "
              f"(raw {raw} - honorarium {honorarium}, method={method})")
        return report

    adjusted_values = []
    methods = []
    for i, fname in enumerate(report["run_report_files"], start=1):
        run_path = os.path.join(results_dir, fname)
        with open(run_path) as f:
            run_report = json.load(f)

        honorarium, method = honorarium_for_run(run_report["baseline_state"], run_report["final_state"])
        raw = run_report["summary"]["credits_gain"]
        adjusted = raw - honorarium
        run_report["summary"]["credits_gain_honorarium"] = honorarium
        run_report["summary"]["credits_gain_honorarium_method"] = method
        run_report["summary"]["credits_gain_honorarium_adjusted"] = adjusted
        with open(run_path, "w") as f:
            json.dump(run_report, f, indent=2, default=str)

        detail = report["runs_detail"][i - 1]
        detail["credits_gain_honorarium"] = honorarium
        detail["credits_gain_honorarium_method"] = method
        detail["credits_gain_honorarium_adjusted"] = adjusted
        adjusted_values.append(adjusted)
        methods.append(method)

    report["aggregate"]["credits_gain_honorarium_adjusted"] = _ci95_stats(adjusted_values)
    report["aggregate"]["credits_gain_honorarium_methods"] = methods

    out = os.path.join(results_dir, "playtest-summary.json")
    with open(out, "w") as f:
        json.dump(report, f, indent=2, default=str)

    stats = report["aggregate"]["credits_gain_honorarium_adjusted"]
    raw_mean = report["aggregate"]["credits_gain"]["mean"]
    print(f"[+] credits_gain (honorarium-adjusted): mean {stats['mean']} "
          f"[{stats['ci95'][0]}, {stats['ci95'][1]}] (raw mean {raw_mean}, "
          f"methods={sorted(set(methods))})")
    return report


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

    apply_honorarium_adjustment(report, config, runs)

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
