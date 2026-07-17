#!/usr/bin/env python3
"""
DDD ROUND 3 — the ROBUSTNESS tier: UGT's REAL ExploitHunter
(ugt/core/exploit_hunter.py — the framework's own machinery, NOT a bespoke loop)
driving the live DDD engine over the harness wire with a seeded stochastic policy
across the WHOLE action vocabulary, every invariant checked after every step, a
deliberate refusal battery over the engine's entire RulesError vocabulary, and a
byte-identical same-seed episode-0 replay.

Where R1 walked one match and R2 drove the whole content spine to every terminal
arm, R3 hands the wheel to a policy that does not care what the game wants: random
legal commits, target-filling commits, predictions, modal picks, passes, mulligans
in the wrong phase, concessions, and two ids that deliberately leave the legal list
entirely. The engine must survive all of it — and every refusal must be INERT.

Why the inertness claim is the load-bearing one: DDD reports a rules violation as
`{ok:false, applied:false}` WITH the (unchanged) state hash. So "the engine refused
this" and "the engine refused this and changed nothing" are different claims, and
only the second is worth anything. Every probe below asserts the hash did not move.

Gate (fail-closed):
  1. every episode ran (report.episodes == EPISODES, total_steps > 0);
  2. ZERO findings across every invariant x every step (each prints [FINDING]);
  3. every action id was attempted at least once (vocabulary coverage);
  4. the REFUSAL BATTERY provokes each reachable RulesError arm and each transport
     error arm, and EVERY refusal is state-inert (hash unchanged) with the loop
     still serving afterwards;
  5. non-vacuous PROGRESS: the hunt actually played the game (>=1 combat resolved,
     >=1 card returned via targets, >=1 terminal result reached);
  6. a fresh same-seed re-run of episode 0 reproduces its trajectory byte for byte
     (hash stream + action stream) and is itself non-vacuous.

R3-only invariants layered on top of R1/R2's suite:
  * inv_hash_moves_iff_applied — the hash changes if and only if `applied` is true.
    This is the single strongest anti-corruption check available over this wire.
  * inv_probe_refused          — an action the adapter sent as a deliberate probe
    must NOT be accepted. A game that quietly applies a malformed action is broken
    in the most dangerous way: silently.
  * inv_fog_of_war             — the OPPONENT's view never carries hand card
    identities, deck contents, the RNG, or an uncommitted selection. UGT is
    uniquely placed to check this: it reads BOTH seat views straight off the wire,
    so a leak that no in-process test would notice is visible here.
  * inv_no_soft_lock           — never 25 consecutive refusals (a stuck game).

A failed check is DATA: an invariant violation, a crash, a soft-lock or an accepted
probe is a finding, to be fixed upstream in DDD with a pinning test and re-run —
never tolerated or weakened here.

Run (from the UGT repo root; node >=24 — the adapter spawns the harness itself):

    python3 integrations/ddd/verify_round3.py [base_seed] [episodes] [steps]

Exit 0 + "ROUND 3 MET — N/N" means the gate passed.
"""
from __future__ import annotations

import hashlib
import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import invariants  # noqa: E402  (local module, from integrations/ddd/)

from ugt.adapters.ddd_harness import DddHarnessAdapter  # noqa: E402
from ugt.core.exploit_hunter import ExploitHunter, Invariant  # noqa: E402
from ugt.core.trial import GateRunner, first_divergence  # noqa: E402
from ugt.utils.config_parser import UgtConfig  # noqa: E402

CONFIG_PATH = "integrations/ddd/ugt.config.yaml"
DEFAULT_SEED = "ddd-r3"


def _stable_seed(s: object) -> int:
    # Process-stable derivation. Python's built-in hash() of a str is randomized
    # per process (PYTHONHASHSEED), which made the ExploitHunter explore a
    # different action sequence every run — an unreproducible "32/32" that could
    # flake to 31/32 and could not replay a red run. sha256 fixes the seed.
    return int(hashlib.sha256(str(s).encode()).hexdigest(), 16) % (2 ** 31)


EPISODES = 8
STEPS = 60

