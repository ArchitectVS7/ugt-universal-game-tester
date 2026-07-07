#!/usr/bin/env python3
"""
Warzones ROUND 3 — ten-turn robustness gate through the REAL game, driven by
UGT's exploit-hunter tier (ugt/core/exploit_hunter.py — the framework's Phase-1
machinery, not a bespoke loop; this is its first browser-game outing).

A scene-aware heuristic policy plays ~10 full turn cycles per episode with
seeded episode resets, and every single step is checked against the game's
invariants:

    AP never negative · fog monotonic · turnNumber changes only via end_turn
    credits never negative · cargo within capacity · hull within bounds
    bots never resurrect · world constants stable (sectors/ports/seed)
    event log append-only · never a stuck/no-run scene · no soft-lock

Gate: all episodes clean (zero findings), >= 2 of 3 episodes complete ten full
cycles (an early DefeatScene/VictoryScene is a legitimate end, not a bug),
every hook action attempted at least once, and a same-seed re-run of episode 0
reproduces the exact step-for-step trajectory (WZ-R7 determinism, end to end).

Run (with `npm run dev` serving :3000 — verify the LISTEN PID!):

    python3 integrations/warzones/verify_round10.py [base_seed]
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from ugt.adapters.playwright import PlaywrightAdapter
from ugt.core.exploit_hunter import ExploitHunter, Invariant
from ugt.utils.config_parser import UgtConfig

CONFIG_PATH = "integrations/warzones/ugt.config.yaml"
BASE_SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 20260707
POLICY_SEED = 424242
EPISODES = 3
TURNS_REQUIRED = 10
STEPS_PER_EPISODE = 400   # cap; ~10 turns normally finish well under this

WAIT, END_TURN, SCAN, WARP_SAFE, WARP_ANY, WARP_PIRATE = 0, 1, 2, 3, 4, 5
COMBAT_ATTACK, COMBAT_FLEE, TRADE_OPEN, TRADE_EXIT = 6, 7, 8, 9
TRADE_BUY, TRADE_SELL = 10, 11

RUN_SCENES = {"GalaxyMapScene", "CombatScene", "TradingScene"}
TERMINAL_SCENES = {"VictoryScene", "DefeatScene"}


# ── instrumented, seeded adapter ─────────────────────────────────────────────
class SeededWarzonesAdapter(PlaywrightAdapter):
    """PlaywrightAdapter with seeded episode resets and a per-episode
    trajectory record (for the 10-cycle and determinism gate checks).
    Instrumentation only — every game interaction is the parent class's."""

    def __init__(self, config, base_seed: int):
        super().__init__(config)
        self.base_seed = base_seed
        self.episode = -1
        self.stats: list[dict] = []

    def reset(self):
        if not self.page:
            self.connect()
        self.episode += 1
        seed = self.base_seed + self.episode
        self.page.evaluate(f"window.__RESET_GAME__({seed})")
        state = self._get_game_state()
        self.stats.append({
            "seed": seed,
            "start_turn": state.get("turnNumber"),
            "max_turn": state.get("turnNumber"),
            "steps": 0,
            "terminated": False,
            "final_scenes": list(state.get("scenes") or []),
            "traj": [],
        })
        return state

    def step(self, action_id):
        state, terminated, truncated, info = super().step(action_id)
        st = self.stats[-1]
        st["steps"] += 1
        st["max_turn"] = max(st["max_turn"], state.get("turnNumber") or 0)
        st["terminated"] = st["terminated"] or terminated
        st["final_scenes"] = list(state.get("scenes") or [])
        p = state.get("player") or {}
        st["traj"].append((
            action_id,
            state.get("turnNumber"),
            p.get("credits"),
            (p.get("ship") or {}).get("hull"),
            (state.get("fog") or {}).get("discoveredCount"),
            state.get("botsAlive"),
            tuple(sorted(state.get("scenes") or [])),
        ))
        return state, terminated, truncated, info


# ── scene-aware heuristic policy ─────────────────────────────────────────────
def warzones_policy(state: dict, action_ids: list, rng, ctx: dict) -> int:
    scenes = set(state.get("scenes") or [])
    if "CombatScene" in scenes:
        # First combat contact of the episode always tries to flee — coverage
        # of the flee path must not depend on a 30% roll ever landing.
        if not ctx.get("fled_once") and not (state.get("combat") or {}).get("resolved"):
            ctx["fled_once"] = True
            return COMBAT_FLEE
        return COMBAT_ATTACK if rng.random() < 0.7 else COMBAT_FLEE
    if "TradingScene" in scenes:
        r = rng.random()
        return TRADE_BUY if r < 0.3 else TRADE_SELL if r < 0.6 else TRADE_EXIT
    ap = (state.get("player") or {}).get("actionPoints") or 0
    if ap < 1:
        return END_TURN
    exits = (state.get("currentSector") or {}).get("exits") or []
    if any(e.get("hasAlivePirate") for e in exits) and rng.random() < 0.5:
        return WARP_PIRATE  # seek combat when it is actually on offer
    actions = [SCAN, WARP_SAFE, WARP_ANY, WARP_PIRATE, TRADE_OPEN, WAIT, END_TURN]
    weights = [0.10, 0.30, 0.25, 0.05, 0.15, 0.05, 0.05]
    return rng.choices(actions, weights=weights, k=1)[0]


