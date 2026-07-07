#!/usr/bin/env python3
"""
Warzones ROUND 2 playability verification — three clean consecutive turn cycles
through the REAL game, exercising the loops Round 1 only touched:

    1. ECONOMY: an actual buy AND an actual sell inside TradingScene (the new
       trade_buy/trade_sell hook actions route through the same Buy-1 / Sell-All
       handlers the commodity-row buttons invoke), with credit/cargo/stock
       deltas asserted against the quoted prices.
    2. COMBAT: a mid-run pirate fight the run SURVIVES, with salvage credited
       exactly and the hull damage persisting back on the galaxy map.
    3. INVARIANTS, checked after every single action across all cycles:
       AP never negative, fog monotonic, turnNumber strictly increasing (and
       only via end_turn), credits never negative, cargo within capacity,
       and never a stuck/no-run scene.

Gate: >= 3 full clean turn cycles AND objectives 1+2 complete AND zero
invariant violations. Expect economy bugs — this loop has never been
player-driven; failures are FINDINGS (WZ-R8+), not harness errors.

Run (with `npm run dev` serving :3000 — verify the LISTEN PID!):

    python3 integrations/warzones/verify_round2.py [seed]
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from ugt.adapters.playwright import PlaywrightAdapter
from ugt.utils.config_parser import UgtConfig

CONFIG_PATH = "integrations/warzones/ugt.config.yaml"
SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 20260706
MAX_TURNS = 8          # objective budget; gate still requires >= 3 clean cycles
MIN_CYCLES = 3

WAIT, END_TURN, SCAN, WARP_SAFE, WARP_ANY, WARP_PIRATE = 0, 1, 2, 3, 4, 5
COMBAT_ATTACK, COMBAT_FLEE, TRADE_OPEN, TRADE_EXIT = 6, 7, 8, 9
TRADE_BUY, TRADE_SELL = 10, 11

RUN_SCENES = {"GalaxyMapScene", "CombatScene", "TradingScene"}


class Invariants:
    """Checks that must hold after EVERY action, across all cycles."""

    def __init__(self, s0: dict):
        self.violations: list[str] = []
        self.prev = s0
        self.steps = 0

    def check(self, s: dict, action: int, info: dict):
        self.steps += 1
        p, prev_p = s.get("player") or {}, self.prev.get("player") or {}

        def viol(rule: str, detail: str):
            self.violations.append(f"step {self.steps} (action {action}): {rule} — {detail}")

        ap = p.get("actionPoints")
        if ap is None or ap < 0:
            viol("AP never negative", f"actionPoints={ap}")
        fog_now = (s.get("fog") or {}).get("discoveredCount") or 0
        fog_prev = (self.prev.get("fog") or {}).get("discoveredCount") or 0
        if fog_now < fog_prev:
            viol("fog monotonic", f"discoveredCount {fog_prev} -> {fog_now}")
        tn, tp = s.get("turnNumber"), self.prev.get("turnNumber")
        if action == END_TURN:
            if tn != tp + 1:
                viol("end_turn advances turn by exactly 1", f"{tp} -> {tn}")
        elif tn != tp:
            viol("turnNumber only changes via end_turn", f"{tp} -> {tn} on action {action}")
        if (p.get("credits") or 0) < 0:
            viol("credits never negative", f"credits={p.get('credits')}")
        cargo = p.get("cargo") or {}
        if cargo.get("used") is not None and cargo.get("capacity") is not None:
            if cargo["used"] > cargo["capacity"]:
                viol("cargo within capacity", f"{cargo['used']}/{cargo['capacity']}")
            if cargo["used"] != sum((cargo.get("items") or {}).values()):
                viol("cargo.used == sum(items)", f"used={cargo['used']} items={cargo.get('items')}")
        hull, max_hull = (p.get("ship") or {}).get("hull"), (p.get("ship") or {}).get("maxHull")
        if hull is not None and max_hull is not None and hull > max_hull:
            viol("hull <= maxHull", f"{hull}/{max_hull}")
        scenes = set(s.get("scenes") or [])
        if not scenes & (RUN_SCENES | {"VictoryScene", "DefeatScene"}):
            viol("no stuck/no-run scene", f"scenes={sorted(scenes)}")
        self.prev = s


def main() -> int:
    config = UgtConfig(CONFIG_PATH)
    ad = PlaywrightAdapter(config)
    checks: list[tuple[str, bool, str]] = []
    findings: list[str] = []

    def ck(name: str, ok: bool, detail: str = ""):
        checks.append((name, ok, detail))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))

    def finding(text: str):
        findings.append(text)
        print(f"  [FINDING] {text}")

    print(f"Round 2 — three clean turn cycles (trade buy+sell, survivable combat), seed {SEED}\n")

    # Objective evidence, filled in as the run progresses.
    obj = {
        "buys": [],        # list of per-buy assertion dicts
        "sells": [],       # list of per-sell assertion dicts
        "combat": None,    # combat evidence dict
        "cycles": 0,
        "ap_refreshes": 0,
        "defeated": False,
        "ports_visited": set(),
        "barren": set(),   # (port_id, cargo_signature) visits that offered no trade
    }

    def cargo_sig(s: dict) -> tuple:
        return tuple(sorted((((s.get("player") or {}).get("cargo") or {}).get("items") or {}).items()))

    try:
        ad.connect()
        ad.page.evaluate(f"window.__RESET_GAME__({SEED})")
        state = ad.page.evaluate("window.__GET_STATE__()")
        if not isinstance(state, dict) or not state.get("ready"):
            raise RuntimeError(f"reset failed: {state}")
        inv = Invariants(state)

        print("  -- A. reset --")
        ck("reset(seed) reaches GalaxyMapScene", "GalaxyMapScene" in state.get("scenes", []),
           f"scenes={state.get('scenes')}")
        ck("seed honored", state.get("seed") == SEED, f"state.seed={state.get('seed')}")

        def step(action: int):
            nonlocal state
            s, term, trunc, info = ad.step(action)
            inv.check(s, action, info)
            state = s
            return s, term, trunc, info

        # ── in-run handlers ──────────────────────────────────────────────────
        def handle_trading():
            """At a port with TradingScene open: sell what we can, buy one unit."""
            port_id = (state.get("trade") or {}).get("portSectorId")
            obj["ports_visited"].add(port_id)
            sig_at_entry = cargo_sig(state)
            traded = False
            # Sell first (frees cargo, tests the sell path as soon as possible).
            table = {c["id"]: c for c in (state.get("trade") or {}).get("commodities", [])}
            held_sellable = [c for c in table.values() if c["inCargo"] > 0 and c["portBuysAt"] > 0]
            if held_sellable:
                s, _, _, info = step(TRADE_SELL)
                expected = (info.get("qty") or 0) * (info.get("unitPrice") or 0)
                got = (info.get("creditsAfter") or 0) - (info.get("creditsBefore") or 0)
                obj["sells"].append({
                    "port": port_id, "commodity": info.get("commodity"),
                    "qty": info.get("qty"), "unitPrice": info.get("unitPrice"),
                    "expected_revenue": expected, "credit_delta": got,
                    "stack_cleared": info.get("cargoQtyAfter") == 0,
                    "stock_delta": (info.get("stockAfter") or 0) - (info.get("stockBefore") or 0),
                    "ok": bool(info.get("ok")) and got == expected,
                    "info": dict(info),
                })
                traded = True
            # Buy one unit only while the buy objective is open, or to
            # diversify (port sells something we don't hold) while a sell is
            # still owed — unconditional buying churns credits at one port.
            need_buy_now, need_sell_now, _ = needs()
            table_now = {c["id"]: c for c in (state.get("trade") or {}).get("commodities", [])}
            sells_new = any(c["portSellsAt"] > 0 and c["stock"] > 0 and c["inCargo"] == 0
                            and c["portSellsAt"] <= state["player"]["credits"]
                            for c in table_now.values())
            if not (need_buy_now or (need_sell_now and sells_new)):
                if not traded:
                    obj["barren"].add((port_id, sig_at_entry))
                step(TRADE_EXIT)
                if "GalaxyMapScene" not in state.get("scenes", []):
                    finding(f"trade_exit did not return to the galaxy map: scenes={state.get('scenes')}")
                return
            s, _, _, info = step(TRADE_BUY)
            if info.get("ok"):
                traded = True
                paid = (info.get("creditsBefore") or 0) - (info.get("creditsAfter") or 0)
                obj["buys"].append({
                    "port": port_id, "commodity": info.get("commodity"),
                    "unitPrice": info.get("unitPrice"), "paid": paid,
                    "cargo_plus_one": info.get("cargoQtyAfter") == (info.get("cargoQtyBefore") or 0) + 1,
                    "stock_delta": (info.get("stockAfter") or 0) - (info.get("stockBefore") or 0),
                    "ok": paid == info.get("unitPrice"),
                    "info": dict(info),
                })
            elif "no buyable commodity" not in str(info.get("error")):
                finding(f"trade_buy failed unexpectedly at port {port_id}: {info.get('error')}")
            if not traded:
                obj["barren"].add((port_id, sig_at_entry))
            step(TRADE_EXIT)
            if "GalaxyMapScene" not in state.get("scenes", []):
                finding(f"trade_exit did not return to the galaxy map: scenes={state.get('scenes')}")

        def handle_combat():
            """In CombatScene: attack to resolution, verify economics, exit."""
            pre = obj["combat_entry_state"]
            enemy = (state.get("combat") or {}).get("enemy")
            outcome = salvage = end_hull = module = None
            for _ in range(12):
                s, term, trunc, info = step(COMBAT_ATTACK)
                combat = s.get("combat") or {}
                if term:
                    obj["defeated"] = True
                    obj["combat"] = {"survived": False, "enemy": enemy,
                                     "detail": f"outcome={combat.get('outcome')} -> defeat/victory scene"}
                    return
                if "GalaxyMapScene" in s.get("scenes", []):
                    break
                if combat.get("resolved"):
                    outcome = combat.get("outcome")
                    salvage = combat.get("salvageAwarded")
                    end_hull = combat.get("attackerEndHull")
                    module = combat.get("moduleDropped")
            else:
                obj["combat"] = {"survived": False, "enemy": enemy,
                                 "detail": "combat did not resolve in 12 attacks"}
                return
            credits_after = state["player"]["credits"]
            hull_on_map = state["player"]["ship"].get("hull")
            obj["combat"] = {
                "survived": True,
                "enemy": enemy,
                "outcome": outcome,
                "salvage": salvage,
                "credit_delta": credits_after - pre["credits"],
                "salvage_credited_exactly": salvage is not None and credits_after - pre["credits"] == salvage,
                "hull_before": pre["hull"],
                "hull_end_combat": end_hull,
                "hull_on_map": hull_on_map,
                "hull_persisted": end_hull is not None and hull_on_map == end_hull,
                "took_damage": hull_on_map is not None and hull_on_map < pre["hull"],
                "bot_removed": state.get("botsAlive") == pre["botsAlive"] - 1,
                "module_dropped": module,
            }

        # ── main loop: cycles until objectives done (>= MIN_CYCLES, <= MAX_TURNS) ──
        print("\n  -- B. turn cycles --")
        start_turn = state["turnNumber"]

        def needs() -> tuple[bool, bool, bool]:
            return (not any(b["ok"] for b in obj["buys"]),
                    not any(s_["ok"] for s_ in obj["sells"]),
                    obj["combat"] is None)

        while obj["cycles"] < MAX_TURNS:
            need_buy, need_sell, need_combat = needs()
            if obj["cycles"] >= MIN_CYCLES and not (need_buy or need_sell or need_combat):
                break

            # Player phase: act while AP allows. phase_steps caps scene-handler
            # retries (combat/trade actions cost no AP — a scene that refuses to
            # exit must fail the run, not hang it).
            stalled = 0
            phase_steps = 0
            while state["player"]["actionPoints"] >= 1 and stalled < 3:
                phase_steps += 1
                if phase_steps > 40:
                    finding(f"player phase exceeded 40 actions on turn {state['turnNumber']} "
                            f"(stuck scene? scenes={state.get('scenes')})")
                    break
                need_buy, need_sell, need_combat = needs()  # refresh per action
                scenes = set(state.get("scenes") or [])
                if "CombatScene" in scenes:
                    if obj["combat"] is not None and not obj["combat"].get("survived"):
                        finding(f"still in CombatScene after an unresolved fight — stuck scene")
                        break
                    handle_combat()
                    if obj["defeated"]:
                        break
                    continue
                if "TradingScene" in scenes:
                    handle_trading()
                    continue
                sector_now = state.get("currentSector") or {}
                port_key = (sector_now.get("id"), cargo_sig(state))
                if sector_now.get("hasPort") and (need_buy or need_sell) and port_key not in obj["barren"]:
                    s, _, _, info = step(TRADE_OPEN)
                    if not info.get("ok"):
                        finding(f"TRADE button refused on a port sector: {info.get('error')}")
                        stalled += 1
                    continue
                # Warp: deliberately enter a pirate sector if combat is still owed.
                exits = (state.get("currentSector") or {}).get("exits", [])
                pirate_adjacent = any(e.get("hasAlivePirate") for e in exits)
                if need_combat and pirate_adjacent:
                    obj["combat_entry_state"] = {
                        "credits": state["player"]["credits"],
                        "hull": state["player"]["ship"].get("hull"),
                        "botsAlive": state.get("botsAlive"),
                    }
                    s, term, trunc, info = step(WARP_PIRATE)
                    if "CombatScene" not in s.get("scenes", []):
                        finding(f"warp into pirate sector did not start combat: scenes={s.get('scenes')} info={info}")
                        stalled += 1
                    continue
                action = WARP_ANY if (need_combat and not need_buy) else WARP_SAFE
                s, term, trunc, info = step(action)
                if term or trunc:
                    break
                if "CombatScene" in s.get("scenes", []):
                    # Accidental encounter via warp_any — entry snapshot is the pre-warp state.
                    obj.setdefault("combat_entry_state", None)
                    if obj["combat_entry_state"] is None or not need_combat:
                        obj["combat_entry_state"] = {
                            "credits": inv.prev["player"]["credits"],
                            "hull": inv.prev["player"]["ship"].get("hull"),
                            "botsAlive": inv.prev.get("botsAlive"),
                        }
                    continue
                if not info.get("ok"):
                    stalled += 1
            if obj["defeated"]:
                break

            # End turn (must be on the map).
            if "TradingScene" in set(state.get("scenes") or []):
                step(TRADE_EXIT)
            ap_before = state["player"]["actionPoints"]
            s, term, trunc, info = step(END_TURN)
            obj["cycles"] += 1
            if s["player"]["actionPoints"] > ap_before:
                obj["ap_refreshes"] += 1
            need_buy, need_sell, need_combat = needs()
            print(f"    cycle {obj['cycles']}: turn -> {s['turnNumber']}, "
                  f"AP {ap_before} -> {s['player']['actionPoints']}, "
                  f"credits {s['player']['credits']}, "
                  f"cargo {((s['player'].get('cargo') or {}).get('items'))}, "
                  f"buy={'done' if not need_buy else 'pending'} "
                  f"sell={'done' if not need_sell else 'pending'} "
                  f"combat={'done' if not need_combat else 'pending'}")

        # ── C. gate checks ────────────────────────────────────────────────────
        print("\n  -- C. cycles & invariants --")
        ck(f"at least {MIN_CYCLES} full turn cycles completed", obj["cycles"] >= MIN_CYCLES,
           f"{obj['cycles']} cycles (turn {start_turn} -> {state['turnNumber']})")
        ck("AP refreshed on every end_turn", obj["ap_refreshes"] == obj["cycles"],
           f"{obj['ap_refreshes']}/{obj['cycles']}")
        ck("invariants held after every action (AP/fog/turn/credits/cargo/scenes)",
           not inv.violations,
           f"{inv.steps} actions checked" if not inv.violations else "; ".join(inv.violations[:4]))
        for v in inv.violations:
            finding(f"invariant violation: {v}")

        print("\n  -- D. economy loop --")
        good_buy = next((b for b in obj["buys"] if b["ok"]), None)
        any_buy = obj["buys"][0] if obj["buys"] else None
        ck("player-driven BUY inside TradingScene (credits -= quoted price, cargo +1)",
           good_buy is not None and good_buy["cargo_plus_one"],
           (f"bought 1 {good_buy['commodity']} at {good_buy['unitPrice']}cr, paid {good_buy['paid']}, "
            f"port stock {good_buy['stock_delta']:+d}" if good_buy else
            f"no clean buy; attempts={[(b['commodity'], b['paid'], b['unitPrice']) for b in obj['buys']]}"
            if any_buy else "no buy executed (no port reached?)"))
        if good_buy and good_buy["stock_delta"] != -1:
            finding(f"buy of 1 {good_buy['commodity']} moved port stock by {good_buy['stock_delta']} (expected -1)")
        good_sell = next((s_ for s_ in obj["sells"] if s_["ok"]), None)
        any_sell = obj["sells"][0] if obj["sells"] else None
        ck("player-driven SELL inside TradingScene (credits += qty x quoted price, stack cleared)",
           good_sell is not None and good_sell["stack_cleared"],
           (f"sold {good_sell['qty']} {good_sell['commodity']} at {good_sell['unitPrice']}cr "
            f"-> +{good_sell['credit_delta']}cr at port {good_sell['port']}" if good_sell else
            f"no clean sell; attempts={[(s_['commodity'], s_['credit_delta'], s_['expected_revenue']) for s_ in obj['sells']]}"
            if any_sell else
            f"no sell executed — ports visited {sorted(obj['ports_visited'])}, "
            f"cargo at end {((state.get('player') or {}).get('cargo') or {}).get('items')}"))
        ck("trade round-trips left the run on the galaxy map",
           "GalaxyMapScene" in state.get("scenes", []) or obj["defeated"],
           f"scenes={state.get('scenes')}")

        print("\n  -- E. combat loop --")
        c = obj["combat"]
        ck("mid-run combat happened and the run SURVIVED it",
           bool(c and c.get("survived")),
           (f"beat {c['enemy']} ({c['outcome']})" if c and c.get("survived")
            else (c or {}).get("detail", "no combat entered — no pirate found in budget")))
        if c and c.get("survived"):
            ck("salvage credited exactly (credits delta == salvageAwarded)",
               bool(c["salvage_credited_exactly"]),
               f"salvage={c['salvage']} credit_delta={c['credit_delta']}")
            ck("hull damage persisted back on the map",
               bool(c["hull_persisted"]),
               f"hull {c['hull_before']} -> {c['hull_end_combat']} (combat) -> {c['hull_on_map']} (map)")
            ck("defeated pirate removed from the galaxy", bool(c["bot_removed"]),
               f"botsAlive delta confirmed" if c["bot_removed"] else "botsAlive did not drop by 1")
            if not c["took_damage"]:
                finding(f"combat vs {c['enemy']} dealt the player no hull damage "
                        f"({c['hull_before']} -> {c['hull_on_map']}) — balance smell, check combat math")
            if c.get("module_dropped"):
                finding(f"module drop '{c['module_dropped']}' was neither taken nor scrapped "
                        f"(hook exits past the Take/Leave overlay) — harness gap, fine for Round 2")

    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        ck("exception-free run", False, f"{type(exc).__name__}: {exc}")
    finally:
        ad.close()

    passed = sum(1 for _, ok, _ in checks if ok)
    total = len(checks)
    print(f"\n{'=' * 70}")
    if findings:
        print("FINDINGS (bugs/gaps to fix upstream or note):")
        for i, f in enumerate(findings, 1):
            print(f"  {i}. {f}")
        print()
    if passed == total:
        print(f"ROUND 2 MET — {passed}/{total} checks. Three clean turn cycles with a real "
              f"buy+sell and a survived combat; all invariants held. Ready for Round 3 (10-turn "
              f"exploit-hunter gate).")
        return 0
    print(f"ROUND 2 NOT MET — {passed}/{total} checks passed. Fix the failures above and re-run.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
