#!/usr/bin/env python3
"""
DDD ROUND 2 — the FULL content spine driven through the real engine: every wave
configuration, both formats, all four decks, every terminal result the engine can
produce, and every one of the 36 shipped cards actually played.

Where R1 walked ONE match under one policy and one config, R2 asserts that UGT
drives the game DDD actually ships — not a shallower one. That distinction is not
academic: before this ladder was re-baselined, UGT's config named only two of the
three wave keys, so `enabledWaves.typeTriangle` read as `undefined` -> falsy and
the ENTIRE 2026-07-11 R1 run certified a game with D16's type triangle switched
off. R2 exists so that class of silent divergence cannot recur unnoticed.

Everything is driven THROUGH `DddHarnessAdapter` over the harness's JSON-lines
wire — never a re-implementation, and never an in-process shortcut (the wire is
the only door UGT has, and defects that live only on the wire are exactly what it
is here to find).

Gate (fail-closed; ~40 checks):
  1. WAVE MATRIX — a full match to a terminal result under each of the 4 wave
     configurations (none / stanceEcho / +chainsPredictions / +typeTriangle),
     invariant sweep CLEAN on every step of every one.
  2. DECK x FORMAT MATRIX — all 4 COMPETITIVE pairings (bb/sw x bb/sw, mirrors
     and crosses) and all 4 TUTORIAL pairings reach a terminal result with a clean
     sweep; the TUTORIAL 25-card decks conserve 25, the COMPETITIVE 40-card decks
     conserve 40 (card conservation is format-relative — the R1 suite's hard-coded
     40 would be WRONG for tutorial, so R2 checks it explicitly per format).
  3. TERMINAL COVERAGE — a seed/config sweep reaches each MatchResult arm the wire
     can produce, and prints the histogram. KNOCKOUT, CONCESSION and TURN_LIMIT are
     GATED (each has a deliberate route); the rarer arms (DOUBLE_KO, EXHAUSTION,
     the TIEs) are reported honestly as reached-or-not rather than faked.
  4. CONTENT COVERAGE — across the corpus every one of the 36 shipped cards is
     COMMITTED at least once (the two competitive decklists are 18 + 18 distinct =
     the whole pack). This is the direct guard against DDD's own T6.0 finding — a
     policy that never fills targets left 7 Swarm cards inert and "the balance gate
     had been measuring a game nobody plays".
  5. TARGETS ARE LOAD-BEARING — `commit_with_targets` (id 3) fires >=1
     CARD_RETURNED; the `commit_no_targets` control (id 4) fires ZERO on the same
     seed. If the `targets` op ever silently returned nothing, check 5b goes red.
  6. D16, DIFFERENTIALLY — the same seed run with typeTriangle ON and OFF: with it
     OFF, `advantage` is null in EVERY combat; with it ON, >=1 combat has an
     advantage, and at the FIRST combat the countering seat's power is EXACTLY
     TYPE_ADVANTAGE_POWER (4) higher than in the OFF run while the other seat's is
     unchanged. Also D2 everywhere: damage == |power0 - power1|.
  7. DETERMINISM, TWO INDEPENDENT ORACLES — every match in the corpus replays
     byte-identically on its own seed (UGT's own hash stream), AND the harness's
     `replay` op re-verifies its recorded log. Non-vacuous (real ply counts).

A failed check is DATA: it prints as a [FINDING], fails the gate, and is fixed
UPSTREAM in DDD with a pinning test — never weakened here.

Run (from the UGT repo root; node >=24, DDD deps installed — the adapter spawns
the harness itself, there is no server to start):

    python3 integrations/ddd/verify_round2.py [seed]

Exit 0 + "ROUND 2 MET — N/N" means the gate passed.
"""
from __future__ import annotations

import copy
import json
import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import invariants  # noqa: E402  (local module, from integrations/ddd/)

from ugt.adapters.ddd_harness import DddHarnessAdapter  # noqa: E402
from ugt.core.trial import GateRunner, first_divergence  # noqa: E402
from ugt.utils.config_parser import UgtConfig  # noqa: E402

CONFIG_PATH = "integrations/ddd/ugt.config.yaml"
DEFAULT_SEED = "ddd-r2"

# Policy ids (must match ugt.config.yaml / DddHarnessAdapter._DEFAULT_ACTION_NAMES)
COMMIT_RANDOM = 1
COMMIT_WITH_TARGETS = 3
COMMIT_NO_TARGETS = 4
COMMIT_WITH_PREDICTION = 5
MULLIGAN_KEEP = 8
CONCEDE = 10

