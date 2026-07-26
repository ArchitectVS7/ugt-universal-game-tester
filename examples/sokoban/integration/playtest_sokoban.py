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
starts). The scoreline is `levels_solved: N/3` and `crates_moved: N`, both
derived from the action log. The moves-against-the-committed-optimum ratio is
**withheld unless every level was solved**: its denominator is the cost of
FINISHING, so on a partial run it is not a worse score, it is not a score.

Two model-free entry points, so scoring is re-runnable without a bridge:

    python3 examples/sokoban/integration/playtest_sokoban.py --score results/<r>.json
    python3 examples/sokoban/integration/playtest_sokoban.py --prove-scoring
"""
from __future__ import annotations

import argparse
import ast
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
#
# Everything below reads a report and prints. It touches no game, no model and
# no network, so it is re-runnable for free against any report on disk
# (`--score`) and self-provable against synthetic ones (`--prove-scoring`).

CRATE_GLYPHS = "$*"   # PRD legend: `$` box, `*` box-on-target
WALL_GLYPH = "#"

_ARROW = " → "         # exactly how `_compute_delta` joins a non-numeric before/after


def _cells(rows, glyphs: str) -> frozenset:
    """Every `(y, x)` in a rendered board whose glyph is one of `glyphs`."""
    return frozenset((y, x)
                     for y, row in enumerate(rows)
                     for x, char in enumerate(row)
                     if char in glyphs)


def _crate_cells(rows) -> frozenset:
    """Where the crates are. A crate is `$` or `*` — a crate standing on a
    target is still a crate, so counting only `$` would report a push ONTO a
    target as a crate vanishing."""
    return _cells(rows, CRATE_GLYPHS)


def _wall_cells(rows) -> frozenset:
    """The level's fingerprint. Walls never move, and the three shipped levels
    are 7x5 / 9x7 / 11x8 with different interior walls, so an unequal wall set
    between the two halves of one delta means the board was REPLACED (the lazy
    level advance) rather than played."""
    return _cells(rows, WALL_GLYPH)


def _grid_delta(entry: dict):
    """`(before_rows, after_rows)` for a log entry, or `None` if it has no grid
    delta at all.

    `_compute_delta` writes a changed non-numeric field as `f"{before!r} → {after!r}"`,
    so ONE entry carries both boards and nothing has to be reconstructed.

    Fail-closed on an unparseable value: silently returning `None` there would
    report `crates_moved: 0` for the wrong reason, which is the same
    flattering-by-accident number this whole function exists to prevent.
    """
    raw = (entry.get("state_delta") or {}).get("grid")
    if raw is None:
        return None
    halves = str(raw).split(_ARROW, 1)
    if len(halves) == 2:
        try:
            before, after = (ast.literal_eval(h) for h in halves)
        except (ValueError, SyntaxError):
            before = after = None
        if (isinstance(before, list) and isinstance(after, list)
                and all(isinstance(r, str) for r in before + after)):
            return before, after
    raise SystemExit(
        f"UNPARSEABLE grid delta at step {entry.get('step')!r}: {raw!r}\n"
        f"    Expected '<rows> {_ARROW.strip()} <rows>' as written by "
        f"ugt.core.playtester._compute_delta. Refusing to score a log this "
        f"function cannot read — a 0 here would look like 'the pilot moved "
        f"nothing' rather than 'the scorer is broken'."
    )


def _signed(value, what: str, step) -> int:
    """`_compute_delta` renders a numeric change as a signed diff (`'+1'`),
    and a bool change too — `bool` is an `int`, so `False -> True` is `'+1'`,
    never `'False → True'`."""
    try:
        return int(str(value))
    except ValueError:
        raise SystemExit(
            f"UNPARSEABLE {what} delta at step {step!r}: {value!r} — expected a "
            f"signed integer diff. Refusing to guess what the run achieved."
        )


def count_crate_moves(report: dict) -> dict:
    """How many steps actually moved a crate, read off the rendered boards.

    Grid-derived on purpose: `boxes_on_target` only changes when a push CROSSES
    a target, so a legitimate push along open floor is invisible to it. The
    crate-cell set changes on every push regardless.

    Two kinds of grid change are not pushes and are excluded — and counted, so
    the exclusions are visible in the output instead of quietly shrinking the
    numerator:

      * a **level advance** (`board.gd` advances a solved level at the start of
        the NEXT move, so that move's delta is 'solved level N -> opening board
        of level N+1' — a wholesale replacement, detected by the wall set);
      * a **reload** (action 4 restores the level, so crate cells revert; a
        rewind is not a push).
    """
    counts = {"moved": 0, "grid_changes": 0, "level_advances": 0, "reloads": 0}
    for entry in report.get("action_log") or []:
        if entry.get("action_type") == "episode_reset":
            continue                      # marker entry, empty delta by construction
        pair = _grid_delta(entry)
        if pair is None:
            continue
        before, after = pair
        counts["grid_changes"] += 1
        if _wall_cells(before) != _wall_cells(after):
            counts["level_advances"] += 1
            continue
        if entry.get("action") == "reload":
            counts["reloads"] += 1
            continue
        if _crate_cells(before) != _crate_cells(after):
            counts["moved"] += 1
    return counts


def count_levels_solved(report: dict, total: int) -> int:
    """The high-water mark of levels solved, from the log and the final states.

    The log is the primary source because of the lazy advance: the solving move
    itself is where `level_solved` flips true, and the level counter only moves
    on the move AFTER it. Recorded final states are folded in as well, since a
    run that ends exactly on a solve records the outcome there.
    """
    solved = 0
    # A run starts on level 1, and a reset returns to level 1 — one fact, used
    # twice. It is not read from `baseline_state`: that would be a branch no
    # fixture and no real report could ever take the other way, i.e. decoration.
    level = 0
    for entry in report.get("action_log") or []:
        if entry.get("action_type") == "episode_reset":
            level = 0
            continue
        delta = entry.get("state_delta") or {}
        if "level_index" in delta:
            level += _signed(delta["level_index"], "level_index", entry.get("step"))
        if _signed(delta.get("level_solved", 0), "level_solved", entry.get("step")) > 0:
            solved = max(solved, level + 1)
    finals = [report.get("final_state") or {}]
    finals += [(ep.get("final_state") or {}) for ep in (report.get("episodes") or [])]
    for final in finals:
        if final.get("all_levels_solved"):
            solved = max(solved, total)
        elif final.get("level_solved"):
            solved = max(solved, int(final.get("level_index") or 0) + 1)
    return min(solved, total)


def competence_lines(report: dict) -> list:
    """Build the competence block. Pure — returns lines, prints nothing."""
    solutions = _committed_solutions()
    total = len(solutions)
    optimum = sum(len(v) for v in solutions.values())

    crates = count_crate_moves(report)
    solved = count_levels_solved(report, total)

    out = ["=" * 70, "COMPETENCE — what this run is worth"]
    out.append(f"  levels_solved: {solved}/{total}")
    out.append(f"  crates_moved:  {crates['moved']}     "
               f"({crates['grid_changes']} grid-changing steps; "
               f"{crates['level_advances']} excluded as level advances, "
               f"{crates['reloads']} as reloads)")
    out.append("")

    episodes = report.get("episodes") or []
    if not episodes:
        out.append("  no episodes recorded at all")
    for ep in episodes:
        final = ep.get("final_state") or {}
        out.append(f"  episode {ep.get('episode')}: end={ep.get('end_reason')} "
                   f"level_index={final.get('level_index')} "
                   f"moves={final.get('moves_taken')} "
                   f"all_levels_solved={final.get('all_levels_solved')}")

    # The move count and the "did it finish" flag are read off the SAME episode.
    # Pairing one episode's moves with another's win would manufacture a ratio.
    final = (episodes[-1].get("final_state") if episodes else {}) or {}
    moves = final.get("moves_taken")
    finished = bool(final.get("all_levels_solved"))

    out.append("")
    out.append(f"  optimum for all {total} levels: {optimum} moves")
    if moves is not None:
        out.append(f"  pilot's move count at the end : {moves}")
    if finished and moves and optimum:
        out.append(f"  moves/optimum ratio: {moves / optimum:.2f}x  "
                   f"({moves} moves against the committed {optimum})")
    else:
        why = ("no move count was recorded" if moves is None
               else "this run never finished")
        out.append("  moves/optimum ratio: NOT REPORTED — undefined for a partial run.")
        out.append(f"      all_levels_solved is {finished}; {solved} of {total} levels "
                   f"solved, {crates['moved']} crates moved.")
        out.append(f"      The denominator ({optimum} moves) is the cost of FINISHING and "
                   f"{why},")
        out.append("      so a ratio would read as 'a little off the pace' when the true")
        out.append("      reading is 'the game was never played'.")

    summary = report.get("summary") or {}
    out.append(f"  invariant violations: {summary.get('invariant_violations', 'n/a')}")
    out.append(f"  seeding: {summary.get('seeding_mode', 'n/a')} — "
               f"{summary.get('sample_note', 'sample size is 1 regardless of episode count')}")
    out.append("=" * 70)
    return out


def report_competence(report_path: str) -> None:
    """Say what the run is worth, in the only currency this game has.

    No rate, no confidence interval, and that is not modesty: with no RNG
    anywhere, N episodes are N replays of one puzzle set, so a percentage over
    them has a denominator of N and a sample size of 1 (§B P9/P13).
    """
    if not os.path.exists(report_path):
        print(f"[!] no report at {report_path} — nothing to score.")
        return
    print("\n" + "\n".join(competence_lines(json.load(open(report_path)))))


# ── Proving the scorer can fail ───────────────────────────────────────────────
#
# `results/` is gitignored, so the real reports do not exist in a clone and
# cannot be the permanent proof. These fixtures are built in memory from
# hand-written boards in the PRD's legend — no game, no model, no file on disk —
# and they carry both the positive and the negative control for every rule in
# the scorer, including the one this task exists to install: a partial run gets
# NO ratio.

L1 = ["#######", "#   . #", "# $   #", "#  @  #", "#######"]
L2 = ["#########", "#   #   #", "# $ # . #", "#  @    #", "# $   . #",
      "#   #   #", "#########"]
L3 = ["###########", "#    #    #", "# $  #  . #", "#    #    #", "#  @      #",
      "# $$   .. #", "#    #    #", "###########"]


def _delta_grid(before, after) -> str:
    """The exact string `_compute_delta` would have written for a grid change."""
    return f"{before!r}{_ARROW}{after!r}"


def _step(n: int, action: str, before, after, **scalars) -> dict:
    delta = {"moves_taken": "+1", **scalars}
    if before is not None:
        delta["grid"] = _delta_grid(before, after)
    return {"step": n, "action_type": "action_id", "action": action,
            "state_delta": delta}


def _report(log, moves, *, all_solved=False, level_index=0, level_solved=False,
            grid=None) -> dict:
    final = {"all_levels_solved": all_solved, "level_index": level_index,
             "level_solved": level_solved, "moves_taken": moves,
             "boxes_on_target": 0, "grid": grid or L1}
    return {"baseline_state": {"level_index": 0}, "final_state": final,
            "episodes": [{"episode": 1, "end_reason":
                          "terminated" if all_solved else "budget_exhausted",
                          "actions": len(log), "final_state": final}],
            "action_log": log,
            "summary": {"invariant_violations": 0, "seeding_mode": "deterministic",
                        "sample_note": "synthetic fixture"}}


def _fixture_walk(steps: int = 100) -> dict:
    """A synthetic replica of the real stage-1 report's shape: every step moves
    the player, no step moves a crate, nothing is ever solved."""
    a = ["#######", "#   . #", "# $   #", "#  @  #", "#######"]
    b = ["#######", "#   . #", "# $@  #", "#     #", "#######"]
    log = [_step(i + 1, "up" if i % 2 == 0 else "down",
                 a if i % 2 == 0 else b, b if i % 2 == 0 else a,
                 **{"player_y": "-1" if i % 2 == 0 else "+1"})
           for i in range(steps)]
    return _report(log, steps)


def _fixture_push_off_target() -> dict:
    """One push along open floor. `boxes_on_target` is 0 before AND after and is
    absent from the delta — so this counts only if the counter reads the grid."""
    before = ["#######", "#   . #", "# $@  #", "#     #", "#######"]
    after = ["#######", "#   . #", "#$@   #", "#     #", "#######"]
    return _report([_step(1, "left", before, after, player_x="-1")], 1)


def _fixture_push_onto_target() -> dict:
    """The ordinary case: `$` becomes `*`. The crate is still a crate."""
    before = ["#######", "#   . #", "#   $ #", "#   @ #", "#######"]
    after = ["#######", "#   * #", "#   @ #", "#     #", "#######"]
    return _report([_step(1, "up", before, after, player_y="-1",
                          boxes_on_target="+1")], 1)


def _fixture_excluded() -> dict:
    """A reload rewind and a level advance. Both change the crate cells and
    neither is a push."""
    mid = ["#######", "#   . #", "#$@   #", "#     #", "#######"]
    solved = ["#######", "#   * #", "#   @ #", "#     #", "#######"]
    return _report([
        _step(1, "reload", mid, L1, player_x="+1", player_y="+1"),
        _step(2, "left", solved, L2, player_x="-1", level_index="+1",
              level_solved="-1"),
    ], 2, level_index=1, grid=L2)


def _fixture_all_solved(moves: int = 94) -> dict:
    """Every level solved, through the lazy advance, exactly as the game emits
    it: `level_solved` flips on the solving move, `level_index` on the next."""
    solved1 = ["#######", "#   * #", "#   @ #", "#     #", "#######"]
    log = [
        _step(1, "up", L1, solved1, level_solved="+1", boxes_on_target="+1"),
        _step(2, "left", solved1, L2, level_index="+1", level_solved="-1"),
        _step(3, "up", None, None, level_solved="+1", boxes_on_target="+2"),
        _step(4, "left", L2, L3, level_index="+1", level_solved="-1"),
        _step(5, "up", None, None, level_solved="+1", all_levels_solved="+1"),
    ]
    return _report(log, moves, all_solved=True, level_index=2, level_solved=True,
                   grid=L3)


def _fixture_partial_progress() -> dict:
    """Levels 1 and 2 solved, then stuck on level 3 — the shape a real paid run
    is most likely to have.

    The final state says `level_solved: False` and `all_levels_solved: False`, so
    both solves exist ONLY in the log. That makes this the sole control over the
    log-parsing path: every other fixture that scores >0 does so via a final
    state, which would leave the lazy-advance handling untested.

    It has to reach level TWO for that to bite. A fixture that stopped after one
    solve is satisfied by a scorer that never tracks `level_index` at all — the
    answer 1 comes out right by accident when the counter is stuck at 0.
    """
    solved1 = ["#######", "#   * #", "#   @ #", "#     #", "#######"]
    walked2 = ["#########", "#   #   #", "# $ # . #", "#   @   #", "# $   . #",
               "#   #   #", "#########"]
    solved2 = ["#########", "#   #   #", "#   # * #", "#   @   #", "#     * #",
               "#   #   #", "#########"]
    walked3 = ["###########", "#    #    #", "# $  #  . #", "#    #    #",
               "#   @     #", "# $$   .. #", "#    #    #", "###########"]
    log = [
        _step(1, "up", L1, solved1, level_solved="+1", boxes_on_target="+1"),
        _step(2, "left", solved1, L2, level_index="+1", level_solved="-1",
              boxes_on_target="-1"),
        _step(3, "right", L2, walked2, player_x="+1"),
        _step(4, "up", walked2, solved2, level_solved="+1", boxes_on_target="+2"),
        _step(5, "left", solved2, L3, level_index="+1", level_solved="-1",
              boxes_on_target="-2"),
        _step(6, "right", L3, walked3, player_x="+1"),
    ]
    return _report(log, 6, level_index=2, grid=walked3)


def _fixture_reset_replays_level_one() -> dict:
    """Level 1 solved, advanced, then the episode RESET and level 1 solved again.

    The board silently returns to level 1 across a reset, and the marker entry
    carries an empty delta — so a scorer that does not rewind its own level
    counter reads the second solve as "level 2 solved" and reports 2 for a run
    that only ever finished level 1. Overcounting is the same class of error as
    the ratio this task removes, in the opposite direction.
    """
    solved1 = ["#######", "#   * #", "#   @ #", "#     #", "#######"]
    log = [
        _step(1, "up", L1, solved1, level_solved="+1", boxes_on_target="+1"),
        _step(2, "left", solved1, L2, level_index="+1", level_solved="-1",
              boxes_on_target="-1"),
        {"step": 2, "action_type": "episode_reset", "action": "EPISODE_RESET",
         "state_delta": {}},
        _step(3, "up", L1, solved1, level_solved="+1", boxes_on_target="+1"),
        _step(4, "left", solved1, L2, level_index="+1", level_solved="-1",
              boxes_on_target="-1"),
    ]
    rep = _report(log, 4, level_index=1)
    # Neither episode ends ON a solve, so the only evidence is the log.
    rep["episodes"] = [
        {"episode": 1, "end_reason": "reset", "actions": 2,
         "final_state": {"all_levels_solved": False, "level_index": 1,
                         "level_solved": False, "moves_taken": 2}},
        {"episode": 2, "end_reason": "budget_exhausted", "actions": 2,
         "final_state": {"all_levels_solved": False, "level_index": 1,
                         "level_solved": False, "moves_taken": 4}},
    ]
    return rep


def _fixture_malformed() -> dict:
    log = [{"step": 1, "action_type": "action_id", "action": "up",
            "state_delta": {"grid": "['#'] -> not a board"}}]
    return _report(log, 1)


_RATIO = "moves/optimum ratio:"


def prove_scoring() -> int:
    """Negative and positive controls for every rule in the scorer. Exit 1 if
    any case fails, so this is a gate and not a demo."""
    solutions = _committed_solutions()
    total = len(solutions)
    optimum = sum(len(v) for v in solutions.values())
    failures = 0

    def check(name, ok, detail):
        nonlocal failures
        print(f"  [{'ok' if ok else 'FAIL'}] {name}: {detail}")
        if not ok:
            failures += 1

    print("PROVE SCORING — the competence block's own controls")

    # A — the real defect's shape: a long walk that solved and pushed nothing.
    rep = _fixture_walk()
    lines = competence_lines(rep)
    text = "\n".join(lines)
    check("A walk: levels_solved 0", count_levels_solved(rep, total) == 0,
          f"{count_levels_solved(rep, total)}/{total}")
    check("A walk: crates_moved 0", count_crate_moves(rep)["moved"] == 0,
          f"{count_crate_moves(rep)}")
    check("A walk: no ratio printed",
          "x optimum" not in text and f"{_RATIO} 1." not in text
          and "1.37x" not in text,
          "no 'Nx' figure anywhere in the block")
    check("A walk: refusal is explicit", "NOT REPORTED" in text,
          "the block says why the ratio is undefined")
    check("A walk: primary lines first",
          lines[2].strip().startswith("levels_solved:")
          and lines[3].strip().startswith("crates_moved:"),
          f"{lines[2].strip()!r} / {lines[3].strip()[:24]!r}")

    # B — the accept criterion: grid-derived, not boxes_on_target-derived.
    rep = _fixture_push_off_target()
    check("B push off-target counts (grid, not boxes_on_target)",
          count_crate_moves(rep)["moved"] == 1, f"{count_crate_moves(rep)}")
    check("B fixture really hides boxes_on_target",
          "boxes_on_target" not in rep["action_log"][0]["state_delta"],
          "delta carries no boxes_on_target, so only the grid can prove the push")

    # C — the ordinary push, onto a target.
    rep = _fixture_push_onto_target()
    check("C push onto target counts", count_crate_moves(rep)["moved"] == 1,
          f"{count_crate_moves(rep)}")

    # D — the two exclusions, and they are reported rather than hidden.
    rep = _fixture_excluded()
    counts = count_crate_moves(rep)
    check("D reload + level advance are not pushes", counts["moved"] == 0, f"{counts}")
    check("D exclusions are counted",
          counts["reloads"] == 1 and counts["level_advances"] == 1, f"{counts}")
    check("D exclusions are printed",
          "1 excluded as level advances, 1 as reloads" in "\n".join(
              competence_lines(rep)),
          "the breakdown shows what was discarded")

    # E — the positive control: a finished run DOES get the ratio.
    rep = _fixture_all_solved()
    text = "\n".join(competence_lines(rep))
    moves = rep["final_state"]["moves_taken"]
    check("E all solved: levels_solved 3", count_levels_solved(rep, total) == total,
          f"{count_levels_solved(rep, total)}/{total}")
    check("E all solved: ratio printed",
          f"{_RATIO} {moves / optimum:.2f}x" in text and "NOT REPORTED" not in text,
          f"expected {moves / optimum:.2f}x for {moves} moves against {optimum}")

    # G — the log-only path, and a partial run WITH real progress still gets no
    # ratio. Withholding must key on all_levels_solved, not on "achieved nothing".
    rep = _fixture_partial_progress()
    text = "\n".join(competence_lines(rep))
    check("G solves visible only in the log are counted, at the right level",
          count_levels_solved(rep, total) == 2,
          f"{count_levels_solved(rep, total)}/{total} from two level_solved '+1's "
          f"across a lazy advance, with final_state "
          f"all_levels_solved={rep['final_state']['all_levels_solved']}, "
          f"level_solved={rep['final_state']['level_solved']}")
    check("G advances across levels are not crate moves",
          count_crate_moves(rep)["moved"] == 2
          and count_crate_moves(rep)["level_advances"] == 2,
          f"{count_crate_moves(rep)}")
    check("G partial-but-progressing run still gets no ratio",
          "NOT REPORTED" in text and f"{_RATIO} 0." not in text, "2 of 3 solved")

    # H — a reset replays level 1; solving it twice is still one level solved.
    rep = _fixture_reset_replays_level_one()
    check("H reset rewinds the level counter (no overcount)",
          count_levels_solved(rep, total) == 1,
          f"{count_levels_solved(rep, total)}/{total} for a run that solved level 1 "
          f"twice across an episode reset")

    # I — a report with no action log at all. The ratio gate reads `final_state`
    # directly, so `levels_solved` must read it too or the block contradicts
    # itself: "0/3 levels solved" printed next to a ratio.
    rep = _report([], 94, all_solved=True, level_index=2, level_solved=True)
    text = "\n".join(competence_lines(rep))
    check("I logless finished report scores from final_state",
          count_levels_solved(rep, total) == total,
          f"{count_levels_solved(rep, total)}/{total} with an empty action_log")
    check("I logless finished report is self-consistent",
          f"levels_solved: {total}/{total}" in text and f"{_RATIO} 1." in text,
          "the ratio never prints beside a 0/3")
    rep = _report([], 20, level_index=1, level_solved=True)
    check("I logless part-finished report scores the level it solved",
          count_levels_solved(rep, total) == 2,
          f"{count_levels_solved(rep, total)}/{total} from level_index 1 + "
          f"level_solved True")
    # `all_levels_solved` is the authoritative finished signal — the same one the
    # ratio gate reads. It must win over the level counter, or a low level_index
    # could print "1/3 solved" directly above a ratio.
    rep = _report([], 94, all_solved=True, level_index=0, level_solved=False)
    check("I the finished flag outranks the level counter",
          count_levels_solved(rep, total) == total,
          f"{count_levels_solved(rep, total)}/{total} from all_levels_solved alone")
    # And the headline can never read "8/3": a wire or state defect that inflates
    # level_index must not inflate the score this tier reports.
    rep = _report([], 20, level_index=7, level_solved=True)
    check("I score is capped at the committed level count",
          count_levels_solved(rep, total) == total,
          f"{count_levels_solved(rep, total)}/{total} from a bogus level_index 7")

    # J — an unreadable log must stop the scorer, not score 0.
    try:
        count_crate_moves(_fixture_malformed())
        check("J malformed grid delta fails closed", False, "no SystemExit raised")
    except SystemExit as exc:
        check("J malformed grid delta fails closed", "UNPARSEABLE" in str(exc),
              "SystemExit naming the step and the raw value")

    print(f"\nPROVE SCORING — "
          f"{'MET' if not failures else f'NOT MET ({failures} failed)'}")
    return 1 if failures else 0


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
    ap.add_argument("--score", default=None, metavar="PATH",
                    help="re-score a report that already exists; no bridge, no model, "
                         "no spend")
    ap.add_argument("--prove-scoring", action="store_true", dest="prove_scoring",
                    help="run the competence block's own controls against synthetic "
                         "reports; no bridge, no model, no spend")
    args = ap.parse_args()

    # Model-free paths first, so scoring never needs Godot or a provider.
    if args.prove_scoring:
        return prove_scoring()
    if args.score:
        report_competence(args.score)
        return 0

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
