#!/usr/bin/env python3
"""
NEXUS ROUND 2 — the FULL 8-mission story spine driven to a REAL win through the
adapter, across all three difficulty modes, under a per-command invariant sweep +
multi-mission same-seed determinism.

Drives the live nexus-world-builder Next.js server (apps/game, `next dev` on
:3100) THROUGH `NexusHttpAdapter` — never a re-implementation. Where R1 walked
the first mission slice, R2 walks the WHOLE spine end-to-end over HTTP and asserts
the game actually reaches its win condition:

    reset(post_tutorial) ->
      M1 the_breadcrumb        (connect + exploit + cat work_vpn)
      M2 following_the_money    (+ cat .insurance -> found_insurance_file)
      M3 project_meridian       (privilege_escalation; delivers sp3ctr3 -> met_sp3ctr3)
      M4 dead_drop
      M5 into_the_syndicate     (crack the gateway, exploit the research host;
                                 delivers AXIOM -> met_axiom)
      M6 the_other              (cat null_origin -> foundation_aware; talk sp3ctr3)
      M7 the_architect          (cat cross_testimony -> met_elena_cross; talk e.cross)
      M8 point_of_no_return     (choose liberation -> Act 3)
    -> gameStatus.isComplete, ending "ending_liberation", 8/8 story missions.

and asserts (~35-40 checks):
  * the full spine reaches isComplete + ending_liberation + 8/8 under NORMAL,
    TUTORIAL and HARDCORE (win reachable under each; hardcore ~30% hack odds, so
    the retry-to-success loop earns its keep — a seed probe picks a winning seed),
  * per mission: status completed, reward flags present, credits delta == the
    mission's core-story.json reward, and the xp residual (xp delta minus summed
    command xpGain) == the mission's reward xp,
  * rewards land EXACTLY once (re-accepting a completed mission is refused AND
    game-state inert — the double-reward probe),
  * `invariants.check_command` finds ZERO violations across EVERY command of EVERY
    mode (failed-hack retries are success:false and must be state-inert),
  * XP scaling: the first `cat work_vpn.txt` (base xpGain 5) returns round(5*mult)
    == tutorial 4 / normal 5 / hardcore 8; while mission-reward xp AND credits are
    mode-INVARIANT (the +250 / +1000 residual constant across all three modes),
  * same-seed determinism over a NON-VACUOUS multi-mission prefix (M1-M4): two
    runs -> identical command sequence, CommandResult stream, rngCounter
    progression and normalized final player-state; non-vacuous because the
    transcript carries a "[Success Rate:" roll AND the seeded sp3ctr3 delivery
    (met_sp3ctr3) fired inside the prefix.

No game logic is reimplemented; every effect is read back from player-state. A
failed check is DATA — it prints as a FINDING and fails the gate, to be fixed
upstream in the game (with a pinning test). This round surfaced NX-R2-1 (the
`talk` verb could never unlock: its AND-gate required the ungrantable
`met_mercury`) and NX-R2-2 (`talk` refused with AI disabled, so `contact_npc`
could never fire over the real command surface) — both fixed on nexus `main`;
verify_round2 NEVER skips the talk legs.

Run (server up on :3100 — verify the LISTEN pid is yours:
lsof -nP -iTCP:3100 -sTCP:LISTEN):

    python3 integrations/nexus/verify_round2.py [seed]

Exit 0 + "ROUND 2 MET — N/N" means the gate passed.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import invariants  # noqa: E402  (local module, from integrations/nexus/)

from ugt.adapters.nexus_http import NexusHttpAdapter  # noqa: E402
from ugt.core.trial import GateRunner, first_divergence  # noqa: E402
from ugt.utils.config_parser import UgtConfig  # noqa: E402

CONFIG_PATH = "integrations/nexus/ugt.config.yaml"
DEFAULT_SEED = "nexus-r2-seed"

# A failed hack (success:false) is retried; the roll re-rolls on the next
# rngCounter position, so retries converge to success. ~15 is generous even at
# hardcore's ~30% base odds (P(fail 15x) < 0.5%).
RETRY_CAP = 15

# The first cat's base xpGain, scaled by the per-mode multiplier (0.7/1.0/1.5)
# and rounded. Anchors the XP-scaling check.
VPN_BASE_XP = 5
XP_MULT = {"tutorial": 0.7, "normal": 1.0, "hardcore": 1.5}


def _scaled_xp(base, mode):
    # Mirror the game's Math.round (round-half-up for .5, matching JS Math.round).
    import math
    return math.floor(base * XP_MULT[mode] + 0.5)


# ── The spine, as data (verified against full-story-winnable.test.ts +
#    core-story.json). Each mission: the accept, its ordered command legs
#    (kind "nav"/"hack"/"cat"/"talk"/"choose"), and its core-story reward. ──────
SPINE = [
    {
        "id": "the_breadcrumb",
        "accept": "accept the_breadcrumb",
        "steps": [
            ("connect 192.168.1.105", "nav"),
            ("exploit weak_password", "hack"),
            ("cat /Users/jmiller/Documents/work_vpn.txt", "cat:vpn"),
        ],
        "credits": 1000, "xp": 250,
        "flags": {"found_meridian_credentials", "neighbor_story_complete"},
    },
    {
        "id": "following_the_money",
        "accept": "accept following_the_money",
        "steps": [
            ("connect 10.52.0.7", "nav"),
            ("exploit weak_password", "hack"),
            ("cat /shared/reports/Q3_2024_CONFIDENTIAL.xlsx", "cat"),
            ("cat /shared/IT/network_diagram.png.txt", "cat"),
            ("cat /home/jmiller/private/.insurance", "cat"),
        ],
        "credits": 2000, "xp": 500,
        "flags": {"found_project_m_reference", "meridian_compromised"},
    },
    {
        "id": "project_meridian",
        "accept": "accept project_meridian",
        "steps": [
            ("connect 10.52.2.20", "nav"),
            ("exploit privilege_escalation", "hack"),
            ("cat /classified/PROJECT_M/README.txt", "cat"),
            ("cat /classified/PROJECT_M/financial_transfers.log", "cat"),
            ("cat /classified/PROJECT_M/surveillance_metadata.json", "cat"),
        ],
        "credits": 5000, "xp": 1000,
        "flags": {"found_meridian_file", "project_meridian_discovered"},
    },
    {
        "id": "dead_drop",
        "accept": "accept dead_drop",
        "steps": [
            ("connect 10.99.0.50", "nav"),
            ("exploit weak_password", "hack"),
            ("cat /drop/meridian_files.enc", "cat"),
            ("cat /drop/contacts.txt", "cat"),
        ],
        "credits": 3000, "xp": 750,
        "flags": {"found_marcus_webb_identity", "ghost_protocol_contact"},
    },
    {
        "id": "into_the_syndicate",
        "accept": "accept into_the_syndicate",
        "steps": [
            ("connect 172.16.50.1", "nav"),
            ("crack /var/log/access.log", "hack"),
            ("connect 172.16.50.25", "nav"),
            ("exploit privilege_escalation", "hack"),
            ("cat /axiom/docs/architecture_v3_FINAL.pdf", "cat"),
            ("cat /axiom/logs/decision_history_summary.txt", "cat"),
        ],
        "credits": 10000, "xp": 2000,
        "flags": {"axiom_core_accessed", "discovered_axiom_sentience"},
    },
    {
        "id": "the_other",
        "accept": "accept the_other",
        "steps": [
            ("connect 10.99.0.50", "nav"),
            ("cat /drop/null_origin.dat", "cat"),
            ("talk sp3ctr3", "talk:spectre"),
        ],
        "credits": 8000, "xp": 2500,
        "flags": {"null_contact", "two_ai_revelation"},
    },
    {
        "id": "the_architect",
        "accept": "accept the_architect",
        "steps": [
            ("connect 10.42.0.1", "nav"),
            ("cat /foundation/cross_testimony.txt", "cat"),
            ("talk e.cross", "talk:cross"),
        ],
        "credits": 5000, "xp": 2000,
        "flags": {"architect_contact", "full_history_known"},
    },
    {
        "id": "point_of_no_return",
        "accept": "accept point_of_no_return",
        "steps": [
            ("choose liberation", "choose"),
        ],
        "credits": 20000, "xp": 5000,
        "flags": {"point_of_no_return_reached"},
    },
]

# The non-vacuous same-seed determinism prefix: missions 1-4 (through the last
# dead_drop cat, NOT into the talk legs). met_sp3ctr3 is delivered inside M3, so
# the prefix exercises a seeded delivery, not just a hack roll.
PREFIX_LEN = 4


class HackFailed(Exception):
    """A hack leg did not succeed within RETRY_CAP — the spine cannot progress."""


def _mission(state, mid):
    for m in state.get("missions", []):
        if m.get("missionId") == mid:
            return m
    return None


_normalize_state = invariants.normalize_state


def run_spine(ad, seed, difficulty, missions=SPINE):
    """Drive the spine (or a mission prefix) once on a freshly-reset player.

    Returns a dict:
      baseline  — post_tutorial state after reset
      records   — ordered per-step dicts {command,result,before,after,violations}
                  (INCLUDES every failed-hack retry attempt)
      summaries — per-mission {before, after, cmd_xp, records}
      tags      — named refs: vpn_cat, talk:spectre, talk:cross, choose
      final     — final player-state
    """
    ad.difficulty = difficulty
    baseline = ad.reset(seed)
    prev = baseline
    records = []
    summaries = {}
    tags = {}

    def drive(command, hack=False):
        nonlocal prev
        rec = None
        for _ in range(RETRY_CAP):
            s, _term, _trunc, info = ad.type_text_step(command)
            result = info.get("result") or {}
            viols = invariants.check_command(prev, s, command, result)
            rec = {"command": command, "result": result,
                   "before": prev, "after": s, "violations": viols}
            records.append(rec)
            prev = s
            if not hack or result.get("success"):
                break
        succeeded = bool(rec["result"].get("success")) if rec else False
        return rec, succeeded

    for m in missions:
        before = prev
        mrecs = []
        acc_rec, _ = drive(m["accept"])
        mrecs.append(acc_rec)
        for command, kind in m["steps"]:
            is_hack = kind == "hack"
            rec, ok = drive(command, hack=is_hack)
            mrecs.append(rec)
            if is_hack and not ok:
                raise HackFailed(
                    f"{command!r} failed within {RETRY_CAP} attempts "
                    f"({difficulty}, seed {seed!r})")
            if kind == "cat:vpn":
                tags["vpn_cat"] = rec
            elif kind in ("talk:spectre", "talk:cross", "choose"):
                tags[kind] = rec
        after = prev
        cmd_xp = sum(int(r["result"].get("xpGain") or 0)
                     for r in mrecs if r["result"].get("success"))
        summaries[m["id"]] = {"before": before, "after": after,
                              "cmd_xp": cmd_xp, "records": mrecs, "mission": m}

    return {"baseline": baseline, "records": records, "summaries": summaries,
            "tags": tags, "final": prev}


def run_spine_seeded(ad, seeds, difficulty):
    """Try candidate seeds until the full spine wins (for hardcore's ~30% odds).
    Returns (seed_used, run) or (None, last_error)."""
    last_err = None
    for sd in seeds:
        try:
            run = run_spine(ad, sd, difficulty)
        except HackFailed as e:
            last_err = str(e)
            continue
        gs = run["final"].get("gameStatus") or {}
        if gs.get("isComplete"):
            return sd, run
        last_err = f"spine completed commands but isComplete=False (seed {sd!r})"
    return None, last_err


def _sweep_violations(run, tag):
    out = []
    for r in run["records"]:
        for v in r["violations"]:
            out.append(f"[{tag}] {r['command']!r}: {v}")
    return out


def _assert_win(run):
    gs = run["final"].get("gameStatus") or {}
    return (gs.get("isComplete") is True
            and gs.get("ending") == "ending_liberation"
            and gs.get("completedStoryMissions") == 8
            and gs.get("totalStoryMissions") == 8), gs


def _all_completed(run):
    return all(
        (_mission(run["final"], m["id"]) or {}).get("status") == "completed"
        for m in SPINE)


def main() -> int:
    seed = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SEED
    cfg = UgtConfig(CONFIG_PATH)
    ad = NexusHttpAdapter(cfg)
    gate = GateRunner()
    ck, finding = gate.ck, gate.finding

    print(f"NEXUS Round 2 — full 8-mission spine to a win, 3 modes (seed {seed!r})\n")

    m1_residuals = {}   # mode -> M1 xp residual (should be mode-invariant == 250)
    m1_credits = {}     # mode -> M1 credits delta (should be mode-invariant == 1000)

    try:
        # ── connect bootstraps a player ─────────────────────────────────────
        ad.connect()
        ck("connect() bootstraps a player", bool(ad.player_id),
           f"playerId={ad.player_id}")

        # ══ NORMAL — the detailed reference run ══════════════════════════════
        print("\n  == NORMAL: full spine (reference) ==")
        run = run_spine(ad, seed, "normal")
        baseline = run["baseline"]
        final = run["final"]

        ck("post_tutorial baseline is sane (lvl5 / xp4000 / cr1000 / rng0 / tutorial_complete)",
           baseline.get("level") == 5 and baseline.get("xp") == 4000
           and baseline.get("credits") == 1000 and baseline.get("rngCounter") == 0
           and "tutorial_complete" in baseline.get("storyFlags", []),
           f"lvl={baseline.get('level')} xp={baseline.get('xp')} cr={baseline.get('credits')} "
           f"rng={baseline.get('rngCounter')}")

        # per-mission: completed + credits Δ + xp residual + reward flags present
        for m in SPINE:
            sm = run["summaries"][m["id"]]
            mrow = _mission(sm["after"], m["id"])
            status = mrow and mrow.get("status")
            credits_delta = sm["after"].get("credits", 0) - sm["before"].get("credits", 0)
            xp_delta = sm["after"].get("xp", 0) - sm["before"].get("xp", 0)
            residual = xp_delta - sm["cmd_xp"]
            flags_present = m["flags"] <= set(sm["after"].get("storyFlags", []))
            ok = (status == "completed" and credits_delta == m["credits"]
                  and residual == m["xp"] and flags_present)
            ck(f"M {m['id']}: completed + credits+{m['credits']} + xp residual {m['xp']} + flags",
               ok,
               f"status={status} creditsΔ={credits_delta} residual={residual} "
               f"(xpΔ={xp_delta}-cmdXP={sm['cmd_xp']}) flags={flags_present}")
            if not ok and credits_delta > m["credits"]:
                finding(f"{m['id']}: credits delta {credits_delta} exceeds the single "
                        f"{m['credits']} reward — possible DOUBLE-REWARD")
            if m["id"] == "the_breadcrumb":
                m1_residuals["normal"] = residual
                m1_credits["normal"] = credits_delta

        # the R2 finding-surface legs must SUCCEED (never skipped/weakened)
        ck("M6 talk sp3ctr3 succeeds (NX-R2-1 unlock + NX-R2-2 scripted delivery)",
           bool(run["tags"].get("talk:spectre", {}).get("result", {}).get("success")),
           f"result={run['tags'].get('talk:spectre', {}).get('result', {}).get('success')}")
        ck("M7 talk e.cross succeeds (per-NPC met-gate still enforced)",
           bool(run["tags"].get("talk:cross", {}).get("result", {}).get("success")),
           f"result={run['tags'].get('talk:cross', {}).get('result', {}).get('success')}")
        ck("M8 choose liberation succeeds",
           bool(run["tags"].get("choose", {}).get("result", {}).get("success")),
           f"result={run['tags'].get('choose', {}).get('result', {}).get('success')}")

        # THE WIN
        win_ok, gs = _assert_win(run)
        ck("WIN: isComplete + ending_liberation + 8/8 story missions (NORMAL)",
           win_ok,
           f"isComplete={gs.get('isComplete')} ending={gs.get('ending')} "
           f"{gs.get('completedStoryMissions')}/{gs.get('totalStoryMissions')}")

        # every reward flag present in the final union
        all_flags = set().union(*(m["flags"] for m in SPINE))
        ck("all 8 missions' reward flags are present in the final state",
           all_flags <= set(final.get("storyFlags", [])),
           f"missing={sorted(all_flags - set(final.get('storyFlags', [])))}")

        # reputation accumulated (underground got every underground reward)
        rep = final.get("reputation") or {}
        ck("reputation accumulated across the spine (underground > 0)",
           (rep.get("underground") or 0) > 0, f"reputation={rep}")

        # invariant sweep + rngCounter accounting
        v_normal = _sweep_violations(run, "normal")
        ck("per-command invariant sweep CLEAN across the whole NORMAL spine",
           not v_normal, "0 violations" if not v_normal else f"{len(v_normal)} violations")
        for v in v_normal:
            finding(f"invariant violation — {v}")
        ck("rngCounter equals the number of commands issued (one tick per command)",
           final.get("rngCounter") == len(run["records"]),
           f"rngCounter={final.get('rngCounter')} commands={len(run['records'])}")

        # XP scaling (normal): first cat work_vpn == round(5*1.0) == 5
        vpn_xp = int((run["tags"].get("vpn_cat", {}).get("result", {}) or {}).get("xpGain") or -1)
        ck("XP scaling NORMAL: first cat work_vpn.txt xpGain == round(5*1.0) == 5",
           vpn_xp == _scaled_xp(VPN_BASE_XP, "normal"),
           f"xpGain={vpn_xp} expected={_scaled_xp(VPN_BASE_XP, 'normal')}")

        # double-reward probe: re-accept a completed mission -> refused + inert
        before_re = final
        s_re, _t, _tr, info_re = ad.type_text_step("accept the_breadcrumb")
        res_re = info_re.get("result") or {}
        re_inert = invariants.inv_refused_state_inert(
            before_re, s_re, "accept the_breadcrumb", res_re) is None
        credits_same = s_re.get("credits") == before_re.get("credits")
        xp_same = s_re.get("xp") == before_re.get("xp")
        ck("re-accept a completed mission is REFUSED + game-state inert (no double reward)",
           res_re.get("success") is False and re_inert and credits_same and xp_same,
           f"success={res_re.get('success')} inert={re_inert} "
           f"creditsSame={credits_same} xpSame={xp_same}")
        if not (credits_same and xp_same):
            finding("re-accepting a completed mission changed credits/xp — DOUBLE-REWARD via re-accept")

        # ── same-seed determinism over the NON-VACUOUS M1-M4 prefix ─────────
        print("\n  == NORMAL: same-seed determinism (M1-M4 prefix) ==")
        pre1 = run_spine(ad, seed, "normal", missions=SPINE[:PREFIX_LEN])
        pre2 = run_spine(ad, seed, "normal", missions=SPINE[:PREFIX_LEN])
        cmds1 = [r["command"] for r in pre1["records"]]
        cmds2 = [r["command"] for r in pre2["records"]]
        if len(cmds1) != len(cmds2):
            ck("determinism: identical command sequence", False,
               f"length differs {len(cmds1)} vs {len(cmds2)}")
        else:
            div = first_divergence(cmds1, cmds2)
            ck("determinism: identical command sequence (M1-M4)", div is None,
               "identical" if div is None else f"first divergence at {div}")
        res1 = [r["result"] for r in pre1["records"]]
        res2 = [r["result"] for r in pre2["records"]]
        ck("determinism: identical CommandResult stream (M1-M4)", res1 == res2,
           "byte-identical" if res1 == res2 else "results diverge")
        rng1 = [r["after"].get("rngCounter") for r in pre1["records"]]
        rng2 = [r["after"].get("rngCounter") for r in pre2["records"]]
        ck("determinism: identical rngCounter progression (M1-M4)", rng1 == rng2,
           "identical" if rng1 == rng2 else "rngCounter diverges")
        n1 = _normalize_state(pre1["final"])
        n2 = _normalize_state(pre2["final"])
        ck("determinism: identical normalized final player-state (M1-M4)", n1 == n2,
           "identical" if n1 == n2 else "final states differ")
        if res1 != res2 or rng1 != rng2 or n1 != n2:
            finding("same-seed replay diverges over the M1-M4 prefix — an unseeded RNG "
                    "call site remains in the pipeline")
        roll_seen = any("[Success Rate:" in (r["result"].get("output", "") or "")
                        for r in pre1["records"])
        met_seen = "met_sp3ctr3" in set(pre1["final"].get("storyFlags", []))
        ck("determinism proof is NON-VACUOUS (M1-M4 has a seeded roll AND met_sp3ctr3 delivered)",
           roll_seen and met_seen, f"roll={roll_seen} met_sp3ctr3={met_seen}")

        # ══ TUTORIAL — full spine (no determinism prefix, per plan) ══════════
        print("\n  == TUTORIAL: full spine ==")
        tut_seed_used, tut = run_spine_seeded(
            ad, [f"{seed}-tut", f"{seed}-tut-1", f"{seed}-tut-2"], "tutorial")
        if tut is None or isinstance(tut, str):
            ck("TUTORIAL: full spine reaches isComplete + 8/8", False,
               f"no winning seed: {tut_seed_used!r} / {tut}")
        else:
            win_ok, gs = _assert_win(tut)
            ck("TUTORIAL: full spine reaches isComplete + ending_liberation + 8/8",
               win_ok and _all_completed(tut),
               f"seed={tut_seed_used!r} isComplete={gs.get('isComplete')} "
               f"ending={gs.get('ending')} {gs.get('completedStoryMissions')}/8")
            v_tut = _sweep_violations(tut, "tutorial")
            ck("per-command invariant sweep CLEAN across the whole TUTORIAL spine",
               not v_tut, "0 violations" if not v_tut else f"{len(v_tut)} violations")
            for v in v_tut:
                finding(f"invariant violation — {v}")
            tut_flags = set().union(*(m["flags"] for m in SPINE))
            ck("TUTORIAL: all 8 missions' reward flags present in the final state",
               tut_flags <= set(tut["final"].get("storyFlags", [])),
               f"missing={sorted(tut_flags - set(tut['final'].get('storyFlags', [])))}")
            tvpn = int((tut["tags"].get("vpn_cat", {}).get("result", {}) or {}).get("xpGain") or -1)
            ck("XP scaling TUTORIAL: first cat work_vpn.txt xpGain == round(5*0.7) == 4",
               tvpn == _scaled_xp(VPN_BASE_XP, "tutorial"),
               f"xpGain={tvpn} expected={_scaled_xp(VPN_BASE_XP, 'tutorial')}")
            sm = tut["summaries"]["the_breadcrumb"]
            m1_residuals["tutorial"] = (sm["after"].get("xp", 0)
                                        - sm["before"].get("xp", 0) - sm["cmd_xp"])
            m1_credits["tutorial"] = sm["after"].get("credits", 0) - sm["before"].get("credits", 0)

        # ══ HARDCORE — full spine, seed-probed (retry cap earns its keep) ════
        print("\n  == HARDCORE: full spine (seed-probed) ==")
        hc_seeds = [f"{seed}-hc-{i}" for i in range(8)]
        hc_seed_used, hc = run_spine_seeded(ad, hc_seeds, "hardcore")
        if hc is None or isinstance(hc, str):
            ck("HARDCORE: full spine reaches isComplete + 8/8", False,
               f"no winning seed in {len(hc_seeds)} tries: {hc}")
        else:
            win_ok, gs = _assert_win(hc)
            ck("HARDCORE: full spine reaches isComplete + ending_liberation + 8/8",
               win_ok and _all_completed(hc),
               f"seed={hc_seed_used!r} isComplete={gs.get('isComplete')} "
               f"ending={gs.get('ending')} {gs.get('completedStoryMissions')}/8")
            v_hc = _sweep_violations(hc, "hardcore")
            ck("per-command invariant sweep CLEAN across the whole HARDCORE spine",
               not v_hc, "0 violations" if not v_hc else f"{len(v_hc)} violations")
            for v in v_hc:
                finding(f"invariant violation — {v}")
            hc_flags = set().union(*(m["flags"] for m in SPINE))
            ck("HARDCORE: all 8 missions' reward flags present in the final state",
               hc_flags <= set(hc["final"].get("storyFlags", [])),
               f"missing={sorted(hc_flags - set(hc['final'].get('storyFlags', [])))}")
            # the retry loop actually earned its keep: at least one hack re-rolled
            hack_retried = any(
                r["result"].get("success") is False
                and r["command"].split(" ", 1)[0] in ("exploit", "crack")
                for r in hc["records"])
            ck("HARDCORE: at least one hack needed a retry (the retry cap earned its keep)",
               hack_retried, "a failed-then-retried hack was observed" if hack_retried
               else "no hack failed — hardcore odds did not bite (re-check seed)")
            hvpn = int((hc["tags"].get("vpn_cat", {}).get("result", {}) or {}).get("xpGain") or -1)
            ck("XP scaling HARDCORE: first cat work_vpn.txt xpGain == round(5*1.5) == 8",
               hvpn == _scaled_xp(VPN_BASE_XP, "hardcore"),
               f"xpGain={hvpn} expected={_scaled_xp(VPN_BASE_XP, 'hardcore')}")
            sm = hc["summaries"]["the_breadcrumb"]
            m1_residuals["hardcore"] = (sm["after"].get("xp", 0)
                                        - sm["before"].get("xp", 0) - sm["cmd_xp"])
            m1_credits["hardcore"] = sm["after"].get("credits", 0) - sm["before"].get("credits", 0)

        # ══ cross-mode invariants: mission reward xp + credits are mode-INVARIANT
        print("\n  == cross-mode: mission-reward xp/credits are mode-invariant ==")
        res_vals = set(m1_residuals.values())
        ck("mission-reward xp is MODE-INVARIANT (M1 residual == 250 in all 3 modes)",
           len(m1_residuals) == 3 and res_vals == {250},
           f"residuals={m1_residuals}")
        cr_vals = set(m1_credits.values())
        ck("mission-reward credits are MODE-INVARIANT (M1 credits Δ == 1000 in all 3 modes)",
           len(m1_credits) == 3 and cr_vals == {1000},
           f"credits={m1_credits}")

        # ══ ECONOMY SPINE (NX-L14-1 / L-015) ════════════════════════════════
        # The tool-tier economy is a major system reachable only by player verbs
        # (`market` / `buy <tier>`), so R2 must drive it to a real outcome like every
        # other mode — a green R2 that never touches it would be a vacuous pass on the
        # newest subsystem in the game. Driven here on the post-spine player, which has
        # real mission income, so the purchase is made the way a player would make it.
        print("\n  == ECONOMY: market / buy / tool tier ==")

        def _cmd(c):
            _, _, _, info = ad.type_text_step(c)
            return info["result"], ad._read_state()

        # NOTE on sequencing: this runs AFTER three full spines, so the player is rich
        # (~55k credits, level 20) and still on `basic`. Ladder UP from there — an earlier
        # draft bought `zero_day` first and then read the correct refusal of the
        # `commercial` DOWNGRADE as a failure. The insufficient-funds case therefore
        # cannot be tested on this player at all; it is done last, on a fresh reset.
        econ_before = ad._read_state()
        ck("economy preconditions: player starts on the free basic toolkit",
           econ_before.get("toolTier") == "basic",
           f"tier={econ_before.get('toolTier')} credits={econ_before.get('credits')}")

        r_mkt, s_mkt = _cmd("market")
        ck("market lists the toolkit catalogue and is READ-ONLY",
           bool(r_mkt.get("success"))
           and "zero_day" in (r_mkt.get("output") or "")
           and s_mkt.get("credits") == econ_before.get("credits")
           and s_mkt.get("toolTier") == econ_before.get("toolTier"),
           f"success={r_mkt.get('success')} creditsΔ="
           f"{s_mkt.get('credits', 0) - econ_before.get('credits', 0)} "
           f"tier={s_mkt.get('toolTier')}")

        # Ascend the ladder properly: buy the cheapest rung first.
        r_buy, s_buy = _cmd("buy commercial")
        spent = (s_mkt.get("credits") or 0) - (s_buy.get("credits") or 0)
        ck("buy commercial debits EXACTLY 1500 and sets toolTier",
           r_buy.get("success") is True and s_buy.get("toolTier") == "commercial"
           and spent == 1500,
           f"success={r_buy.get('success')} spent={spent} tier={s_buy.get('toolTier')}")
        if r_buy.get("success") and spent != 1500:
            finding(f"buy commercial debited {spent} credits, not the 1500 sticker price")

        # Re-buying what you own must refuse inertly.
        r_re, s_re = _cmd("buy commercial")
        ck("re-buying the tier you already own is REFUSED and state-inert",
           r_re.get("success") is False and s_re.get("credits") == s_buy.get("credits")
           and s_re.get("toolTier") == "commercial",
           f"success={r_re.get('success')} credits={s_re.get('credits')} "
           f"tier={s_re.get('toolTier')}")

        # Downgrading must refuse inertly too (basic is not even purchasable).
        r_dn, s_dn = _cmd("buy basic")
        ck("downgrading is REFUSED and state-inert",
           r_dn.get("success") is False and s_dn.get("credits") == s_buy.get("credits")
           and s_dn.get("toolTier") == "commercial",
           f"success={r_dn.get('success')} tier={s_dn.get('toolTier')}")

        # THE point of the feature: the purchased tier must reach the odds math. This is
        # the check that fires if anyone re-hardcodes ToolTier.BASIC at a call site.
        ad.type_text_step("scan")
        tgt = (s_dn.get("discoveredServers") or [None])[0]
        ck("economy: a target host was discoverable for the odds check", bool(tgt),
           f"target={tgt}")
        if tgt:
            ad.type_text_step(f"connect {tgt}")
            r_hack, _ = _cmd("escalate")
            out = r_hack.get("output") or ""
            ck("a purchased tier reaches the success-rate breakdown (Tool: +20%)",
               "Tool: +20%" in out,
               f"breakdown={[l for l in out.splitlines() if 'Tool' in l or 'Base' in l]}")
            if "Basic" in out:
                finding("odds breakdown still reports Basic tools after a commercial "
                        "purchase — a success-rate call site is still hardcoded")

        # Climbing a second rung charges the new tier's full price (no trade-in).
        r_bm, s_bm = _cmd("buy black_market")
        spent2 = (s_dn.get("credits") or 0) - (s_bm.get("credits") or 0)
        ck("climbing to black_market charges its FULL 6000 (no trade-in credit)",
           r_bm.get("success") is True and s_bm.get("toolTier") == "black_market"
           and spent2 == 6000,
           f"success={r_bm.get('success')} spent={spent2} tier={s_bm.get('toolTier')}")

        ck("credits never went negative across the economy sequence",
           (s_bm.get("credits") or 0) >= 0, f"credits={s_bm.get('credits')}")

        # Insufficient funds needs a POOR player, which the post-spine one is not.
        # A fresh reset gives the post_tutorial baseline: 1000 credits, basic tier.
        poor = ad.reset()
        r_poor, s_poor = _cmd("buy commercial")
        ck("buy beyond your means is REFUSED and state-inert (fresh 1000-credit player)",
           r_poor.get("success") is False
           and s_poor.get("credits") == poor.get("credits")
           and s_poor.get("toolTier") == "basic",
           f"success={r_poor.get('success')} credits={s_poor.get('credits')} "
           f"(was {poor.get('credits')}) tier={s_poor.get('toolTier')}")

        # ══ GATED ACCESS SEMANTICS (NX-L16-1 / NX-L17-1) ════════════════════
        # The game deliberately distinguishes "you have not reached this yet" from
        # "this does not exist", and throttles its [HINT] line to attempts 1/5/10 so
        # repeated refusals do not nag. Both are player-facing CONTENT, so they belong
        # in R2 — and neither had any gate coverage, which is how the economy sat
        # untested at a green 36/36 (LESSONS.md O10).
        # Runs on the fresh post-reset player from the economy leg above, whose hint
        # counters reset-episode has just zeroed.
        print("\n  == GATED ACCESS: blocked vs nonexistent, hint throttling ==")

        st0 = ad._read_state()
        r_gate, _ = _cmd("connect 10.42.0.1")      # real host, story-gated
        r_none, s_none = _cmd("connect 10.99.99.99")  # no such host
        gate_out = r_gate.get("output") or ""
        none_out = r_none.get("output") or ""

        ck("a story-gated host is REFUSED with an access-denied message",
           r_gate.get("success") is False and "blocked" in gate_out
           and "Access denied" in gate_out,
           f"success={r_gate.get('success')} first={gate_out.splitlines()[:1]}")
        ck("a NONEXISTENT host is refused with a DIFFERENT, 'no such server' message",
           r_none.get("success") is False and "No server at" in none_out,
           f"first={none_out.splitlines()[:1]}")
        # THE regression guard: a change that collapsed these into one message would
        # pass every other check in the ladder.
        ck("gated-host and nonexistent-host messages are DISTINGUISHABLE",
           gate_out != none_out and "No server at" not in gate_out
           and "blocked" not in none_out,
           "gated!=missing and neither leaks the other's wording")
        ck("both connection refusals are state-inert",
           s_none.get("credits") == st0.get("credits")
           and s_none.get("compromisedServersCount") == st0.get("compromisedServersCount")
           and s_none.get("discoveredServersCount") == st0.get("discoveredServersCount"),
           f"credits={s_none.get('credits')} disc={s_none.get('discoveredServersCount')}")

        # Hint cadence on gated ADDRESSES: attempt 1 already fired above, so 2/3/4
        # must be silent and 5 must fire again.
        addr_hits = ["HINT" in gate_out]
        for _ in range(4):
            r, _ = _cmd("connect 10.42.0.1")
            addr_hits.append("HINT" in (r.get("output") or ""))
        ck("gated-address [HINT] throttles to attempts 1 and 5 (silent on 2-4)",
           addr_hits == [True, False, False, False, True],
           f"attempts 1..5 -> {addr_hits}")

        # Gated COMMANDS: `talk` is still gated at the post_tutorial baseline.
        r_cmd, _ = _cmd("talk sp3ctr3")
        cmd_out = r_cmd.get("output") or ""
        ck("a gated COMMAND says blocked/access-denied, NOT 'Command not found'",
           r_cmd.get("success") is False and "blocked" in cmd_out
           and "Command not found" not in cmd_out,
           f"first={cmd_out.splitlines()[:1]}")
        r_typo, _ = _cmd("zzqq_not_a_command")
        ck("a genuine TYPO still says 'Command not found' (unknown != gated)",
           r_typo.get("success") is False
           and "Command not found" in (r_typo.get("output") or ""),
           f"first={(r_typo.get('output') or '').splitlines()[:1]}")

        # The two counters must be independent: the 5 address attempts above must not
        # have consumed the command tally, so this command run still reads 1..5.
        cmd_hits = ["HINT" in cmd_out]
        for _ in range(4):
            r, _ = _cmd("talk sp3ctr3")
            cmd_hits.append("HINT" in (r.get("output") or ""))
        ck("gated-command [HINT] throttles 1/5 INDEPENDENTLY of the address counter",
           cmd_hits == [True, False, False, False, True],
           f"attempts 1..5 -> {cmd_hits} (address counter already at 5)")

        # NOTE ordering: these run AFTER the cadence assertions above. `help <gated>`
        # shares the gated-COMMAND tally, so issuing it earlier would consume an attempt
        # and shift the 1/5 cadence the check above asserts — caught by reasoning about
        # the counter rather than by a red run, but it would have been a real failure.
        # NX-L19-1: `help <locked>` was the last place the old "pretend it does not
        # exist" behaviour survived. All three refusal surfaces must now agree, while
        # `help <unknown>` deliberately still reads as a typo.
        r_hg, _ = _cmd("help talk")
        hg_out = r_hg.get("output") or ""
        ck("help <GATED command> gives the access-denied message, not 'Unknown command'",
           r_hg.get("success") is False and "blocked" in hg_out
           and "Unknown command" not in hg_out,
           f"first={hg_out.splitlines()[:1]}")
        r_hu, _ = _cmd("help zzqq_not_a_command")
        hu_out = r_hu.get("output") or ""
        ck("help <UNKNOWN command> STILL says 'Unknown command' (unknown != gated)",
           r_hu.get("success") is False and "Unknown command" in hu_out
           and "blocked" not in hu_out and "Access denied" not in hu_out,
           f"first={hu_out.splitlines()[:1]}")


    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        ck("exception-free run", False, f"{type(exc).__name__}: {exc}")
    finally:
        ad.close()

    return gate.finish(
        "ROUND 2",
        "UGT drove the FULL 8-mission spine to a real win (isComplete + "
        "ending_liberation + 8/8) through the real handler, across "
        "normal/tutorial/hardcore; rewards landed once, XP scaled per mode "
        "while mission rewards stayed mode-invariant, every command held the "
        "invariants, and the M1-M4 prefix replays byte-identically. "
        "Ready for Round 3.")


if __name__ == "__main__":
    sys.exit(main())