# D16: the counterer's power bonus (engine state/matchup.ts TYPE_ADVANTAGE_POWER).
TYPE_ADVANTAGE_POWER = 4

ALL_WAVES = {"stanceEcho": True, "chainsPredictions": True, "typeTriangle": True}
NO_WAVES = {"stanceEcho": False, "chainsPredictions": False, "typeTriangle": False}

WAVE_MATRIX = [
    ("none", NO_WAVES),
    ("stanceEcho", {"stanceEcho": True, "chainsPredictions": False, "typeTriangle": False}),
    ("+chainsPredictions", {"stanceEcho": True, "chainsPredictions": True, "typeTriangle": False}),
    ("+typeTriangle (shipped)", ALL_WAVES),
]

COMPETITIVE_DECKS = ["bb_competitive", "sw_competitive"]
TUTORIAL_DECKS = ["bb_tutorial", "sw_tutorial"]

# The game's own content manifest — read to learn what SHOULD be playable. This is
# reading the game's data, not re-implementing its rules.
MANIFEST = os.path.join(
    os.environ.get("DDD_REPO", "/Users/vs7/Dev/Games/DDD"),
    "packages/content/data/base/manifest.json",
)


def deck_lists():
    """{deckId: {cardId: count}} straight from DDD's shipped manifest."""
    with open(MANIFEST) as fh:
        data = json.load(fh)
    out = {}

    def walk(node):
        if isinstance(node, dict):
            if "id" in node and "format" in node and isinstance(node.get("cards"), list):
                out[node["id"]] = {c["cardId"]: c["count"] for c in node["cards"]}
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)
    return out


def make_config(base: UgtConfig, *, decks=None, fmt=None, waves=None, max_turns=None):
    """A per-scenario UgtConfig clone with engine keys overridden."""
    cfg = copy.deepcopy(base)
    eng = cfg.data.setdefault("engine", {})
    if decks is not None:
        eng["decks"] = list(decks)
    if fmt is not None:
        eng["format"] = fmt
    if waves is not None:
        eng["enabledWaves"] = dict(waves)
    if max_turns is not None:
        eng["maxTurns"] = int(max_turns)
    return cfg


def drive(cfg, seed, policy, suite, *, ply_cap=None, concede_at=None):
    """Play one whole match. Returns a dict of everything the gates need.

    `policy` is an action id, or a callable(ply) -> action id.
    `concede_at` (ply index) forces the CONCEDE id at that ply — the only route to
    a CONCESSION result.
    """
    ad = DddHarnessAdapter(cfg)
    ad.connect()
    cap = ply_cap or (ad.max_turns * 6)
    try:
        state = ad.reset(seed)
        violations, events, committed, combats = [], [], [], []
        plies = 0
        terminated = False
        while plies < cap:
            if concede_at is not None and plies == concede_at:
                aid = CONCEDE
            elif callable(policy):
                aid = policy(plies)
            else:
                aid = policy

            seat = ad._pending_seat()
            before = state
            after, term, _trunc, info = ad.step(aid)
            action = info.get("action") or {}

            # Resolve the committed card to its defId BEFORE the view moves on —
            # `before` is the pre-act view, so the card is still in hand there.
            if action.get("t") == "COMMIT_SELECTION" and seat is not None:
                committed.append(info.get("defIdCommitted"))

            result = info["result"]
            for msg in suite.check_command(before, after, "act", result):
                violations.append(f"ply {plies} {action.get('t')}: {msg}")
            for e in (result.get("events") or []):
                events.append(e)
                if e.get("t") == "COMBAT_RESOLVED":
                    combats.append(e)
            plies += 1
            state = after
            if term:
                terminated = True
                break

        replay = ad.replay_current()
        return {
            "final": state,
            "resultKind": state.get("resultKind"),
            "via": (state.get("result") or {}).get("via"),
            "terminated": terminated,
            "plies": plies,
            "violations": violations,
            "events": events,
            "combats": combats,
            "committed": [c for c in committed if c],
            "stream": list(ad.hash_stream),
            "replayOk": bool(replay.get("ok")) and replay.get("verified") is True,
            "seats": (state.get("p0"), state.get("p1")),
        }
    finally:
        ad.close()


def count_events(events, kind):
    return sum(1 for e in events if e.get("t") == kind)


