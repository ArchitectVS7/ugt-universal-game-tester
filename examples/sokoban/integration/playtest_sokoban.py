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
        --model claude-haiku-4-5-20251001

**The PAID action budget defaults to, and is floored at, twice the committed
reference solution** — derived from `levels/solutions.json`, not written down here,
so a re-authored level re-checks it. Below that floor `all_levels_solved` is
unreachable by construction, so the run is refused before anything is spent rather
than allowed to buy a partial result the core-interaction gate then declines to
score. Stage 1 is untouched: 30 actions by default, §B P12's ~100 ceiling.

**What this tier measures here is COMPETENCE, never a rate.** The game has no
randomness at all — three fixed levels in a fixed order — so every episode is a
replay and the honest sample size is 1 however many are run
(`playtest.seeding: deterministic`, proven against the live game before the run
starts). The scoreline is `levels_solved: N/3` and `crates_moved: N`, both
derived from the action log. The moves-against-the-committed-reference ratio is
**withheld unless every level was solved**: its denominator is the cost of
FINISHING, so on a partial run it is not a worse score, it is not a score.

**Scoring is GATED on the core interaction having happened at all.** A run in
which no crate ever moved and no crate ever reached a target is a proof about the
transport and no evidence at all about the game, so it reports
`CHANNEL PROVEN / GAME UNMEASURED` and exits non-zero instead of printing a
competence line. Exit codes: 0 scored, 1 unmeasured (or no report), 2 the log
contradicts itself and is refused.

Three model-free entry points, so scoring and prompt rendering are re-runnable
without a bridge:

    python3 examples/sokoban/integration/playtest_sokoban.py --score results/<r>.json
    python3 examples/sokoban/integration/playtest_sokoban.py --prove-scoring
    python3 examples/sokoban/integration/playtest_sokoban.py --prove-prompt
