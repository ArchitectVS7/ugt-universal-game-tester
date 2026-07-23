#!/usr/bin/env python3
"""
Tarot-war ROUND 3 — full-game robustness gate through the REAL game, driven by
UGT's exploit-hunter tier (ugt/core/exploit_hunter.py — the framework's Phase-1
machinery, not a bespoke loop; second browser-game outing after warzones).

A phase-aware heuristic policy plays whole games (mode and difficulty chosen
per episode through the real setup pickers) with seeded episode resets, and
every single step is checked against the game's invariants:

    scores never decrease · currentRound monotonic · game log append-only
    no card id ever more than twice (TW-R1) · census total only drops by
    exactly 2 alongside a Tower destruction · war pile empty between steps
    only legal phase transitions · finished implies a winner · finished is
    terminal (TW-R8) · refused actions change no material state · state
    always readable · no soft-lock

The policy also probes the refusal paths on purpose: mid-game picker attempts
(the UI hides those controls outside setup) and an UNMAPPED action id (99),
which the hooks must reject without side effects.

Gate: all episodes clean (zero findings), >= 2 of 3 episodes play a full game
to 'finished', every hook action attempted at least once, the unmapped-id
probe fired, and a same-seed re-run of episode 0 reproduces the exact
step-for-step trajectory (TW-R3 determinism, end to end).

Run (with `npm run dev` serving :5173 — verify the LISTEN PID!):

    python3 integrations/tarot-war/verify_round3.py [base_seed]
"""
from __future__ import annotations

import sys
from collections import Counter

sys.path.insert(0, ".")

from ugt.adapters.playwright import PlaywrightAdapter
from ugt.core.exploit_hunter import ExploitHunter, Invariant
from ugt.utils.config_parser import UgtConfig

CONFIG_PATH = "integrations/tarot-war/ugt.config.yaml"
BASE_SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 20260709
POLICY_SEED = 424242
EPISODES = 3
STEPS_PER_EPISODE = 400   # cap; observed full classic games need ~70-330 dispatches

WAIT, PLAY_ROUND = 0, 1
SET_AI_EASY, SET_AI_MEDIUM, SET_AI_HARD = 2, 3, 4
SET_MODE_CLASSIC, SET_MODE_SURVIVAL, SET_MODE_ENDLESS = 5, 6, 7
UNMAPPED_ID = 99          # deliberately not in the hook's dispatch table

PICKERS = [SET_AI_EASY, SET_AI_MEDIUM, SET_AI_HARD,
           SET_MODE_CLASSIC, SET_MODE_SURVIVAL, SET_MODE_ENDLESS]


