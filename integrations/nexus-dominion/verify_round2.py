#!/usr/bin/env python3
"""
Nexus Dominion ROUND 2 — full spine. Every player order type driven to a REAL
observed outcome through the wire (adapter -> harness -> processCycle), plus
the systems that only show up over a longer horizon (Reckonings, market
events, achievements, syndicate/covert cycles). Full PRD scale, seed 20260920,
30 cycles.

Order-type coverage (all 15):
  claim-system, build-unit, build-installation, build-wormhole, trade (R1
  differential + sell riders here), research, select-doctrine,
  select-specialization, propose-pact, break-pact, fund-syndicate,
  purchase-black-register, launch-covert-op, attack, move-fleet.

Positive paths that are unreachable inside a 30-cycle horizon by design
economics (wormhole: 20k credits/5k ore; covert launch: 200-agent pool;
tier-3 specialization) are exercised via SAVE-PAYLOAD INJECTION — save, edit
the game's own serialized state, load, order. The engine's contract from that
state is real; every injection is printed loudly where it happens.

Checks:
   1. 30 cycles committed; ZERO flat-invariant violations
   2. full-state cross-reference integrity at the end
   3. research gates hold on the wire: doctrine/spec REFUSED at tier 0
      (ND-6 regression), then research x3 -> tier 3, doctrine + spec land
   4. build-installation: a real home slot holds a trade-hub Installation
      (biome-legal type; the earlier mining-complex refusal was core-world
      biome law, observed and respected)
   5. propose-pact -> pact in diplomacy state + pact-formed event
      (auto-accept without bot consent -> design observation)
   6. break-pact -> pact.active false + relationship hostile with a violation
   7. move-fleet: target+arrival set; fleet ARRIVES (flat 10-cycle transit —
      known deviation, observed)
   8. attack -> combat event with phases; every casualty id removed from both
      the unit roster and all fleets
   9. syndicate: funding creates a member, influence >= 100, rank >= 2
  10. purchase-black-register: the item lands in ownedBlackRegisterItems and
      SURVIVES subsequent cycles (ND-5 regression)
  11. covert op (agent injection): resolves to a covert event, pool debited
      by the 200-agent cost
  12. build-wormhole (resource injection): wormhole exists, BOTH ends gain
      adjacency, exact cost band deducted — and it SURVIVES the next cycle
      (ND-5 regression)
  13. duplicate wormhole to the same target refused WITHOUT a second charge
  14. Reckonings at exactly cycles 10/20/30; player holds a Cosmic tier
  15. >=1 market event over 30 cycles (p=0.2/cycle; zero would be ~0.1%)
  16. achievement ledger is CONSISTENT with the thresholds the checker
      publishes (every empire meeting a threshold holds the achievement)
  17. powerHistory contract: harness history 1/cycle while state.powerHistory
      stays EMPTY — ND-P1 evidence (App-side bug, fix tracked separately)

Run (from the UGT repo root):
    python3 integrations/nexus-dominion/verify_round2.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ugt.core.trial import GateRunner, InvariantSuite  # noqa: E402
from ugt.utils.config_parser import UgtConfig  # noqa: E402
from ugt.adapters.nexus_dominion_harness import (  # noqa: E402
    NexusDominionHarnessAdapter,
)
from invariants import ALL_FLAT_PREDICATES, full_state_violations  # noqa: E402

CONFIG_PATH = "integrations/nexus-dominion/ugt.config.yaml"
SEED = 20260920
COVERT_COST = 200  # flat agent cost per launched op (engine constant)
# Achievement thresholds as the checker publishes them (content constants,
# used only to CROSS-CHECK the ledger — never to re-implement the award).
ACHIEVEMENT_THRESHOLDS = {
    "warlord": lambda e, ctx: len(e.get("systemIds") or []) >= 40,
    "market-overlord": lambda e, ctx: len(e.get("systemIds") or []) >= 12,
    "conquest": lambda e, ctx: len(e.get("systemIds") or [])
    >= 0.30 * ctx["totalSystems"],
    "singularity": lambda e, ctx: e.get("researchTier", 0) >= 8,
}


class Driver:
    """Thin scripted driver: raw order lists per commit + invariant sweep."""

    def __init__(self, adapter):
        self.a = adapter
        self.suite = InvariantSuite(ALL_FLAT_PREDICATES)
        self.states = []
        self.events = []
        self.violations = []
        self.reckonings = []

    def reset(self, seed):
        self.states = [self.a.reset(seed=seed)]
        return self.states[0]

    @property
    def now(self):
        return self.states[-1]

    def commit(self, orders, label=""):
        before = self.states[-1]
        r = self.a.send_raw({
            "op": "commit", "campaignId": self.a.campaign_id,
            "actions": orders,
        })
        after = self.a.resync()
        result = {"ok": r.get("ok"), "committed": r.get("committed"),
                  "error": r.get("error"),
                  "hashBefore": before.get("stateHash")}
        vs = self.suite.check_command(before, after, "commit", result)
        self.violations.extend(f"cycle {after.get('cycle')} ({label}): {v}"
                               for v in vs)
        cyc = (r.get("summary") or {}).get("cycle")
        self.events.extend((cyc, e)
                           for e in (r.get("report") or {}).get("events") or [])
        if (r.get("report") or {}).get("reckoningOccurred"):
            self.reckonings.append(cyc)
        self.states.append(after)
        return r, after

    def events_of(self, etype, **fields):
        return [(c, e) for c, e in self.events
                if e.get("type") == etype
                and all(e.get(k) == v for k, v in fields.items())]

    def inject(self, mutate, label):
        """Save -> edit the game's own serialized state -> load. LOUD."""
        print(f"      [INJECT] {label}")
        payload = self.a.save_payload()
        state = json.loads(payload["state"])
        mutate(state)
        payload["state"] = json.dumps(state)
        self.a.load_payload(payload)
        self.states.append(self.a._read_state())