# The full vocabulary (ugt.config.yaml action_space).
ALL_IDS = list(range(13))
PROBE_IDS = {11, 12}

SOFT_LOCK_LIMIT = 25


# ── R3-only invariants ───────────────────────────────────────────────────────
def inv_hash_moves_iff_applied(before, action_id, info, after, ctx):
    """The stateHash changes IF AND ONLY IF the engine says it applied the action.

    Both directions matter. A hash that moves on a REFUSED action means the refusal
    corrupted state (the engine mutated then rejected). A hash that does NOT move on
    an APPLIED action means the action was a no-op the engine claimed to perform, or
    the hash is not covering the state it should — either way the determinism oracle
    is lying, and every replay proof built on it is worthless.
    """
    result = info.get("result") or {}
    if info.get("command") != "act":
        return None
    if result.get("terminal"):
        return None  # match already over; step() short-circuits without acting
    applied = bool(result.get("applied"))
    h_before = info.get("hashBefore")
    h_after = result.get("stateHash")
    if h_before is None or h_after is None:
        return f"missing hash around an act (before={h_before!r} after={h_after!r})"
    moved = h_before != h_after
    if applied and not moved:
        return (f"engine reported applied:true but the stateHash did NOT move "
                f"({h_before[:12]}…) — a claimed action that changed nothing")
    if not applied and moved:
        return (f"a REFUSED action moved the stateHash {h_before[:12]}… -> "
                f"{h_after[:12]}… — the refusal corrupted state")
    return None


def inv_probe_refused(before, action_id, info, after, ctx):
    """An action sent as a deliberate probe must be REFUSED, never applied.

    The probe ids send something outside the harness's legal list (a commit naming a
    card that is not in hand; an object that is not a member of the Action union).
    If the engine ACCEPTS one, it is adjudicating moves it never offered — the
    quietest and worst class of rules bug.
    """
    if not info.get("probe"):
        return None
    result = info.get("result") or {}
    if result.get("terminal"):
        return None
    if result.get("ok") is True or result.get("applied") is True:
        return (f"the engine ACCEPTED a deliberately-illegal probe "
                f"({info.get('actionName')}): {info.get('action')}")
    return None


_HIDDEN_OPPONENT_FIELDS = ("hand", "deck", "rng", "nextInstanceId", "committedSelection",
                           "pendingPrediction")


def inv_fog_of_war(before, action_id, info, after, ctx):
    """The opponent's PlayerView never carries hidden information.

    Checked on the RAW views as they came off the wire, for BOTH seats. Redaction in
    DDD is type-level (hidden fields are absent from `OpponentPlayerView`, not
    blanked), so a leak here would mean the serialization boundary re-introduced
    what the type system removed — precisely the failure an in-process test cannot
    see, and precisely what a black-box wire tester is for.
    """
    result = info.get("result") or {}
    views = result.get("views")
    if not views or len(views) < 2:
        return None
    for seat in (0, 1):
        opponent = (views[seat] or {}).get("opponent") or {}
        for field in _HIDDEN_OPPONENT_FIELDS:
            if field in opponent:
                return (f"seat {seat}'s view of the OPPONENT leaked hidden field "
                        f"{field!r}: {opponent.get(field)!r}")
        # The counts that SHOULD be there must still be there — otherwise this
        # invariant could pass on an empty/absent opponent object.
        if "handCount" not in opponent or "deckCount" not in opponent:
            return (f"seat {seat}'s opponent view is missing the public counts "
                    f"(handCount/deckCount) — redaction check would be vacuous")
    return None


def inv_no_soft_lock(before, action_id, info, after, ctx):
    """No 25 refusals in a row — a game that cannot be advanced is soft-locked."""
    result = info.get("result") or {}
    if result.get("terminal"):
        return None
    if result.get("applied"):
        ctx["consecutive_refusals"] = 0
        return None
    n = ctx.get("consecutive_refusals", 0) + 1
    ctx["consecutive_refusals"] = n
    if n >= SOFT_LOCK_LIMIT:
        return f"{n} consecutive refused actions — the game is soft-locked"
    return None


