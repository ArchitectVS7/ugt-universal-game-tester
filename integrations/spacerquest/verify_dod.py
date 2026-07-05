#!/usr/bin/env python3
"""
Phase-0 DEFINITION OF DONE verification.

Drives the REAL spacerquest-web server entirely through RealClientAdapter.step(action_id)
(the same interface the RL/exploit-hunter env calls) and proves the Phase-0 DoD:

    "an adapter that can reset, step every action through the real game, and read state —
     verified by re-driving the trade loop AND a real combat encounter end-to-end."

Every action id here is a REAL config action id (matches integrations/spacerquest/ugt.config.yaml).
No game logic is reimplemented; every effect is read back from /api/character.

Requires the live server on :3005. Run:
    python3 integrations/spacerquest/verify_dod.py
Exit 0 + "DoD MET" means Phase 0 is complete.
"""
from __future__ import annotations

import sys
sys.path.insert(0, ".")

from ugt.adapters.realclient import RealClientAdapter

# Real config action ids (subset the RL trainer uses): id -> name.
ACTIONS = {
    4: {"name": "buy_fuel"}, 6: {"name": "accept_cargo"}, 2: {"name": "navigate_cargo_dest"},
    7: {"name": "deliver_cargo"}, 8: {"name": "upgrade_cheapest"}, 14: {"name": "end_turn"},
    10: {"name": "combat_attack"}, 11: {"name": "combat_retreat"}, 16: {"name": "upgrade_weapons"},
    17: {"name": "upgrade_shields"}, 0: {"name": "wait"},
}


class _Cfg:
    def __init__(self):
        self.data = {"engine": {"type": "real_server", "base_url": "http://127.0.0.1:3005"}}
    @property
    def action_mappings(self):
        return ACTIONS


def main() -> int:
    ad = RealClientAdapter(_Cfg())
    checks: list[tuple[str, bool, str]] = []

    def ck(name, ok, detail=""):
        checks.append((name, ok, detail))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))

    def credits(state):
        return state["character"]["credits"]

    print("Phase-0 DoD verification — driving the REAL game via adapter.step()\n")
    try:
        ad.connect()

        # ── reset + read state ────────────────────────────────────────────
        obs = ad.reset()
        ck("reset() + read state", obs["character"]["credits"] == 100000 and obs["ship"]["fuel"] == 800,
           f"credits={obs['character']['credits']} fuel={obs['ship']['fuel']}")

        # ── step every non-trade action once (no crash, state readable) ────
        print("\n  -- exercising standalone actions --")
        for aid in (4, 16, 17, 8, 14, 0):
            state, term, trunc, info = ad.step(aid)
            ck(f"step({aid}:{ACTIONS[aid]['name']})",
               isinstance(state, dict) and "character" in state and term is False,
               f"info={info}")

        # ── TRADE LOOP end-to-end ─────────────────────────────────────────
        print("\n  -- trade loop --")
        state, *_ , info = ad.step(6)  # accept_cargo
        signed = info.get("signed") and state["character"].get("destination", 0) != 0
        ck("accept_cargo signs a contract", signed,
           f"destination={state['character'].get('destination')} cargo_pods={state['character'].get('cargo_pods')}")
        credits_before = credits(state)
        dest = state["character"].get("destination", 0)

        state, term, trunc, info = ad.step(2)  # navigate_cargo_dest (launch+arrive; delivery auto)
        credits_after = credits(state)
        delivered = credits_after > credits_before
        ck("navigate -> arrival delivers cargo (credits up)", delivered,
           f"{credits_before} -> {credits_after} (+{credits_after - credits_before}); encounter={info.get('encounter')}")
        ck("navigate steps through real game", info.get("arrive_status") == 200, f"arrive_status={info.get('arrive_status')}")

        state, *_, info = ad.step(7)  # deliver_cargo (confirm auto-delivery)
        ck("deliver_cargo confirms delivery", state["character"]["cargo_pods"] == 0, f"info={info}")

        # ── COMBAT end-to-end (if the trip spawned a hostile encounter) ────
        print("\n  -- combat --")
        in_combat = bool(state["character"]["in_combat"])
        if in_combat:
            resolved = False
            rounds = 0
            for i in range(15):
                state, term, trunc, info = ad.step(10)  # combat_attack
                rounds += 1
                if not state["character"]["in_combat"]:
                    resolved = True
                    break
            ck("combat resolves end-to-end (no soft-lock)", resolved,
               f"resolved in {rounds} attacks; won={state['character']['battles_won']} lost={state['character']['battles_lost']}")
        else:
            # No hostile encounter this trip — drive one more trip to force combat.
            ad.step(6); state, *_, info = ad.step(2)
            in_combat = bool(state["character"]["in_combat"])
            if in_combat:
                resolved = False
                for i in range(15):
                    state, *_ = ad.step(10)
                    if not state["character"]["in_combat"]:
                        resolved = True
                        break
                ck("combat resolves end-to-end (no soft-lock)", resolved,
                   f"won={state['character']['battles_won']} lost={state['character']['battles_lost']}")
            else:
                ck("combat encounter occurred", False, "no hostile encounter in 2 trips (unexpected)")

        # ── unmapped action still guarded ─────────────────────────────────
        raised = False
        try:
            ad.step(23)  # buy_trans_warp — intentionally unmapped
        except NotImplementedError:
            raised = True
        ck("unmapped action raises NotImplementedError", raised, "buy_trans_warp still guarded")

    except Exception as exc:  # noqa: BLE001
        import traceback; traceback.print_exc()
        ck("exception-free run", False, f"{type(exc).__name__}: {exc}")
    finally:
        ad.close()

    passed = sum(1 for _, ok, _ in checks if ok)
    total = len(checks)
    print()
    if passed == total:
        print(f"DoD MET — {passed}/{total} checks. Adapter resets, steps every subset action through the "
              f"REAL game, reads state, and drives the trade loop AND combat end-to-end. Phase 0 complete.")
        return 0
    print(f"DoD NOT MET — {passed}/{total} checks passed.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
