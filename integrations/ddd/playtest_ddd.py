#!/usr/bin/env python3
"""
DDD LLM playtest via the L-002 legal-action drive mode.

This is the end-to-end validation harness for the structured/legal-action
`ugt playtest` channel. DDD has the cleanest `_legal(seat)` of the three JSON-lines
harness games, so it is the reference exercise for `playtest_game_with_adapter`.

Unlike the trial ladder (random/heuristic ids), here an LLM reads DddHarnessAdapter's
OWN structured state (`_read_state`) plus its live legal-action list, and picks one
legal action per step by index. The SAME playtest loop as the browser/simulation/
real_server path runs — state-delta assertion, bug-report shape, and the DDD
invariant suite (inv_card_conservation is a literal before/after assertion) — this
task only adds the input channel, not a second tester.

Run (from the UGT repo root; node >=24, DDD deps installed — the adapter spawns the
harness itself, there is no server to start). Use ollama (free/local) to validate:

    python3 integrations/ddd/playtest_ddd.py --provider ollama --model gemma4:26b
    python3 integrations/ddd/playtest_ddd.py --provider ollama --model llama3:8b --max-actions 40

Exit 0 + "PLAYTEST MET" means: >=20 actions taken, >=1 state-delta-based step, and
the invariant suite ran (an invariant_violations list is present in the report).
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import invariants  # noqa: E402  (local module, from integrations/ddd/)

from ugt.adapters.ddd_harness import DddHarnessAdapter  # noqa: E402
from ugt.core.playtester import playtest_game_with_adapter  # noqa: E402
from ugt.utils.config_parser import UgtConfig  # noqa: E402

CONFIG_PATH = "integrations/ddd/ugt.config.yaml"
GUIDE_PATH = "integrations/ddd/strategy-guide.md"
REPORT_PATH = "integrations/ddd/results/playtest-report.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="DDD LLM playtest (legal-action mode)")
    parser.add_argument("--provider", default="ollama", choices=["ollama", "anthropic"],
                        help="LLM provider (default: ollama — free/local)")
    parser.add_argument("--model", default=None, help="model override (provider default if unset)")
    parser.add_argument("--max-actions", type=int, default=40,
                        help="max LLM actions this run (default 40 — margin over the 20 bar)")
    args = parser.parse_args()

    cfg = UgtConfig(CONFIG_PATH)
    adapter = DddHarnessAdapter(cfg)
    with open(GUIDE_PATH) as fh:
        guide = fh.read()

    report = playtest_game_with_adapter(
        adapter,
        provider=args.provider,
        strategy_guide=guide,
        max_actions=args.max_actions,
        model=args.model,
        action_mode="legal_action",
        # One definition, both tiers: hand the DDD invariant suite to the playtest
        # loop exactly as R3 hands it to the ExploitHunter.
        invariants=lambda ad: invariants.build_suite().to_hunter_invariants(),
        output_path=REPORT_PATH,
    )

    summary = report.get("summary", {})
    actions = summary.get("actions_taken", 0)
    action_log = report.get("action_log", [])
    delta_steps = sum(
        1 for e in action_log
        if e.get("action_type") == "legal_action" and e.get("state_delta")
    )
    invariants_ran = "invariant_violations" in report
    violations = len(report.get("invariant_violations", []))

    print()
    print(f"[=] actions_taken       = {actions}")
    print(f"[=] legal_action steps with a state delta = {delta_steps}")
    print(f"[=] invariant suite ran = {invariants_ran} (violations={violations})")
    print(f"[=] report              = {REPORT_PATH}")

    ok = actions >= 20 and delta_steps >= 1 and invariants_ran
    print(f"\n{'PLAYTEST MET' if ok else 'PLAYTEST NOT MET'} — "
          f"actions>=20:{actions >= 20} delta_steps>=1:{delta_steps >= 1} "
          f"invariants_ran:{invariants_ran}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
