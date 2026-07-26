#!/usr/bin/env python3
"""Tier 3 — LLM playtest runner for Sokoban Mini.

Why this exists rather than a bare `ugt playtest --config ...`:

  * **The CLI cannot drive this game at all.** `engine.type: custom` means
    `env.py` has no adapter to dispatch, and `playtest_game()` raises saying so.
    The LLM loop itself is shared — this file builds `GodotTcpAdapter` and hands
    it to `playtest_game_with_adapter()`, which runs the identical loop.
  * The adapter owns the bridge's lifecycle, so — like every other rung here —
    nothing needs starting by hand and no stale Godot on a known port can be
    mistaken for the build under test.
  * The CLI cannot pass an invariant suite. The same predicates R1/R2/R3 assert
    run after every action the pilot takes, so a defect the pilot does not
    happen to notice is still caught.
  * The `LESSONS.md` §B pre-flight has to run somewhere, fail-closed, BEFORE any
    model is contacted.

Staging (§B P12) — local proves the CHANNEL, paid measures the GAME:

    # stage 1  local, free — does the pilot see the board and process the loop?
    python3 examples/sokoban/integration/playtest_sokoban.py --provider ollama
    # stage 2  paid — the only stage allowed to produce a quotable figure
    python3 examples/sokoban/integration/playtest_sokoban.py --provider anthropic \
        --model claude-haiku-4-5-20251001 --max-actions 150

**What this tier measures here is COMPETENCE, never a rate.** The game has no
randomness at all — three fixed levels in a fixed order — so every episode is a
replay and the honest sample size is 1 however many are run
(`playtest.seeding: deterministic`, proven against the live game before the run
starts). The scoreline is: how many levels were solved, and how many moves it
took against the committed 73-move optimum in `levels/solutions.json`.
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
for _p in (HERE, REPO):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from godot_tcp_adapter import GodotTcpAdapter  # noqa: E402
from invariants import SUITE  # noqa: E402

from ugt.core.playtester import _build_prompt, playtest_game_with_adapter  # noqa: E402
from ugt.utils.config_parser import UgtConfig  # noqa: E402

GUIDE = os.path.join(HERE, "strategy-guide.md")
CONFIG = os.path.join(HERE, "ugt.config.yaml")
SOLUTIONS = os.path.join(HERE, "..", "game", "levels", "solutions.json")

UP, DOWN, LEFT, RIGHT, RELOAD = 0, 1, 2, 3, 4


def _pt(config) -> dict:
    return config.data.get("playtest") or {}


def _committed_solutions() -> dict:
    """The game side's own artifact — never a copy kept here, or the two drift."""
    return json.load(open(SOLUTIONS))


# ── §B pre-flight ────────────────────────────────────────────────────────────

def assert_guide_fits(config: UgtConfig, guide: str) -> None:
    """§B P3 — truncation is silent starvation.

    `_fit()` cuts the guide at `playtest.guide_char_budget` from the TAIL, and
    the tail of this guide is everything that creates the skill: push geometry,
    corner deadlocks, when to reload. An over-budget guide leaves a pilot that
    has read the legend and none of the reasoning, and the run still reports
    PLAYTEST MET. Measured here so it fails before anything is spent.
    """
    budget = int(_pt(config).get("guide_char_budget", 2000))
    if len(guide) > budget:
        raise SystemExit(
            f"P3 VIOLATION — strategy-guide.md is {len(guide)} chars but "
            f"playtest.guide_char_budget is {budget}. The last "
            f"{len(guide) - budget} chars would be silently cut from the prompt, "
            f"and the cut lands in the 'how to play' half.\n"
            f"    Raise the budget in ugt.config.yaml, or shorten the guide."
        )
    print(f"[P3] guide {len(guide)} chars <= budget {budget} — no truncation.")


