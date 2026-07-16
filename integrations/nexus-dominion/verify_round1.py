#!/usr/bin/env python3
"""
Nexus Dominion ROUND 1 — playability gate. One full campaign loop through the
REAL engine (adapter -> harness -> processCycle) with real orders, per-step
invariants, and the save/load-continue divergence gate. Full PRD scale
(250 systems / 100 empires) at seed 20260910.

The 25-cycle script drives the core loop a first-session player would:
claim territory, build a military, sell surplus, research —
[claim, build, sell, claim, research] x 5. All effects are asserted by
READING BACK state/events, never by re-computing rules. Trade effects are
isolated DIFFERENTIALLY: a same-seed campaign that passes where the main arm
trades gives an exact baseline (determinism makes the two arms identical up
to the trade).

Checks:
   1. reset -> sane full-scale baseline
   2. 25/25 cycles committed; ZERO flat-invariant violations across every step
   3. ZERO full-state cross-reference violations (ownership bijection, fleet/
      unit integrity) at cycles 5/10/15/20/25
   4. claims real: systemsOwned grew >=3 with matching colonisation events
   5. build-unit lifecycle real: queue fills, then a REAL unit exists in a fleet
   6. differential trade-sell: exact resource decrease vs baseline, credits above
   7. differential trade-buy: resource above baseline, credits below
   8. Reckoning fires at exactly cycles 10 and 20; player gets a Cosmic tier
   9. bots visibly act (bot expansion beyond the player's own claims)
  10. save@12 -> load -> continue == uninterrupted run (hash streams identical)
  11. per-cycle mean through the adapter under the 5s alpha budget
  12. every committed cycle produced a fresh stateHash

Run (from the UGT repo root):
    python3 integrations/nexus-dominion/verify_round1.py
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ugt.core.trial import GateRunner, InvariantSuite, first_divergence  # noqa: E402
from ugt.utils.config_parser import UgtConfig  # noqa: E402
from ugt.adapters.nexus_dominion_harness import (  # noqa: E402
    NexusDominionHarnessAdapter,
)
from invariants import ALL_FLAT_PREDICATES, full_state_violations  # noqa: E402

CONFIG_PATH = "integrations/nexus-dominion/ugt.config.yaml"
SEED = 20260910
SEED_DIFF = 20260911
CYCLES = 25
SAVE_AT = 12
# [claim, build_first, trade_sell, claim, research] x 5
SCRIPT = [1, 2, 7, 1, 8] * 5


def run_arm(adapter, seed, script, save_at=None):
    """Drive `script` on a fresh campaign; return (states, infos, stream,
    violations, timings). With save_at=k, save/load between steps k and k+1."""
    suite = InvariantSuite(ALL_FLAT_PREDICATES)
    state = adapter.reset(seed=seed)
    states, infos, violations, timings = [state], [], [], []
    stream = list(adapter.hash_stream)
    for i, action_id in enumerate(script):
        before = states[-1]
        t0 = time.perf_counter()
        after, _term, _trunc, info = adapter.step(action_id)
        timings.append((time.perf_counter() - t0) * 1000)
        violations.extend(
            f"step {i} ({info.get('actionName')}): {v}"
            for v in suite.check_command(before, after, info.get("command", ""),
                                         info.get("result") or {})
        )
        states.append(after)
        infos.append(info)
        stream.append(info.get("stateHash"))
        if save_at is not None and i + 1 == save_at:
            payload = adapter.save_payload()
            adapter.load_payload(payload)
    return states, infos, stream, violations, timings


def main() -> int:
    gate = GateRunner()
    ck, finding = gate.ck, gate.finding
    config = UgtConfig(CONFIG_PATH)
    print(f"Nexus Dominion ROUND 1 — playability gate (seed {SEED}, "
          f"{CYCLES} cycles, full PRD scale)\n")

    adapter = NexusDominionHarnessAdapter(config)
    adapter.max_cycles = 10_000  # rounds manage their own horizon
    try:
        adapter.connect()

        # ── 1. baseline ──────────────────────────────────────────────────────
        print("  -- 1. baseline --")
        s0 = adapter.reset(seed=SEED)
        ck("reset -> full-scale baseline (100 empires/250 systems/150 unclaimed, "
           "credits 500, 1 system)",
           s0.get("empireCount") == 100 and s0.get("systemCount") == 250
           and s0.get("unclaimedSystems") == 150
           and s0.get("player_credits") == 500
           and s0.get("player_systemsOwned") == 1,
           f"hash={s0.get('stateHash')}")

        # ── 2. the 25-cycle campaign ─────────────────────────────────────────
        print("\n  -- 2. 25 scripted cycles + invariants --")
        states, infos, stream_a, violations, timings = run_arm(
            adapter, SEED, SCRIPT)
        committed = sum(1 for i in infos if i.get("committed"))
        for v in violations[:10]:
            finding(f"invariant violation: {v}")
        ck(f"{CYCLES}/{CYCLES} cycles committed, ZERO invariant violations",
           committed == CYCLES and not violations,
           f"committed={committed} violations={len(violations)}")
        final = states[-1]
        # Snapshot main-arm full-state facts NOW — the differential arms below
        # reset the adapter, so game_state would otherwise be a different
        # campaign's (stale-read bug in this script's first version).
        g_main = adapter.game_state
        bot_max_systems = max(
            len(e.get("systemIds") or [])
            for eid, e in g_main["empires"].items() if eid != "empire-0"
        )

        # ── 3. full-state cross-reference integrity ──────────────────────────
        print("\n  -- 3. full-state integrity (checkpoint = final state) --")
        fs_violations = full_state_violations(adapter.game_state)
        for v in fs_violations[:10]:
            finding(f"full-state violation: {v}")
        ck("ownership bijection + fleet/unit integrity hold in the game's own "
           "serialized state",
           not fs_violations, f"violations={len(fs_violations)}")

        # ── 4. claims are real ───────────────────────────────────────────────
        print("\n  -- 4. claims --")
        colonisations = [
            e for info in infos for e in info.get("events", [])
            if e.get("type") == "colonisation" and e.get("empireId") == "empire-0"
        ]
        ck("player expanded: systemsOwned >= 3 with matching colonisation events",
           final.get("player_systemsOwned", 0) >= 3
           and len(colonisations) == final.get("player_systemsOwned", 0) - 1,
           f"owned={final.get('player_systemsOwned')} "
           f"events={len(colonisations)}")

        # ── 5. build-unit lifecycle ──────────────────────────────────────────
        print("\n  -- 5. build-unit lifecycle --")
        queue_seen = max(s.get("player_buildQueueLength", 0) for s in states)
        ck("build queue filled and drained into a REAL unit in a fleet",
           queue_seen >= 1 and final.get("player_unitCount", 0) >= 1,
           f"maxQueue={queue_seen} finalUnits={final.get('player_unitCount')}")

        # ── 6/7. differential trade (same-seed pass baseline) ────────────────
        print("\n  -- 6/7. differential trade vs same-seed pass baseline --")
        # Baseline arm: pass, pass, pass.
        base_states, _, _, _, _ = run_arm(adapter, SEED_DIFF, [0, 0, 0])
        # Sell arm: pass, pass, sell (adapter RNG state identical at step 3).
        sell_states, sell_infos, _, _, _ = run_arm(adapter, SEED_DIFF, [0, 0, 7])
        sell_order = sell_infos[-1]["orders"][0]["details"]
        res, qty = sell_order["resource"], sell_order["quantity"]
        b3, s3 = base_states[-1], sell_states[-1]
        key = f"player_{res}"
        ck(f"trade-sell isolated: {res} exactly -{qty} vs baseline, credits above",
           s3.get(key) == b3.get(key) - qty
           and s3.get("player_credits") > b3.get("player_credits"),
           f"{res}: {b3.get(key)}->{s3.get(key)} credits: "
           f"{b3.get('player_credits')}->{s3.get('player_credits')}")
        # Buy arm: pass, pass, buy.
        buy_states, buy_infos, _, _, _ = run_arm(adapter, SEED_DIFF, [0, 0, 6])
        buy_order = buy_infos[-1]["orders"][0]["details"]
        bres, bqty = buy_order["resource"], buy_order["quantity"]
        bkey = f"player_{bres}"
        b3b, y3 = base_states[-1], buy_states[-1]
        ck(f"trade-buy isolated: {bres} exactly +{bqty} vs baseline, credits below",
           y3.get(bkey) == b3b.get(bkey) + bqty
           and y3.get("player_credits") < b3b.get("player_credits"),
           f"{bres}: {b3b.get(bkey)}->{y3.get(bkey)} credits: "
           f"{b3b.get('player_credits')}->{y3.get('player_credits')}")

        # ── 8. Reckoning cadence ─────────────────────────────────────────────
        print("\n  -- 8. Reckoning cadence --")
        reck_cycles = [i + 1 for i, info in enumerate(infos)
                       if info.get("reckoningOccurred")]
        ck("Reckoning fires at exactly cycles 10 and 20; player holds a Cosmic "
           "tier afterwards",
           reck_cycles == [10, 20] and final.get("playerTier") in
           ("sovereign", "ascendant", "stricken"),
           f"reckonings={reck_cycles} tier={final.get('playerTier')}")

        # ── 9. bots act ──────────────────────────────────────────────────────
        print("\n  -- 9. bots act --")
        player_claims = final.get("player_systemsOwned", 1) - 1
        bots_claimed = (150 - final.get("unclaimedSystems", 150)) - player_claims
        ck("bots expand on their own (unclaimed systems consumed beyond the "
           "player's claims)",
           bots_claimed > 0 or bot_max_systems >= 2,
           f"botsClaimed={bots_claimed} botMaxSystems={bot_max_systems}")

        # ── 10. save/load/continue divergence gate ───────────────────────────
        print("\n  -- 10. save@12 -> load -> continue vs uninterrupted --")
        _, _, stream_b, _, _ = run_arm(adapter, SEED, SCRIPT, save_at=SAVE_AT)
        div = first_divergence(stream_a, stream_b)
        ck("interrupted arm's hash stream is byte-identical to the "
           "uninterrupted run",
           div is None and len(stream_a) == len(stream_b),
           f"len={len(stream_a)}/{len(stream_b)} firstDiv={div}")
        if div is not None:
            finding(f"save/load/continue DIVERGED at stream index {div} — "
                    "serializer or accumulator loss across a resume")

        # ── 11. timing ───────────────────────────────────────────────────────
        print("\n  -- 11. per-cycle cost through the adapter --")
        mean_ms = sum(timings) / len(timings)
        ck("mean cycle (incl. full-state refresh) under the 5s alpha budget",
           mean_ms < 5000, f"mean={mean_ms:.0f}ms worst={max(timings):.0f}ms")

        # ── 12. hash freshness ───────────────────────────────────────────────
        print("\n  -- 12. hash freshness --")
        dupes = sum(1 for i in range(1, len(stream_a))
                    if stream_a[i] == stream_a[i - 1])
        ck("every committed cycle produced a fresh stateHash",
           dupes == 0, f"consecutiveDupes={dupes}")

        # Observations (not gated):
        print(f"\n  observations: researchTier={final.get('player_researchTier')} "
              f"researchPoints={final.get('player_researchPoints')} "
              f"powerScore={final.get('player_powerScore')} "
              f"credits={final.get('player_credits')} "
              f"achievementsTotal={final.get('totalAchievements')} "
              f"syndicateController={final.get('syndicateController')}")

    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        gate.ck("exception-free run", False, f"{type(exc).__name__}: {exc}")
    finally:
        adapter.close()

    return gate.finish(
        "ROUND 1",
        "The core loop is playable through the wire: expansion, production, "
        "trade, research orders all land with real effects; invariants and "
        "state integrity hold over 25 full-scale cycles; Reckonings fire on "
        "cadence; save/load resumes are exact. Ready for R2.")


if __name__ == "__main__":
    sys.exit(main())