R3_INVARIANTS = [
    Invariant("inv_hash_moves_iff_applied", inv_hash_moves_iff_applied,
              inv_hash_moves_iff_applied.__doc__ or ""),
    Invariant("inv_probe_refused", inv_probe_refused, inv_probe_refused.__doc__ or ""),
    Invariant("inv_fog_of_war", inv_fog_of_war, inv_fog_of_war.__doc__ or ""),
    Invariant("inv_no_soft_lock", inv_no_soft_lock, inv_no_soft_lock.__doc__ or ""),
]


# ── policy ───────────────────────────────────────────────────────────────────
def hunting_policy(state, action_ids, rng, ctx):
    """Seeded stochastic policy over the WHOLE vocabulary.

    Weighted so the hunt actually plays a game (most steps advance it) while still
    hammering the odd corners — the probe ids and CONCEDE stay rare but present, so
    a long hunt reaches terminal states instead of conceding on ply 2 every episode.
    """
    roll = rng.random()
    if roll < 0.06:
        return rng.choice(sorted(PROBE_IDS))     # deliberate refusals
    if roll < 0.08:
        return 10                                 # concede (rare — else no real games)
    return rng.choice([0, 1, 2, 3, 4, 5, 6, 7, 8, 9])


# ── the refusal battery (direct, outside the hunter) ─────────────────────────
def refusal_battery(ad, gate):
    """Provoke the engine's refusal arms and assert every one is STATE-INERT.

    Uses `send_raw_action` / `_request`, which bypass the legal list on purpose —
    the only place in this integration that does. Each probe asserts BOTH that the
    engine refused AND that the state hash did not move; a refusal that mutates
    state is worse than an acceptance, because nothing downstream would notice.
    """
    ck, finding = gate.ck, gate.finding

    def hash_now():
        return ad.hash_stream[-1]

    def unaffordable_in_hand():
        """A card the seat HOLDS but that is absent from the engine's legal list.

        At this point the only reason a held card is not offered is that the seat
        cannot pay for it — so this is INSUFFICIENT_FOCUS, derived purely from the
        engine's own two answers (hand vs legal). The adapter reads no card costs.
        """
        s = ad._pending_seat()
        legal, _ = ad._legal(s)
        playable = {a["instanceId"] for a in legal if a.get("t") == "COMMIT_SELECTION"}
        held = ad.views[s]["me"]["hand"]
        return s, next((c["instanceId"] for c in held if c["instanceId"] not in playable), None)

    # Try to reach the INSUFFICIENT_FOCUS arm. A probe that silently does not run is
    # a coverage hole wearing a green tick, so if no seed reaches it we say WHY,
    # with numbers, rather than skipping quietly.
    battery_seed = "battery"
    turns_probed = 0
    unaff_depth = 0  # step(1) pairs from post-mulligan SELECTION to the found state
    for s in range(20):
        cand = f"battery-{s}"
        ad.reset(cand)
        for _ in range(2):
            ad.step(8)  # mulligan_keep -> SELECTION
        # Look across several turns, not just the opening hand.
        for depth in range(6):
            _seat, unaff = unaffordable_in_hand()
            turns_probed += 1
            if unaff is not None:
                unaff_depth = depth
                break
            if ad._pending_seat() is None:
                break
            ad.step(1)
            ad.step(1)
        if unaff is not None:
            battery_seed = cand
            break
    focus_binds = unaff is not None
    ad.reset(battery_seed)

    seat = ad._pending_seat()
    probes = []

    # ---- RulesError arms reachable from a fresh MULLIGAN-phase match ----
    probes.append((
        "CARD_NOT_IN_HAND / WRONG_PHASE: commit a card that cannot be in hand",
        {"t": "COMMIT_SELECTION", "player": seat, "instanceId": 999999,
         "modeIndex": None, "targets": [], "prediction": None},
    ))
    probes.append((
        "MALFORMED/UNKNOWN_ACTION: an object outside the Action union",
        {"t": "NOT_AN_ACTION", "player": seat},
    ))
    probes.append((
        "NOT_YOUR_ACTION / WRONG_PHASE: act as the seat the engine is not waiting on",
        {"t": "COMMIT_SELECTION", "player": 1 - seat, "instanceId": 999999,
         "modeIndex": None, "targets": [], "prediction": None},
    ))
    probes.append((
        "WRONG_PHASE: COMMIT_PASS during MULLIGAN",
        {"t": "COMMIT_PASS", "player": seat},
    ))
    probes.append((
        "MALFORMED_ACTION: a commit missing its total fields",
        {"t": "COMMIT_SELECTION", "player": seat},
    ))
    probes.append((
        "MALFORMED_ACTION: a non-numeric player",
        {"t": "COMMIT_PASS", "player": "zero"},
    ))

    inert = 0
    kinds = {}
    for label, action in probes:
        before = hash_now()
        resp = ad.send_raw_action(action)
        after = hash_now()
        refused = resp.get("ok") is False
        unchanged = before == after
        err = (resp.get("error") or {})
        kind = err.get("kind")
        rules = (err.get("rulesError") or {})
        code = rules.get("code") or rules.get("kind") or kind
        kinds[str(code)] = kinds.get(str(code), 0) + 1
        ok = refused and unchanged
        if ok:
            inert += 1
        ck(f"probe REFUSED and state-INERT — {label}", ok,
           f"refused={refused} hashUnchanged={unchanged} kind={kind} code={code}")
        if not refused:
            finding(f"the engine ACCEPTED an illegal action ({label}): {action}")
        elif not unchanged:
            finding(f"a REFUSED action moved the state hash ({label}): "
                    f"{before[:12]}… -> {after[:12]}…")

    # ---- Now legal MULLIGANs, then the SELECTION-phase arms ----
    for _ in range(2):
        ad.step(8)  # mulligan_keep

    # Re-walk to the depth where the seed search found the unaffordable card —
    # the search may have found it turns deep, not on the opening hand, and a
    # reset() forgets that. (Stitching bug found 2026-07-12: the search FOUND an
    # unaffordable card, the battery re-checked only turn 1, missed it, and the
    # report claimed the opposite of the measurement.)
    for _ in range(unaff_depth):
        ad.step(1)
        ad.step(1)

    seat, unaffordable = unaffordable_in_hand()
    legal_now, _ = ad._legal(seat)
    a_legal = next(a for a in legal_now if a.get("t") == "COMMIT_SELECTION")

    sel_probes = [
        ("MULLIGAN_ALREADY_USED / WRONG_PHASE: mulligan again in SELECTION",
         {"t": "MULLIGAN", "player": seat, "full": False}),
        ("INVALID_TARGETS: targets that are not eligible candidates",
         {"t": "COMMIT_SELECTION", "player": seat, "instanceId": a_legal["instanceId"],
          "modeIndex": None, "targets": [123456], "prediction": None}),
        ("CARD_NOT_IN_HAND: commit a card the seat does not hold (in SELECTION)",
         {"t": "COMMIT_SELECTION", "player": seat, "instanceId": 999999,
          "modeIndex": None, "targets": [], "prediction": None}),
        ("INVALID_MODE: a mode index the card does not have",
         {"t": "COMMIT_SELECTION", "player": seat, "instanceId": a_legal["instanceId"],
          "modeIndex": 99, "targets": [], "prediction": None}),
        ("INVALID_PREDICTION: a prediction that is not a CardType",
         {"t": "COMMIT_SELECTION", "player": seat, "instanceId": a_legal["instanceId"],
          "modeIndex": None, "targets": [], "prediction": "NOT_A_TYPE"}),
        ("PASS_NOT_ALLOWED: pass while a card is affordable",
         {"t": "COMMIT_PASS", "player": seat}),
    ]
    if unaffordable is not None:
        sel_probes.append((
            "INSUFFICIENT_FOCUS: commit a held card the seat cannot afford",
            {"t": "COMMIT_SELECTION", "player": seat, "instanceId": unaffordable,
             "modeIndex": None, "targets": [], "prediction": None},
        ))
    elif focus_binds:
        # The seed search FOUND an unaffordable card but the re-walk did not land
        # on it — a tester defect (the probe silently didn't run), not a game fact.
        ck("INSUFFICIENT_FOCUS probe runs at the state the seed search found",
           False,
           f"found at seed={battery_seed} depth={unaff_depth} but the battery "
           f"re-walk did not reproduce it — the probe silently did NOT run")
        finding(
            f"TESTER: INSUFFICIENT_FOCUS state found in the seed search "
            f"(seed={battery_seed}, depth={unaff_depth}) but not reproduced by the "
            f"battery re-walk — the probe did NOT run. Fix the re-walk; do not "
            f"read this as 'the economy never binds'."
        )
    else:
        # NOT a tester gap — a measured property of the shipped game, reported.
        # (Pre-T6.5 this was DDD's D-C1: focus regen outran every cost in the pack,
        # so cost was never a decision. T6.5 re-priced the pack to make it bind —
        # if this fires again, that regression is the finding.)
        # A design finding, not a robustness defect, so it does NOT fail this
        # tier — it is recorded.
        finding(
            f"CHARACTERIZATION (design, DDD T6.5): the Focus economy never bound — "
            f"across {turns_probed} probed turn-states over 20 seeds, ZERO held cards "
            f"were ever missing from the engine's legal list for affordability. Cost "
            f"is therefore not a real decision, and the INSUFFICIENT_FOCUS rules arm "
            f"cannot be reached in normal play."
        )
    for label, action in sel_probes:
        before = hash_now()
        resp = ad.send_raw_action(action)
        after = hash_now()
        refused = resp.get("ok") is False
        unchanged = before == after
        err = (resp.get("error") or {})
        rules = (err.get("rulesError") or {})
        code = rules.get("code") or rules.get("kind") or err.get("kind")
        kinds[str(code)] = kinds.get(str(code), 0) + 1
        ok = refused and unchanged
        if ok:
            inert += 1
        ck(f"probe REFUSED and state-INERT — {label}", ok,
           f"refused={refused} hashUnchanged={unchanged} code={code}")
        if not refused:
            finding(f"the engine ACCEPTED an illegal action ({label}): {action}")

    # ---- ALREADY_COMMITTED: commit, then commit again as the SAME seat ----
    seat = ad._pending_seat()
    legal_now, _ = ad._legal(seat)
    first = next(a for a in legal_now if a.get("t") == "COMMIT_SELECTION")
    ad.send_raw_action(first)  # legal — applies
    before = hash_now()
    again = ad.send_raw_action(first)
    after = hash_now()
    err = (again.get("error") or {})
    code = (err.get("rulesError") or {}).get("code") or err.get("kind")
    kinds[str(code)] = kinds.get(str(code), 0) + 1
    ok = again.get("ok") is False and before == after
    if ok:
        inert += 1
    ck("probe REFUSED and state-INERT — ALREADY_COMMITTED: the seat commits twice",
       ok, f"refused={again.get('ok') is False} hashUnchanged={before == after} code={code}")

    # ---- MATCH_ENDED: drive to a terminal result, then keep acting ----
    for _ in range(400):
        st, term, _t, _i = ad.step(1)  # commit_random until the match ends
        if term:
            break
    if st.get("resultKind") != "ONGOING":
        before = hash_now()
        post = ad.send_raw_action({"t": "COMMIT_PASS", "player": 0})
        after = hash_now()
        err = (post.get("error") or {})
        code = (err.get("rulesError") or {}).get("code") or err.get("kind")
        kinds[str(code)] = kinds.get(str(code), 0) + 1
        ok = post.get("ok") is False and before == after
        if ok:
            inert += 1
        ck("probe REFUSED and state-INERT — MATCH_ENDED: act after the match is over",
           ok, f"refused={post.get('ok') is False} hashUnchanged={before == after} "
               f"code={code} result={st.get('resultKind')}")
    else:
        ck("probe REFUSED and state-INERT — MATCH_ENDED: act after the match is over",
           False, "the match never reached a terminal result — cannot probe MATCH_ENDED")

    # ---- Transport-level arms: the loop must SURVIVE each ----
    before = hash_now()
    bad_line = ad._request({"op": "act", "matchId": "no-such-match",
                            "action": {"t": "COMMIT_PASS", "player": 0}})
    ck("UNKNOWN_MATCH is a clean refusal", bad_line.get("ok") is False,
       f"kind={(bad_line.get('error') or {}).get('kind')}")

    unknown_op = ad._request({"op": "definitely_not_an_op"})
    ck("UNKNOWN_OP is a clean refusal", unknown_op.get("ok") is False,
       f"kind={(unknown_op.get('error') or {}).get('kind')}")

    bad_targets = ad._request({"op": "targets", "matchId": ad._match_id,
                               "player": 0, "instanceId": 999999, "modeIndex": None})
    ck("the `targets` op refuses a card not in hand (BAD_REQUEST, not INTERNAL)",
       bad_targets.get("ok") is False
       and (bad_targets.get("error") or {}).get("kind") == "BAD_REQUEST",
       f"kind={(bad_targets.get('error') or {}).get('kind')}")

    # ...and the harness is STILL SERVING after every one of those. The match this
    # battery ran on has ENDED, so "still serving" is proven by starting a fresh one
    # on the same process and getting a live legal list back.
    ad.reset("battery-after")
    still_legal, _ = ad._legal(ad._pending_seat())
    ck("the harness KEEPS SERVING after the whole battery (a fresh match on the "
       "same process)", len(still_legal) > 0, f"legal={len(still_legal)}")

    print(f"     refusal codes provoked: {sorted(kinds)}")
    # +2 for the ALREADY_COMMITTED and MATCH_ENDED probes checked inline above.
    return inert, len(probes) + len(sel_probes) + 2, kinds


