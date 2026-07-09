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


def _normalize_state(state):
    """Canonical player-state for a byte-identical compare. player-state exposes
    NO timestamp fields, so nothing to strip — only sort the set-like fields."""
    return {
        "level": state.get("level"),
        "xp": state.get("xp"),
        "credits": state.get("credits"),
        "rngCounter": state.get("rngCounter"),
        "difficulty": state.get("difficulty"),
        "reputation": dict(sorted((state.get("reputation") or {}).items())),
        "storyFlags": sorted(state.get("storyFlags") or []),
        "unlockedCommands": sorted(state.get("unlockedCommands") or []),
        "currentServerId": state.get("currentServerId"),
        "discoveredServers": sorted(state.get("discoveredServers") or []),
        "compromisedServers": sorted(
            (c.get("ipAddress") for c in state.get("compromisedServers") or []),
            key=lambda x: (x is None, x),
        ),
        "missions": sorted(
            ((m.get("missionId"), m.get("status"),
              m.get("objectivesCompleted", 0), m.get("objectivesTotal", 0))
             for m in state.get("missions") or []),
            key=lambda t: (t[0] is None, t[0]),
        ),
        "gameStatus": state.get("gameStatus") or {},
    }


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
    checks: list[tuple[str, bool, str]] = []
    findings: list[str] = []

    def ck(name, ok, detail=""):
        checks.append((name, ok, detail))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))

    def finding(text):
        findings.append(text)
        print(f"  [FINDING] {text}")

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
            div = next((i for i in range(len(cmds1)) if cmds1[i] != cmds2[i]), None)
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

    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        ck("exception-free run", False, f"{type(exc).__name__}: {exc}")
    finally:
        ad.close()

    passed = sum(1 for _, ok, _ in checks if ok)
    total = len(checks)
    print(f"\n{'=' * 70}")
    if findings:
        print("FINDINGS (bugs/anomalies in the game, to fix upstream):")
        for i, f in enumerate(findings, 1):
            print(f"  {i}. {f}")
        print()
    if passed == total:
        print(f"ROUND 2 MET — {passed}/{total} checks. UGT drove the FULL 8-mission spine to "
              f"a real win (isComplete + ending_liberation + 8/8) through the real handler, "
              f"across normal/tutorial/hardcore; rewards landed once, XP scaled per mode while "
              f"mission rewards stayed mode-invariant, every command held the invariants, and "
              f"the M1-M4 prefix replays byte-identically. Ready for Round 3.")
        return 0
    print(f"ROUND 2 NOT MET — {passed}/{total} checks passed. Fix the failures above and re-run.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