def map_get(node, key):
    for k, v in node["e"]:
        if k == key:
            return v
    return None


def main() -> int:
    gate = GateRunner()
    ck, finding = gate.ck, gate.finding
    config = UgtConfig(CONFIG_PATH)
    print(f"Nexus Dominion ROUND 2 — full spine (seed {SEED}, full PRD scale)\n")

    adapter = NexusDominionHarnessAdapter(config)
    adapter.max_cycles = 10_000
    d = Driver(adapter)
    try:
        adapter.connect()
        d.reset(SEED)
        g0 = adapter.game_state
        pid = g0["playerEmpireId"]
        home = g0["empires"][pid]["homeSystemId"]
        systems0 = g0["galaxy"]["systems"]
        bot_target = sorted(g0["bots"].keys())[0]

        def adjacent_of(owned_ids, want):
            live = adapter.game_state["galaxy"]["systems"]
            for sid in owned_ids:
                for adj in systems0.get(sid, {}).get("adjacentSystemIds") or []:
                    owner = (live.get(adj) or {}).get("owner")
                    if want == "unclaimed" and owner is None:
                        return adj
                    if want == "enemy" and owner and owner != pid:
                        return adj
            return None

        # ── cycles 1-4: military base, a claim, fleet en route ──────────────
        d.commit([{"type": "build-unit", "details": {"unitTypeId": "fighter"}}],
                 "build fighter")
        d.commit([{"type": "build-unit", "details": {"unitTypeId": "infantry"}}],
                 "build infantry")
        claim1 = adjacent_of([home], "unclaimed")
        d.commit([{"type": "claim-system", "details": {"systemId": claim1}}],
                 "claim")
        fleets = {fid: f for fid, f in adapter.game_state["fleets"].items()
                  if f.get("ownerId") == pid}
        fleet_id = sorted(fleets.keys())[0]
        d.commit([{"type": "move-fleet",
                   "details": {"fleetId": fleet_id,
                               "targetSystemId": claim1}}], "move-fleet")
        moved = adapter.game_state["fleets"][fleet_id]
        move_ordered = (moved.get("targetSystemId") == claim1
                        and isinstance(moved.get("arrivalCycle"), (int, float)))
        arrival_cycle = moved.get("arrivalCycle")

        # ── cycle 5: installation (trade-hub IS core-world-legal) ───────────
        d.commit([{"type": "build-installation",
                   "details": {"installationType": "trade-hub",
                               "systemId": home}}], "build-installation")

        # ── cycles 6-7: pact lifecycle ───────────────────────────────────────
        d.commit([{"type": "propose-pact",
                   "details": {"targetId": bot_target,
                               "type": "stillness-accord"}}], "propose-pact")
        pact_ids = sorted(adapter.game_state["diplomacy"]["pacts"].keys())
        d.commit([{"type": "break-pact",
                   "details": {"pactId": pact_ids[0] if pact_ids else "none"}}],
                 "break-pact")
        dip = adapter.game_state["diplomacy"]
        pact_after = (dip["pacts"] or {}).get(pact_ids[0]) if pact_ids else None
        rel_keys = [k for k in (dip.get("relationships") or {})
                    if pid in k and bot_target in k]
        rel = (dip["relationships"] or {}).get(rel_keys[0]) if rel_keys else None
        pact_broken = (pact_after is not None
                       and pact_after.get("active") is False
                       and rel is not None and rel.get("status") == "hostile"
                       and rel.get("violations", 0) >= 1)

        # ── cycles 8-13: syndicate funding to rank 2 (sell riders keep the
        #    treasury liquid so no funding is silently skipped) ───────────────
        for _ in range(6):
            d.commit([{"type": "trade",
                       "details": {"resource": "food", "quantity": 20,
                                   "direction": "sell"}},
                      {"type": "fund-syndicate", "details": {"amount": 100}}],
                     "fund-syndicate")

        # ── cycle 14: black register ─────────────────────────────────────────
        d.commit([{"type": "purchase-black-register",
                   "details": {"itemId": "empire-dossier"}}], "black-register")
        member_after = ((adapter.game_state.get("syndicate") or {})
                        .get("members") or {}).get(pid) or {}
        owned_items_now = (adapter.game_state.get("ownedBlackRegisterItems")
                           or {}).get(pid) or []

        # ── cycles 15-18: attacks until combat resolves ──────────────────────
        combat_events = []
        for _ in range(4):
            target = adjacent_of(
                adapter.game_state["empires"][pid]["systemIds"], "enemy")
            unit_ids = [uid for f in adapter.game_state["fleets"].values()
                        if f.get("ownerId") == pid
                        for uid in (f.get("unitIds") or [])]
            orders = ([{"type": "attack",
                        "details": {"targetSystemId": target,
                                    "unitIds": unit_ids}}]
                      if target and unit_ids else [])
            d.commit(orders, "attack")
            combat_events = d.events_of("combat", attackerId=pid)
            if combat_events:
                break
        ghost_casualties = []
        if combat_events:
            _, ce = combat_events[0]
            dead = (ce.get("attackerCasualties") or []) + \
                   (ce.get("defenderCasualties") or [])
            g = adapter.game_state
            in_fleets = {uid for f in g["fleets"].values()
                         for uid in (f.get("unitIds") or [])}
            ghost_casualties = [uid for uid in dead
                                if uid in g["units"] or uid in in_fleets]

        # ── cycles 19-21: research-gate probes + ladder (injection) ─────────
        def zero_research(state):
            emp = map_get(state["empires"], pid)
            emp["researchTier"] = 0
            emp["researchPoints"] = 0
            emp["researchPath"] = None
            emp["specialization"] = None
            emp["resources"]["researchPoints"] = 0
        d.inject(zero_research, "researchTier=0, no doctrine (ND-6 probe)")
        d.commit([
            {"type": "select-doctrine", "details": {"pathId": "war-machine"}},
            {"type": "select-specialization",
             "details": {"specId": "shock-troops"}},
        ], "gate probe")
        probe_state = d.now
        gates_held = (probe_state.get("player_researchPath") is None
                      and probe_state.get("player_specialization") is None)

        def grant_research(state):
            emp = map_get(state["empires"], pid)
            emp["resources"]["researchPoints"] = 100000
        d.inject(grant_research, "researchPoints=100000 (research ladder)")
        d.commit([{"type": "research", "details": {}} for _ in range(3)],
                 "research x3")
        d.commit([
            {"type": "select-doctrine", "details": {"pathId": "war-machine"}},
            {"type": "select-specialization",
             "details": {"specId": "shock-troops"}},
        ], "doctrine+spec")
        ladder_state = d.now

        # ── covert op via agent injection ────────────────────────────────────
        def give_agents(state):
            cs = map_get(state["covert"]["empireStates"], pid)
            cs["agentPool"] = 500
        d.inject(give_agents, "agentPool=500 (covert positive path)")
        d.commit([{"type": "launch-covert-op",
                   "details": {"targetId": bot_target,
                               "opType": "steal-credits"}}], "covert-op")
        cs_after = ((adapter.game_state.get("covert") or {})
                    .get("empireStates") or {}).get(pid) or {}
        covert_events = [e for c, e in d.events_of("covert")
                         if e.get("attackerId") == pid
                         and e.get("kind") in ("op-succeeded", "op-failed",
                                               "op-detected")]

        # ── wormhole via resource injection ──────────────────────────────────
        def give_riches(state):
            emp = map_get(state["empires"], pid)
            emp["resources"]["credits"] = 25000
            emp["resources"]["ore"] = 6000
        d.inject(give_riches, "credits=25000 ore=6000 (wormhole positive path)")
        far = sorted(sid for sid in systems0 if sid != home)[-1]
        pre = d.now
        d.commit([{"type": "build-wormhole",
                   "details": {"targetSystemId": far}}], "build-wormhole")
        g = adapter.game_state
        wormholes = g["galaxy"].get("wormholes") or []
        home_adj = g["galaxy"]["systems"][home].get("adjacentSystemIds") or []
        far_adj = g["galaxy"]["systems"][far].get("adjacentSystemIds") or []
        post = d.now
        credits_spent = pre.get("player_credits") - post.get("player_credits")
        ore_spent = pre.get("player_ore") - post.get("player_ore")
        wh_ok = (len(wormholes) == 1 and far in home_adj and home in far_adj
                 and 19000 <= credits_spent <= 20100
                 and 4900 <= ore_spent <= 5100)
        pre2 = d.now
        d.commit([{"type": "build-wormhole",
                   "details": {"targetSystemId": far}}], "wormhole dupe")
        g = adapter.game_state
        wh_after_dupe = g["galaxy"].get("wormholes") or []
        dupe_ok = (len(wh_after_dupe) == 1
                   and d.now.get("player_credits")
                   >= pre2.get("player_credits") - 200)

        # ── run out the horizon ──────────────────────────────────────────────
        while d.now.get("cycle", 0) < 30:
            d.commit([], "pass")
        final = d.now
        g_final = adapter.game_state

        # ═════ CHECKS ═════
        print("\n  -- checks --")
        for v in d.violations[:10]:
            finding(f"invariant violation: {v}")
        ck("1. 30 cycles committed, ZERO invariant violations",
           final.get("cycle") == 30 and not d.violations,
           f"cycle={final.get('cycle')} violations={len(d.violations)}")

        fs = full_state_violations(g_final)
        for v in fs[:8]:
            finding(f"full-state violation: {v}")
        ck("2. full-state cross-reference integrity at cycle 30",
           not fs, f"violations={len(fs)}")

        ck("3. research gates hold (tier-0 refusals) then ladder lands "
           "(tier>=3, doctrine, specialization)",
           gates_held
           and ladder_state.get("player_researchTier", 0) >= 3
           and ladder_state.get("player_researchPath") == "war-machine"
           and ladder_state.get("player_specialization") == "shock-troops",
           f"gatesHeld={gates_held} tier={ladder_state.get('player_researchTier')} "
           f"path={ladder_state.get('player_researchPath')} "
           f"spec={ladder_state.get('player_specialization')}")

        home_slots = g_final["galaxy"]["systems"][home].get("slots") or []
        hub = [s for s in home_slots
               if isinstance(s.get("installation"), dict)
               and s["installation"].get("type") == "trade-hub"]
        ck("4. build-installation -> a real home slot holds a trade-hub "
           "Installation",
           len(hub) == 1,
           f"slots={[(s.get('installation') or {}).get('type') if isinstance(s.get('installation'), dict) else None for s in home_slots]}")

        pact_events = d.events_of("diplomacy", action="pact-formed")
        ck("5. propose-pact -> pact recorded + pact-formed event",
           bool(pact_ids) and len(pact_events) >= 1,
           f"pactIds={pact_ids} events={len(pact_events)}")
        finding("design observation: propose-pact is auto-ACCEPTED in the "
                "same commit (proposePact -> acceptPact, no bot consent step)")

        ck("6. break-pact -> active:false + hostile relationship with a "
           "violation recorded",
           pact_broken,
           f"active={pact_after.get('active') if pact_after else None} "
           f"rel={rel.get('status') if rel else None}/"
           f"{rel.get('violations') if rel else None}")

        ck("7. move-fleet ordered and ARRIVED",
           move_ordered
           and g_final["fleets"][fleet_id].get("locationSystemId") == claim1,
           f"arrivalCycle={arrival_cycle} (flat 10-cycle transit — "
           f"calculateTransitTime ignores distance/wormholes, known deviation) "
           f"loc={g_final['fleets'][fleet_id].get('locationSystemId')}")

        ck("8. attack -> combat event with phases; casualties truly removed",
           bool(combat_events) and not ghost_casualties
           and bool(combat_events[0][1].get("phasesFought")),
           (f"phases={combat_events[0][1].get('phasesFought') if combat_events else None} "
            f"captured={combat_events[0][1].get('ownershipChanged') if combat_events else None} "
            f"ghosts={ghost_casualties}"))

        ck("9. syndicate member, influence >= 100, rank >= 2",
           member_after.get("influence", 0) >= 100
           and member_after.get("rank", 0) >= 2,
           f"influence={member_after.get('influence')} "
           f"rank={member_after.get('rank')}")

        owned_items_final = (g_final.get("ownedBlackRegisterItems") or {}) \
            .get(pid) or []
        ck("10. black-register purchase landed AND survived to cycle 30 "
           "(ND-5 regression)",
           "empire-dossier" in owned_items_now
           and "empire-dossier" in owned_items_final,
           f"atPurchase={owned_items_now} final={owned_items_final}")

        ck("11. covert op resolves + agent pool debited by the 200 cost",
           len(covert_events) >= 1
           and cs_after.get("agentPool") == 500 - COVERT_COST,
           f"kinds={[e.get('kind') for e in covert_events]} "
           f"agentPool={cs_after.get('agentPool')}")

        wh_final = g_final["galaxy"].get("wormholes") or []
        ck("12. wormhole built (link + both adjacencies + exact cost) AND "
           "survives to cycle 30 (ND-5 regression)",
           wh_ok and len(wh_final) == 1,
           f"built={wh_ok} spent={credits_spent}cr/{ore_spent}ore "
           f"finalWormholes={len(wh_final)}")

        ck("13. duplicate wormhole refused WITHOUT a second charge",
           dupe_ok, f"wormholes={len(wh_after_dupe)}")

        ck("14. Reckonings at exactly [10, 20, 30]; player holds a tier",
           d.reckonings == [10, 20, 30] and final.get("playerTier") in
           ("sovereign", "ascendant", "stricken"),
           f"reckonings={d.reckonings} tier={final.get('playerTier')}")

        market_events = d.events_of("market")
        ck("15. >=1 market event over 30 cycles",
           len(market_events) >= 1, f"marketEvents={len(market_events)}")
        if not market_events:
            finding("ZERO market events in 30 cycles at p=0.2/cycle (~0.1%) — "
                    "the probability path likely never fires on the wire")

        # 16. achievement ledger vs thresholds
        ctx = {"totalSystems": final.get("systemCount", 250)}
        earned = g_final.get("earnedAchievements") or {}
        mismatches = []
        for eid, emp in g_final["empires"].items():
            has = set(earned.get(eid) or [])
            for ach, qualifies in ACHIEVEMENT_THRESHOLDS.items():
                if qualifies(emp, ctx) and ach not in has:
                    mismatches.append(f"{eid} qualifies for {ach} "
                                      f"({len(emp.get('systemIds') or [])} systems, "
                                      f"tier {emp.get('researchTier')}) but was "
                                      "never awarded it")
        for m in mismatches[:5]:
            finding(f"achievement ledger: {m}")
        total_earned = sum(len(v) for v in earned.values())
        ck("16. achievement ledger consistent with published thresholds",
           not mismatches,
           f"earnedTotal={total_earned} mismatches={len(mismatches)}")

        phl = final.get("powerHistoryLengths") or {}
        ck("17. powerHistory contract: harness 1/cycle; state stays empty "
           "(ND-P1 evidence)",
           phl.get("harness", 0) >= 30 and phl.get("state", 0) == 0,
           f"harness={phl.get('harness')} state={phl.get('state')}")
        finding(
            "ND-P1 (App-side): processCycle never writes the caller's "
            "powerHistory into state, but App.tsx re-points its refs to "
            "result.state.powerHistory (always empty) after every commit and "
            "never pushes scores — the REAL app computes every Reckoning "
            "from an empty rolling window and drops history across "
            "save/load. Fix in App: push per-cycle scores into the refs "
            "(integration.test.ts contract) and carry both accumulators "
            "through save/load.")

        print(f"\n  observations: credits={final.get('player_credits')} "
              f"owned={final.get('player_systemsOwned')} "
              f"units={final.get('player_unitCount')} "
              f"achievementsTotal={total_earned} "
              f"combatCaptured="
              f"{combat_events[0][1].get('ownershipChanged') if combat_events else None} "
              f"marketEvents={len(market_events)}")

    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        gate.ck("exception-free run", False, f"{type(exc).__name__}: {exc}")
    finally:
        adapter.close()

    return gate.finish(
        "ROUND 2",
        "Every order type lands with a real observed outcome; combat, "
        "syndicate, covert, wormholes, pacts, installations, research gates "
        "and Reckonings all resolve through the wire; invariants hold "
        "throughout. Ready for R3.")


if __name__ == "__main__":
    sys.exit(main())