def main() -> int:
    seed = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SEED
    base = UgtConfig(CONFIG_PATH)
    suite = invariants.build_suite()
    gate = GateRunner()
    ck, finding = gate.ck, gate.finding
    decks = deck_lists()

    print(f"DDD Round 2 — the full content spine (seed {seed!r})\n")

    all_committed = set()
    corpus = []  # (label, run)

    # ── 1. WAVE MATRIX ───────────────────────────────────────────────────────
    print("  -- 1. wave matrix (4 configs, shipped decks) --")
    for label, waves in WAVE_MATRIX:
        cfg = make_config(base, decks=COMPETITIVE_DECKS, fmt="COMPETITIVE", waves=waves)
        run = drive(cfg, f"{seed}-w-{label}", COMMIT_RANDOM, suite)
        corpus.append((f"waves:{label}", run))
        all_committed.update(run["committed"])
        ck(f"waves[{label}]: full match -> terminal, sweep CLEAN",
           run["terminated"] and run["resultKind"] in ("WIN", "DRAW") and not run["violations"],
           f"kind={run['resultKind']}/{run['via']} plies={run['plies']} "
           f"violations={len(run['violations'])}")
        for v in run["violations"][:3]:
            finding(f"waves[{label}] invariant violation: {v}")

    # ── 2. DECK x FORMAT MATRIX ──────────────────────────────────────────────
    print("\n  -- 2. deck x format matrix (mirrors + crosses, both formats) --")
    for fmt, pool, deck_total in (
        ("COMPETITIVE", COMPETITIVE_DECKS, 40),
        ("TUTORIAL", TUTORIAL_DECKS, 25),
    ):
        for d0 in pool:
            for d1 in pool:
                cfg = make_config(base, decks=[d0, d1], fmt=fmt, waves=ALL_WAVES)
                run = drive(cfg, f"{seed}-{d0}-{d1}", COMMIT_WITH_TARGETS, suite)
                corpus.append((f"{fmt}:{d0}v{d1}", run))
                all_committed.update(run["committed"])
                p0, p1 = run["seats"]
                conserved = all(
                    (s or {}).get("handCount", 0)
                    + (s or {}).get("deckCount", 0)
                    + (s or {}).get("graveyardCount", 0)
                    + (s or {}).get("committedCard", 0)
                    == deck_total
                    for s in (p0, p1)
                )
                ck(f"{fmt} {d0} vs {d1}: terminal, sweep CLEAN, {deck_total}-card conservation",
                   run["terminated"] and not run["violations"] and conserved,
                   f"kind={run['resultKind']}/{run['via']} plies={run['plies']} "
                   f"conserved={conserved} violations={len(run['violations'])}")
                for v in run["violations"][:3]:
                    finding(f"{fmt} {d0}v{d1} invariant violation: {v}")

    # ── 3. TERMINAL COVERAGE ─────────────────────────────────────────────────
    print("\n  -- 3. terminal-result coverage --")
    seen_terminals = {}

    def note(run):
        key = f"{run['resultKind']}/{run['via']}" if run["via"] else run["resultKind"]
        seen_terminals[key] = seen_terminals.get(key, 0) + 1

    for label, run in corpus:
        note(run)

    # CONCESSION: only reachable via the explicit concede id.
    cfg = make_config(base, decks=COMPETITIVE_DECKS, fmt="COMPETITIVE", waves=ALL_WAVES)
    conc = drive(cfg, f"{seed}-concede", COMMIT_RANDOM, suite, concede_at=6)
    note(conc)
    ck("CONCESSION is reachable (the concede id) and the sweep stays CLEAN",
       conc["resultKind"] == "WIN" and conc["via"] == "CONCESSION" and not conc["violations"],
       f"kind={conc['resultKind']}/{conc['via']} plies={conc['plies']}")

    # TURN_LIMIT: a tiny maxTurns forces the cap.
    tl_runs = []
    for s in range(12):
        cfg = make_config(base, decks=COMPETITIVE_DECKS, fmt="COMPETITIVE",
                          waves=ALL_WAVES, max_turns=2)
        r = drive(cfg, f"{seed}-tl-{s}", COMMIT_RANDOM, suite)
        tl_runs.append(r)
        note(r)
    tl_kinds = {f"{r['resultKind']}/{r['via']}" for r in tl_runs}
    ck("TURN_LIMIT is reachable (maxTurns=2) and every such run sweeps CLEAN",
       any("TURN_LIMIT" in k for k in tl_kinds) and not any(r["violations"] for r in tl_runs),
       f"kinds={sorted(tl_kinds)}")

    # A broader seed sweep to surface the rarer arms honestly.
    for s in range(20):
        cfg = make_config(base, decks=COMPETITIVE_DECKS, fmt="COMPETITIVE", waves=ALL_WAVES)
        note(drive(cfg, f"{seed}-sweep-{s}", COMMIT_RANDOM, suite))

    print(f"     terminal histogram: {json.dumps(seen_terminals, sort_keys=True)}")
    ck("KNOCKOUT reached", any(k.startswith("WIN/KNOCKOUT") for k in seen_terminals),
       f"{seen_terminals.get('WIN/KNOCKOUT', 0)} runs")
    ck("the terminal histogram is non-degenerate (>=3 distinct arms across the corpus)",
       len(seen_terminals) >= 3, f"{len(seen_terminals)} distinct: {sorted(seen_terminals)}")

    # ── 4. CONTENT COVERAGE ──────────────────────────────────────────────────
    print("\n  -- 4. content coverage (every shipped card actually played) --")
    expected = set()
    for d in COMPETITIVE_DECKS:
        expected.update(decks.get(d, {}).keys())
    missing = sorted(expected - all_committed)
    ck(f"every card in the two COMPETITIVE decklists is COMMITTED at least once "
       f"({len(expected)} distinct)",
       not missing,
       f"played={len(all_committed & expected)}/{len(expected)}"
       + (f" MISSING={missing}" if missing else ""))
    if missing:
        finding(
            f"{len(missing)} shipped cards were never played across the whole R2 corpus: "
            f"{missing} — a card the tester cannot reach is a card nobody is testing "
            f"(DDD's own T6.0 lesson)."
        )

    # ── 5. TARGETS ARE LOAD-BEARING ──────────────────────────────────────────
    print("\n  -- 5. graveyard targets (the `targets` op) --")
    sw_cfg = make_config(base, decks=["sw_competitive", "sw_competitive"],
                         fmt="COMPETITIVE", waves=ALL_WAVES)
    with_t = drive(sw_cfg, f"{seed}-targets", COMMIT_WITH_TARGETS, suite)
    no_t = drive(sw_cfg, f"{seed}-targets", COMMIT_NO_TARGETS, suite)
    returned_with = count_events(with_t["events"], "CARD_RETURNED")
    returned_without = count_events(no_t["events"], "CARD_RETURNED")

    ck("commit_with_targets fires >=1 CARD_RETURNED (the mechanic is LIVE over the wire)",
       returned_with >= 1, f"{returned_with} CARD_RETURNED in {with_t['plies']} plies")
    ck("the commit_no_targets CONTROL fires ZERO CARD_RETURNED (so check 5 is not vacuous)",
       returned_without == 0, f"{returned_without} CARD_RETURNED (expected 0)")
    if returned_with == 0:
        finding(
            "no CARD_RETURNED even under commit_with_targets — the `targets` op is inert, "
            "so every graveyard-targeting card is being played blank."
        )

    # ── 6. D16, DIFFERENTIALLY ───────────────────────────────────────────────
    print("\n  -- 6. D16 type triangle (same seed, triangle ON vs OFF) --")
    on_cfg = make_config(base, decks=COMPETITIVE_DECKS, fmt="COMPETITIVE", waves=ALL_WAVES)
    off_waves = {**ALL_WAVES, "typeTriangle": False}
    off_cfg = make_config(base, decks=COMPETITIVE_DECKS, fmt="COMPETITIVE", waves=off_waves)

    # Seek a seed whose FIRST combat is an actual COUNTER. If the first combat is
    # type-neutral the differential degenerates to "nothing changed", which would
    # pass without ever testing the +4 — a vacuous green. Search until the +4 is
    # genuinely on the line; if no seed in the band produces one, say so and FAIL
    # rather than accept the neutral branch as proof.
    on = off = None
    d16_seed = None
    for s in range(30):
        cand_seed = f"{seed}-d16-{s}"
        cand_on = drive(on_cfg, cand_seed, COMMIT_RANDOM, suite)
        if cand_on["combats"] and cand_on["combats"][0].get("advantage") is not None:
            on = cand_on
            off = drive(off_cfg, cand_seed, COMMIT_RANDOM, suite)
            d16_seed = cand_seed
            break
    if on is None:
        # Fall back to a fixed seed so the OFF/D2 checks below still run and report.
        d16_seed = f"{seed}-d16-0"
        on = drive(on_cfg, d16_seed, COMMIT_RANDOM, suite)
        off = drive(off_cfg, d16_seed, COMMIT_RANDOM, suite)
    print(f"     d16 seed {d16_seed!r} — first combat countered: "
          f"{bool(on['combats']) and on['combats'][0].get('advantage') is not None}")

    ck("triangle OFF: `advantage` is null in EVERY combat",
       all(c.get("advantage") is None for c in off["combats"]),
       f"{len(off['combats'])} combats, "
       f"{sum(1 for c in off['combats'] if c.get('advantage') is not None)} with advantage")

    on_adv = [c for c in on["combats"] if c.get("advantage") is not None]
    ck("triangle ON: >=1 combat is COUNTERED (advantage set)",
       len(on_adv) >= 1, f"{len(on_adv)}/{len(on['combats'])} combats countered")

    # D2 (damage == power differential) must hold in both worlds, always.
    d2_bad = [
        c for c in (on["combats"] + off["combats"])
        if c.get("damage") != abs(c.get("power0", 0) - c.get("power1", 0))
    ]
    ck("D2 holds in every combat of both runs: damage == |power0 - power1|",
       not d2_bad, f"{len(on['combats']) + len(off['combats'])} combats, {len(d2_bad)} bad")
    for c in d2_bad[:3]:
        finding(f"D2 violated: {c}")

    # The differential: at the first combat the SAME seed plays the same cards, so
    # the ONLY difference the triangle may introduce is +4 power to the counterer.
    c_on = on["combats"][0] if on["combats"] else None
    c_off = off["combats"][0] if off["combats"] else None
    adv = c_on.get("advantage") if c_on else None

    if c_on is None or c_off is None:
        ok, detail = False, "no combats to compare"
    elif adv is None:
        # Refuse the neutral branch: it would pass without ever exercising the +4.
        ok = False
        detail = ("first combat is type-NEUTRAL — the +4 was never on the line; "
                  "no seed in the band produced a countered first combat")
    else:
        other = 1 - adv
        gained = c_on[f"power{adv}"] - c_off[f"power{adv}"]
        unchanged = c_on[f"power{other}"] == c_off[f"power{other}"]
        ok = gained == TYPE_ADVANTAGE_POWER and unchanged
        detail = (f"counterer=p{adv} power {c_off[f'power{adv}']}->{c_on[f'power{adv}']} "
                  f"(+{gained}, expected +{TYPE_ADVANTAGE_POWER}); "
                  f"p{other} power {c_off[f'power{other}']} unchanged={unchanged}; "
                  f"damage {c_off['damage']}->{c_on['damage']}")
    ck("D16 differential: on a COUNTERED first combat the triangle adds EXACTLY +4 "
       "power to the counterer and moves nothing else", ok, detail)
    if not ok:
        finding(f"D16 differential failed — ON={c_on} OFF={c_off}")

    # ── 7. DETERMINISM (two independent oracles) ─────────────────────────────
    print("\n  -- 7. determinism --")
    bad_replay = [label for label, r in corpus if not r["replayOk"]]
    ck("the harness's own `replay` op re-verifies EVERY match in the corpus",
       not bad_replay, f"{len(corpus)} matches, {len(bad_replay)} failed"
       + (f": {bad_replay}" if bad_replay else ""))
    for label in bad_replay:
        finding(f"harness replay did not verify for {label}")

    # UGT's own oracle: a fresh same-seed re-run reproduces the hash stream.
    rerun_cfg = make_config(base, decks=COMPETITIVE_DECKS, fmt="COMPETITIVE", waves=ALL_WAVES)
    a = drive(rerun_cfg, f"{seed}-det", COMMIT_WITH_TARGETS, suite)
    b = drive(rerun_cfg, f"{seed}-det", COMMIT_WITH_TARGETS, suite)
    div = first_divergence(a["stream"], b["stream"])
    ck("same-seed determinism: byte-identical stateHash stream across two fresh runs",
       div is None and len(a["stream"]) == len(b["stream"]),
       f"lenA={len(a['stream'])} lenB={len(b['stream'])} firstDiv={div}")
    ck("the determinism proof is NON-VACUOUS (a real match, not an init stub)",
       a["plies"] >= 8 and len(a["stream"]) > 1,
       f"plies={a['plies']} streamLen={len(a['stream'])}")

    # ── summary ──────────────────────────────────────────────────────────────
    total_plies = sum(r["plies"] for _, r in corpus)
    print(f"\n  -- corpus: {len(corpus)} matches, {total_plies} plies, "
          f"{len(all_committed)} distinct cards played --")

    return gate.finish(
        "ROUND 2",
        "UGT drove the FULL DDD content spine through the real engine: every wave "
        "configuration, both formats, all four decks (mirrors and crosses), every "
        "terminal arm the wire can reach, and every shipped card actually played. "
        "Graveyard targets fire over the wire (with a zero-firing control proving "
        "the check is not vacuous), the D16 triangle adds exactly +4 to the "
        "counterer and nothing else, D2 holds in every combat, the invariant sweep "
        "is clean on every step of every match, and both determinism oracles agree. "
        "Ready for Round 3.",
    )


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\ninterrupted")
        sys.exit(130)
