#!/usr/bin/env python3
"""
Pond Conspiracy LLM playtest — the MACRO layer, via the L-002 legal-action drive
mode (`playtest_game_with_adapter`, action_mode="legal_action").

WHY macro-only (not frame-by-frame): real-time per-frame dodging is not a
reasoning task and was already judged the wrong granularity for an LLM loop. The
one decision class in this game that IS a reasoning task is the LEVEL-UP mutation
choice — a macro tradeoff (offense vs survivability vs Pollution vs investigation,
plus synergies and the PC-15 boss-scaling caveat). So the LLM is consulted ONLY at
each `level_up_pending()` decision point; the combat BETWEEN level-ups is driven by
the EXACT R1 heuristic (`verify_round1.heuristic_combat_action`), reused verbatim —
never a rewrite (the sim_bridge discipline).

HOW it fits L-002 with ZERO changes to ugt/core/playtester.py: the generic loop
prompts the LLM on every step where `adapter.legal_actions()` is non-empty
(playtester.py:303-323, :431-443). We make `legal_actions()` return non-empty
EXACTLY WHEN a level-up is pending, and push all combat-driving into `reset()` and
`apply_legal()` (they fast-forward with the R1 heuristic to the NEXT level-up or a
terminal, returning the state AT that decision point). The loop then naturally
calls the LLM at each level-up and nowhere else, and `_build_legal_prompt` builds
its state prompt from that exact snapshot (playtester.py:322/326) — fresh, never
stale. This mirrors the L-003 precedent (PlaytestNexusDominionAdapter): a LOCAL
subclass in the integration script, leaving the base `PondHarnessAdapter` — and
therefore the whole R1/R2/R3 ladder + exploit-hunter — structurally untouched.

The invariant suite is the SAME one R3 hands the ExploitHunter
(`invariants.build_suite().to_hunter_invariants()`) — one definition, both tiers.
DISCLOSED COARSENING: here the predicates fire at each DECISION BOUNDARY
(before = the level-up snapshot, after = the next level-up / terminal snapshot),
not on every intermediate combat frame — per-frame robustness stays R3's job. Each
predicate can still FAIL on those boundary snapshots (hp bounds, finite positions,
run-state consistency, level-up-freezes-the-game, mutations/evidence monotonic,
death-is-terminal), so this is coarser coverage, not a vacuous check.

Run (from the UGT repo root; needs godot 4.7 on PATH or UGT_GODOT_BIN, and an
Ollama server for --provider ollama — the adapter spawns the game itself, no
server to start):

    python3 integrations/pond/playtest_pond.py --provider ollama --model qwen3-coder:30b
    python3 integrations/pond/playtest_pond.py --provider ollama --max-actions 40 --seed 20260719

Exit 0 + "PLAYTEST MET" means: the LLM decided at >=1 level-up, EVERY legal_action
step applied a real mutation (mutations_taken delta == +1 — the load-bearing,
failable check, read from live per-run game state), >=1 run reached a terminal
(death/victory/truncation), and the invariant suite ran.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import invariants  # noqa: E402  (local module, from integrations/pond/)
from verify_round1 import heuristic_combat_action  # noqa: E402  (REUSE R1's combat policy)

from ugt.adapters.pond_harness import PondHarnessAdapter  # noqa: E402
from ugt.core.playtester import playtest_game_with_adapter  # noqa: E402
from ugt.utils.config_parser import UgtConfig  # noqa: E402

CONFIG_PATH = "integrations/pond/ugt.config.yaml"
GUIDE_PATH = "integrations/pond/strategy-guide.md"
REPORT_PATH = "integrations/pond/results/playtest-report.json"


class MacroPlaytestPondAdapter(PondHarnessAdapter):
    """Adds the L-002 legal-action surface, confining the LLM to the macro layer.

    Every method is a PURE RELAY over the base adapter's existing primitives
    (`reset`/`step`/`level_up_pending`/`level_up_options`/`choose_mutation`) plus
    the reused R1 combat heuristic — no game logic, no fabricated behavior. An
    unmapped action still raises NotImplementedError inside the base `_compose`.

    The base adapter, and thus the R1/R2/R3 ladder, is untouched.
    """

    # Belt-and-suspenders cap on one fast-forward segment. The real limit is the
    # base adapter's own `max_steps` truncation (per-episode, resets to 0 on
    # reset), which guarantees a terminal regardless; this only stops a pathological
    # segment from spinning if a level-up somehow never arrives.
    MAX_COMBAT_STEPS = 600

    def __init__(self, config=None, first_seed=None, run_number=None):
        super().__init__(config)
        self._first_seed = first_seed
        self._pin_run_number = run_number
        self._reset_calls = 0
        # Terminal accounting so the MET gate can report HOW runs ended (death vs
        # truncation vs victory) — read off the adapter after the run, R3-style.
        self.deaths = 0
        self.truncations = 0
        self.victories = 0        # RUN_END reached without player_dead (victory path)
        self.mutations_applied = 0  # count of choose_mutation() calls that landed

    # ── combat between decisions: fast-forward with the R1 heuristic ──────────
    def _drive_to_decision(self, state):
        """Fast-forward combat with the reused R1 heuristic until a level-up is
        pending OR the run terminates/truncates. NO LLM here — this is the
        between-decisions combat, driven by the SAME policy R1 validates.

        Returns (state, terminated, truncated, info); info carries the raw
        snapshot as `result` + command="step" so the invariant suite (via
        to_hunter_invariants) fingerprints the real world at the decision boundary
        — exactly the wiring R3's HuntAdapter.step uses."""
        snap = self.last_snapshot or {}
        terminated = bool(state["player_dead"]) or \
            (snap.get("run") or {}).get("phase") == "RUN_END"
        truncated = False
        steps = 0
        while (not self.level_up_pending() and not terminated and not truncated
               and steps < self.MAX_COMBAT_STEPS):
            action = heuristic_combat_action(state)
            state, terminated, truncated, _info = super().step(action)
            steps += 1

        # Count the terminal exactly once, at the single site every run's combat
        # drive passes through (reset()'s initial drive OR each apply_legal()).
        if terminated:
            if state["player_dead"]:
                self.deaths += 1
            else:
                self.victories += 1
        elif truncated:
            self.truncations += 1

        info = {"result": self.last_snapshot, "command": "step",
                "combat_steps": steps}
        return state, terminated, truncated, info

    # ── BaseAdapter overrides ─────────────────────────────────────────────────
    def reset(self, seed=None, run_number=None, with_board=False):
        """Fresh episode, then fast-forward to the FIRST level-up (or a terminal).
        The loop calls this with no args; the first reset honors a pinned seed for
        reproducibility, later resets let the base derive a distinct per-episode
        seed (real run isolation)."""
        if seed is None and self._reset_calls == 0:
            seed = self._first_seed
        if run_number is None:
            run_number = self._pin_run_number
        self._reset_calls += 1
        state = super().reset(seed=seed, run_number=run_number,
                              with_board=with_board)
        state, _t, _tr, _i = self._drive_to_decision(state)
        return state

    # ── L-002 legal-action surface (relay only) ───────────────────────────────
    def legal_actions(self):
        """Non-empty EXACTLY at a level-up — this is what confines the LLM to the
        macro layer. Each option carries its laid-out index (for apply_legal) plus
        the harness's own {name, id} for the prompt. Between level-ups this returns
        [], which the generic loop treats as 'episode over' -> reset() (whose drive
        then advances to the next decision)."""
        if not self.level_up_pending():
            return []
        return [{"index": i, "name": o.get("name"), "id": o.get("id")}
                for i, o in enumerate(self.level_up_options())]

    def apply_legal(self, action, legal_count=None):
        """Execute one LLM mutation pick (a real MutationCard click), then
        fast-forward combat to the next decision / terminal. Relay only:
        choose_mutation() is the base adapter's real click path (it raises if the
        click is refused — no fabricated selection)."""
        idx = int(action["index"])
        state, _events = self.choose_mutation(idx)
        self.mutations_applied += 1
        state, terminated, truncated, info = self._drive_to_decision(state)
        info["chosen_mutation"] = action.get("name")
        info["chosen_index"] = idx
        return state, terminated, truncated, info


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pond Conspiracy macro-layer LLM playtest (level-up choices)")
    parser.add_argument("--provider", default="ollama",
                        choices=["ollama", "anthropic"],
                        help="LLM provider (default: ollama — free/local)")
    parser.add_argument("--model", default=None,
                        help="model override (provider default if unset; e.g. "
                             "qwen3-coder:30b for ollama)")
    parser.add_argument("--max-actions", type=int, default=40,
                        help="max LLM level-up decisions this run (default 40 — "
                             "margin for several level-ups AND >=1 terminal)")
    parser.add_argument("--seed", type=int, default=None,
                        help="pin the first run's game seed (reproducibility); "
                             "later episodes derive distinct seeds")
    parser.add_argument("--run-number", type=int, default=None,
                        help="pin the lifetime run count (selects arena/difficulty; "
                             "default: virgin run 1)")
    parser.add_argument("--max-steps", type=int, default=None,
                        help="OVERRIDE the adapter's per-episode truncation bound "
                             "(default: the config's 600). Lower it for a faster "
                             "validation — DISCLOSED tuning of the truncation only, "
                             "not of combat driving.")
    args = parser.parse_args()

    cfg = UgtConfig(CONFIG_PATH)
    adapter = MacroPlaytestPondAdapter(cfg, first_seed=args.seed,
                                       run_number=args.run_number)
    if args.max_steps is not None:
        adapter.max_steps = int(args.max_steps)
    with open(GUIDE_PATH) as fh:
        guide = fh.read()

    report = playtest_game_with_adapter(
        adapter,
        provider=args.provider,
        strategy_guide=guide,
        max_actions=args.max_actions,
        model=args.model,
        action_mode="legal_action",
        # One definition, both tiers: the SAME invariant suite R3 hands the
        # ExploitHunter, asserted here at each decision boundary.
        invariants=lambda ad: invariants.build_suite().to_hunter_invariants(),
        output_path=REPORT_PATH,
    )

    # ── MET gate (each criterion prints its boolean and CAN fail) ─────────────
    summary = report.get("summary", {})
    action_log = report.get("action_log", [])
    legal_steps = [e for e in action_log if e.get("action_type") == "legal_action"]
    mutation_choices = len(legal_steps)

    # LOAD-BEARING: every LLM level-up pick applied a REAL mutation, evidenced by
    # a +1 delta on mutations_taken read from live per-run game state. Fails if any
    # pick were a no-op. (The only way this is not +1 is the 10-mutation cap, which
    # needs ~100 kills in one run — not reachable in a bounded playtest.)
    deltas = [e.get("state_delta", {}).get("mutations_taken") for e in legal_steps]
    every_pick_applied = mutation_choices >= 1 and all(d == "+1" for d in deltas)

    at_least_one_full_run = summary.get("episode_resets", 0) >= 1 \
        or bool(summary.get("lost_game"))
    invariants_ran = "invariant_violations" in report
    violations = len(report.get("invariant_violations", []))

    # Reasoning/expected present on every recorded pick (report-quality guard).
    picks_documented = mutation_choices >= 1 and all(
        (e.get("reasoning") or "").strip() and (e.get("expected") or "").strip()
        for e in legal_steps)

    print()
    print(f"[=] mutation choices (LLM level-up decisions) = {mutation_choices}")
    print(f"[=]   mutations_taken deltas                  = {deltas}")
    print(f"[=]   every pick applied (+1 each)            = {every_pick_applied}")
    print(f"[=]   every pick has reasoning + expected     = {picks_documented}")
    print(f"[=] episode_resets (runs reaching a terminal) = "
          f"{summary.get('episode_resets', 0)}")
    print(f"[=]   terminal kinds: deaths={adapter.deaths} "
          f"truncations={adapter.truncations} victories={adapter.victories}")
    print(f"[=] invariant suite ran = {invariants_ran} (violations={violations})")
    print(f"[=] bugs flagged        = {summary.get('bugs_flagged', 0)}")
    print(f"[=] report              = {REPORT_PATH}")

    ok = (mutation_choices >= 1 and every_pick_applied and picks_documented
          and at_least_one_full_run and invariants_ran)
    print(f"\n{'PLAYTEST MET' if ok else 'PLAYTEST NOT MET'} — "
          f"mutation_choices>=1:{mutation_choices >= 1} "
          f"every_pick_applied:{every_pick_applied} "
          f"picks_documented:{picks_documented} "
          f"full_run:{at_least_one_full_run} invariants_ran:{invariants_ran}")
    if adapter.deaths == 0 and adapter.victories == 0 and adapter.truncations > 0:
        print("[note] every completed run ended by TRUNCATION, not death/victory — "
              "the R1 survival heuristic outlasted the truncation bound. Recorded "
              "as a balance observation (not hacked into a suicide).")
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\ninterrupted")
        raise SystemExit(130)
