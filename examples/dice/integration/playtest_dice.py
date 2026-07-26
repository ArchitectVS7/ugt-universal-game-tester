#!/usr/bin/env python3
"""Tier 3 — LLM playtest runner for Dice Duel.

Why this exists rather than a bare `ugt playtest --config ...`:

  * The CLI needs a server already running on a fixed port. Every other rung in
    this ladder spawns and reaps its own on an EPHEMERAL port precisely so a
    stale :8080 from an older build can never be the thing under test
    (`serve_process.py`, and LESSONS.md O1 one layer up). A balance run is the
    LAST place to relax that: a stale bundle here produces a confident number
    about a game nobody is shipping.
  * The CLI cannot pass an invariant suite. `playtest_game(..., invariants=)`
    runs the same predicates R1/R2/R3 assert, after every action the pilot
    takes, so a defect the LLM does not happen to notice is still caught.
  * The §B pre-flight checks have to run somewhere, fail-closed, BEFORE any
    model is contacted — the guide budget (P3), the terminal channel (P2) and,
    above all, the seed rotation (P9).
  * The paired score is the headline metric and it needs the game's engine.

Staging (LESSONS.md §B P12) — local proves the CHANNEL, paid measures the GAME.
The seed dimension splits each half in two, so there are four steps and each one
answers a question the previous one could not:

    # 1a  local, one seed          — does the loop work at all, on one battle?
    python3 playtest_dice.py --provider ollama   --seeds 1 --max-actions 14
    # 1b  local, the whole set     — does the rotation actually ROTATE?
    python3 playtest_dice.py --provider ollama   --seeds 8 --max-actions 96
    # 2a  paid, one seed           — is Haiku's data good before we commit spend?
    python3 playtest_dice.py --provider anthropic --seeds 1 --max-actions 14
    # 2b  paid, the measurement    — 8 seeds x 2 reps = 16 battles
    python3 playtest_dice.py --provider anthropic --seeds 8 --max-actions 96 --runs 2

Stage 1 never produces a number, whatever it reports: past ~100 local calls the
decisions degrade below Haiku's, and bad decisions are not better evidence.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
GAME = os.path.abspath(os.path.join(HERE, "..", "game"))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from serve_process import served_bundle  # noqa: E402
from invariants import SUITE  # noqa: E402

from ugt.core.playtester import playtest_game  # noqa: E402
from ugt.utils.config_parser import UgtConfig  # noqa: E402

GUIDE = os.path.join(HERE, "strategy-guide.md")
CONFIG = os.path.join(HERE, "ugt.config.yaml")
BASELINE_TOOL = os.path.join(GAME, "tools", "paired_baseline.mjs")


def _pt(config) -> dict:
    return config.data.get("playtest") or {}


# ── §B pre-flight ────────────────────────────────────────────────────────────

def assert_guide_fits(config: UgtConfig, guide: str) -> None:
    """LESSONS.md §B P3 — truncation is silent starvation.

    `_fit()` cuts the guide at `playtest.guide_char_budget` from the TAIL. On
    this game's guide the tail is "How to play well" — the two-for-one block,
    the points decision, and the enemy's behaviour — so an over-budget guide
    produces a pilot that has read the rules of the game but none of the skill,
    and reports `PLAYTEST MET` while doing it. Fail before spending anything.
    """
    budget = int(_pt(config).get("guide_char_budget", 2000))
    if len(guide) > budget:
        raise SystemExit(
            f"P3 VIOLATION — strategy-guide.md is {len(guide)} chars but "
            f"playtest.guide_char_budget is {budget}. The last "
            f"{len(guide) - budget} chars would be silently cut from the prompt.\n"
            f"    Raise the budget in ugt.config.yaml, or shorten the guide."
        )
    print(f"[P3] guide {len(guide)} chars <= budget {budget} — no truncation.")


def assert_seed_sets_agree(config: UgtConfig) -> list:
    """The YAML seed list and the scorer's seed list must be the same list.

    They live in two files in two languages, and a batch scored against a
    baseline computed for DIFFERENT seeds would produce a confident, wrong
    number with nothing red anywhere. Cheap to check, so check it.
    """
    yaml_seeds = [str(s) for s in (_pt(config).get("episode_seeds") or [])]
    if not yaml_seeds:
        raise SystemExit("playtest.episode_seeds is empty — see LESSONS.md §B P9.")
    js = subprocess.run(
        ["node", BASELINE_TOOL, "--seeds-json"],
        capture_output=True, text=True, cwd=GAME,
    )
    if js.returncode != 0:
        raise SystemExit(f"could not read DEFAULT_SEEDS from paired_baseline.mjs:\n{js.stderr}")
    tool_seeds = json.loads(js.stdout)
    if tool_seeds != yaml_seeds:
        raise SystemExit(
            f"SEED SET DRIFT — ugt.config.yaml and paired_baseline.mjs disagree.\n"
            f"    config: {yaml_seeds}\n"
            f"    tool  : {tool_seeds}\n"
            f"    Scoring a batch against the wrong baseline is silent and wrong."
        )
    print(f"[P9] seed set agrees across config and scorer: {len(yaml_seeds)} seeds.")
    return yaml_seeds


def assert_terminal_channel_is_live(config: UgtConfig, port: int) -> None:
    """LESSONS.md §B P2 — the adapter must pass through what the game shows.

    Non-vacuity check for the D19 `__GET_TERMINAL_TEXT__` hook (O2): this
    returned the empty string for the whole life of the integration, because
    `PlaywrightAdapter.get_terminal_text` found neither the hook nor a terminal
    element, and nothing noticed.
    """
    adapter = _probe_adapter(port)
    adapter.connect()
    try:
        budget = int(_pt(config).get("terminal_char_budget", 400))
        adapter.reset()
        opening = adapter.get_terminal_text(budget)
        adapter.step(0)
        adapter.step(0)
        after = adapter.get_terminal_text(budget)
    finally:
        adapter.close()

    if not opening.strip():
        raise SystemExit("P2 VIOLATION — the terminal channel is empty at round 0.")
    if "Round 1" not in after or "Round 2" not in after:
        raise SystemExit(
            f"P2 VIOLATION — two resolved rounds are not both visible in the "
            f"{budget}-char terminal channel. Got:\n{after}"
        )
    if "volley" not in after:
        raise SystemExit(
            "P2 VIOLATION — the dispatch text carries no exchange line, so the "
            "pilot cannot see hits-vs-blocked."
        )
    print(f"[P2] terminal channel live: {len(after)} chars, rounds 1-2 both in view.")


def assert_seed_rotation_works(port: int, seeds: list) -> None:
    """LESSONS.md §B P9 — PROVE the seeds do something. This is the load-bearing check.

    `reset_seeded` raises for an adapter that cannot seed, but that is not
    enough: JavaScript discards extra arguments in silence, so
    `window.__RESET_GAME__(seed)` against a game that never implemented seeding
    returns a perfectly normal state and raises nothing. The integration would
    then report N episodes on N seeds while playing one battle N times — which
    is precisely the bug this whole mechanism was built to remove, surviving the
    fix intact and now wearing a green light.

    So: two different seeds must produce different battles, and one seed must
    reproduce itself exactly. Both directions, because a hook that returned
    random state on every call would pass the first test and be just as broken.
    """
    if len(seeds) < 2:
        raise SystemExit("need >= 2 seeds to prove rotation; check the config.")
    adapter = _probe_adapter(port)
    adapter.connect()
    try:
        def battle(seed):
            adapter.reset_seeded(seed)
            out = []
            for _ in range(4):
                state, terminated, _t, _i = adapter.step(3)
                out.append((state["player"]["force_strength"], state["enemy"]["force_strength"]))
                if terminated:
                    break
            return out

        a1, b1, a2 = battle(seeds[0]), battle(seeds[1]), battle(seeds[0])
    finally:
        adapter.close()

    if a1 == b1:
        raise SystemExit(
            f"P9 VIOLATION — seeds {seeds[0]!r} and {seeds[1]!r} produce the IDENTICAL "
            f"battle {a1}. The seed is being ignored, so every episode is the same "
            f"match and no batch computed from this run means anything."
        )
    if a1 != a2:
        raise SystemExit(
            f"P9 VIOLATION — seed {seeds[0]!r} did not reproduce itself: {a1} then {a2}. "
            f"Seeding is not deterministic, so a 'seed' names nothing."
        )
    print(f"[P9] rotation proven: {seeds[0]} -> {a1[:2]}…, {seeds[1]} -> {b1[:2]}…, "
          f"and {seeds[0]} replays byte-identical.")


def _probe_adapter(port: int):
    from ugt.adapters.playwright import PlaywrightAdapter
    cfg = UgtConfig(CONFIG)
    cfg.data["engine"]["entry"] = f"http://localhost:{port}/index.html"
    return PlaywrightAdapter(cfg)


# ── Scoring ──────────────────────────────────────────────────────────────────

def paired_baselines(seeds: list) -> dict:
    """`{seed: {mean_margin, best_margin, winnable, ...}}` straight off the engine."""
    out = subprocess.run(
        ["node", BASELINE_TOOL, "--json", *seeds],
        capture_output=True, text=True, cwd=GAME,
    )
    if out.returncode != 0:
        raise SystemExit(f"paired_baseline.mjs failed:\n{out.stderr}")
    return {r["seed"]: r for r in json.loads(out.stdout)}


def score_batch(report_paths: list, seeds: list) -> None:
    """Report the PAIRED margin, and say plainly why the win rate is not the headline.

    Paired score for one battle = (the pilot's final force-strength margin)
    − (that seed's mean margin across the reference policies). The seed's
    difficulty cancels, which is worth 2.7x the battles: across 200 seeds a
    fixed policy's raw margin has sd 3.53 and its paired margin sd 2.16.
    """
    base = paired_baselines(seeds)
    rows = []
    for path in report_paths:
        rep = json.load(open(path))
        for ep in rep.get("episodes", []):
            if ep["end_reason"] not in ("terminated", "truncated"):
                continue  # never score an unfinished battle (O8)
            fs = ep["final_state"]
            m = fs["player"]["force_strength"] - fs["enemy"]["force_strength"]
            b = base.get(ep["seed"])
            if b is None:
                raise SystemExit(f"no baseline for seed {ep['seed']!r} — seed-set drift.")
            rows.append({
                "seed": ep["seed"], "outcome": ep["outcome"], "margin": m,
                "baseline": b["mean_margin"], "paired": round(m - b["mean_margin"], 3),
                "best": b["best_margin"], "winnable": b["winnable"], "actions": ep["actions"],
            })

    print("\n" + "=" * 70)
    if not rows:
        print("NO COMPLETED BATTLES — nothing to score. (Raise --max-actions.)")
        return
    print(f"PAIRED SCORE — {len(rows)} completed battle(s)")
    print("seed        outcome   margin  baseline   paired   best  winnable  actions")
    for r in rows:
        print(f"{r['seed']:<12}{str(r['outcome']):<9}{r['margin']:>7}{r['baseline']:>10}"
              f"{r['paired']:>9}{r['best']:>7}{str(r['winnable']):>10}{r['actions']:>9}")

    paired = [r["paired"] for r in rows]
    mean = statistics.mean(paired)
    print(f"\n  PAIRED MEAN  {mean:+.2f}", end="")
    if len(paired) >= 2:
        sd = statistics.stdev(paired)
        ci = 1.96 * sd / (len(paired) ** 0.5)
        print(f"   95% CI +/-{ci:.2f}  (sd {sd:.2f}, n={len(paired)})")
        print(f"  {'ABOVE' if mean - ci > 0 else 'BELOW' if mean + ci < 0 else 'NOT DISTINGUISHABLE FROM'} "
              f"the average reference policy at 95%.")
    else:
        print("   (n=1 — no interval; this is a data-quality check, not a measurement)")

    wins = sum(1 for r in rows if r["outcome"] == "player")
    n = len(rows)
    p = wins / n
    lo, hi = _wilson(wins, n)
    unwinnable = sum(1 for r in rows if not r["winnable"])
    print(f"\n  win rate {wins}/{n} = {100*p:.1f}%   95% CI [{100*lo:.1f}%, {100*hi:.1f}%] "
          f"(Wilson) — NOT a quotable figure at this n.")
    if unwinnable:
        print(f"  ({unwinnable} of these battles were on seeds NO reference policy can win, "
              f"which is why the win rate is not the headline.)")
    print("=" * 70)


def _wilson(successes: int, n: int, z: float = 1.96) -> tuple:
    """Wilson score interval for a proportion.

    NOT the textbook normal approximation `z*sqrt(p(1-p)/n)`: that collapses to
    +/-0.0 at p=0 or p=1, which is how the first version of this function
    reported "0/1 = 0.0%, 95% CI +/-0.0 points" — an interval asserting perfect
    certainty from a single battle. A CI that cannot express uncertainty at the
    exact points where uncertainty is highest is a vacuous number (O2), and this
    metric's whole job is to SHOW that it is underpowered. Wilson returns
    [0%, 79%] for 0/1, which is the honest answer.
    """
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z / denom) * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return (max(0.0, centre - half), min(1.0, centre + half))


# ── Entry point ──────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--provider", default="ollama", choices=["ollama", "anthropic"],
                    help="local (free, proves the channel) or paid (produces the number)")
    ap.add_argument("--model", default=None,
                    help="default: gemma4:26b for ollama, the playtester's default for anthropic")
    ap.add_argument("--max-actions", type=int, default=30, dest="max_actions")
    ap.add_argument("--runs", type=int, default=1, help="repeats of the whole seed rotation")
    ap.add_argument("--seeds", type=int, default=None,
                    help="use only the first N configured seeds (1 = the single-seed stage)")
    ap.add_argument("--output", default=None)
    ap.add_argument("--no-score", action="store_true",
                    help="skip the paired scoring pass (it needs node)")
    args = ap.parse_args()

    if args.provider == "ollama" and args.max_actions > 100:
        raise SystemExit(
            f"--max-actions {args.max_actions} on a local model: LESSONS.md §B P12 caps "
            f"stage 1 at ~100. Past ~200 local calls the decisions degrade below Haiku's, "
            f"so a longer run buys worse play, not more evidence. Use --provider anthropic."
        )

    guide = open(GUIDE).read()
    config = UgtConfig(CONFIG)
    assert_guide_fits(config, guide)
    all_seeds = assert_seed_sets_agree(config)

    seeds = all_seeds[: args.seeds] if args.seeds else all_seeds
    if args.seeds:
        # Narrowing the set is legitimate for the single-seed stages, but it must
        # be visible in the output — a reader must never have to infer the
        # denominator from the run length.
        print(f"[*] using the first {len(seeds)} of {len(all_seeds)} configured seeds: {seeds}")
        config.data["playtest"]["episode_seeds"] = seeds

    with served_bundle() as port:
        print(f"[*] serving the built bundle on :{port}")
        assert_terminal_channel_is_live(config, port)
        assert_seed_rotation_works(port, all_seeds)
        config.data["engine"]["entry"] = f"http://localhost:{port}/index.html"
        playtest_game(
            config, guide,
            max_actions=args.max_actions,
            output_path=args.output,
            provider=args.provider,
            model=args.model,
            runs=args.runs,
            # The identical predicates R1/R2 and R3 assert — one definition, now
            # three tiers. A pilot that never notices a bug does not make it absent.
            invariants=lambda _adapter: SUITE.to_hunter_invariants(),
        )

    if args.no_score:
        return 0
    results = os.path.join(HERE, "results")
    if args.runs > 1:
        paths = [os.path.join(results, f"playtest-run-{i}.json") for i in range(1, args.runs + 1)]
    else:
        paths = [args.output or os.path.join(results, "playtest-report.json")]
    score_batch([p for p in paths if os.path.exists(p)], seeds)
    return 0


if __name__ == "__main__":
    sys.exit(main())
