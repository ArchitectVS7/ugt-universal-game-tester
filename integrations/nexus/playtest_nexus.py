#!/usr/bin/env python3
"""
NEXUS LLM playtest via the L-002 direct-adapter entry point (text/type_text mode).

NexusHttpAdapter isn't registered under an `engine.type` in env.py — the game's
own ladder scripts build it directly — so this uses `playtest_game_with_adapter`
(the L-002 seam), exactly like DDD's playtest script. NEXUS is a terminal-hacking
RPG, so the FAITHFUL player channel is the terminal itself: the LLM reads the
adapter's live terminal text (`get_terminal_text`) + player-state and TYPES one raw
command line per step (`action_type="type_text"`), the way a human hacker would.
The SAME playtest loop as every other engine runs (state-delta assertion, bug-report
shape, contradiction detector) plus the NEXUS invariant suite R3 hands the
ExploitHunter. This task only adds an input channel for this game — not a second tester.

── DRIVE CHANNEL (type_text — the real terminal UX) ─────────────────────────────
`action_mode="text"` drives NEXUS through the adapter's `type_text`/`get_terminal_text`
exactly as L-006 requires: the LLM types full command lines it composes from the live
state ("scan", "connect <ip>", "exploit <vuln>", "accept <mission>", "cat <file>", …),
not a canned action-id whose arguments the adapter fills in. `NexusHttpAdapter` reports
each command's real transition via `type_text_step() -> (state, term, trunc, info)`, so
the shared loop's type_text branch (playtester.py) reassigns `current_state` from it and
the state-delta assertion sees GENUINE deltas — no vacuous empty-delta passes. The same
`info={"command","result","state"}` dict feeds the invariant suite (nexus_http.py:242).

This is a strictly more faithful channel than action_id: action_id mode would route
each verb through the adapter's `_compose_command` heuristic (which auto-fills the
target/file/mission from state) — closer to the tester composing commands than the
player. Here the LLM composes the whole command line, which is what a real player does.

── Run (from the UGT repo root) ─────────────────────────────────────────────────
The NEXUS server must be up on :3100 with the UGT test routes (heavier than the
self-spawning harness games — needs `next dev` + Postgres). Recipe: HANDOFF.md
"Live bring-up recipe"; export the matching TEST_API_KEY in this shell (config
api_key:null falls back to it). VERIFY the LISTEN pid is your `next dev`:
`lsof -nP -iTCP:3100 -sTCP:LISTEN` (the repo's stale-server lesson). Then:

    python3 integrations/nexus/playtest_nexus.py --provider ollama
    python3 integrations/nexus/playtest_nexus.py --provider ollama --max-actions 40

MODEL CHOICE: leave --model unset. The ollama default is `gemma4:26b`, which is what
this tier is validated on. Do NOT run this with a CODING model — `qwen3-coder:30b` was
tried on 2026-07-22 and is unfit for the balance tier: across two 40-action runs it
never once issued `cat` (the verb that completes missions), so it finished 0 missions
while looking healthy (PLAYTEST MET, 0 violations). See RESULTS.md L-014 P7 / L-015.

Exit 0 + "PLAYTEST MET" means: >=20 actions taken, >=1 typed (type_text) command with a
real state delta, and the invariant suite ran (an invariant_violations list is present).
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import invariants  # noqa: E402  (local module, from integrations/nexus/)

from ugt.adapters.nexus_http import NexusHttpAdapter  # noqa: E402
from ugt.core.playtester import playtest_game_with_adapter  # noqa: E402
from ugt.utils.config_parser import UgtConfig  # noqa: E402

CONFIG_PATH = "integrations/nexus/ugt.config.yaml"
GUIDE_PATH = "integrations/nexus/strategy-guide.md"
REPORT_PATH = "integrations/nexus/results/playtest-report.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="NEXUS LLM playtest (text/type_text mode)")
    parser.add_argument("--provider", default="ollama", choices=["ollama", "anthropic"],
                        help="LLM provider (default: ollama — free/local)")
    parser.add_argument("--model", default=None,
                        help="model override; leave unset for the ollama default "
                             "gemma4:26b (do NOT use a coding model — see the header)")
    parser.add_argument("--max-actions", type=int, default=40,
                        help="max LLM actions this run (default 40 — margin over the 20 bar)")
    args = parser.parse_args()

    cfg = UgtConfig(CONFIG_PATH)
    adapter = NexusHttpAdapter(cfg)
    with open(GUIDE_PATH) as fh:
        guide = fh.read()

    # ── Pre-flight P3 (LESSONS.md §B): fail CLOSED on a truncated guide ──────
    # The core loop warns when a budget bites; here it is a hard stop, because a
    # silently half-delivered guide is precisely how DDD's L-009/L-011 batches were
    # lost — the run still reports PLAYTEST MET and the balance number is measuring a
    # pilot that was never told the rules. NEXUS's guide teaches the success-rate
    # formula from §4 onward, so a cut costs exactly the part that matters.
    guide_budget = int((cfg.data.get("playtest") or {}).get("guide_char_budget", 2000))
    if len(guide) > guide_budget:
        print(f"[FAIL] strategy guide is {len(guide)} chars but playtest.guide_char_budget "
              f"is {guide_budget} — the LLM would never see the last {len(guide) - guide_budget}. "
              f"Raise the budget in {CONFIG_PATH} (LESSONS.md P3).")
        return 1
    print(f"[=] pre-flight: guide {len(guide)}/{guide_budget} chars (fits)")

    report = playtest_game_with_adapter(
        adapter,
        provider=args.provider,
        strategy_guide=guide,
        max_actions=args.max_actions,
        model=args.model,
        # Terminal drive channel: the LLM TYPES raw command lines via type_text, and
        # NexusHttpAdapter.type_text_step reports the real transition so deltas are
        # genuine (never vacuous). See DRIVE CHANNEL note above.
        action_mode="text",
        # The "text" prompt lists the command vocabulary from config.action_mappings
        # and the per-run "KEY VALUES" line reads config.playtest — pass cfg explicitly.
        config=cfg,
        # One definition, both tiers: hand the SAME NEXUS invariant suite to the
        # playtest loop exactly as R3 hands it to the ExploitHunter. Its wrappers
        # read info["command"]/info["result"], which is the {command,result,state}
        # info dict NexusHttpAdapter.type_text_step returns (nexus_http.py:242).
        invariants=lambda ad: invariants.SUITE.to_hunter_invariants(),
        output_path=REPORT_PATH,
    )

    summary = report.get("summary", {})
    actions = summary.get("actions_taken", 0)
    action_log = report.get("action_log", [])
    typed_delta_steps = sum(
        1 for e in action_log
        if e.get("action_type") == "type_text" and e.get("state_delta")
    )
    typed_steps = sum(1 for e in action_log if e.get("action_type") == "type_text")
    invariants_ran = "invariant_violations" in report
    violations = len(report.get("invariant_violations", []))

    print()
    print(f"[=] actions_taken               = {actions}")
    print(f"[=] typed (type_text) commands  = {typed_steps}")
    print(f"[=] typed commands with a delta = {typed_delta_steps}")
    print(f"[=] invariant suite ran         = {invariants_ran} (violations={violations})")
    print(f"[=] report                      = {REPORT_PATH}")

    ok = actions >= 20 and typed_delta_steps >= 1 and invariants_ran
    print(f"\n{'PLAYTEST MET' if ok else 'PLAYTEST NOT MET'} — "
          f"actions>=20:{actions >= 20} typed_delta_steps>=1:{typed_delta_steps >= 1} "
          f"invariants_ran:{invariants_ran}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