# ── instrumented, seeded adapter ─────────────────────────────────────────────
class SeededTarotAdapter(PlaywrightAdapter):
    """PlaywrightAdapter with seeded episode resets and a per-episode
    trajectory record (for the completion and determinism gate checks).
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
        # RESET_GAME deliberately preserves the previous game's mode/difficulty
        # (a real UI behavior, verified in Round 2) — which makes episode
        # initial conditions depend on the PREVIOUS episode. Normalize to the
        # canonical baseline through the same hooks so episodes are
        # independent and a same-seed episode replay is well-defined.
        self.page.evaluate(f"window.__SEND_ACTION__({SET_MODE_CLASSIC})")
        self.page.evaluate(f"window.__SEND_ACTION__({SET_AI_MEDIUM})")
        state = self._get_game_state()
        self.stats.append({
            "seed": seed,
            "steps": 0,
            "max_round": 0,
            "finished": False,
            "final": None,
            "traj": [],
        })
        return state

    def step(self, action_id):
        state, terminated, truncated, info = super().step(action_id)
        st = self.stats[-1]
        st["steps"] += 1
        st["max_round"] = max(st["max_round"], state.get("currentRound") or 0)
        st["finished"] = st["finished"] or state.get("gamePhase") == "finished"
        st["final"] = (state.get("gamePhase"), state.get("winner"),
                       state.get("gameMode"), state.get("aiDifficulty"),
                       state["player1"]["score"], state["player2"]["score"])
        st["traj"].append((
            action_id,
            state.get("gamePhase"),
            state.get("currentRound"),
            state["player1"]["score"], state["player2"]["score"],
            state["player1"]["deckCount"], state["player1"]["discardCount"],
            state["player2"]["deckCount"], state["player2"]["discardCount"],
            (state["lastPlayedCards"]["player1"] or {}).get("id"),
            (state["lastPlayedCards"]["player2"] or {}).get("id"),
            state.get("gameLogTotal"),
            state.get("gameMode"), state.get("aiDifficulty"),
        ))
        return state, terminated, truncated, info


# ── phase-aware heuristic policy (deterministic given state + seeded rng) ────
def tarot_policy(state: dict, action_ids: list, rng, ctx: dict) -> int:
    phase = state.get("gamePhase")
    if phase == "setup":
        # Choose this episode's difficulty (seeded rng) and mode (derived from
        # the episode seed so the mix is classic/endless/survival across the
        # three episodes and a replayed episode picks the same mode) through
        # the real pickers.
        if not ctx.get("picked_ai"):
            ctx["picked_ai"] = True
            return rng.choice([SET_AI_EASY, SET_AI_MEDIUM, SET_AI_HARD])
        if not ctx.get("picked_mode"):
            ctx["picked_mode"] = True
            modes = [SET_MODE_CLASSIC, SET_MODE_ENDLESS, SET_MODE_SURVIVAL]
            return modes[((state.get("seed") or BASE_SEED) - BASE_SEED) % len(modes)]
        return PLAY_ROUND
    r = rng.random()
    if r < 0.03:
        return UNMAPPED_ID          # hooks must refuse an unmapped id
    if r < 0.08:
        return rng.choice(PICKERS)  # mid-game picker: the UI hides these — must refuse
    if r < 0.12:
        return WAIT
    return PLAY_ROUND


# ── invariants (checked after EVERY step) ────────────────────────────────────
# Phase set is tolerant of the AI auto-advance timer racing a dispatch
# (resolving->resolving = timer advanced, our dispatch resolved a full round).
ALLOWED_TRANSITIONS = {
    ("setup", "setup"),           # picker steps / refused probes
    ("setup", "resolving"), ("setup", "finished"),
    ("playing", "playing"),       # refused probes / wait
    ("playing", "resolving"), ("playing", "finished"),
    ("resolving", "resolving"), ("resolving", "playing"), ("resolving", "finished"),
    ("finished", "finished"),
}


def census(s: dict) -> Counter:
    return Counter(
        s["player1"]["deckIds"] + s["player1"]["discardIds"]
        + s["player2"]["deckIds"] + s["player2"]["discardIds"]
    )


def new_entries(before: dict, after: dict) -> list[dict]:
    added = (after.get("gameLogTotal") or 0) - (before.get("gameLogTotal") or 0)
    if added <= 0:
        return []
    log = after.get("gameLog", [])
    return log[-added:] if added <= len(log) else log


def inv_ready(before, action, info, after, ctx):
    if after.get("ready") is not True:
        return f"state not ready: {after.get('reason')}"
    if not after.get("player1") or not after.get("player2"):
        return "player projection missing"
    return None


def inv_scores(before, action, info, after, ctx):
    for p in ("player1", "player2"):
        if after[p]["score"] < before[p]["score"]:
            return f"{p} score {before[p]['score']} -> {after[p]['score']}"
    return None


def inv_round(before, action, info, after, ctx):
    b, a = before.get("currentRound") or 0, after.get("currentRound") or 0
    if a < b:
        return f"currentRound {b} -> {a}"
    if a > b + 2:
        return f"currentRound jumped {b} -> {a} in one step"
    return None


def inv_log(before, action, info, after, ctx):
    b, a = before.get("gameLogTotal") or 0, after.get("gameLogTotal") or 0
    if a < b:
        return f"gameLogTotal {b} -> {a} (log shrank)"
    return None


def inv_no_duplication(before, action, info, after, ctx):
    over = {cid: n for cid, n in census(after).items() if n > 2}
    if over:
        return f"card id seen more than twice: {over} (TW-R1 class)"
    return None


def inv_census_total(before, action, info, after, ctx):
    delta = sum(census(after).values()) - sum(census(before).values())
    towers = sum(1 for e in new_entries(before, after) if "Tower destroys" in e["message"])
    if delta != -2 * towers:
        return f"census total changed by {delta} with {towers} Tower destruction(s) logged"
    return None


def inv_war_pile(before, action, info, after, ctx):
    if after.get("warCardCount", 0) != 0:
        return f"war pile not empty between steps: {after.get('warCardCount')}"
    return None


def inv_phase(before, action, info, after, ctx):
    tr = (before.get("gamePhase"), after.get("gamePhase"))
    if tr not in ALLOWED_TRANSITIONS:
        return f"illegal phase transition {tr[0]} -> {tr[1]}"
    return None


def inv_finished_winner(before, action, info, after, ctx):
    if after.get("gamePhase") == "finished" and after.get("winner") not in ("player1", "player2"):
        return f"finished without a winner: {after.get('winner')}"
    return None


def inv_finished_terminal(before, action, info, after, ctx):
    if before.get("gamePhase") == "finished" and after.get("gamePhase") != "finished":
        return f"finished game came back to life: -> {after.get('gamePhase')} (TW-R8 class)"
    return None


def inv_refusal_inert(before, action, info, after, ctx):
    """A refused action must not change material state. Phase is excluded:
    the AI auto-advance timer may legitimately flip resolving->playing while
    a refused probe is in flight."""
    if info.get("ok"):
        return None
    material = lambda s: (  # noqa: E731
        s.get("currentRound"),
        s["player1"]["score"], s["player2"]["score"],
        s["player1"]["deckCount"], s["player1"]["discardCount"],
        s["player2"]["deckCount"], s["player2"]["discardCount"],
        s.get("gameLogTotal"),
    )
    if material(before) != material(after):
        return (f"refused action (error={info.get('error')}) changed state: "
                f"{material(before)} -> {material(after)}")
    return None


def inv_softlock(before, action, info, after, ctx):
    fails = 0 if info.get("ok") else ctx.get("consecutive_fails", 0) + 1
    ctx["consecutive_fails"] = fails
    if fails >= 25:
        return f"{fails} consecutive failed actions (last: {info.get('error')})"
    return None


def trajectories_match(first: list, second: list) -> tuple[bool, str]:
    """True only when two NON-EMPTY, same-length trajectories agree step for step.

    Two empty trajectories are the vacuous-pass trap this guard exists to close:
    `len([]) == len([])` is True and `next(zip([], []))` is None, so the old inline
    `same_len and divergence is None` predicate reported a clean replay without ever
    comparing a driven step. Empty input therefore FAILS here — nothing was measured.
    A negative case is pinned in integrations/tarot-war/determinism_selftest.py.
    """
    if not first or not second:
        return False, (f"empty trajectory — nothing compared "
                       f"(first={len(first)} steps, second={len(second)} steps)")
    if len(first) != len(second):
        return False, f"length differs: {len(first)} vs {len(second)} steps"
    div = next((i for i, (x, y) in enumerate(zip(first, second)) if x != y), None)
    if div is not None:
        return False, f"first divergence at step {div}: {first[div]} vs {second[div]}"
    return True, f"{len(first)} steps identical"


INVARIANTS = [
    Invariant("state_readable", inv_ready),
    Invariant("scores_never_decrease", inv_scores),
    Invariant("round_monotonic", inv_round),
    Invariant("log_append_only", inv_log),
    Invariant("no_card_duplication", inv_no_duplication),
    Invariant("census_total_conserved", inv_census_total),
    Invariant("war_pile_empty_between_steps", inv_war_pile),
    Invariant("legal_phase_transitions", inv_phase),
    Invariant("finished_implies_winner", inv_finished_winner),
    Invariant("finished_is_terminal", inv_finished_terminal),
    Invariant("refused_actions_inert", inv_refusal_inert),
    Invariant("no_soft_lock", inv_softlock),
]


def main() -> int:
    config = UgtConfig(CONFIG_PATH)
    action_names = {int(k): v["name"] for k, v in config.data["action_space"]["actions"].items()}
    checks: list[tuple[str, bool, str]] = []

    def ck(name: str, ok: bool, detail: str = ""):
        checks.append((name, ok, detail))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))

    print(f"Round 3 — full-game exploit-hunter gate, {EPISODES} episodes, base seed {BASE_SEED}\n")

    adapter = SeededTarotAdapter(config, BASE_SEED)
    try:
        adapter.connect()

        print("  -- hunt --")
        hunter = ExploitHunter(adapter, INVARIANTS, list(action_names.keys()),
                               action_names=action_names,
                               policy=tarot_policy, seed=POLICY_SEED)
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

        finished_eps, capped_eps = [], []
        for i, st in enumerate(adapter.stats[:EPISODES]):
            (finished_eps if st["finished"] else capped_eps).append(i)
            print(f"    episode {i}: seed {st['seed']}, {st['steps']} steps, "
                  f"{st['max_round']} rounds, final={st['final']}")
        ck(f"at least 2 of {EPISODES} episodes played a full game to 'finished'",
           len(finished_eps) >= 2, f"finished={finished_eps} capped={capped_eps}")
        ck("episodes that hit the step cap were still making progress",
           all(adapter.stats[i]["max_round"] >= 50 for i in capped_eps),
           "none capped" if not capped_eps else
           f"capped at rounds { {i: adapter.stats[i]['max_round'] for i in capped_eps} }")

        missing = [n for n in action_names.values() if n not in report.action_counts]
        ck("every hook action attempted at least once", not missing,
           f"coverage: { {k: report.action_counts[k] for k in sorted(report.action_counts)} }"
           if not missing else f"never attempted: {missing}")
        ck("unmapped action id probed and refused without side effects",
           report.action_counts.get(str(UNMAPPED_ID), 0) > 0,
           f"{report.action_counts.get(str(UNMAPPED_ID), 0)} probes of id {UNMAPPED_ID} "
           f"(inertness enforced by the refused_actions_inert invariant)")

        # ── determinism: replay episode 0 and require the same trajectory ────
        print("\n  -- determinism replay (episode 0) --")
        replay_adapter = SeededTarotAdapter(config, BASE_SEED)
        replay_adapter.page = adapter.page          # reuse the live browser page
        replay_adapter.browser = adapter.browser
        replay_adapter.playwright = adapter.playwright
        replay_hunter = ExploitHunter(replay_adapter, INVARIANTS, list(action_names.keys()),
                                      action_names=action_names,
                                      policy=tarot_policy, seed=POLICY_SEED)
        replay_report = replay_hunter.run(episodes=1, steps_per_episode=STEPS_PER_EPISODE,
                                          log=lambda m: print(f"    {m}"))
        first, second = adapter.stats[0], replay_adapter.stats[0]
        traj_ok, traj_detail = trajectories_match(first["traj"], second["traj"])
        ck("same-seed replay reproduces episode 0 step for step (TW-R3 end to end)",
           traj_ok and not replay_report.findings,
           traj_detail if not replay_report.findings
           else f"{traj_detail}; replay produced {len(replay_report.findings)} finding(s)")

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
        print(f"ROUND 3 MET — {passed}/{total} checks. Whole games run clean under the "
              f"exploit-hunter: every invariant held on every step, all actions (and the "
              f"unmapped-id probe) exercised, and a same-seed episode replays step for step. "
              f"Tarot-war trial ladder complete.")
        return 0
    print(f"ROUND 3 NOT MET — {passed}/{total} checks passed. Findings above are the work list.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