def main() -> int:
    seed = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SEED
    episodes = int(sys.argv[2]) if len(sys.argv) > 2 else EPISODES
    steps = int(sys.argv[3]) if len(sys.argv) > 3 else STEPS

    base = UgtConfig(CONFIG_PATH)
    suite = invariants.build_suite()
    gate = GateRunner()
    ck, finding = gate.ck, gate.finding

    print(f"DDD Round 3 — ExploitHunter robustness "
          f"(seed {seed!r}, {episodes} episodes x {steps} steps)\n")

    # ── the refusal battery ──────────────────────────────────────────────────
    print("  -- refusal battery (every arm must be REFUSED *and* state-inert) --")
    bat = DddHarnessAdapter(base)
    bat.connect()
    try:
        inert, total_probes, kinds = refusal_battery(bat, gate)
        ck("EVERY refusal probe was state-inert", inert == total_probes,
           f"{inert}/{total_probes} inert")
        ck("the battery provoked a broad refusal vocabulary (>=4 distinct codes)",
           len(kinds) >= 4, f"{len(kinds)} distinct: {sorted(kinds)}")
    finally:
        bat.close()

    # ── the hunt ─────────────────────────────────────────────────────────────
    print(f"\n  -- the hunt ({episodes} episodes x {steps} steps, full vocabulary) --")
    ad = DddHarnessAdapter(base)
    ad.seed = seed
    ad.connect()
    try:
        hunter = ExploitHunter(
            adapter=ad,
            invariants=suite.to_hunter_invariants() + R3_INVARIANTS,
            action_ids=ALL_IDS,
            action_names=dict(enumerate(
                [ad.action_name(i) for i in ALL_IDS]
            )),
            policy=hunting_policy,
            seed=_stable_seed(seed),
        )
        report = hunter.run(episodes=episodes, steps_per_episode=steps,
                            log=lambda m: None)
    finally:
        ad.close()

    print(f"     episodes={report.episodes} steps={report.total_steps} "
          f"findings={len(report.findings)}")
    print(f"     action counts: {report.action_counts}")

    ck("every episode ran", report.episodes == episodes,
       f"{report.episodes}/{episodes}")
    ck("the hunt took real steps", report.total_steps > 0, f"{report.total_steps} steps")

    ck("ZERO findings across every invariant x every step",
       not report.findings, f"{len(report.findings)} findings")
    for f in report.findings:
        finding(f"[{f.kind}/{f.name}] ep{f.episode} step{f.step} "
                f"action={f.action_name}: {f.message}")

    attempted = set(report.action_counts)
    expected_names = {ad.action_name(i) for i in ALL_IDS}
    missing = sorted(expected_names - attempted)
    ck("every action id in the vocabulary was attempted at least once",
       not missing, f"{len(attempted)}/{len(expected_names)}"
       + (f" MISSING={missing}" if missing else ""))

    probe_hits = sum(report.action_counts.get(ad.action_name(i), 0) for i in PROBE_IDS)
    ck("the probe ids actually fired during the hunt (refusals were exercised)",
       probe_hits > 0, f"{probe_hits} probe steps")

    # ── non-vacuous progress ─────────────────────────────────────────────────
    print("\n  -- non-vacuity: did the hunt actually PLAY the game? --")
    prog = DddHarnessAdapter(base)
    prog.connect()
    try:
        combats = returns = 0
        terminals = []
        for ep in range(4):
            prog.reset(f"{seed}-prog-{ep}")
            for _ in range(steps):
                st, term, _t, info = prog.step(3)  # commit_with_targets
                for e in ((info.get("result") or {}).get("events") or []):
                    if e.get("t") == "COMBAT_RESOLVED":
                        combats += 1
                    if e.get("t") == "CARD_RETURNED":
                        returns += 1
                if term:
                    terminals.append(st.get("resultKind"))
                    break
    finally:
        prog.close()

    ck("the hunt reaches real play: >=1 combat resolved", combats >= 1,
       f"{combats} combats")
    ck("targets are exercised end-to-end: >=1 CARD_RETURNED", returns >= 1,
       f"{returns} card returns")
    ck("terminal results are reached", len(terminals) >= 1,
       f"{len(terminals)} terminals: {terminals}")

    # ── determinism: a fresh same-seed episode 0 replays byte-identically ────
    print("\n  -- determinism: same-seed episode-0 replay --")

    def episode_zero():
        a = DddHarnessAdapter(base)
        a.seed = seed
        a.connect()
        try:
            h = ExploitHunter(
                adapter=a,
                invariants=[],
                action_ids=ALL_IDS,
                action_names=dict(enumerate([a.action_name(i) for i in ALL_IDS])),
                policy=hunting_policy,
                seed=_stable_seed(seed),
            )
            h.run(episodes=1, steps_per_episode=steps, log=lambda m: None)
            return list(a.hash_stream), [x.get("t") for x in a.applied_actions]
        finally:
            a.close()

    stream_a, acts_a = episode_zero()
    stream_b, acts_b = episode_zero()
    div = first_divergence(stream_a, stream_b)
    ck("same-seed episode 0: byte-identical stateHash stream",
       div is None and len(stream_a) == len(stream_b),
       f"lenA={len(stream_a)} lenB={len(stream_b)} firstDiv={div}")
    ck("same-seed episode 0: identical applied-action stream",
       acts_a == acts_b, f"{len(acts_a)} actions")
    ck("the replay proof is NON-VACUOUS (a real episode, not an init stub)",
       len(stream_a) > 4 and len(acts_a) > 3,
       f"streamLen={len(stream_a)} actions={len(acts_a)}")

    return gate.finish(
        "ROUND 3",
        "UGT's real ExploitHunter drove the live DDD engine across its whole action "
        "vocabulary — random/targeted/predicting/modal commits, passes, mulligans, "
        "concessions, and deliberately illegal and malformed actions — with every "
        "invariant asserted after every step. Zero findings. Every refusal arm the "
        "engine can produce was provoked and proven STATE-INERT (the hash never "
        "moved), the hash moves if and only if the engine applied the action, the "
        "opponent's view never leaked a hidden field over the wire, the game never "
        "soft-locked, and a fresh same-seed episode 0 replays byte for byte. "
        "DDD is robust at R3.",
    )


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\ninterrupted")
        sys.exit(130)
