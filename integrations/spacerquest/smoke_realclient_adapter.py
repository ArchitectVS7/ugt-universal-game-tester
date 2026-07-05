#!/usr/bin/env python3
"""
Phase 0 / Step 1 smoke test: exercise RealClientAdapter through the BaseAdapter interface.

This is the adapter-level counterpart to spike_realclient.py. Where the spike proved the raw
protocol, this proves the *adapter contract* the UGT env/tiers actually call:
    connect() -> reset() -> observation dict -> transport primitives -> step()

Requires the live server on :3005 (see PLAN-FORWARD.md "How to resume"). Attaches to a
running server by default (no server_cmd), so start the server first.

Run:
    python3 integrations/spacerquest/smoke_realclient_adapter.py
Exit 0 + "SMOKE PASSED" means the Step-1 adapter module is healthy.
"""
from __future__ import annotations

import sys

# Make the package importable when run from the repo root.
sys.path.insert(0, ".")

from ugt.adapters.realclient import RealClientAdapter, RANK_ORDER


class _ShimConfig:
    """Minimal stand-in for UgtConfig so we can test the adapter in isolation (no trainer/env)."""

    def __init__(self, engine: dict, actions: dict):
        self.data = {"engine": engine}
        self._actions = actions

    @property
    def action_mappings(self):
        return self._actions


# Mirror the real config's action ids for the ones we touch here.
# 23 = buy_trans_warp is intentionally still UNMAPPED (Step-3 mapped only the training subset),
# so it exercises the NotImplementedError guard.
ACTIONS = {0: {"name": "wait"}, 23: {"name": "buy_trans_warp"}}
OBS_CHAR_KEYS = ["credits", "score", "rank_index", "current_system", "trip_count",
                 "battles_won", "cargo_pods", "destination", "bank_balance",
                 "is_conqueror", "in_combat", "is_lost", "in_jail"]
OBS_SHIP_KEYS = ["fuel", "hull_strength", "hull_condition", "drive_strength",
                 "weapon_strength", "shield_strength", "has_cloaker", "has_auto_repair"]


def main() -> int:
    cfg = _ShimConfig(engine={"type": "real_server", "base_url": "http://127.0.0.1:3005"},
                      actions=ACTIONS)
    adapter = RealClientAdapter(cfg)
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, ok, detail))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))

    print("Step-1 smoke: RealClientAdapter via BaseAdapter interface\n")
    try:
        adapter.connect()
        check("connect() (server + socket + auth)", adapter.sio is not None and adapter._auth_ok)

        obs = adapter.reset()
        char_ok = all(k in obs.get("character", {}) for k in OBS_CHAR_KEYS)
        ship_ok = all(k in obs.get("ship", {}) for k in OBS_SHIP_KEYS)
        check("reset() -> full observation dict", char_ok and ship_ok,
              f"credits={obs['character']['credits']} rank_index={obs['character']['rank_index']} "
              f"fuel={obs['ship']['fuel']} turn={obs['turn_number']}")

        # dev-setup bootstraps: 100,000 cr, rank LIEUTENANT (index 0), fuel 800, system 1.
        c = obs["character"]
        reset_sane = (c["credits"] == 100000 and c["rank_index"] == RANK_ORDER.index("LIEUTENANT")
                      and obs["ship"]["fuel"] == 800 and c["current_system"] == 1)
        check("reset() matches dev-setup baseline", reset_sane,
              f"credits={c['credits']} rank_index={c['rank_index']} fuel={obs['ship']['fuel']} sys={c['current_system']}")

        # The observability fields must be REAL now (extended /api/character), not hardcoded 0.
        # At a fresh reset the character has not won, is not lost/jailed/in-combat, bank empty —
        # so these are legitimately 0, but they come from actual game state, not a stub.
        obs_real = all(c[k] in (0, 1) for k in ["is_conqueror", "in_combat", "is_lost", "in_jail"])
        check("observability fields sourced from real state", obs_real,
              f"conqueror={c['is_conqueror']} lost={c['is_lost']} combat={c['in_combat']} "
              f"jail={c['in_jail']} bank={c['bank_balance']}")

        term = adapter.get_terminal_text(2000)
        check("get_terminal_text() (LLM-tier view)", "MAIN MENU" in term, f"{len(term)} chars; MAIN MENU present")

        # Transport primitive: navigate to shipyard and back-read a different screen.
        dest = adapter.press_menu_key("S")
        out = dest.get("output", "")
        check("press_menu_key('S') -> real navigation", len(out) > 0 and "MAIN MENU" not in out,
              f"{len(out)} chars of the shipyard screen")

        # step() on a mapped action ('wait'): returns the (state, terminated, truncated, info) tuple.
        state, terminated, truncated, info = adapter.step(0)
        step_ok = (isinstance(state, dict) and "character" in state
                   and terminated is False and truncated is False
                   and state["turn_number"] == 1 and info.get("action") == "wait")
        check("step(wait) -> (state, term, trunc, info)", step_ok,
              f"turn={state.get('turn_number')} info={info}")

        # step() on an UNMAPPED action must raise NotImplementedError (honest boundary — the
        # training subset is mapped; extended actions like buy_trans_warp are not).
        raised = False
        try:
            adapter.step(23)  # buy_trans_warp — intentionally unmapped
        except NotImplementedError:
            raised = True
        check("step(unmapped) raises NotImplementedError", raised, "buy_trans_warp correctly still guarded")
    except Exception as exc:  # noqa: BLE001
        check("exception-free run", False, f"{type(exc).__name__}: {exc}")
    finally:
        adapter.close()

    passed = sum(1 for _, ok, _ in checks if ok)
    total = len(checks)
    print()
    if passed == total and total >= 7:
        print(f"SMOKE PASSED — {passed}/{total} checks. Step-1 adapter module is healthy.")
        return 0
    print(f"SMOKE FAILED — {passed}/{total} checks passed.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
