#!/usr/bin/env python3
"""
Nexus Dominion LLM playtest via the L-002 legal-action drive mode.

An LLM reads NexusDominionHarnessAdapter's OWN normalized state (`_read_state`)
plus a legal-action list, and picks ONE action per step by index. The SAME
playtest loop as the browser/simulation/real_server path runs — state-delta
assertion, bug-report shape, and the Nexus Dominion FLAT invariant suite
(`invariants.ALL_FLAT_PREDICATES`, whose predicates are literal before/after
assertions that can fail) — this task only ADDS the input channel, not a second
tester. The invariants are the same predicates R3 hands to the ExploitHunter,
via `InvariantSuite(...).to_hunter_invariants()` (one definition, both tiers).

WHY a local subclass (PlaytestNexusDominionAdapter) instead of methods on the
shared adapter:
  * The L-002 entry point requires `legal_actions()` + `apply_legal()`. DDD's live
    on its adapter because they relay ENGINE truth (`_legal(seat)`). Nexus Dominion
    has NO engine-provided legal-action enumerator — the engine silently refuses
    illegal orders — so "legal actions" here is the INTEGRATION's chosen action
    vocabulary (the config id space 0-17), which is integration-specific knowledge
    that belongs in integrations/, not in the pure-transport adapter.
  * Both methods are PURE RELAYS over the adapter's existing `action_name()` /
    `step()` primitives — no game logic, no fabricated effect (the sim_bridge
    discipline). An id the base adapter cannot compose still raises inside step().
  * Keeping the base adapter untouched GUARANTEES the R1/R2/R3 ladder and the
    exploit-hunter are structurally unaffected by this task.

DISCLOSED NARROWING: legal_actions() offers action ids 0-17 and DELIBERATELY
omits ids 18/19 (probe_unknown_type / probe_malformed). Those two are R3
robustness probes that send deliberately-malformed orders the engine should
refuse — they are not meaningful balance actions, so they have no place in a
balance-playtester's legal menu. This is a stated narrowing, not a hidden one.

Run (from the UGT repo root; node >=24, Nexus Dominion deps installed — the
adapter spawns the harness itself, there is no server to start). Use ollama
(free/local) to validate:

    python3 integrations/nexus-dominion/playtest_nexus_dominion.py --provider ollama
    python3 integrations/nexus-dominion/playtest_nexus_dominion.py --provider ollama --max-actions 40

Exit 0 + "PLAYTEST MET" means: >=20 actions taken, >=1 legal_action step with a
non-empty state delta, and the invariant suite ran (an invariant_violations list
is present in the report). NOTE: the load-bearing assertion is the FLAT invariant
suite (`inv_cycle_advances_only_on_commit`, `inv_no_negative_resources`,
`inv_hash_progress`, ...), which are literal before/after checks that CAN fail;
the delta-step tally is a secondary liveness signal — Nexus Dominion's `cycle`
advances on every commit, so a non-empty delta is essentially guaranteed.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import invariants as ND  # noqa: E402  (local module, from integrations/nexus-dominion/)

from ugt.adapters.nexus_dominion_harness import NexusDominionHarnessAdapter  # noqa: E402
from ugt.core.playtester import playtest_game_with_adapter  # noqa: E402
from ugt.core.trial import InvariantSuite  # noqa: E402
from ugt.utils.config_parser import UgtConfig  # noqa: E402

CONFIG_PATH = "integrations/nexus-dominion/ugt.config.yaml"
GUIDE_PATH = "integrations/nexus-dominion/strategy-guide.md"
REPORT_PATH = "integrations/nexus-dominion/results/playtest-report.json"

# One-line balance note per real action id (0-17), lifted from the ugt.config.yaml
# action comments. Integration-level metadata for the LLM prompt — NOT game logic
# (no cost/probability/rule is encoded; the engine remains authoritative).
ACTION_NOTES = {
    0: "commit an empty order list (advance the cycle, do nothing)",
    1: "claim an unclaimed system adjacent to one you own (expand)",
    2: "build a unit of the first registry type (military)",
    3: "build a unit of a random type (military)",
    4: "build an installation on an owned system (resource boost)",
    5: "build a wormhole to a non-home system (connectivity)",
    6: "buy a resource on the market (spend credits)",
    7: "sell a resource on the market (earn credits)",
    8: "research — spend accrued researchPoints to climb a tier",
    9: "select a doctrine path (war-machine / fortress / commerce)",
    10: "select a specialization within your doctrine",
    11: "propose a pact with a bot empire (diplomacy)",
    12: "break your first existing pact (diplomacy)",
    13: "fund the syndicate (100 credits, covert)",
    14: "purchase a black-register item (covert intel)",
    15: "launch a covert op against a bot (recon / sabotage / steal)",
    16: "attack an adjacent enemy system with your units",
    17: "move a fleet to an adjacent system",
}


class PlaytestNexusDominionAdapter(NexusDominionHarnessAdapter):
    """Adds the L-002 legal-action surface over Nexus Dominion's fixed config id
    vocabulary. Both methods are PURE RELAYS over the base adapter's existing
    `action_name()` / `step()` primitives — no game logic, no fabricated effect.

    LEGAL_IDS is ids 0-17: every composable action, DELIBERATELY excluding the two
    R3 malformed probes (18=probe_unknown_type, 19=probe_malformed), which are not
    balance actions. This narrowing is disclosed in the module docstring.
    """

    LEGAL_IDS = list(range(18))  # 0..17; omit 18/19 (the R3 malformed probes)

    def legal_actions(self):
        """The integration's legal action menu, as {id, name, note} dicts.

        Relay only: `action_name()` is the base adapter's config id->name map.
        The engine, not this list, is the final authority on whether a given
        order applies in the current state (its silent-refusal contract is part
        of what the trial observes)."""
        return [
            {"id": i, "name": self.action_name(i), "note": ACTION_NOTES.get(i, "")}
            for i in self.LEGAL_IDS
        ]

    def apply_legal(self, action, legal_count=None):
        """Execute one chosen legal action. Relay to the base adapter's step(),
        which composes the order from structural state reads and returns the
        standard (state, terminated, truncated, info) 4-tuple whose `info` carries
        command="commit" + a `result` sub-dict — exactly what the flat invariant
        suite reads. No behavior is invented here."""
        return self.step(int(action["id"]))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Nexus Dominion LLM playtest (legal-action mode)")
    parser.add_argument("--provider", default="ollama", choices=["ollama", "anthropic"],
                        help="LLM provider (default: ollama — free/local)")
    parser.add_argument("--model", default=None,
                        help="model override (provider default if unset)")
    parser.add_argument("--max-actions", type=int, default=30,
                        help="max LLM actions this run (default 30 — margin over "
                             "the 20 bar, under the 50-cycle truncation)")
    args = parser.parse_args()

    cfg = UgtConfig(CONFIG_PATH)
    adapter = PlaytestNexusDominionAdapter(cfg)
    with open(GUIDE_PATH) as fh:
        guide = fh.read()

    report = playtest_game_with_adapter(
        adapter,
        provider=args.provider,
        strategy_guide=guide,
        max_actions=args.max_actions,
        model=args.model,
        action_mode="legal_action",
        # One definition, both tiers: hand the Nexus Dominion FLAT invariant suite
        # to the playtest loop exactly as R3 hands it to the ExploitHunter.
        invariants=lambda ad: InvariantSuite(ND.ALL_FLAT_PREDICATES).to_hunter_invariants(),
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