# ── invariants (checked after EVERY step) ────────────────────────────────────
def _player(s):
    return s.get("player") or {}


def inv_ap(before, action, info, after, ctx):
    ap = _player(after).get("actionPoints")
    if ap is None or ap < 0:
        return f"actionPoints={ap}"
    return None


def inv_fog(before, action, info, after, ctx):
    b = (before.get("fog") or {}).get("discoveredCount") or 0
    a = (after.get("fog") or {}).get("discoveredCount") or 0
    if a < b:
        return f"discoveredCount {b} -> {a}"
    return None


def inv_turn(before, action, info, after, ctx):
    b, a = before.get("turnNumber"), after.get("turnNumber")
    if action == END_TURN:
        if a not in (b, b + 1):  # unchanged is legal when end_turn was refused
            return f"end_turn moved turn {b} -> {a}"
        if a == b and info.get("ok"):
            return f"end_turn reported ok but turn stayed {b}"
    elif a != b:
        return f"turn {b} -> {a} on non-end_turn action {action}"
    return None


def inv_credits(before, action, info, after, ctx):
    c = _player(after).get("credits")
    if c is None or c < 0:
        return f"credits={c}"
    return None


def inv_cargo(before, action, info, after, ctx):
    cargo = _player(after).get("cargo") or {}
    used, cap = cargo.get("used"), cargo.get("capacity")
    if used is None or cap is None:
        return "cargo used/capacity missing from state"
    if used > cap:
        return f"cargo {used}/{cap}"
    if used != sum((cargo.get("items") or {}).values()):
        return f"cargo.used={used} != sum(items {cargo.get('items')})"
    return None


def inv_hull(before, action, info, after, ctx):
    ship = _player(after).get("ship") or {}
    hull, mx = ship.get("hull"), ship.get("maxHull")
    if hull is None or mx is None:
        return "hull/maxHull missing from state"
    if hull < 0 or hull > mx:
        return f"hull={hull} maxHull={mx}"
    return None


def inv_scene(before, action, info, after, ctx):
    if after.get("ready") is not True:
        return f"state not ready: {after.get('reason')}"
    scenes = set(after.get("scenes") or [])
    if not scenes & (RUN_SCENES | TERMINAL_SCENES):
        return f"no run/terminal scene active: {sorted(scenes)}"
    return None


def inv_bots(before, action, info, after, ctx):
    b, a = before.get("botsAlive"), after.get("botsAlive")
    if a is not None and b is not None and a > b:
        return f"botsAlive {b} -> {a} (resurrection)"
    return None


def inv_world(before, action, info, after, ctx):
    if "world" not in ctx:
        ctx["world"] = (before.get("sectorCount"), before.get("portCount"), before.get("seed"))
    sectors, ports, seed = ctx["world"]
    now = (after.get("sectorCount"), after.get("portCount"), after.get("seed"))
    if now != (sectors, ports, seed):
        return f"world constants drifted: {ctx['world']} -> {now}"
    if sectors != 100:
        return f"sectorCount={sectors} (expected 100)"
    return None


def inv_eventlog(before, action, info, after, ctx):
    b, a = before.get("eventLogTotal") or 0, after.get("eventLogTotal") or 0
    if a < b:
        return f"eventLogTotal {b} -> {a} (log truncated)"
    return None


def inv_softlock(before, action, info, after, ctx):
    fails = ctx.get("consecutive_fails", 0)
    fails = 0 if info.get("ok") else fails + 1
    ctx["consecutive_fails"] = fails
    if fails >= 25:
        return f"{fails} consecutive failed actions (last: {info.get('error')})"
    return None


INVARIANTS = [
    Invariant("ap_never_negative", inv_ap),
    Invariant("fog_monotonic", inv_fog),
    Invariant("turn_only_via_end_turn", inv_turn),
    Invariant("credits_never_negative", inv_credits),
    Invariant("cargo_within_capacity", inv_cargo),
    Invariant("hull_within_bounds", inv_hull),
    Invariant("no_stuck_scene", inv_scene),
    Invariant("bots_never_resurrect", inv_bots),
    Invariant("world_constants_stable", inv_world),
    Invariant("event_log_append_only", inv_eventlog),
    Invariant("no_soft_lock", inv_softlock),
]