"""
from __future__ import annotations

import argparse
import ast
import itertools
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
for _p in (HERE, REPO):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from godot_tcp_adapter import GodotTcpAdapter  # noqa: E402
from invariants import SUITE  # noqa: E402

from ugt.core.playtester import (  # noqa: E402
    _build_prompt,
    _compute_delta,
    _prompt_hidden_paths,
    _redact_delta,
    _unexpected_delta_fields,
    playtest_game_with_adapter,
)
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


# ── Action budget ────────────────────────────────────────────────────────────
#
# A paid run that cannot reach `all_levels_solved` even by playing the committed
# reference perfectly is not a cheap measurement, it is a purchased refusal: the
# core-interaction gate and the withheld ratio both key on finishing, so the whole
# spend buys a CHANNEL PROVEN / GAME UNMEASURED banner. The floor below is what
# makes that unbuyable, and it is DERIVED from the game's own committed solutions
# so a re-authored level re-checks it by itself — the same discipline
# `assert_repeat_guard_allows_real_play` uses for the repeat guard.

# Why 2x and not 1x, since the task requires the multiple to be STATED: the
# reference is the cost of playing three known puzzles perfectly. A pilot that has
# never seen them pays for every exploratory step, every walk to line up behind a
# crate, and every `reload` (which costs an action AND rewinds the level). At 1x,
# finishing demands zero wasted moves; at anything below 1x, `all_levels_solved`
# is unreachable by construction, which is the defect this floor removes. 2x is
# the smallest floor that leaves a non-zero error allowance.
# Rejected: a `playtest.paid_budget_multiple` config knob. `playtest.*` holds
# per-game GAME facts (with a curated "DELIBERATELY UNSET" list); how much credit
# a run may spend is a harness policy and stays in the harness.
PAID_BUDGET_MULTIPLE = 2

# Stage 1 is priced for a different job and the two policies are deliberately
# disjoint (the paid floor of 146 is above this ceiling): stage 1 proves the
# CHANNEL and may not spend, stage 2 measures the GAME and must be able to finish
# it. Applying the floor to ollama would make stage 1 unrunnable; applying the
# ceiling to anthropic would make finishing impossible. §B P12.
STAGE1_DEFAULT_ACTIONS = 30
STAGE1_CEILING = 100


def reference_moves(solutions: dict = None) -> int:
    """Total moves in the committed reference solution for every level.

    `solutions=` exists so a control can prove this is COMPUTED rather than typed:
    pass a synthetic level set and the answer has to move with it.

    Fail-closed on an empty or zero-move set — a truncated `solutions.json` must
    not silently disable the floor and hand a paid run an unbounded default.
    """
    solutions = _committed_solutions() if solutions is None else solutions
    total = sum(len(seq) for seq in solutions.values())
    if total <= 0:
        raise SystemExit(
            f"levels/solutions.json carries no moves ({len(solutions)} level(s), "
            f"{total} moves), so the paid action budget cannot be derived from it. "
            f"Refusing to run: the floor exists precisely so a paid run cannot be "
            f"launched at a budget that makes all_levels_solved unreachable, and a "
            f"floor of 0 would be no floor at all."
        )
    return total


def paid_budget_floor(solutions: dict = None) -> int:
    """The smallest paid budget at which finishing is possible with slack."""
    return PAID_BUDGET_MULTIPLE * reference_moves(solutions)


def resolve_max_actions(provider: str, requested, solutions: dict = None) -> int:
    """The budget this run will actually use. An explicit `--max-actions` always
    wins; `None` means "no flag", and the default is provider-dependent."""
    if requested is not None:
        return int(requested)
    if provider == "anthropic":
        return paid_budget_floor(solutions)
    return STAGE1_DEFAULT_ACTIONS


def assert_stage1_ceiling(provider: str, max_actions: int) -> None:
    """§B P12 — a longer local run buys worse play, not more evidence."""
    if provider == "ollama" and max_actions > STAGE1_CEILING:
        raise SystemExit(
            f"--max-actions {max_actions} on a local model: LESSONS.md §B P12 caps "
            f"stage 1 at ~{STAGE1_CEILING}. Past ~200 local calls the decisions degrade "
            f"below Haiku's, so a longer run buys worse play, not more evidence. Use "
            f"--provider anthropic."
        )


def assert_budget_can_finish(provider: str, max_actions: int,
                             solutions: dict = None) -> None:
    """Refuse a PAID run whose budget cannot reach the win condition.

    Paid-only on purpose: stage 1 is free and is not trying to finish.
    """
    if provider != "anthropic":
        return
    reference = reference_moves(solutions)
    floor = paid_budget_floor(solutions)
    if max_actions < floor:
        raise SystemExit(
            f"--max-actions {max_actions} with --provider anthropic is below the budget "
            f"floor of {floor}. The committed {reference}-move reference — the sum of the "
            f"three sequences in levels/solutions.json — is what FINISHING costs when "
            f"played perfectly, so at {max_actions} actions all_levels_solved is "
            f"unreachable by construction. The run would spend credit to produce a "
            f"partial result the core-interaction gate then declines to score, i.e. a "
            f"purchased refusal.\n"
            f"    Drop --max-actions to take the derived default ({floor} = "
            f"{PAID_BUDGET_MULTIPLE}x the {reference}-move reference), or pass "
            f"--max-actions {floor} or more."
        )


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
            f"committed reference solution contains a run of {longest} identical moves: "
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


def _prompt_section(prompt: str, header: str) -> str:
    """One `## <header>` section of a rendered prompt, header line included.

    Assertions about a channel must be made against THAT channel: the board is in
    the Terminal panel, in the state block if it were not held back, and (since
    T-009) in the Recent Actions deltas. A whole-prompt substring check cannot
    tell those apart, so it proves nothing about where the pilot reads it.

    Fail-closed on a missing header rather than returning "" — an empty slice
    would make every `not in` assertion below trivially true.
    """
    marker = f"## {header}\n"
    start = prompt.find(marker)
    if start < 0:
        raise SystemExit(
            f"the rendered prompt has no '## {header}' section, so a check scoped to "
            f"it would assert against an empty string. Refusing a vacuous pass — "
            f"`ugt.core.playtester` has renamed or dropped the block."
        )
    end = prompt.find("\n## ", start + len(marker))
    return prompt[start:] if end < 0 else prompt[start:end]


def assert_prompt_shows_a_player_view(config: UgtConfig, guide: str, adapter,
                                      screen: str) -> None:
    """§B P5 — the prompt must not leak what the real client hides, and must not
    hide what it shows.

    Checked against a REAL rendered prompt rather than by reading the config,
    because holding a field back is easy to configure and easy to configure for
    the wrong path. Two fields are held back, by two different knobs and for
    opposite reasons:

      * `moves_taken` — FOG OF WAR (`playtest.redact_state_fields`). There is no
        HUD in this game, so it is a score the game keeps and shows to nobody, and
        it is the number this tier scores against. Gone from EVERY channel, which
        is why it is checked against the whole prompt.
      * `grid` — CONTEXT ECONOMY (`playtest.hide_from_state_block`). The same
        board is already rendered, aligned, in the Terminal panel, so it is
        dropped from the state block ONLY — and is legitimately present in the
        Recent Actions deltas, which is what makes a push distinguishable from a
        walk. Hence the state-block-scoped check here.

    This function renders with an EMPTY action log, so it says nothing about the
    history channel: that is `assert_history_shows_the_board`'s job.
    """
    state = adapter.reset()
    for a in (LEFT, UP):
        state, _t, _tr, _i = adapter.step(a)
    prompt = _build_prompt(config, guide, state, adapter.get_terminal_text(600), [])

    if "moves_taken" in prompt:
        raise SystemExit(
            "P5 VIOLATION — moves_taken appears in the rendered prompt despite "
            "playtest.redact_state_fields. This one is fog of war and must be gone "
            "from every channel the pilot reads, the history included."
        )
    state_block = _prompt_section(prompt, "Current State")
    if '"grid"' in state_block:
        raise SystemExit(
            "P5 VIOLATION — \"grid\" appears in the prompt's Current State block "
            "despite playtest.hide_from_state_block. The board would be printed "
            "twice, once JSON-quoted, spending context on a worse rendering."
        )
    board_rows = [r for r in screen.splitlines() if r.strip()]
    if not board_rows or board_rows[0] not in prompt:
        raise SystemExit(
            "P5/P2 VIOLATION — the board is held back from the state block AND "
            "missing from the prompt's Terminal panel, so the pilot has no view of "
            "the game at all. This is the one combination that must never ship."
        )
    print(f"[P5] prompt is a player's view: {len(prompt)} chars, board present, "
          f"no move counter, no raw grid field in the state block.")


def assert_history_shows_the_board(config: UgtConfig, guide: str, adapter) -> None:
    """§B P10 — the pilot's own memory must be able to tell a push from a walk.

    This game's one feedback signal is the board. A push to a non-target cell
    moves NO visible scalar — `boxes_on_target` only changes when a push crosses a
    target, and `moves_taken` is fog of war — so if the history carries no board,
    a crate-pushing move renders exactly like a plain walk
    (`Step 2: up → {'player_y': '-1'}`) and the pilot cannot learn from its own
    moves at all. That is what `grid` sitting in `redact_state_fields` did, since
    that knob strips the deltas too.

    Asserted against a REAL rendered prompt built from a REAL replay of the
    committed solution, using the framework's own `_compute_delta`, so the check
    exercises the rendering path the loop uses rather than a hand-built delta.

    The pushing step is FOUND, never assumed to be step 2: the first replayed step
    whose crate-cell set changes. A re-authored level re-finds it — the same
    discipline `assert_repeat_guard_allows_real_play` uses for the repeat guard.
    """
    names = {aid: (d.get("name") if isinstance(d, dict) else str(d))
             for aid, d in config.action_mappings.items()}
    window = int(_pt(config).get("history_window", 5))

    state = adapter.reset()
    action_log, push_step, walk_step = [], None, None
    for n, action in enumerate(_committed_solutions()["level_01"], start=1):
        before = state
        state, _t, _tr, _i = adapter.step(action)
        action_log.append({"step": n, "action_type": "action_id",
                           "action": names[action],
                           "state_delta": _compute_delta(before, state)})
        moved_a_crate = _crate_cells(before["grid"]) != _crate_cells(state["grid"])
        if moved_a_crate and push_step is None:
            push_step = action_log[-1]
        if not moved_a_crate and walk_step is None:
            walk_step = action_log[-1]
        if push_step is not None and walk_step is not None:
            break
    if push_step is None or walk_step is None:
        raise SystemExit(
            f"P10 CHECK IS VACUOUS — replaying level_01's committed solution "
            f"produced {'no crate-moving step' if push_step is None else ''}"
            f"{' and ' if push_step is None and walk_step is None else ''}"
            f"{'no step that moved only the player' if walk_step is None else ''}. "
            f"This check needs both to assert that they render DIFFERENTLY, so a "
            f"pass here would prove nothing. Re-derive it against the level as "
            f"authored now."
        )
    if len(action_log) > window:
        raise SystemExit(
            f"P10 CHECK IS OUT OF WINDOW — the contrast steps are {len(action_log)} "
            f"entries deep but playtest.history_window is {window}, so the prompt "
            f"below would not contain them and the assertions would be about the "
            f"wrong thing."
        )

    prompt = _build_prompt(config, guide, state, adapter.get_terminal_text(600),
                           action_log)
    history = _prompt_section(prompt, "Recent Actions")
    push_line = next(ln for ln in history.splitlines()
                     if ln.strip().startswith(f"Step {push_step['step']}:"))
    walk_line = next(ln for ln in history.splitlines()
                     if ln.strip().startswith(f"Step {walk_step['step']}:"))

    before_rows, after_rows = _grid_delta(push_step)
    # 1. the pushing step carries the whole after-board.
    missing = [r for r in after_rows if r not in push_line]
    if missing:
        raise SystemExit(
            f"P10 VIOLATION — the crate-pushing step's history line does not carry "
            f"the board it produced: {len(missing)} of {len(after_rows)} rows absent "
            f"({missing[0]!r} first). The pilot's memory of the game's one feedback "
            f"signal is incomplete.\n    Line: {push_line.strip()}"
        )
    # 2. position sensitivity — the crate is shown MOVED, not merely present. The
    #    row it now occupies must differ from the same row before, and that exact
    #    row string must not occur anywhere in the before-board (which would let a
    #    board with the crate one cell along satisfy check 1).
    crate_rows = sorted({y for y, _x in _crate_cells(after_rows)
                         - _crate_cells(before_rows)})
    if not crate_rows:
        raise SystemExit(
            "P10 CHECK IS VACUOUS — the step selected as the push gained no crate "
            "cell, so there is no moved crate to assert about."
        )
    for y in crate_rows:
        if after_rows[y] == before_rows[y]:
            raise SystemExit(
                f"P10 VIOLATION — row {y} holds the crate's new cell but renders "
                f"identically before and after ({after_rows[y]!r}), so the history "
                f"cannot show the crate as having moved."
            )
        if after_rows[y] in before_rows:
            raise SystemExit(
                f"P10 VIOLATION — the after-row {after_rows[y]!r} also occurs in the "
                f"before-board, so its presence in the history line is not evidence "
                f"the crate moved."
            )
    # 3. the defect sentence, asserted: a push and a walk are DISTINGUISHABLE.
    #    Every accepted move redraws the board (the `@` moves), so "a board
    #    appears" is not the claim and could never be — the claim is that the
    #    pilot can read a crate having moved off the pushing step's own pair and
    #    can read that it did NOT on the walked step's.
    walk_before, walk_after = _grid_delta(walk_step)
    if _crate_cells(walk_before) != _crate_cells(walk_after):
        raise SystemExit(
            f"P10 CHECK IS VACUOUS — the step selected as a plain walk moved a crate "
            f"after all, so the two lines are not a contrast.\n"
            f"    Line: {walk_line.strip()}"
        )
    for label, line, entry in (("push", push_line, push_step),
                               ("walk", walk_line, walk_step)):
        pair = _grid_delta(entry)
        if not all(r in line for r in pair[0] + pair[1]):
            raise SystemExit(
                f"P10 VIOLATION — the {label} step's history line does not carry both "
                f"boards, so a crate move cannot be read off it either way.\n"
                f"    Line: {line.strip()}"
            )
    # 4. and the board is the ONLY channel that says so, which is why stripping it
    #    made the two identical. No non-grid delta key on the pushing step names a
    #    crate at all: `boxes_on_target` moves only when a push CROSSES a target,
    #    and there are no crate coordinates on the wire.
    crate_terms = sorted(k for k in push_step["state_delta"]
                         if k != "grid" and ("box" in k.lower() or "crate" in k.lower()))
    if crate_terms:
        raise SystemExit(
            f"P10 CHECK IS NO LONGER THE CHECK — the pushing step's delta carries "
            f"{crate_terms}, so a crate move is visible without the board and the "
            f"premise of this assertion has changed. Re-derive it: the game's wire "
            f"has grown a scalar that tracks crates."
        )
    # 5. fog of war survives the split — the move counter is in every delta and
    #    must be in no rendered line.
    if "moves_taken" in prompt:
        raise SystemExit(
            "P5/P10 VIOLATION — moves_taken reached the prompt through the history. "
            "It is fog of war (`redact_state_fields`), so splitting the board out of "
            "that list must not have taken the move counter with it."
        )

    print(f"[P10] history distinguishes a push from a walk. Pushing step "
          f"{push_step['step']} ({push_step['action']}) renders as:\n"
          f"        {push_line.strip()}")
    # What the same step used to render as, printed so the difference is visible
    # rather than asserted about in prose. This is the old behaviour exactly:
    # `grid` in `redact_state_fields` stripped it from the deltas as well.
    print(f"[P10] the same step with the board stripped, i.e. before this fix:\n"
          f"        Step {push_step['step']}: {push_step['action']} → "
          f"{_redact_delta(push_step['state_delta'], ['grid', 'moves_taken'])}")
    print(f"[P10] the walked step {walk_step['step']} ({walk_step['action']}) "
          f"carries both boards too, and its crate cells are UNCHANGED — which is "
          f"the distinction:\n        {walk_line.strip()}")
    print(f"[P10] prompt {len(prompt)} chars with {len(action_log)} history "
          f"entries; Recent Actions block {len(history)} chars.")


# ── Competence ───────────────────────────────────────────────────────────────
#
# Everything below reads a report, prints, and decides an exit code. It touches no
# game, no model and no network, so the whole gate is re-runnable for free against
# any report on disk (`--score`) and self-provable against synthetic ones
# (`--prove-scoring`).

CRATE_GLYPHS = "$*"      # PRD legend: `$` box, `*` box-on-target
ON_TARGET_GLYPH = "*"    # a box STANDING ON a target — the game's whole objective
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


def count_target_arrivals(report: dict) -> dict:
    """Did a crate ever REACH a target, and does the log agree with itself?

    Read off the action log only, in two independent ways so they can be made to
    argue:

      * the scalar the game keeps (`boxes_on_target`), accumulated from the signed
        diffs `_compute_delta` writes;
      * the rendered board (`*` cells GAINED between the two halves of one delta).

    An ARRIVAL is a step where the count ROSE, not a high-water mark of the count
    itself, and the difference is load-bearing. Two things can raise
    `boxes_on_target` without the pilot achieving anything: a reload, which
    restores the level's own starting arrangement, and a level advance, which
    replaces the board wholesale. Neither is a crate arriving anywhere, so BOTH
    readings exclude those steps — the same two exclusions `count_crate_moves`
    applies, for the same reason. On the three shipped levels the exclusions are
    currently unobservable (none starts with a `*`, so a restore can only take the
    count DOWN or leave it), but authoring one level that ships a crate already on
    a target would otherwise hand every run a free arrival the moment the board was
    replaced, and a gate must not rest on a content fact a level author can change.

    `max_boxes_on_target` is reported alongside as evidence, and it is relative to
    the START of the run — the running value begins at 0 rather than at
    `baseline_state`'s, and an `episode_reset` rewinds it to 0 (the same fact
    `count_levels_solved` uses) while the high-water mark stands. Reading a
    baseline would add a branch no fixture and no real report could take the other
    way; and because it is a level's arrangement rather than the pilot's work, it
    is exactly what the gate must NOT be conditioned on.
    """
    out = {"max_boxes_on_target": 0,
           "scalar_arrival_steps": [], "grid_arrival_steps": [],
           "advances_excluded": 0, "reloads_excluded": 0}
    running = 0
    for entry in report.get("action_log") or []:
        step = entry.get("step")
        if entry.get("action_type") == "episode_reset":
            running = 0               # back to level 1; the high-water mark stands
            continue
        delta = entry.get("state_delta") or {}
        diff = (_signed(delta["boxes_on_target"], "boxes_on_target", step)
                if "boxes_on_target" in delta else 0)
        running += diff
        out["max_boxes_on_target"] = max(out["max_boxes_on_target"], running)

        pair = _grid_delta(entry)
        excluded = False
        if pair is not None and _wall_cells(pair[0]) != _wall_cells(pair[1]):
            out["advances_excluded"] += 1
            excluded = True
        elif entry.get("action") == "reload":
            out["reloads_excluded"] += 1
            excluded = True
        if excluded:
            continue                  # neither reading may claim an arrival here

        if diff > 0:
            out["scalar_arrival_steps"].append(step)
        if pair is not None and (_cells(pair[1], ON_TARGET_GLYPH)
                                 - _cells(pair[0], ON_TARGET_GLYPH)):
            out["grid_arrival_steps"].append(step)
    # Both lists are built in log order, so they are directly comparable without
    # sorting — and no sort key has to guess what a `step` field might contain.
    return out


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
    # The committed REFERENCE — and since the game grew
    # `tests/test_solution_optimality.gd`, each of the three sequences is also
    # known to be the SHORTEST possible for its level (BFS through the live
    # rules engine, in the game's own suite; `tests/test_shipped_levels.gd`
    # separately pins that each solves, is unpadded and does not win early).
    # The proof is game-side on purpose: minimality is a claim about authored
    # content, and a solver in this harness would be a second rules engine.
    # The LABEL below stays "reference" anyway — see case W in
    # `--prove-scoring` for why. One derivation for the whole file, so the
    # scoreline and the budget floor cannot drift, and a truncated
    # solutions.json fails closed instead of scoring against 0.
    reference = reference_moves(solutions)

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
    out.append(f"  reference for all {total} levels: {reference} moves")
    out.append("      (the committed levels/solutions.json sequences. Each is the")
    out.append("       SHORTEST possible for its level — proven by search in the")
    out.append("       game's own test suite, never by anything in this harness)")
    if moves is not None:
        out.append(f"  pilot's move count at the end : {moves}")
    if finished and moves and reference:
        out.append(f"  moves/reference ratio: {moves / reference:.2f}x  "
                   f"({moves} moves against the committed {reference})")
    else:
        why = ("no move count was recorded" if moves is None
               else "this run never finished")
        out.append("  moves/reference ratio: NOT REPORTED — undefined for a partial run.")
        out.append(f"      all_levels_solved is {finished}; {solved} of {total} levels "
                   f"solved, {crates['moved']} crates moved.")
        out.append(f"      The denominator ({reference} moves) is the cost of FINISHING and "
                   f"{why},")
        out.append("      so a ratio would read as 'a little off the pace' when the true")
        out.append("      reading is 'the game was never played'.")

    summary = report.get("summary") or {}
    out.append(f"  invariant violations: {summary.get('invariant_violations', 'n/a')}")
    out.append(f"  seeding: {summary.get('seeding_mode', 'n/a')} — "
               f"{summary.get('sample_note', 'sample size is 1 regardless of episode count')}")
    out.append("=" * 70)
    return out


def core_interaction_verdict(report: dict, report_path: str = None):
    """`(verdict, lines)` — may this run be scored at all?

    `verdict` is one of:

      * `"SCORE"`          — the core interaction happened; score it.
      * `"UNMEASURED"`     — the pilot walked around. The transport is proven and
                             the game was never played, so there is nothing to
                             score and a competence line would misrepresent that.
      * `"CONTRADICTION"`  — the two independent readings of "a crate reached a
                             target" disagree. Refused rather than resolved.

    Two conditions, ANDed, both read off the ACTION LOG rather than the summary
    block or `final_state` (a summary can say `all_levels_solved` while the log
    shows nothing ever moved; the log is the primary evidence and the one a wire
    defect shows up in):

      * `crates_moved > 0` — a crate moved at all, grid-derived, so a push along
        open floor counts;
      * at least one ARRIVAL — a step where `boxes_on_target` rose and the board
        gained a `*`, excluding the two steps that can raise the count without the
        pilot doing anything (see `count_target_arrivals`).

    Neither implies the other and neither alone is enough. A crate can be shoved
    around for a hundred moves without ever landing on a target (the second
    condition is what makes the gate about the OBJECTIVE), and `boxes_on_target`
    is blind to any push that does not cross a target (the first is what makes it
    about the MECHANIC). Requiring both is what the reasoning channel cannot fake.

    The contradiction branch comes first, because scoring across untrusted
    evidence reports a number derived from two different games. On honest wire
    data the two readings name the SAME steps: one push per step, and a crate
    landing on a target both increments the counter and turns `$` into `*` on the
    board. The comparison is like-for-like because the two exclusions are applied
    to both readings, not just to the board (`count_target_arrivals`). A
    disagreement is therefore the wire-only defect class the
    `grid_matches_scalar_state` invariant exists to catch — the counter and the
    render having drifted apart — and it is filed, not tuned away.
    """
    crates = count_crate_moves(report)
    arrivals = count_target_arrivals(report)
    solutions = _committed_solutions()
    total = len(solutions)
    solved = count_levels_solved(report, total)

    scalar_steps = arrivals["scalar_arrival_steps"]
    grid_steps = arrivals["grid_arrival_steps"]

    evidence = [
        f"  crates_moved: {crates['moved']}     "
        f"({crates['grid_changes']} grid-changing steps; "
        f"{crates['level_advances']} excluded as level advances, "
        f"{crates['reloads']} as reloads)",
        f"  max boxes_on_target over the log: {arrivals['max_boxes_on_target']}",
        f"  crate-on-target steps: scalar {scalar_steps} / board {grid_steps}     "
        f"({arrivals['advances_excluded']} steps excluded as level advances, "
        f"{arrivals['reloads_excluded']} as reloads)",
        f"  levels_solved: {solved}/{total}",
    ]
    if report_path:
        evidence.append(f"  report (written, unscored): {report_path}")

    if scalar_steps != grid_steps:
        return "CONTRADICTION", (
            ["=" * 70, "REFUSING TO SCORE — CONTRADICTORY LOG"]
            + [f"  boxes_on_target rose on steps : {scalar_steps}",
               f"  the board gained a `*` on step: {grid_steps}"]
            + evidence
            + ["", "  The counter and the render disagree about the game's own",
               "  objective, so one of them is describing a different game. This is",
               "  a wire defect to file against whoever owns the game (the",
               "  `grid_matches_scalar_state` invariant is the one that guards it),",
               "  not a scoring threshold to loosen.",
               "=" * 70])

    # Past the contradiction check the two readings agree, so either one IS the
    # arrival list. `scalar_steps` is named for the reader; `grid_steps` is the
    # same list.
    a_crate_moved = crates["moved"] > 0
    a_crate_reached_a_target = len(scalar_steps) > 0
    if a_crate_moved and a_crate_reached_a_target:
        return "SCORE", []

    return "UNMEASURED", (
        ["=" * 70, "CHANNEL PROVEN / GAME UNMEASURED",
         f"  a crate moved at all      : {'YES' if a_crate_moved else 'NO'}",
         f"  a crate reached a target  : "
         f"{'YES' if a_crate_reached_a_target else 'NO'}",
         ""]
        + evidence
        + ["",
           "  The pilot took its turns, the board came back, no invariant broke —",
           "  and the game's one interaction never happened. That is a result about",
           "  the TRANSPORT, which is proven, and no evidence whatever about the",
           "  puzzles, so no competence figure is printed: refusing to score is not",
           "  a claim that the pilot played badly, it is a refusal to publish a",
           "  number with nothing behind it.",
           "",
           "  The reasoning channel is not a substitute, and this tier has already",
           "  paid to learn it: on the recorded 100-action stage-1 run the pilot",
           "  said \"push\" on 96 of 100 steps and pushed 0 times. A §B P7 keyword",
           "  grep scores that a clean pass, while the one objective observable sat",
           "  unread in the report — which is why this is a machine check.",
           "=" * 70])


def score_lines(report: dict, report_path: str = None):
    """`(exit_code, lines)` for a loaded report. Pure — prints nothing.

    Say what the run is worth, in the only currency this game has: no rate, no
    confidence interval, and that is not modesty — with no RNG anywhere, N
    episodes are N replays of one puzzle set, so a percentage over them has a
    denominator of N and a sample size of 1 (§B P9/P13).

    And say nothing at all when the run has no worth to report. The competence
    block is REPLACED by the banner rather than printed beside it: a scoreline
    next to "the game was never played" is exactly the flattering-by-accident
    reading this gate exists to remove.
    """
    verdict, lines = core_interaction_verdict(report, report_path)
    if verdict == "SCORE":
        return 0, competence_lines(report)
    return (2 if verdict == "CONTRADICTION" else 1), lines


def report_competence(report_path: str) -> int:
    """Print the verdict for a report on disk and return its EXIT CODE.

    A gate, not a printout: 0 scored, 1 unmeasured or absent, 2 contradictory.
    A missing report is 1 too — "nothing to score" has never been a pass.
    """
    if not os.path.exists(report_path):
        print(f"[!] no report at {report_path} — nothing to score.")
        return 1
    code, lines = score_lines(json.load(open(report_path)), report_path)
    print("\n" + "\n".join(lines))
    return code


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
    it: `level_solved` flips on the solving move, `level_index` on the next.

    Every step that claims `boxes_on_target` rose carries the BOARD that rose with
    it, because the core-interaction gate refuses a log whose counter and render
    disagree — and an abridged fixture that raised the counter without drawing the
    `*` would be asserting the wire defect it is meant to be a clean control for.
    """
    solved1 = ["#######", "#   * #", "#   @ #", "#     #", "#######"]
    solved2 = ["#########", "#   #   #", "#   # * #", "#   @   #", "#     * #",
               "#   #   #", "#########"]
    log = [
        _step(1, "up", L1, solved1, level_solved="+1", boxes_on_target="+1"),
        _step(2, "left", solved1, L2, level_index="+1", level_solved="-1"),
        _step(3, "up", L2, solved2, level_solved="+1", boxes_on_target="+2"),
        _step(4, "left", solved2, L3, level_index="+1", level_solved="-1"),
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


def _fixture_preplaced_target_restored() -> dict:
    """A hypothetical level that SHIPS a crate already on a target, pushed off it
    and then reloaded.

    None of the three shipped levels starts with a `*`, so this cannot be recorded
    today — and that is the point: it is the control for the arrival exclusions,
    which are otherwise conditioned on a content fact any level author could
    change. On the reload, `boxes_on_target` rises by 1 AND the board gains its
    `*` back, both honestly, and no crate arrived anywhere: the level simply
    returned to how it was authored. The run also contains one real push, so
    `crates_moved` is 1 and only the arrival condition stands between this and a
    scored run.
    """
    start = ["#######", "#     #", "#  *  #", "#  @  #", "# $ . #", "#######"]
    pushed = ["#######", "#  $  #", "#  @  #", "#  .  #", "# $ . #", "#######"]
    return _report([
        _step(1, "up", start, pushed, player_y="-1", boxes_on_target="-1"),
        _step(2, "reload", pushed, start, player_y="+1", boxes_on_target="+1"),
    ], 2, grid=start)


def _fixture_scalar_without_grid() -> dict:
    """The counter says a crate reached a target; the board never shows a `*`.

    A wire defect, not a scoring edge case — and the direction that matters most,
    because `boxes_on_target` is the field a lazy gate would trust on its own.
    """
    before = ["#######", "#   . #", "# $@  #", "#     #", "#######"]
    after = ["#######", "#   . #", "#$@   #", "#     #", "#######"]
    return _report([_step(1, "left", before, after, player_x="-1",
                          boxes_on_target="+1")], 1)


def _fixture_grid_without_scalar() -> dict:
    """The board shows a crate landing on a target; the counter never moves.

    The reverse direction, so the check cannot be satisfied by only ever
    distrusting one of the two sources.
    """
    before = ["#######", "#   . #", "#   $ #", "#   @ #", "#######"]
    after = ["#######", "#   * #", "#   @ #", "#     #", "#######"]
    return _report([_step(1, "up", before, after, player_y="-1")], 1)


def _fixture_malformed() -> dict:
    log = [{"step": 1, "action_type": "action_id", "action": "up",
            "state_delta": {"grid": "['#'] -> not a board"}}]
    return _report(log, 1)


_RATIO = "moves/reference ratio:"


def prove_scoring() -> int:
    """Negative and positive controls for every rule in the scorer AND for the
    action-budget policy. Exit 1 if any case fails, so this is a gate and not a
    demo."""
    solutions = _committed_solutions()
    total = len(solutions)
    reference = reference_moves(solutions)
    failures = 0

    def check(name, ok, detail):
        nonlocal failures
        print(f"  [{'ok' if ok else 'FAIL'}] {name}: {detail}")
        if not ok:
            failures += 1

    print("PROVE SCORING — the competence block's, the gate's and the budget "
          "floor's own controls")

    # A — the real defect's shape: a long walk that solved and pushed nothing.
    rep = _fixture_walk()
    lines = competence_lines(rep)
    text = "\n".join(lines)
    check("A walk: levels_solved 0", count_levels_solved(rep, total) == 0,
          f"{count_levels_solved(rep, total)}/{total}")
    check("A walk: crates_moved 0", count_crate_moves(rep)["moved"] == 0,
          f"{count_crate_moves(rep)}")
    # The guard is on the SHAPE of a ratio, not on the word next to it: a
    # substring check like `"x optimum" not in text` stops guarding anything the
    # moment the label is renamed, which is silent and is exactly how the 1.37x
    # survived. `\d+\.\d+x` catches any multiple however it is labelled.
    check("A walk: no ratio printed",
          re.search(r"\d+\.\d+x", text) is None and f"{_RATIO} 1." not in text
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
          f"{_RATIO} {moves / reference:.2f}x" in text and "NOT REPORTED" not in text,
          f"expected {moves / reference:.2f}x for {moves} moves against {reference}")

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

    # ── The core-interaction gate ────────────────────────────────────────────
    # Below the threshold the run must refuse to score. Each case names the
    # condition it is the control for, so a mutation has an obvious victim.
    _BANNER = "CHANNEL PROVEN / GAME UNMEASURED"
    _COMP = "COMPETENCE — what this run is worth"

    # K — the real defect's shape: 100 legal moves, nothing touched.
    rep = _fixture_walk()
    verdict, lines = core_interaction_verdict(rep)
    text = "\n".join(lines)
    check("K walk trips the gate", verdict == "UNMEASURED", verdict)
    check("K walk prints the banner and no competence block",
          _BANNER in text and _COMP not in text,
          "the banner REPLACES the scoreline rather than sitting beside it")
    code, printed = score_lines(rep)
    check("K walk exits non-zero", code == 1, f"exit {code}")
    check("K refusal still carries the evidence",
          "crates_moved: 0" in text and "levels_solved: 0/3" in text
          and "max boxes_on_target over the log: 0" in text,
          "no figure is lost by declining to score")

    # L — one crate reaching one target is enough to be scored.
    rep = _fixture_push_onto_target()
    verdict, _ = core_interaction_verdict(rep)
    check("L one target-reaching step passes the gate", verdict == "SCORE",
          f"{verdict} for {count_target_arrivals(rep)}")

    # M — the two conditions are ANDed: a real push that reached nothing.
    rep = _fixture_push_off_target()
    verdict, _ = core_interaction_verdict(rep)
    check("M a push that reaches no target still trips the gate",
          verdict == "UNMEASURED" and count_crate_moves(rep)["moved"] == 1,
          f"{verdict} with crates_moved=1 — crates_moved alone cannot open the gate")

    # N — the exclusions carry into the gate: a reload and a level advance both
    # change the board and neither is the pilot playing.
    rep = _fixture_excluded()
    verdict, _ = core_interaction_verdict(rep)
    arrivals = count_target_arrivals(rep)
    check("N reload + level advance do not open the gate",
          verdict == "UNMEASURED" and not arrivals["grid_arrival_steps"],
          f"{verdict}; advances={arrivals['advances_excluded']} "
          f"reloads={arrivals['reloads_excluded']}")

    # N2 — and they are excluded from the ARRIVAL reading too, not just from
    # `crates_moved`: restoring a level that ships a crate on a target raises the
    # counter and redraws the `*`, both honestly, with nothing achieved.
    rep = _fixture_preplaced_target_restored()
    verdict, _ = core_interaction_verdict(rep)
    arrivals = count_target_arrivals(rep)
    check("N2 a reload that restores a pre-placed `*` is not an arrival",
          verdict == "UNMEASURED" and count_crate_moves(rep)["moved"] == 1
          and not arrivals["scalar_arrival_steps"]
          and not arrivals["grid_arrival_steps"],
          f"{verdict} with a real push already counted (crates_moved=1), "
          f"{arrivals['reloads_excluded']} reload excluded from both readings")

    # O — the gate reads the LOG, not the summary. A report claiming
    # all_levels_solved with an empty log is exactly what a broken wire or a
    # hand-edited artifact looks like, and it must not be scored.
    rep = _report([], 94, all_solved=True, level_index=2, level_solved=True)
    verdict, _ = core_interaction_verdict(rep)
    check("O a clean summary with an empty log does not open the gate",
          verdict == "UNMEASURED",
          f"{verdict} despite final_state.all_levels_solved=True — the gate reads "
          f"the action log")

    # P — the end-to-end positive control: a real run scores, ratio and all.
    rep = _fixture_all_solved()
    code, printed = score_lines(rep)
    text = "\n".join(printed)
    moves = rep["final_state"]["moves_taken"]
    check("P a finished run is scored", code == 0, f"exit {code}")
    check("P a finished run prints the competence block",
          _COMP in text and f"{_RATIO} {moves / reference:.2f}x" in text
          and _BANNER not in text, "scoreline and ratio, no banner")

    # Q/R — the two sources are made to argue, in both directions.
    rep = _fixture_scalar_without_grid()
    verdict, lines = core_interaction_verdict(rep)
    text = "\n".join(lines)
    check("Q counter rose but the board shows no `*`",
          verdict == "CONTRADICTION" and "scalar [1] / board []" in text
          and "rose on steps : [1]" in text,
          f"{verdict}; both step sets named in the message")
    check("Q a contradiction is its own exit code", score_lines(rep)[0] == 2,
          f"exit {score_lines(rep)[0]} — distinguishable from an unmeasured run")
    rep = _fixture_grid_without_scalar()
    verdict, lines = core_interaction_verdict(rep)
    check("R board shows a `*` the counter never counted",
          verdict == "CONTRADICTION" and "scalar [] / board [1]" in "\n".join(lines),
          verdict)

    # S — the exit code reaches the CLI, off a real file on disk. `--score` is
    # the gate, not a viewer.
    for name, fixture, want in (("walk", _fixture_walk, 1),
                                ("push-onto-target", _fixture_push_onto_target, 0),
                                ("contradiction", _fixture_scalar_without_grid, 2)):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(fixture(), fh)
            path = fh.name
        try:
            got = report_competence(path)
        finally:
            os.unlink(path)
        check(f"S --score on a {name} report exits {want}", got == want, f"exit {got}")
    check("S a missing report is not a pass",
          report_competence(os.path.join(HERE, "results", "does-not-exist.json")) == 1,
          "exit 1")

    # ── The paid budget floor ────────────────────────────────────────────────
    # A budget below the committed reference makes all_levels_solved unreachable
    # by construction, so a paid run at one buys a refusal. These are the controls
    # for the floor that forbids it — including that it is DERIVED.

    # T — the floor is computed from solutions.json, never typed.
    committed_total = sum(len(seq) for seq in solutions.values())
    check("T reference_moves sums the committed sequences",
          reference_moves() == committed_total,
          f"{reference_moves()} moves across {total} levels")
    check("T the floor is the stated multiple of the reference",
          paid_budget_floor() == PAID_BUDGET_MULTIPLE * committed_total,
          f"{paid_budget_floor()} = {PAID_BUDGET_MULTIPLE}x{committed_total}")
    # The case that dies the moment anyone writes the number down: a synthetic
    # level set has to move the answer.
    synthetic = {"a": [0] * 10, "b": [0] * 5}
    check("T a synthetic level set moves the reference and the floor",
          reference_moves(synthetic) == 15 and paid_budget_floor(synthetic) == 30,
          f"reference {reference_moves(synthetic)}, floor {paid_budget_floor(synthetic)} "
          f"for a 10+5-move set — a hard-coded {committed_total} cannot produce this")
    for label, empty in (("no levels", {}), ("a level with no moves", {"a": []})):
        try:
            reference_moves(empty)
            check(f"T {label} fails closed", False, "no SystemExit raised")
        except SystemExit as exc:
            check(f"T {label} fails closed", "solutions.json" in str(exc),
                  "SystemExit naming the artifact rather than a floor of 0")

    # U — the refusal, on both sides of the boundary, and paid-only.
    floor = paid_budget_floor()
    try:
        assert_budget_can_finish("anthropic", STAGE1_DEFAULT_ACTIONS)
        check("U the old default is refused for a paid run", False, "no SystemExit")
    except SystemExit as exc:
        msg = str(exc)
        check("U the old default is refused for a paid run",
              str(committed_total) in msg and str(floor) in msg,
              f"SystemExit naming the {committed_total}-move reference and the "
              f"{floor}-action floor")
    try:
        assert_budget_can_finish("anthropic", floor - 1)
        check("U one below the floor is refused", False, "no SystemExit")
    except SystemExit:
        check("U one below the floor is refused", True, f"{floor - 1} < {floor}")
    for at in (floor, floor + 1):
        try:
            assert_budget_can_finish("anthropic", at)
            check(f"U {at} is allowed", True, f"{at} >= {floor}")
        except SystemExit as exc:
            check(f"U {at} is allowed", False, f"refused: {exc}")
    try:
        assert_budget_can_finish("ollama", STAGE1_DEFAULT_ACTIONS)
        check("U the floor is paid-only", True,
              f"ollama at {STAGE1_DEFAULT_ACTIONS} is not held to the {floor}-action floor")
    except SystemExit as exc:
        check("U the floor is paid-only", False, f"stage 1 would be unrunnable: {exc}")

    # V — the provider-dependent defaults, and P12's ceiling still bites.
    check("V no --max-actions on anthropic resolves to the floor, not 30",
          resolve_max_actions("anthropic", None) == floor
          and resolve_max_actions("anthropic", None) != STAGE1_DEFAULT_ACTIONS,
          f"{resolve_max_actions('anthropic', None)} actions")
    check("V no --max-actions on ollama is unchanged",
          resolve_max_actions("ollama", None) == STAGE1_DEFAULT_ACTIONS,
          f"{resolve_max_actions('ollama', None)} actions")
    check("V an explicit budget always wins",
          all(resolve_max_actions(p, 55) == 55 for p in ("ollama", "anthropic")),
          "55 for both providers — the floor refuses, it never silently rewrites")
    try:
        assert_stage1_ceiling("ollama", STAGE1_CEILING + 1)
        check("V the §B P12 ceiling still refuses 101 on ollama", False, "no SystemExit")
    except SystemExit as exc:
        check("V the §B P12 ceiling still refuses 101 on ollama", "P12" in str(exc),
              f"SystemExit citing P12 for {STAGE1_CEILING + 1}")
    try:
        assert_stage1_ceiling("ollama", STAGE1_CEILING)
        check("V the ceiling itself is allowed", True, f"{STAGE1_CEILING} actions")
    except SystemExit as exc:
        check("V the ceiling itself is allowed", False, f"refused: {exc}")

    # ── The scoring denominator's own name ───────────────────────────────────
    # W — 73 is printed as the committed REFERENCE, and that stays true even
    # though the denominator is now a proven per-level minimum: the game's
    # `tests/test_solution_optimality.gd` searches each level and asserts the
    # committed sequence is the shortest possible. So this is no longer a
    # control against an UNPROVEN claim; it is a control against the LABEL
    # re-acquiring a reading it should not have. "1.37x <that word>" is heard as
    # a verdict on two things at once — how far off the best line the pilot
    # played, AND what the level design costs — and only the first is what this
    # tier measures. Keeping the control is also what keeps the vocabulary
    # permanent: the word leaked once already, from a delivery note into two
    # READMEs and then into the denominator's label. It may live in prose, where
    # a reader can see what proves it; it may not be a printed scoreline label.
    _CLAIM = re.compile(r"optim", re.I)
    for label, fixture in (("a finished run", _fixture_all_solved),
                           ("a walk", _fixture_walk)):
        rep = fixture()
        text = "\n".join(competence_lines(rep) + core_interaction_verdict(rep)[1])
        hit = _CLAIM.search(text)
        check(f"W nothing printed for {label} claims optimality",
              hit is None,
              "no 'optim…' anywhere in the scoreline or the banner" if hit is None
              else f"printed {text[max(0, hit.start() - 40):hit.end() + 40]!r}")

    print(f"\nPROVE SCORING — "
          f"{'MET' if not failures else f'NOT MET ({failures} failed)'}")
    return 1 if failures else 0


# ── Proving the two prompt knobs do different things ─────────────────────────
#
# `assert_history_shows_the_board` needs Godot; these cases need nothing at all.
# They are the permanent control over the framework split this harness depends on
# — including the case that protects the OTHER shipped example, whose
# `redact_state_fields` really is fog of war and must keep stripping the deltas.

class _ConfigShim:
    """The three attributes the prompt builders read, and nothing else.

    Deliberately synthetic: a real `UgtConfig` would tie these cases to the file
    on disk, and the point is to vary the two knobs INDEPENDENTLY of it.
    """

    def __init__(self, playtest: dict):
        self.data = {"playtest": dict(playtest)}
        self.action_mappings = {0: {"name": "up"}, 2: {"name": "left"}}
        self.project_name = "PromptKnobFixture"


# A push left, in the PRD's legend: the crate goes from column 2 to column 1 and
# the player follows it. No scalar the pilot can see moves — which is the whole
# reason the history has to carry the board.
_FIX_BEFORE = ["#######", "# $@  #", "#######"]
_FIX_AFTER = ["#######", "#$@   #", "#######"]


def prove_prompt() -> int:
    """Controls for `redact_state_fields` vs `hide_from_state_block`, and for the
    surprise filter that reads both. No bridge, no model, no file on disk."""
    failures = 0

    def check(name, ok, detail):
        nonlocal failures
        print(f"  [{'ok' if ok else 'FAIL'}] {name}: {detail}")
        if not ok:
            failures += 1

    state = {"player_x": 2, "player_y": 1, "grid": _FIX_AFTER}
    log = [{"step": 1, "action_type": "action_id", "action": "left",
            "state_delta": _compute_delta(
                {"player_x": 3, "player_y": 1, "grid": _FIX_BEFORE}, state)}]
    if "grid" not in log[0]["state_delta"]:
        raise SystemExit(
            "the fixture's two boards are identical, so every case below would be "
            "vacuous. `_compute_delta` wrote no grid term."
        )

    def render(playtest: dict):
        prompt = _build_prompt(_ConfigShim(playtest), "guide", state, "SCREEN", log)
        return (prompt,
                _prompt_section(prompt, "Current State"),
                _prompt_section(prompt, "Recent Actions"))

    print("PROVE PROMPT — the two knobs, and that they are not the same knob")

    # a — the split this task installs: economy hides it from the block and
    #     LEAVES it in the pilot's memory of its own moves.
    _p, block, hist = render({"hide_from_state_block": ["grid"]})
    check("a hide_from_state_block: absent from the state block",
          '"grid"' not in block, f"state block {len(block)} chars, no grid key")
    check("a hide_from_state_block: PRESENT in the recent-action delta",
          "grid" in hist and _FIX_AFTER[1] in hist,
          "the history carries the board's before→after")

    # b — the regression guard for the OTHER shipped example: real fog of war must
    #     still strip both channels, history included.
    _p, block, hist = render({"redact_state_fields": ["grid"]})
    check("b redact_state_fields: absent from the state block",
          '"grid"' not in block, "unchanged behaviour")
    check("b redact_state_fields: absent from the history TOO",
          "grid" not in hist,
          "fog of war still strips the deltas — the escape-room example's `flags` "
          "depends on exactly this")

    # c — a path in both lists is hidden from both channels (no interaction).
    _p, block, hist = render({"redact_state_fields": ["grid"],
                              "hide_from_state_block": ["grid"]})
    check("c in both lists: hidden from both channels",
          '"grid"' not in block and "grid" not in hist,
          "the stricter list wins; listing it twice is not a way to un-hide it")

    # d — neither knob set: the field is in both. Without this the three cases
    #     above could pass on a prompt that never renders a board at all.
    _p, block, hist = render({})
    check("d neither knob: present in both channels",
          '"grid"' in block and "grid" in hist,
          "the knobs are the cause, not a coincidence of the fixture")

    # e — §B P16's second half: a field the pilot never saw NAMED cannot be a
    #     surprise. The heuristic matches leaf names against the pilot's prose.
    delta = log[0]["state_delta"]
    prose = "I walk left"                     # mentions no field name at all
    for label, cfg, want in (
            ("hide_from_state_block", {"hide_from_state_block": ["grid"]}, False),
            ("redact_state_fields", {"redact_state_fields": ["grid"]}, False),
            ("neither list", {}, True)):
        got = "grid" in _unexpected_delta_fields(delta, prose,
                                                 redact=_prompt_hidden_paths(cfg))
        check(f"e grid is {'a' if want else 'not a'} surprise under {label}",
              got == want,
              f"unexpected_deltas {'includes' if got else 'excludes'} grid — "
              + ("a field the pilot was shown and did not predict is still counted"
                 if want else
                 "the pilot is not charged for a name it was never shown"))

    print(f"\nPROVE PROMPT — "
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
    ap.add_argument("--max-actions", type=int, default=None, dest="max_actions",
                    help=f"default: {STAGE1_DEFAULT_ACTIONS} for ollama (§B P12 caps stage 1 "
                         f"at {STAGE1_CEILING}); for anthropic, the derived floor — "
                         f"{PAID_BUDGET_MULTIPLE}x the committed reference read from "
                         f"levels/solutions.json — below which a paid run cannot finish")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--output", default=None)
    ap.add_argument("--score", default=None, metavar="PATH",
                    help="re-score a report that already exists; no bridge, no model, "
                         "no spend. GATED: exit 0 scored, 1 the core interaction never "
                         "happened (or no report), 2 the log contradicts itself")
    ap.add_argument("--prove-scoring", action="store_true", dest="prove_scoring",
                    help="run the competence block's, the gate's and the budget floor's "
                         "own controls against synthetic reports and synthetic level "
                         "sets; no bridge, no model, no spend")
    ap.add_argument("--prove-prompt", action="store_true", dest="prove_prompt",
                    help="run the prompt knobs' own controls — that "
                         "hide_from_state_block drops a field from the state block "
                         "while LEAVING it in the pilot's history, and that "
                         "redact_state_fields still strips both; synthetic states, no "
                         "bridge, no model, no spend")
    args = ap.parse_args()

    # Model-free paths first, so scoring never needs Godot or a provider.
    if args.prove_scoring:
        return prove_scoring()
    if args.prove_prompt:
        return prove_prompt()
    if args.score:
        return report_competence(args.score)

    # Budget policy next — it costs nothing, needs no config and must refuse
    # BEFORE Godot is started, let alone a model contacted.
    budget = resolve_max_actions(args.provider, args.max_actions)
    assert_stage1_ceiling(args.provider, budget)
    assert_budget_can_finish(args.provider, budget)
    if args.provider == "anthropic":
        print(f"[budget] anthropic: {budget} actions "
              f"({PAID_BUDGET_MULTIPLE}x the committed {reference_moves()}-move reference "
              f"across {len(_committed_solutions())} levels).")
    else:
        print(f"[budget] ollama: {budget} actions (stage 1; §B P12 ceiling "
              f"{STAGE1_CEILING} — the paid floor of {paid_budget_floor()} does not apply).")

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
        assert_history_shows_the_board(config, guide, probe)
    finally:
        probe.close()

    output = args.output or os.path.join(HERE, "results", "playtest-report.json")
    os.makedirs(os.path.dirname(output), exist_ok=True)

    summary = playtest_game_with_adapter(
        GodotTcpAdapter(config),
        provider=args.provider,
        strategy_guide=guide,
        max_actions=budget,
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

    # The gate runs on the report that was just WRITTEN, so a tripped gate never
    # loses the artifact — and `--score` reproduces this exact verdict for free.
    if args.runs == 1:
        return report_competence(output)

    # Every run is scored, and one unmeasured run is one unmeasured game: with no
    # RNG anywhere, N runs are N replays, so "most of them pushed something" is
    # not a thing this game can mean.
    files = (summary or {}).get("run_report_files")
    if not files:
        raise SystemExit(
            f"--runs {args.runs} produced no run_report_files in {output}, so the "
            f"per-run reports cannot be located and the core-interaction gate has "
            f"nothing to read. Refusing to report a batch as scored on the strength "
            f"of an aggregate block."
        )
    worst = 0
    for name in files:
        path = os.path.join(os.path.dirname(output), name)
        code = report_competence(path)
        print(f"[gate] {name}: exit {code}")
        worst = max(worst, code)
    return worst


if __name__ == "__main__":
    sys.exit(main())