def assert_repeat_guard_allows_real_play(config: UgtConfig) -> None:
    """§B P11 — a guard rail is part of the game as far as the pilot is concerned.

    UGT's repeat guard counts consecutive IDENTICAL proposals whether or not they
    changed the state, and at its default of 3 it hard-blocks the third and
    substitutes `wait`. Pushing a crate five cells along a row IS five
    consecutive `left`s. So on the default config the pilot is physically
    prevented from playing the game's own committed solution, and the substituted
    `wait` burns budget without touching the game.

    The bound is DERIVED from `levels/solutions.json` rather than written down
    here, so authoring a level with a longer push run re-checks this by itself.
    """
    longest = 0
    where = ""
    for level, seq in _committed_solutions().items():
        for action, group in itertools.groupby(seq):
            run = len(list(group))
            if run > longest:
                longest, where = run, f"{level} ({run}x action {action})"
    threshold = int(_pt(config).get("repeat_block_threshold", 3))
    if threshold <= longest:
        raise SystemExit(
            f"P11 VIOLATION — playtest.repeat_block_threshold is {threshold}, but the "
            f"committed optimal solution contains a run of {longest} identical moves: "
            f"{where}. The guard would hard-block the pilot mid-push and force `wait`, "
            f"so the shipped solution is unplayable and the measurement is of a "
            f"different game.\n    Raise repeat_block_threshold above {longest}."
        )
    print(f"[P11] repeat_block_threshold {threshold} > longest committed push run "
          f"{longest} — {where} is playable.")


def assert_screen_channel_is_live(config: UgtConfig, adapter) -> str:
    """§B P2 — the adapter must pass through what the game shows.

    This game shows exactly one thing: the board. `main.tscn` is ColorRects with
    no Label, no font and no message line, so there is no prose channel to check
    — the board IS the player-facing text, and if it does not arrive the pilot is
    playing blind with a plausible-looking state dump.

    Both directions are checked, because "a board arrived" is not enough: a
    channel that returned the OPENING board forever would pass that and starve
    the pilot from move two onward. So the board must also CHANGE when the game
    says something changed.
    """
    budget = int(_pt(config).get("terminal_char_budget", 600))
    before_state = adapter.reset()
    opening = adapter.get_terminal_text(budget)
    if not opening.strip():
        raise SystemExit(
            "P2 VIOLATION — the screen channel is empty at level 1 start. The pilot "
            "would choose its first move with no board at all."
        )
    if "@" not in opening and "+" not in opening:
        raise SystemExit(
            f"P2 VIOLATION — the board carries no player glyph, so the pilot cannot "
            f"see where it is standing. Got:\n{opening}"
        )
    if "$" not in opening and "*" not in opening:
        raise SystemExit(f"P2 VIOLATION — the board carries no crate. Got:\n{opening}")

    after_state, _t, _tr, _i = adapter.step(LEFT)  # level 1's first committed move
    after = adapter.get_terminal_text(budget)
    if after == opening:
        raise SystemExit(
            "P2 VIOLATION — the board did not change after a move the game ACCEPTED "
            f"(player {before_state['player_x']},{before_state['player_y']} -> "
            f"{after_state['player_x']},{after_state['player_y']}). The channel is "
            "serving a stale screen, which is worse than an empty one: it looks right."
        )
    rows = len(after.splitlines())
    print(f"[P2] screen channel live: {rows} rows, {len(after)} chars, and it moves "
          f"when the game does.")
    return after


def assert_prompt_shows_a_player_view(config: UgtConfig, guide: str, adapter,
                                      screen: str) -> None:
    """§B P5 — the prompt must not leak what the real client hides, and must not
    hide what it shows.

    Checked against a REAL rendered prompt rather than by reading the config,
    because redaction is easy to configure and easy to configure for the wrong
    path. There is no HUD in this game, so `moves_taken` is a score the game
    keeps and shows to nobody, and it is also the number this tier scores
    against — a pilot watching its own metric is playing a different game.
    `grid` is redacted from the state block only because the SAME board is
    already rendered, aligned, in the Terminal panel.
    """
    state = adapter.reset()
    for a in (LEFT, UP):
        state, _t, _tr, _i = adapter.step(a)
    prompt = _build_prompt(config, guide, state, adapter.get_terminal_text(600), [])

    for leaked in ("moves_taken", '"grid"'):
        if leaked in prompt:
            raise SystemExit(
                f"P5 VIOLATION — {leaked} appears in the rendered prompt despite "
                f"playtest.redact_state_fields. Redaction is not doing what the "
                f"config claims."
            )
    board_rows = [r for r in screen.splitlines() if r.strip()]
    if not board_rows or board_rows[0] not in prompt:
        raise SystemExit(
            "P5/P2 VIOLATION — the board is redacted from the state block AND missing "
            "from the prompt's Terminal panel, so the pilot has no view of the game "
            "at all. This is the one combination that must never ship."
        )
    print(f"[P5] prompt is a player's view: {len(prompt)} chars, board present, "
          f"no move counter, no raw grid field.")