def main() -> int:
    config = UgtConfig(CONFIG_PATH)
    action_names = {int(k): v["name"] for k, v in config.data["action_space"]["actions"].items()}
    checks: list[tuple[str, bool, str]] = []

    def ck(name: str, ok: bool, detail: str = ""):
        checks.append((name, ok, detail))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))

    print(f"Round 3 — {TURNS_REQUIRED}-turn exploit-hunter gate, "
          f"{EPISODES} episodes, base seed {BASE_SEED}\n")

    adapter = SeededWarzonesAdapter(config, BASE_SEED)
    try:
        adapter.connect()

        # ── hunt ──────────────────────────────────────────────────────────────
        print("  -- hunt --")
        hunter = ExploitHunter(adapter, INVARIANTS, list(action_names.keys()),
                               action_names=action_names,
                               policy=warzones_policy, seed=POLICY_SEED)
        report = hunter.run(episodes=EPISODES, steps_per_episode=STEPS_PER_EPISODE,
                            log=lambda m: print(f"    {m}"))

        print("\n  -- gate --")
        ck(f"all {EPISODES} episodes ran through the exploit-hunter",
           report.episodes == EPISODES and report.total_steps > 0,
           f"{report.episodes} episodes, {report.total_steps} steps")

        ck("zero invariant violations / crashes across every step",
           not report.findings,
           f"{len(INVARIANTS)} invariants x {report.total_steps} steps" if not report.findings
           else f"{len(report.findings)} finding(s) — see below")
        for f in report.findings:
            print(f"      [FINDING] ep{f.episode} step{f.step} {f.kind}/{f.name} "
                  f"action={f.action_name}: {f.message}")

        full, legit_early = [], []
        for i, st in enumerate(adapter.stats[:EPISODES]):
            cycles = st["max_turn"] - st["start_turn"]
            if cycles >= TURNS_REQUIRED:
                full.append(i)
            elif st["terminated"] and set(st["final_scenes"]) & TERMINAL_SCENES:
                legit_early.append(i)
            print(f"    episode {i}: seed {st['seed']}, {st['steps']} steps, "
                  f"turn {st['start_turn']} -> {st['max_turn']} ({cycles} cycles), "
                  f"end scenes {st['final_scenes']}")
        ck(f"at least 2 of {EPISODES} episodes completed {TURNS_REQUIRED} full cycles",
           len(full) >= 2, f"full={full} legitimate-early-end={legit_early}")
        ck("every episode either finished its cycles or ended on a real terminal scene",
           len(full) + len(legit_early) == EPISODES,
           f"unaccounted={sorted(set(range(EPISODES)) - set(full) - set(legit_early))}")

        missing = [n for n in action_names.values() if n not in report.action_counts]
        ck("every hook action attempted at least once", not missing,
           f"coverage: { {k: report.action_counts[k] for k in sorted(report.action_counts)} }"
           if not missing else f"never attempted: {missing}")

        # ── determinism: replay episode 0 and require the same trajectory ────
        print("\n  -- determinism replay (episode 0) --")
        replay_adapter = SeededWarzonesAdapter(config, BASE_SEED)
        replay_adapter.page = adapter.page          # reuse the live browser page
        replay_adapter.browser = adapter.browser
        replay_adapter.playwright = adapter.playwright
        replay_hunter = ExploitHunter(replay_adapter, INVARIANTS, list(action_names.keys()),
                                      action_names=action_names,
                                      policy=warzones_policy, seed=POLICY_SEED)
        replay_report = replay_hunter.run(episodes=1, steps_per_episode=STEPS_PER_EPISODE,
                                          log=lambda m: print(f"    {m}"))
        first, second = adapter.stats[0], replay_adapter.stats[0]
        same_len = len(first["traj"]) == len(second["traj"])
        divergence = next((i for i, (x, y) in enumerate(zip(first["traj"], second["traj"]))
                           if x != y), None)
        ck("same-seed replay reproduces episode 0 step for step (WZ-R7 end to end)",
           same_len and divergence is None and not replay_report.findings,
           f"{len(first['traj'])} steps identical" if same_len and divergence is None
           else f"len {len(first['traj'])} vs {len(second['traj'])}, "
                f"first divergence at step {divergence}: "
                f"{first['traj'][divergence] if divergence is not None and divergence < len(first['traj']) else '-'} vs "
                f"{second['traj'][divergence] if divergence is not None and divergence < len(second['traj']) else '-'}")

        replay_adapter.page = None   # page belongs to the primary adapter
        replay_adapter.browser = None
        replay_adapter.playwright = None

    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        ck("exception-free run", False, f"{type(exc).__name__}: {exc}")
    finally:
        adapter.close()

    passed = sum(1 for _, ok, _ in checks if ok)
    total = len(checks)
    print(f"\n{'=' * 70}")
    if passed == total:
        print(f"ROUND 3 MET — {passed}/{total} checks. Ten-turn cycles run clean under the "
              f"exploit-hunter: every invariant held on every step, all actions exercised, "
              f"and a same-seed episode replays step for step. Warzones trial ladder complete.")
        return 0
    print(f"ROUND 3 NOT MET — {passed}/{total} checks passed. Findings above are the work list.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
