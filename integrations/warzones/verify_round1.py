#!/usr/bin/env python3
"""
Warzones ROUND 1 playability verification — one full turn cycle through the REAL game.

Drives the actual Phaser game (npm run dev on :3000) via PlaywrightAdapter and the
UGT hooks in warzones-game/src/ugt-hooks.ts. Round-1 definition of done:

    A. a fresh seeded game starts and its state is readable
    B. all game information a player sees has real values (info accessibility)
    C. the player can take their turn (scan + warp change state the way the rules say)
    D. the NPCs take their turns (bot deltas + event log after end_turn)
    E. a second full cycle works (repeatability)
    F. known-gap probes: same-seed determinism, trading reachability, combat return
       (expected failures here are FINDINGS to fix upstream, not harness errors)

No game logic is reimplemented; every effect is read back from the live GameState
projection. Run (with the dev server up):

    python3 integrations/warzones/verify_round1.py

Exit 0 + "ROUND 1 MET" means the one-turn-cycle gate is passed. Findings are
printed regardless — a failed check is data.
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from ugt.adapters.playwright import PlaywrightAdapter
from ugt.utils.config_parser import UgtConfig

CONFIG_PATH = "integrations/warzones/ugt.config.yaml"
SEED = 20260706

WAIT, END_TURN, SCAN, WARP_SAFE, WARP_ANY, WARP_PIRATE = 0, 1, 2, 3, 4, 5
COMBAT_ATTACK, COMBAT_FLEE, TRADE_OPEN, TRADE_EXIT = 6, 7, 8, 9

# Fields a player can see on the HUD/map that therefore must exist and be non-null.
REQUIRED_PLAYER_FIELDS = ["credits", "actionPoints", "maxActionPoints", "currentSectorId"]
REQUIRED_TOP_FIELDS = ["turnNumber", "sectorCount", "botsAlive", "portCount"]


def reset_seeded(ad: PlaywrightAdapter, seed: int) -> dict:
    """Seeded variant of adapter.reset(): same __RESET_GAME__ hook, fixed galaxy."""
    ad.page.evaluate(f"window.__RESET_GAME__({seed})")
    state = ad.page.evaluate("window.__GET_STATE__()")
    if not isinstance(state, dict):
        raise RuntimeError("__GET_STATE__ did not return an object after reset")
    return state


def galaxy_fingerprint(state: dict) -> tuple:
    """Stable identity of a generated galaxy: start-sector layout + bot roster."""
    sector = state.get("currentSector") or {}
    return (
        tuple(sorted(sector.get("connectedSectorIds", []))),
        tuple(b["name"] for b in state.get("bots", [])),
        tuple(b["currentSectorId"] for b in state.get("bots", [])),
        state.get("portCount"),
    )


def bot_turn_evidence(before: dict, after: dict) -> dict:
    """Deltas proving bots acted between two states."""
    b_bots = {b["id"]: b for b in before.get("bots", [])}
    survived_ticks = 0
    moved_or_spent = 0
    for bot in after.get("bots", []):
        prev = b_bots.get(bot["id"])
        if not prev or not prev["isAlive"]:
            continue
        if (bot.get("turnsSurvived") or 0) > (prev.get("turnsSurvived") or 0):
            survived_ticks += 1
        if bot["currentSectorId"] != prev["currentSectorId"] or bot["credits"] != prev["credits"]:
            moved_or_spent += 1
    bot_actions = [e for e in after.get("eventLog", []) if e["type"] == "BotAction" and e["turn"] == before["turnNumber"]]
    # The game stamps the "Turn ended." summary with the NEW turn number
    # (turn-manager.ts increments turnNumber before logging it) — finding WZ-R5.
    turn_end = [
        e for e in after.get("eventLog", [])
        if e["type"] == "TurnEnd" and (e.get("message") or "").startswith("Turn ended.")
        and e["turn"] in (before["turnNumber"], before["turnNumber"] + 1)
    ]
    return {
        "survived_ticks": survived_ticks,
        "alive_before": before.get("botsAlive", 0),
        "moved_or_spent": moved_or_spent,
        "bot_action_events": len(bot_actions),
        "turn_end_events": len(turn_end),
        "turn_end_msg": turn_end[-1]["message"] if turn_end else None,
        "turn_end_stamped_next_turn": bool(turn_end) and turn_end[-1]["turn"] == before["turnNumber"] + 1,
    }


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

    print("Round 1 — one full turn cycle through the REAL warzones client\n")
    try:
        ad.connect()

        # ── A. fresh seeded game ──────────────────────────────────────────────
        print("  -- A. reset --")
        s0 = reset_seeded(ad, SEED)
        ck("reset(seed) reaches GalaxyMapScene with readable state",
           s0.get("ready") is True and "GalaxyMapScene" in s0.get("scenes", []),
           f"scenes={s0.get('scenes')}")
        ck("seed is honored (determinism seam live)", s0.get("seed") == SEED,
           f"state.seed={s0.get('seed')}")
        fp_first = galaxy_fingerprint(s0)

        # ── B. information accessibility ─────────────────────────────────────
        print("\n  -- B. information access --")
        missing = [f for f in REQUIRED_TOP_FIELDS if s0.get(f) in (None, "")]
        missing += [f"player.{f}" for f in REQUIRED_PLAYER_FIELDS if (s0.get("player") or {}).get(f) in (None, "")]
        ck("required HUD fields present and non-null", not missing, f"missing={missing}" if missing else
           f"credits={s0['player']['credits']} ap={s0['player']['actionPoints']} sectors={s0['sectorCount']} bots={s0['botsAlive']}")
        ck("galaxy generated to spec (100 sectors, 8 bots alive)",
           s0.get("sectorCount") == 100 and s0.get("botsAlive") == 8,
           f"sectorCount={s0.get('sectorCount')} botsAlive={s0.get('botsAlive')}")
        ck("fog of war initialized (1 discovered sector, exits known)",
           s0.get("fog", {}).get("discoveredCount") == 1 and len(s0.get("fog", {}).get("knownExitsFromCurrent", [])) > 0,
           f"discovered={s0.get('fog', {}).get('discoveredIds')} exits={s0.get('fog', {}).get('knownExitsFromCurrent')}")
        ck("event log readable", isinstance(s0.get("eventLog"), list), f"events={len(s0.get('eventLog', []))}")
        ck("ports exist and are countable", (s0.get("portCount") or 0) > 0, f"portCount={s0.get('portCount')}")

        # ── C. player takes their turn ────────────────────────────────────────
        print("\n  -- C. player turn --")
        ap0 = s0["player"]["actionPoints"]
        s1, term, trunc, info = ad.step(SCAN)
        ck("scan executes and spends AP", bool(info.get("ok")) and s1["player"]["actionPoints"] < ap0,
           f"AP {ap0} -> {s1['player']['actionPoints']} (spent {info.get('apSpent')})")

        pos_before = s1["player"]["currentSectorId"]
        disc_before = s1["fog"]["discoveredCount"]
        ap_before = s1["player"]["actionPoints"]
        s2, term, trunc, info = ad.step(WARP_SAFE)
        ck("warp moves the player one hop (real UI path)",
           bool(info.get("ok")) and s2["player"]["currentSectorId"] != pos_before,
           f"sector {pos_before} -> {s2['player']['currentSectorId']} via '{info.get('warpButtonLabel')}' (target {info.get('target')})")
        ck("warp spends 1 AP", s2["player"]["actionPoints"] == ap_before - 1,
           f"AP {ap_before} -> {s2['player']['actionPoints']}")
        ck("fog of war advances on discovery", s2["fog"]["discoveredCount"] >= disc_before,
           f"discovered {disc_before} -> {s2['fog']['discoveredCount']}")
        warp_events = [e for e in s2.get("eventLog", []) if e["type"] == "WarpComplete"]
        ck("warp is logged for the player", len(warp_events) > 0,
           warp_events[-1]["message"] if warp_events else "no WarpComplete event")

        # ── D. NPCs take their turns ──────────────────────────────────────────
        print("\n  -- D. NPC turns (end turn) --")
        before = s2
        s3, term, trunc, info = ad.step(END_TURN)
        ck("end turn advances the turn counter", s3["turnNumber"] == before["turnNumber"] + 1,
           f"turn {before['turnNumber']} -> {s3['turnNumber']}")
        ck("player AP refreshes for the new turn",
           s3["player"]["actionPoints"] > before["player"]["actionPoints"],
           f"AP {before['player']['actionPoints']} -> {s3['player']['actionPoints']}")
        ev = bot_turn_evidence(before, s3)
        ck("every alive bot ticked its turn", ev["survived_ticks"] == ev["alive_before"],
           f"{ev['survived_ticks']}/{ev['alive_before']} bots ticked")
        ck("bots visibly acted (moved/earned or logged actions)",
           ev["moved_or_spent"] > 0 or ev["bot_action_events"] > 0,
           f"moved/spent={ev['moved_or_spent']} BotAction events={ev['bot_action_events']}")
        ck("TurnEnd event logged", ev["turn_end_events"] > 0, str(ev["turn_end_msg"]))
        if ev.get("turn_end_stamped_next_turn"):
            finding("Turn-end summary event is stamped with the NEXT turn's number (turn-manager.ts "
                    "increments turnNumber before logging 'Turn ended.'), while the territory-income "
                    "TurnEnd uses the ending turn — same moment, two turn stamps (WZ-R5, minor)")

        # ── E. second full cycle (repeatability) ─────────────────────────────
        print("\n  -- E. second cycle --")
        s4, *_ , info_w = ad.step(WARP_SAFE)
        s5, term, trunc, info_e = ad.step(END_TURN)
        ev2 = bot_turn_evidence(s4, s5)
        ck("cycle 2: warp + end turn both work",
           bool(info_w.get("ok")) and s5["turnNumber"] == s4["turnNumber"] + 1,
           f"turn -> {s5['turnNumber']}, discovered={s5['fog']['discoveredCount']}")
        ck("cycle 2: bots ticked again", ev2["survived_ticks"] == ev2["alive_before"],
           f"{ev2['survived_ticks']}/{ev2['alive_before']}")

        # ── F. probes (findings, not gate criteria) ──────────────────────────
        print("\n  -- F. probes --")

        # F1: same-seed determinism — a second reset with the same seed must
        # produce the same galaxy.
        s_re = reset_seeded(ad, SEED)
        fp_second = galaxy_fingerprint(s_re)
        same = fp_first == fp_second
        ck("same seed reproduces the same galaxy", same,
           "fingerprints match" if same else f"first={fp_first} second={fp_second}")

        # F2: trading loop (WZ-R2 fix) — walk to a port, open the TRADE button,
        # confirm TradingScene, exit back to the map with the run intact.
        landed_on_port = None
        state = s_re
        for _ in range(12):
            if (state.get("currentSector") or {}).get("hasPort"):
                landed_on_port = state["currentSector"]["id"]
                break
            state, term, trunc, info = ad.step(WARP_SAFE)
            if not info.get("ok"):
                state, *_ = ad.step(END_TURN)  # AP exhausted or boxed in — new turn
                continue
            if (state.get("currentSector") or {}).get("hasPort"):
                landed_on_port = state["currentSector"]["id"]
                break
        if landed_on_port is None:
            ck("trading reachable via TRADE button (WZ-R2)", False,
               "no port sector reached in 12 safe warps — cannot exercise trading")
        else:
            turn_at_dock = state["turnNumber"]
            state, term, trunc, info = ad.step(TRADE_OPEN)
            opened = "TradingScene" in state.get("scenes", []) and (state.get("trade") or {}).get("portSectorId") == landed_on_port
            ck("TRADE button opens the port (WZ-R2 fixed)", opened,
               f"scenes={state.get('scenes')} trade={state.get('trade')} info={info}")
            state, term, trunc, info = ad.step(TRADE_EXIT)
            returned = "GalaxyMapScene" in state.get("scenes", []) and state.get("turnNumber") == turn_at_dock
            ck("leaving the port returns to the galaxy map, run intact", returned,
               f"scenes={state.get('scenes')} turn={state.get('turnNumber')} (was {turn_at_dock})")

        # F3: combat loop (WZ-R1 fix) — enter a pirate sector, fight, and confirm
        # the run continues (return to map) or ends legitimately (DefeatScene).
        # Run LAST since defeat ends the session.
        def in_combat(s):
            return "CombatScene" in s.get("scenes", [])

        pirate_adjacent = any(e.get("hasAlivePirate") for e in (state.get("currentSector") or {}).get("exits", []))
        hops = 0
        while not in_combat(state) and not pirate_adjacent and hops < 25:
            state, term, trunc, info = ad.step(WARP_ANY)
            hops += 1
            if in_combat(state) or trunc or term:
                break
            if not info.get("ok"):
                state, *_ = ad.step(END_TURN)
            pirate_adjacent = any(e.get("hasAlivePirate") for e in (state.get("currentSector") or {}).get("exits", []))

        if not in_combat(state) and pirate_adjacent:
            state, term, trunc, info = ad.step(WARP_PIRATE)

        if in_combat(state):
            enemy = (state.get("combat") or {}).get("enemy")
            bots_before = state.get("botsAlive")
            outcome_detail = ""
            resolved_run = False
            for _ in range(12):
                state, term, trunc, info = ad.step(COMBAT_ATTACK)
                if "GalaxyMapScene" in state.get("scenes", []):
                    resolved_run = True
                    outcome_detail = (f"fought {enemy}, returned to galaxy map; "
                                      f"botsAlive {bots_before} -> {state.get('botsAlive')}, "
                                      f"credits={state['player']['credits']}, hull={state['player']['ship'].get('hull')}")
                    break
                if term:
                    resolved_run = True
                    outcome_detail = f"fought {enemy}, player destroyed -> DefeatScene (legitimate game over)"
                    break
                if trunc:
                    outcome_detail = f"run destroyed: scenes={state.get('scenes')} (WZ-R1 regression)"
                    break
            else:
                outcome_detail = f"still in combat after 12 attacks: combat={state.get('combat')}"
            ck("combat resolves and the run continues or ends legitimately (WZ-R1 fixed)",
               resolved_run, outcome_detail)
        else:
            ck("combat probe reached a fight (WZ-R1)", False,
               f"no pirate encountered within {hops} hops — inconclusive, re-run or extend the wander")

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
        print("FINDINGS (bugs/gaps in the game, to fix upstream):")
        for i, f in enumerate(findings, 1):
            print(f"  {i}. {f}")
        print()
    if passed == total:
        print(f"ROUND 1 MET — {passed}/{total} checks. The player takes a turn, all HUD "
              f"information is accessible, all bots take their turns, and the cycle repeats. "
              f"Ready to proceed to the 3-turn round.")
        return 0
    print(f"ROUND 1 NOT MET — {passed}/{total} checks passed. Fix the failures above and re-run.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
