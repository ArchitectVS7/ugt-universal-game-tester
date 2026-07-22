#!/usr/bin/env python3
"""
DDD LLM-vs-opponent playtest — pits the LLM on ONE seat against a FIXED,
non-LLM opponent on the other, instead of `playtest_ddd.py`'s self-play (the
same LLM driving both seats).

Why this exists: self-play measures "if one competent policy pilots both
sides, does the match play out sanely" — it does not measure how the LLM
performs against a distinct, independent opponent, which is the actual
question a balance/strategy read needs answered before human playtesting.

Opponent choices (--opponent):
  self    — the SAME LLM plays both seats (playtest_ddd.py's existing mode,
            included here for a same-harness comparison point).
  random  — DDD's real tier-1 AI (packages/ai/src/tier1/uniformRandom.ts).
  greedy  — DDD's real tier-2 AI (packages/ai/src/tier2/greedy.ts).
  tier3   — DDD's real tier-3 AI (packages/ai/src/tier3/onePly.ts).

random/greedy/tier3 are driven through a NEW stdio helper added to the DDD
repo, packages/ai/bin/choose-move.mjs, which exposes @ddd/ai's REAL strategies
(pure functions of a seat's own PlayerView + a public ContentIndex + an RNG
seed — packages/ai/src/strategy.ts) as a move-picker service. This Python side
never decides a move for that seat: it forwards DddHarnessAdapter.seat_view()
(the engine's own raw view for that seat, already cached from the last
create/act response) to the helper and submits whatever Action comes back via
adapter.apply_legal — the SAME submission path every other action in this
harness uses. No change to packages/harness's wire protocol; no game logic
duplicated on either side (the sim_bridge discipline this whole harness holds
to). See ugt/adapters/ddd_harness.py::seat_view and DDD's
packages/ai/bin/choose-move.mjs for the two halves of this seam.

Isolation (raised explicitly by the user): every LLM decision
(`llm.choose_action`) is ONE stateless API/HTTP call built by
`_build_legal_prompt` — it carries only the current normalized state (public
p0/p1 fields only; neither seat's hand contents are ever in that block) and
the ACTING seat's own legal-action list (which alone carries that seat's own
hand-card identities). No conversation history is kept between calls, and the
recent-actions summary shown in every prompt carries only the action's index
and a fog-of-war-redacted delta — never the free-text `reasoning` a prior
decision produced. So even in `--opponent self`, "the seat about to move" is
never shown "the other seat's" prior internal reasoning or hand — only the
same public reveal a real opponent would see. This script changes no data
path from `playtest_ddd.py`; it only reuses the same prompt builder per seat.

Run (from the UGT repo root; node >=24, DDD deps installed):

    python3 integrations/ddd/playtest_ddd_matchup.py --opponent random
    python3 integrations/ddd/playtest_ddd_matchup.py --opponent greedy --max-actions 40
    python3 integrations/ddd/playtest_ddd_matchup.py --opponent tier3
    python3 integrations/ddd/playtest_ddd_matchup.py --opponent self

Report: integrations/ddd/results/playtest-matchup-<opponent>.json
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import invariants  # noqa: E402  (local module, from integrations/ddd/)

from ugt.adapters.ddd_harness import DddHarnessAdapter  # noqa: E402
from ugt.core.playtester import (  # noqa: E402
    _AnthropicLLM,
    _OllamaLLM,
    _build_legal_prompt,
    _compute_delta,
    _make_bug_report,
    _unexpected_delta_fields,
)
from ugt.utils.config_parser import UgtConfig  # noqa: E402

CONFIG_PATH = "integrations/ddd/ugt.config.yaml"
GUIDE_PATH = "integrations/ddd/strategy-guide.md"
RESULTS_DIR = "integrations/ddd/results"

CHOOSE_MOVE_ENTRY = "/Users/vs7/Dev/Games/DDD/packages/ai/bin/choose-move.mjs"
NODE_BIN = "node"

# Display name (this script's --opponent flag) -> the AI_TIERS name
# packages/ai/src/strategy.ts and choose-move.mjs use.
TIER_NAMES = {"random": "TUTORIAL", "greedy": "BEGINNER", "tier3": "INTERMEDIATE"}


class AiChooser:
    """Stdio transport to DDD's packages/ai/bin/choose-move.mjs. Pure relay —
    this class never picks a move itself, only forwards a view and returns
    whatever Action the real @ddd/ai strategy chose."""

    def __init__(self):
        self.process = subprocess.Popen(
            [NODE_BIN, CHOOSE_MOVE_ENTRY],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )
        self._req_id = 0

    def choose(self, tier: str, view: dict, rng_seed: str) -> dict:
        self._req_id += 1
        req = {"id": self._req_id, "tier": tier, "view": view, "rngSeed": rng_seed}
        self.process.stdin.write(json.dumps(req) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            err = self.process.stderr.read() if self.process.stderr else ""
            raise RuntimeError(f"choose-move exited: {err or '<empty>'}")
        resp = json.loads(line)
        if not resp.get("ok"):
            raise RuntimeError(f"choose-move error: {resp.get('error')}")
        return resp["action"]

    def close(self):
        if self.process and self.process.poll() is None:
            try:
                self.process.stdin.close()
                self.process.terminate()
                self.process.wait(timeout=2)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass


def run_matchup(adapter, llm, chooser, opponent, llm_seat, config, strategy_guide,
                 max_actions, playtest_cfg, invariant_list, run_seed):
    """One match: LLM on `llm_seat`, `opponent` on the other (or the SAME llm on
    both seats when opponent == "self"). Mirrors ugt/core/playtester.py's
    `_run_single_playtest` legal_action branch (delta/bug/invariant machinery
    reused verbatim) but routes non-LLM-seat turns through `chooser` instead of
    a second LLM call."""
    opponent_tier = TIER_NAMES.get(opponent)
    current_state = adapter.reset()
    baseline_state = json.loads(json.dumps(current_state, default=str))

    action_log = []
    potential_bugs = []
    novel_behaviors = []
    invariant_violations = []
    action_counts = {}
    episode_resets = 0
    ended_early = None
    inv_ctx = {}
    start_time = time.time()

    llm_step_num = 0  # only LLM decisions count against max_actions
    total_steps = 0

    while llm_step_num < max_actions:
        total_steps += 1
        if total_steps > max_actions * 20:
            ended_early = "step_budget_exhausted (opponent never yielded to the LLM)"
            break

        legal_list = adapter.legal_actions()
        if not legal_list:
            pre_reset = current_state
            try:
                current_state = adapter.reset()
            except Exception:
                ended_early = "no_legal_actions_and_reset_failed"
                break
            baseline_state = json.loads(json.dumps(current_state, default=str))
            episode_resets += 1
            inv_ctx.clear()
            continue

        seat = current_state.get("pendingSeat")
        is_llm_turn = opponent == "self" or seat == llm_seat

        before_state = json.loads(json.dumps(current_state, default=str))

        if is_llm_turn:
            llm_step_num += 1
            prompt = _build_legal_prompt(config, strategy_guide, current_state,
                                         legal_list, action_log, playtest_cfg)
            try:
                llm_action = llm.choose_action(prompt)
            except Exception as api_err:
                print(f"  [Step {llm_step_num}] LLM error: {api_err}")
                ended_early = f"llm_error: {api_err}"
                break

            action_type = llm_action.get("action_type", "wait")
            value = llm_action.get("value", "")
            reasoning = llm_action.get("reasoning", "")
            expected = llm_action.get("expected_outcome", "")
            potential_bug = llm_action.get("potential_bug", "")
            is_novel = bool(llm_action.get("is_novel", False))

            print(f"  [Step {llm_step_num}] seat{seat} (LLM) legal_action({value!r}) — {reasoning[:60]}")

            if potential_bug:
                potential_bugs.append(_make_bug_report(
                    step=llm_step_num, source="llm_flag", description=potential_bug,
                    action_log=action_log,
                    current_action={"step": llm_step_num, "action_type": action_type,
                                    "action": value, "expected": expected},
                    preconditions=current_state, post_state=current_state,
                    expected=expected, actual=potential_bug, terminal_text="",
                ))

            if action_type != "legal_action":
                # A non-move response (wait/diagnose) still consumes an LLM
                # decision but has no engine action to submit.
                action_log.append({
                    "step": llm_step_num, "action_type": action_type, "action": value,
                    "reasoning": reasoning, "expected": expected, "state_delta": {},
                })
                continue

            try:
                idx = int(str(value).strip())
            except (ValueError, TypeError):
                idx = -1
            if not (0 <= idx < len(legal_list)):
                print(f"  [Step {llm_step_num}] legal index {value!r} out of range — skipping")
                continue

            current_state, terminated, truncated, step_info = adapter.apply_legal(
                legal_list[idx], legal_count=len(legal_list))
            executed_action_id = -1
            step_label = "legal_action"
            action_value = value
        else:
            view = adapter.seat_view(seat)
            try:
                action = chooser.choose(opponent_tier, view, rng_seed=f"{run_seed}-s{seat}-{total_steps}")
            except Exception as chooser_err:
                print(f"  [step {total_steps}] opponent ({opponent}) error: {chooser_err}")
                ended_early = f"opponent_error: {chooser_err}"
                break
            current_state, terminated, truncated, step_info = adapter.apply_legal(
                action, legal_count=len(legal_list))
            executed_action_id = -1
            step_label = f"opponent:{opponent}"
            action_value = action.get("t") if isinstance(action, dict) else str(action)
            print(f"  [step {total_steps}] seat{seat} ({opponent}) {action_value}")

        after_state = current_state
        delta = _compute_delta(before_state, after_state)
        log_entry = {
            "step": total_steps, "seat": seat, "action_type": step_label,
            "action": action_value, "state_delta": delta,
        }
        action_log.append(log_entry)
        action_counts[f"{step_label}:{action_value}"] = action_counts.get(f"{step_label}:{action_value}", 0) + 1

        if invariant_list and executed_action_id is not None:
            for inv in invariant_list:
                try:
                    msg = inv.check(before_state, executed_action_id, step_info, current_state, inv_ctx)
                except Exception as inv_err:
                    msg = f"invariant check crashed: {inv_err}"
                if msg:
                    invariant_violations.append({
                        "step": total_steps, "name": getattr(inv, "name", inv.__class__.__name__),
                        "message": msg, "seat": seat, "driver": step_label,
                    })
                    print(f"  [!!] INVARIANT VIOLATION [{getattr(inv, 'name', '?')}]: {msg}")

        if terminated or truncated:
            print(f"  [step {total_steps}] Episode ended (terminated={terminated}) — resetting")
            pre_reset = current_state
            try:
                current_state = adapter.reset()
                episode_resets += 1
                inv_ctx.clear()
                baseline_state = json.loads(json.dumps(current_state, default=str))
                action_log.append({
                    "step": total_steps, "action_type": "episode_reset", "action": "EPISODE_RESET",
                    "final_p0_hp": pre_reset.get("p0", {}).get("hp"),
                    "final_p1_hp": pre_reset.get("p1", {}).get("hp"),
                    "resultKind": pre_reset.get("resultKind"),
                })
            except Exception:
                ended_early = "reset_failed_after_episode_end"
                break

    duration = time.time() - start_time
    summary = {
        "opponent": opponent,
        "llm_seat": llm_seat,
        "llm_actions": llm_step_num,
        "total_steps": total_steps,
        "episode_resets": episode_resets,
        "bugs_flagged": len(potential_bugs),
        "invariant_violations": len(invariant_violations),
        "novel_behaviors": len(novel_behaviors),
        "duration_seconds": round(duration, 1),
        "ended_early": ended_early,
        "p0_hp_final": current_state.get("p0", {}).get("hp"),
        "p1_hp_final": current_state.get("p1", {}).get("hp"),
        "resultKind": current_state.get("resultKind"),
    }
    return {
        "summary": summary,
        "action_log": action_log,
        "potential_bugs": potential_bugs,
        "invariant_violations": invariant_violations,
        "action_counts": action_counts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="DDD LLM-vs-opponent playtest")
    parser.add_argument("--opponent", default="self", choices=["self", "random", "greedy", "tier3"])
    parser.add_argument("--provider", default="ollama", choices=["ollama", "anthropic"])
    parser.add_argument("--model", default=None)
    parser.add_argument("--max-actions", type=int, default=40,
                        help="LLM decisions this run (opponent moves are free, not counted)")
    parser.add_argument("--llm-seat", type=int, default=0, choices=[0, 1])
    parser.add_argument("--seed", default=None, help="RNG seed prefix for the opponent AI (default: opponent name)")
    args = parser.parse_args()

    cfg = UgtConfig(CONFIG_PATH)
    adapter = DddHarnessAdapter(cfg)
    with open(GUIDE_PATH) as fh:
        guide = fh.read()
    playtest_cfg = cfg.data.get("playtest", {}) if isinstance(cfg.data, dict) else {}
    invariant_list = invariants.build_suite().to_hunter_invariants()

    if args.provider == "anthropic":
        llm = _AnthropicLLM(args.model or "claude-haiku-4-5-20251001")
    else:
        llm = _OllamaLLM(args.model or "gemma4:26b")

    chooser = AiChooser() if args.opponent != "self" else None
    run_seed = args.seed or f"matchup-{args.opponent}"

    print(f"[*] DDD matchup — LLM(seat {args.llm_seat}, {args.provider}/{llm.model}) vs "
          f"{'itself (self-play)' if args.opponent == 'self' else args.opponent} "
          f"(max {args.max_actions} LLM actions)")

    adapter.connect()
    try:
        report = run_matchup(adapter, llm, chooser, args.opponent, args.llm_seat,
                             cfg, guide, args.max_actions, playtest_cfg, invariant_list, run_seed)
    finally:
        adapter.close()
        if chooser:
            chooser.close()

    os.makedirs(RESULTS_DIR, exist_ok=True)
    model_tag = (llm.model or args.provider).replace("/", "-").replace(":", "-")
    out_path = os.path.join(
        RESULTS_DIR, f"playtest-matchup-{args.opponent}-seat{args.llm_seat}-{model_tag}.json")
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    s = report["summary"]
    print()
    for k, v in s.items():
        print(f"[=] {k:20s} = {v}")
    print(f"[=] report               = {out_path}")

    ok = s["llm_actions"] >= 20 and s["invariant_violations"] == 0 and s["ended_early"] is None
    print(f"\n{'MATCHUP SMOKE MET' if ok else 'MATCHUP SMOKE NOT MET'} — "
          f"llm_actions>=20:{s['llm_actions'] >= 20} "
          f"invariant_violations==0:{s['invariant_violations'] == 0} "
          f"ended_early is None:{s['ended_early'] is None}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
