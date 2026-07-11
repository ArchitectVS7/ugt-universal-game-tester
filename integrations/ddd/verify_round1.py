#!/usr/bin/env python3
"""
DDD ROUND 1 — one full match through the REAL engine (via the harness adapter) +
same-seed determinism + a per-command invariant sweep after EVERY action.

Drives the live DDD engine THROUGH `DddHarnessAdapter` (the subprocess harness),
never a re-implementation. R1 plays a whole match to a terminal result under a
fixed `commit_random` policy (id 1) — the adapter walks the MULLIGAN step then
each SELECTION step for whichever seat the engine is waiting on, choosing a random
LEGAL commit each time and NEVER conceding — and asserts, per plan §4:

  * the match reaches a terminal result (WIN/DRAW) within the ply cap,
  * the DDD invariant suite (integrations/ddd/invariants.py) finds ZERO violations
    across EVERY step of BOTH runs (HP/focus bounds, hand cap, EXACT 40-card
    conservation per seat, turn monotonic, no RULES_ERROR on a self-selected legal
    action, ≥1 legal action while ONGOING),
  * explicit end-state card conservation == 40 for each seat,
  * no RULES_ERROR fired on any action the adapter sent,
  * same-seed determinism: two runs on the same seed produce byte-identical
    stateHash streams (first_divergence None + equal length) — and NON-VACUOUS
    (the match ran a real number of plies, not just the initial hash),
  * the harness's own replay op re-verifies the recorded log (verified:true,
    divergedAtTurn:null).

No game logic is reimplemented; every fact is read back from the harness views.
A failed check is DATA — it prints as a FINDING and fails the gate, to be fixed
upstream in DDD (with a pinning test), never tolerated here.

Run (from the UGT repo root; node >=24, DDD deps installed):
    python3 integrations/ddd/verify_round1.py [seed]

Exit 0 + "ROUND 1 MET — N/N" means the gate passed.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import invariants  # noqa: E402  (local module, from integrations/ddd/)

from ugt.adapters.ddd_harness import DddHarnessAdapter  # noqa: E402
from ugt.core.trial import GateRunner, first_divergence  # noqa: E402
from ugt.utils.config_parser import UgtConfig  # noqa: E402

CONFIG_PATH = "integrations/ddd/ugt.config.yaml"
DEFAULT_SEED = "ddd-r1"
POLICY_ID = 1  # commit_random — a full random-but-seeded match driver
MIN_PLIES = 8  # non-vacuity floor: a real match, not a one-step stub


def run_episode(ad, seed, ply_cap, suite):
    """Drive one full match under the commit_random policy on a fresh reset.

    Returns a dict: stream (stateHash list), records (per-step), final (state),
    terminated (bool), plies (int), violations (list[str])."""
    state = ad.reset(seed)
    records = []
    violations = []
    terminated = False
    while len(records) < ply_cap:
        before = state
        after, term, _trunc, info = ad.step(POLICY_ID)
        result = info["result"]  # raw harness resp, already carries legalCount
        v = suite.check_command(before, after, "act", result)
        for msg in v:
            violations.append(f"ply {len(records)} {info.get('action')}: {msg}")
        records.append({"before": before, "after": after, "info": info})
        state = after
        if term:
            terminated = True
            break
    return {
        "stream": list(ad.hash_stream),
        "records": records,
        "final": state,
        "terminated": terminated,
        "plies": len(records),
        "violations": violations,
    }


def main() -> int:
    seed = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SEED
    cfg = UgtConfig(CONFIG_PATH)
    ad = DddHarnessAdapter(cfg)
    ply_cap = ad.max_turns * 4
    suite = invariants.build_suite()
    gate = GateRunner()
    ck, finding = gate.ck, gate.finding

    print(f"DDD Round 1 — one full match + determinism (seed {seed!r}, cap {ply_cap} plies)\n")
    try:
        ad.connect()
        ck("connect() spawns a live harness process",
           ad.process is not None and ad.process.poll() is None,
           f"pid={ad.process.pid if ad.process else None}")

        # ── RUN 1 (primary) ──────────────────────────────────────────────────
        print("\n  -- run 1 (primary match) --")
        r1 = run_episode(ad, seed, ply_cap, suite)
        final = r1["final"]
        result = final.get("result") or {}

        ck("match reaches a terminal result within the ply cap",
           r1["terminated"] and final.get("resultKind") in ("WIN", "DRAW"),
           f"terminated={r1['terminated']} kind={final.get('resultKind')} "
           f"plies={r1['plies']} turn={final.get('turn')}")

        ck("run 1: per-command invariant sweep is CLEAN (zero violations)",
           not r1["violations"],
           "0 violations" if not r1["violations"] else f"{len(r1['violations'])} violations")
        for v in r1["violations"]:
            finding(f"[run1] invariant violation — {v}")

        # explicit end-state conservation
        cons_ok = True
        cons_detail = []
        for seat in ("p0", "p1"):
            s = final.get(seat, {})
            total = (s.get("handCount", 0) + s.get("deckCount", 0)
                     + s.get("graveyardCount", 0) + s.get("committedCard", 0))
            cons_ok = cons_ok and (total == invariants.DECK_TOTAL)
            cons_detail.append(f"{seat}={total}")
        ck("end-state card conservation == 40 for each seat", cons_ok,
           " ".join(cons_detail))
        if not cons_ok:
            finding(f"end-state card conservation != 40: {' '.join(cons_detail)}")

        # no RULES_ERROR on any self-selected legal action
        rules_errs = [rec for rec in r1["records"]
                      if rec["info"]["result"].get("ok") is False]
        ck("no RULES_ERROR on any action the adapter sent (all self-selected legal)",
           not rules_errs,
           "0 rules-errors" if not rules_errs else f"{len(rules_errs)} rules-errors")
        for rec in rules_errs:
            finding(f"RULES_ERROR on adapter action {rec['info'].get('action')}: "
                    f"{rec['info']['result'].get('error')}")

        # legal_nonempty_while_ongoing every step
        empty_legal = [rec for rec in r1["records"]
                       if rec["after"].get("resultKind") == "ONGOING"
                       and rec["info"]["result"].get("legalCount", 0) < 1]
        ck("every ONGOING step had >=1 legal action (no soft-lock)",
           not empty_legal,
           "all steps had legal moves" if not empty_legal
           else f"{len(empty_legal)} zero-legal ONGOING steps")

        # ── RUN 2 (determinism) ──────────────────────────────────────────────
        print("\n  -- run 2 (same-seed determinism) --")
        r2 = run_episode(ad, seed, ply_cap, suite)

        ck("run 2: per-command invariant sweep is CLEAN (zero violations)",
           not r2["violations"],
           "0 violations" if not r2["violations"] else f"{len(r2['violations'])} violations")
        for v in r2["violations"]:
            finding(f"[run2] invariant violation — {v}")

        streamA, streamB = r1["stream"], r2["stream"]
        div = first_divergence(streamA, streamB)
        same_seed_ok = len(streamA) == len(streamB) and div is None
        ck("same-seed determinism: byte-identical stateHash stream",
           same_seed_ok,
           f"lenA={len(streamA)} lenB={len(streamB)} firstDiv={div}")
        if not same_seed_ok:
            finding("same-seed replay diverged — an unseeded RNG call site remains "
                    "in the engine/harness")

        ck("determinism proof is NON-VACUOUS (real match: >=MIN plies, stream > init)",
           r1["plies"] >= MIN_PLIES and len(streamA) > 1,
           f"plies={r1['plies']} (>= {MIN_PLIES}) streamLen={len(streamA)}")

        # ── harness self-replay of the last driven match ─────────────────────
        print("\n  -- harness replay --")
        rep = ad.replay_current()
        ck("harness replay re-verifies the recorded log (verified:true, divergedAtTurn:null)",
           rep.get("ok") is True and rep.get("verified") is True
           and rep.get("divergedAtTurn") is None,
           f"verified={rep.get('verified')} divergedAtTurn={rep.get('divergedAtTurn')}")
        if rep.get("verified") is not True:
            finding(f"harness replay failed to verify: {rep!r}")

        # ── match summary ────────────────────────────────────────────────────
        print("\n  -- match summary --")
        ck("summary: terminal, single decisive/draw outcome recorded",
           final.get("resultKind") in ("WIN", "DRAW"),
           f"turns={final.get('turn')} kind={result.get('kind')} "
           f"via={result.get('via')} winner={result.get('winner')} plies={r1['plies']}")

    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        ck("exception-free run", False, f"{type(exc).__name__}: {exc}")
    finally:
        ad.close()

    return gate.finish(
        "ROUND 1",
        "UGT drove a full DDD match to a terminal result through the real engine "
        "harness, every invariant held on every step of both runs (exact 40-card "
        "conservation, HP/focus bounds, no illegal-move adjudication), the run "
        "replays byte-identically on the same seed, and the harness self-replay "
        "re-verifies the log. Ready for Round 2.")


if __name__ == "__main__":
    sys.exit(main())