# ── Competence ───────────────────────────────────────────────────────────────

def report_competence(report_path: str) -> None:
    """Say what the run is worth, in the only currency this game has.

    No rate, no confidence interval, and that is not modesty: with no RNG
    anywhere, N episodes are N replays of one puzzle set, so a percentage over
    them has a denominator of N and a sample size of 1 (§B P9/P13).
    """
    if not os.path.exists(report_path):
        print(f"[!] no report at {report_path} — nothing to score.")
        return
    report = json.load(open(report_path))
    optimum = sum(len(v) for v in _committed_solutions().values())

    print("\n" + "=" * 70)
    print("COMPETENCE — solved, and moves against the committed optimum")
    episodes = report.get("episodes") or []
    if not episodes:
        print("  no completed episodes recorded (the run hit the action budget first)")
    for ep in episodes:
        final = ep.get("final_state") or {}
        print(f"  episode {ep.get('episode')}: end={ep.get('end_reason')} "
              f"level_index={final.get('level_index')} "
              f"moves={final.get('moves_taken')} "
              f"all_levels_solved={final.get('all_levels_solved')}")
    summary = report.get("summary") or {}
    final = (episodes[-1].get("final_state") if episodes else {}) or {}
    moves = final.get("moves_taken")
    print(f"\n  optimum for all three levels: {optimum} moves")
    if moves is not None:
        print(f"  pilot's move count at the end : {moves}"
              + (f"  ({moves / optimum:.2f}x optimum)" if optimum and moves else ""))
    print(f"  invariant violations: {summary.get('invariant_violations', 'n/a')}")
    print(f"  seeding: {summary.get('seeding_mode', 'n/a')} — "
          f"{summary.get('sample_note', 'sample size is 1 regardless of episode count')}")
    print("=" * 70)


# ── Entry point ──────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--provider", default="ollama", choices=["ollama", "anthropic"],
                    help="local (free, proves the channel) or paid (produces the number)")
    ap.add_argument("--model", default=None,
                    help="default: gemma4:26b for ollama, the playtester's default for anthropic")
    ap.add_argument("--max-actions", type=int, default=30, dest="max_actions")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--output", default=None)
    args = ap.parse_args()

    if args.provider == "ollama" and args.max_actions > 100:
        raise SystemExit(
            f"--max-actions {args.max_actions} on a local model: LESSONS.md §B P12 caps "
            f"stage 1 at ~100. Past ~200 local calls the decisions degrade below Haiku's, "
            f"so a longer run buys worse play, not more evidence. Use --provider anthropic."
        )

    guide = open(GUIDE).read()
    config = UgtConfig(CONFIG)

    # Cheap, model-free checks first — no bridge, no spend.
    assert_guide_fits(config, guide)
    assert_repeat_guard_allows_real_play(config)

    # Then the ones that need the live game. Its own bridge, reaped before the
    # run gets a fresh one — never shared, never assumed already up.
    probe = GodotTcpAdapter(config)
    probe.connect()
    try:
        screen = assert_screen_channel_is_live(config, probe)
        assert_prompt_shows_a_player_view(config, guide, probe, screen)
    finally:
        probe.close()

    output = args.output or os.path.join(HERE, "results", "playtest-report.json")
    os.makedirs(os.path.dirname(output), exist_ok=True)

    playtest_game_with_adapter(
        GodotTcpAdapter(config),
        provider=args.provider,
        strategy_guide=guide,
        max_actions=args.max_actions,
        output_path=output,
        model=args.model,
        runs=args.runs,
        # The identical predicates R1/R2 and R3 assert — one definition, three
        # tiers. A pilot that never notices a bug does not make the bug absent.
        invariants=lambda _adapter: SUITE.to_hunter_invariants(),
        # 5 declared ids, named in the config; NOT legal_action mode, which would
        # need the adapter to compute which moves are legal — i.e. to know the
        # push rules, which is exactly the game logic an adapter must never hold.
        action_mode="action_id",
        config=config,
    )

    if args.runs == 1:
        report_competence(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
