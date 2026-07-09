#!/usr/bin/env python3
"""
NEXUS ROUND 1 — one full playable mission loop through the REAL game +
same-seed determinism + a per-command invariant sweep.

Drives the live nexus-world-builder Next.js server (apps/game, `next dev` on
:3100) THROUGH `NexusHttpAdapter` — never a re-implementation. R1 walks the very
first story mission slice end-to-end over HTTP:

    reset(post_tutorial) -> help/status/missions/clues -> a garbage refusal ->
    accept the_breadcrumb -> scan -> connect 192.168.1.105 ->
    exploit sql_injection (refused: only weak_password exists here) ->
    exploit weak_password (the seeded roll) -> crack work_vpn.txt (seeded
    password draw) -> cat work_vpn.txt (auto-completes the mission + rewards) ->
    re-accept the_breadcrumb (a DOUBLE-REWARD probe) -> progress

and asserts, per plan §4 (~25 checks):
  * the post_tutorial baseline + info commands are sane and readable,
  * the mission accepts, an exploit fires a real seeded roll and compromises the
    server, crack draws a seeded password, cat completes the mission and grants
    its rewards EXACTLY ONCE (credits +1000, xp == sum(command xpGain)+250,
    underground rep +5, both reward flags),
  * every refused command is GAME-STATE inert (rngCounter excluded — NX-OBS-1),
  * `invariants.check_command` finds ZERO violations across BOTH runs,
  * same-seed determinism (identical commands, CommandResults, rngCounter
    progression, and normalized final player-state) — and NON-VACUOUS (the
    transcript actually contains the seeded roll + the drawn password),
  * a cross-seed variance sweep proves the roll is seed-dependent.

No game logic is reimplemented; every effect is read back from player-state.
A failed check is DATA — it prints as a FINDING and fails the gate, to be fixed
upstream in the game (with a pinning test), never tolerated here.

Run (server up on :3100 — verify the LISTEN pid is yours:
lsof -nP -iTCP:3100 -sTCP:LISTEN):

    python3 integrations/nexus/verify_round1.py [seed]

Exit 0 + "ROUND 1 MET — N/N" means the gate passed.
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

# Default episode seed. The first exploit's roll is seeded (~90% success at the
# post_tutorial baseline); the exploit step retries up to 5x, and crack succeeds
# on this seed so the non-vacuity anchor ("Password: jmiller_pass") is present.
DEFAULT_SEED = "nexus-r1-seed"

HACK_IP = "192.168.1.105"                              # neighbor_pc (seed-story)
VULN = "weak_password"                                 # the only vuln on that host
BAD_VULN = "sql_injection"                             # refusal probe 2
VPN_FILE = "/Users/jmiller/Documents/work_vpn.txt"     # find_vpn_creds target + crack file
MISSION = "the_breadcrumb"
BOGUS = "zzqq_r1_bogus"                                 # refusal probe 1

EXPLOIT_RETRY_CAP = 5


def _mission(state, mid):
    for m in state.get("missions", []):
        if m.get("missionId") == mid:
            return m
    return None


def _compromised_ips(state):
    return {c.get("ipAddress") for c in state.get("compromisedServers", [])}


def _crack_tail(output):
    """The seeded suffix of the drawn password ('jmiller_pass<NNN>'), or None."""
    marker = "Password: jmiller_pass"
    idx = output.find(marker)
    if idx < 0:
        return None
    return output[idx + len(marker):].splitlines()[0]


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


def run_episode(ad, seed):
    """Drive the full R1 command sequence once on a freshly-reset player.

    Returns (records, marks):
      records — ordered list of per-step dicts:
                {command, result, before, after, violations}
      marks   — named references into `records` for the checks (help/status/... ,
                accept1/accept2, exploit_attempts, crack, cat, connect_sid, ...)
    """
    baseline = ad.reset(seed)  # post_tutorial baseline, rngCounter re-pinned to 0
    prev = baseline
    records = []
    marks = {"baseline": baseline}

    def drive(command):
        nonlocal prev
        s, _term, _trunc, info = ad.type_text_step(command)
        result = info.get("result") or {}
        viols = invariants.check_command(prev, s, command, result)
        rec = {"command": command, "result": result,
               "before": prev, "after": s, "violations": viols}
        records.append(rec)
        prev = s
        return rec

    marks["help"] = drive("help")
    marks["status"] = drive("status")
    marks["missions"] = drive("missions")
    marks["clues"] = drive("clues")
    marks["bogus"] = drive(BOGUS)                       # refusal probe 1
    marks["accept1"] = drive(f"accept {MISSION}")
    marks["scan"] = drive("scan")
    marks["connect"] = drive(f"connect {HACK_IP}")
    marks["connect_sid"] = ad._cur_server_id           # carried nav state
    marks["exploit_bad"] = drive(f"exploit {BAD_VULN}")  # refusal probe 2

    attempts = []
    for _ in range(EXPLOIT_RETRY_CAP):
        rec = drive(f"exploit {VULN}")
        attempts.append(rec)
        if rec["result"].get("success"):
            break
    marks["exploit_attempts"] = attempts

    marks["crack"] = drive(f"crack {VPN_FILE}")
    marks["cat"] = drive(f"cat {VPN_FILE}")
    marks["accept2"] = drive(f"accept {MISSION}")       # refusal probe 3 (double-reward)
    marks["progress"] = drive("progress")

    marks["records"] = records
    marks["final"] = records[-1]["after"]
    return records, marks


def variance_sweep(ad, seed, n=8):
    """Cross-seed sweep: reset -> connect -> exploit -> crack on N derived seeds,
    collecting (exploit_success, crack_tail). >=2 distinct tuples proves the roll
    is seed-dependent; all-identical is a FINDING (unseeded RNG suspected)."""
    tuples = []
    for i in range(n):
        ad.reset(f"{seed}-var-{i}")
        ad.type_text_step(f"connect {HACK_IP}")
        _s, _t, _tr, info_ex = ad.type_text_step(f"exploit {VULN}")
        ex_ok = bool((info_ex.get("result") or {}).get("success"))
        _s, _t, _tr, info_cr = ad.type_text_step(f"crack {VPN_FILE}")
        tail = _crack_tail((info_cr.get("result") or {}).get("output", "") or "")
        tuples.append((ex_ok, tail))
    return tuples


def main() -> int:
    seed = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SEED
    cfg = UgtConfig(CONFIG_PATH)
    ad = NexusHttpAdapter(cfg)
    checks: list[tuple[str, bool, str]] = []
    findings: list[str] = []

    def ck(name: str, ok: bool, detail: str = ""):
        checks.append((name, ok, detail))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))

    def finding(text: str):
        findings.append(text)
        print(f"  [FINDING] {text}")

    print(f"NEXUS Round 1 — one full mission loop + determinism (seed {seed!r})\n")
    try:
        # ── connect bootstraps a player ──────────────────────────────────────
        boot = ad.connect()
        ck("connect() bootstraps a player", bool(ad.player_id),
           f"playerId={ad.player_id}")

        # ── RUN 1 (primary) ──────────────────────────────────────────────────
        print("\n  -- run 1 (primary episode) --")
        records1, m = run_episode(ad, seed)
        baseline = m["baseline"]
        final = m["final"]

        # baseline sanity
        ck("post_tutorial baseline is sane (lvl5 / xp4000 / cr1000 / rng0 / tutorial_complete)",
           baseline.get("level") == 5 and baseline.get("xp") == 4000
           and baseline.get("credits") == 1000 and baseline.get("rngCounter") == 0
           and "tutorial_complete" in baseline.get("storyFlags", []),
           f"lvl={baseline.get('level')} xp={baseline.get('xp')} cr={baseline.get('credits')} "
           f"rng={baseline.get('rngCounter')} flags={baseline.get('storyFlags')}")
        ck("target IP is in the post_tutorial discoveredServers",
           HACK_IP in baseline.get("discoveredServers", []),
           f"{HACK_IP} discovered={HACK_IP in baseline.get('discoveredServers', [])}")

        # info commands well-formed + successful
        info_recs = [m["help"], m["status"], m["missions"], m["clues"]]
        info_bad = [r["command"] for r in info_recs
                    if invariants.inv_well_formed(r["before"], r["after"], r["command"], r["result"])
                    or not r["result"].get("success")]
        ck("info commands (help/status/missions/clues) are well-formed and succeed",
           not info_bad, f"bad={info_bad}" if info_bad else "all 4 ok")
        ck("missions output names the_breadcrumb",
           "breadcrumb" in (m["missions"]["result"].get("output", "") or "").lower(),
           "the_breadcrumb listed" if "breadcrumb" in (m["missions"]["result"].get("output", "") or "").lower()
           else "not named in missions output")

        # garbage refusal is state-inert
        bogus = m["bogus"]
        bogus_inert = invariants.inv_refused_state_inert(
            bogus["before"], bogus["after"], bogus["command"], bogus["result"]) is None
        ck("garbage command is refused AND game-state inert (rngCounter excluded)",
           bogus["result"].get("success") is False and bogus_inert,
           f"success={bogus['result'].get('success')} inert={bogus_inert}")

        # accept -> active 0/3
        acc = m["accept1"]
        acc_mission = _mission(acc["after"], MISSION)
        ck("accept the_breadcrumb -> mission active with 0/3 objectives",
           bool(acc["result"].get("success")) and acc_mission is not None
           and acc_mission.get("status") == "active"
           and acc_mission.get("objectivesCompleted") == 0
           and acc_mission.get("objectivesTotal") == 3,
           f"mission={acc_mission}")

        # scan ok
        ck("scan succeeds", bool(m["scan"]["result"].get("success")),
           f"success={m['scan']['result'].get('success')}")

        # connect ok + carried server id
        ck("connect succeeds and the adapter carries a currentServerId",
           bool(m["connect"]["result"].get("success")) and bool(m["connect_sid"]),
           f"currentServerId={m['connect_sid']}")

        # exploit sql_injection refused + inert
        exb = m["exploit_bad"]
        exb_inert = invariants.inv_refused_state_inert(
            exb["before"], exb["after"], exb["command"], exb["result"]) is None
        ck("exploit sql_injection is refused AND game-state inert (wrong vuln for this host)",
           exb["result"].get("success") is False and exb_inert,
           f"success={exb['result'].get('success')} inert={exb_inert}")

        # exploit weak_password: real seeded roll + success within cap
        attempts = m["exploit_attempts"]
        rolled = any("[Success Rate:" in (a["result"].get("output", "") or "") for a in attempts)
        succeeded = any(a["result"].get("success") for a in attempts)
        ck("exploit weak_password fired a real seeded roll and succeeded within 5 attempts",
           rolled and succeeded and len(attempts) <= EXPLOIT_RETRY_CAP,
           f"attempts={len(attempts)} rolled={rolled} succeeded={succeeded}")

        # compromise visible + objective incremented
        exp_success_rec = next((a for a in attempts if a["result"].get("success")), None)
        after_exploit = exp_success_rec["after"] if exp_success_rec else final
        exp_mission = _mission(after_exploit, MISSION)
        ck("compromise is visible (server in compromisedServers + objectivesCompleted>=1)",
           HACK_IP in _compromised_ips(after_exploit)
           and exp_mission is not None and exp_mission.get("objectivesCompleted", 0) >= 1,
           f"compromised={sorted(_compromised_ips(after_exploit))} "
           f"objComp={exp_mission and exp_mission.get('objectivesCompleted')}")

        # crack drew a seeded password
        crack_out = m["crack"]["result"].get("output", "") or ""
        ck("crack drew a seeded password ('Password: jmiller_pass...')",
           "Password: jmiller_pass" in crack_out,
           f"tail={_crack_tail(crack_out)!r}")

        # cat completes the mission
        cat = m["cat"]
        cat_out = cat["result"].get("output", "") or ""
        cat_mission = _mission(cat["after"], MISSION)
        ck("cat work_vpn.txt -> MISSION COMPLETED! + status completed + 2/3 objectives",
           "MISSION COMPLETED!" in cat_out and cat_mission is not None
           and cat_mission.get("status") == "completed"
           and cat_mission.get("objectivesCompleted") == 2,
           f"mission={cat_mission} banner={'MISSION COMPLETED!' in cat_out}")

        # rewards granted EXACTLY once
        xp_gain_sum = sum(int(r["result"].get("xpGain") or 0)
                          for r in records1 if r["result"].get("success"))
        credits_delta = final.get("credits", 0) - baseline.get("credits", 0)
        xp_delta = final.get("xp", 0) - baseline.get("xp", 0)
        rep_underground = (final.get("reputation") or {}).get("underground")
        reward_flags = {"found_meridian_credentials", "neighbor_story_complete"}
        flags_present = reward_flags <= set(final.get("storyFlags", []))
        rewards_ok = (credits_delta == 1000 and xp_delta == xp_gain_sum + 250
                      and rep_underground == 5 and flags_present)
        ck("mission rewards land EXACTLY once (credits +1000, xp Σgain+250, underground +5, flags)",
           rewards_ok,
           f"creditsΔ={credits_delta} xpΔ={xp_delta} (Σgain={xp_gain_sum}+250={xp_gain_sum + 250}) "
           f"underground={rep_underground} flags={flags_present}")
        if not rewards_ok and credits_delta > 1000:
            finding(f"credits delta {credits_delta} exceeds the single 1000 reward — "
                    f"possible DOUBLE-REWARD on mission completion")

        # re-accept refused (double-reward probe): credits unchanged, inert
        acc2 = m["accept2"]
        acc2_inert = invariants.inv_refused_state_inert(
            acc2["before"], acc2["after"], acc2["command"], acc2["result"]) is None
        acc2_credits_same = acc2["after"].get("credits") == acc2["before"].get("credits")
        ck("re-accept a completed mission is refused AND inert (no double reward)",
           acc2["result"].get("success") is False and acc2_inert and acc2_credits_same,
           f"success={acc2['result'].get('success')} inert={acc2_inert} "
           f"creditsSame={acc2_credits_same}")
        if not acc2_credits_same:
            finding("re-accepting a completed mission changed credits — DOUBLE-REWARD via re-accept")

        # ── RUN 2 (determinism) ──────────────────────────────────────────────
        print("\n  -- run 2 (same-seed determinism) --")
        records2, m2 = run_episode(ad, seed)

        # per-command invariant sweep across BOTH runs -> zero violations
        all_viol = []
        for tag, recs in (("run1", records1), ("run2", records2)):
            for r in recs:
                for v in r["violations"]:
                    all_viol.append(f"[{tag}] {r['command']!r}: {v}")
        ck("per-command invariant sweep is CLEAN across both runs (zero violations)",
           not all_viol, "0 violations" if not all_viol else f"{len(all_viol)} violations")
        for v in all_viol:
            finding(f"invariant violation — {v}")

        # rngCounter == number of commands issued, episode-wide
        ck("rngCounter equals the number of commands issued (one tick per command)",
           records1[-1]["after"].get("rngCounter") == len(records1),
           f"rngCounter={records1[-1]['after'].get('rngCounter')} commands={len(records1)}")

        # same-seed determinism: commands, CommandResults, rngCounter, final state
        cmds1 = [r["command"] for r in records1]
        cmds2 = [r["command"] for r in records2]
        if len(cmds1) != len(cmds2):
            ck("same-seed determinism: identical command sequence", False,
               f"length differs: run1={len(cmds1)} run2={len(cmds2)}")
        else:
            first_div = next((i for i in range(len(cmds1)) if cmds1[i] != cmds2[i]), None)
            ck("same-seed determinism: identical command sequence", first_div is None,
               "identical" if first_div is None
               else f"first divergence at index {first_div}: {cmds1[first_div]!r} vs {cmds2[first_div]!r}")
        results1 = [r["result"] for r in records1]
        results2 = [r["result"] for r in records2]
        ck("same-seed determinism: identical CommandResult stream",
           results1 == results2,
           "byte-identical results" if results1 == results2 else "CommandResults diverge")
        rng1 = [r["after"].get("rngCounter") for r in records1]
        rng2 = [r["after"].get("rngCounter") for r in records2]
        ck("same-seed determinism: identical rngCounter progression",
           rng1 == rng2, "identical" if rng1 == rng2 else f"run1={rng1} run2={rng2}")
        norm1 = _normalize_state(records1[-1]["after"])
        norm2 = _normalize_state(records2[-1]["after"])
        ck("same-seed determinism: identical normalized final player-state",
           norm1 == norm2, "identical" if norm1 == norm2 else "final states differ")
        if results1 != results2 or rng1 != rng2 or norm1 != norm2:
            finding("same-seed replay diverges — an unseeded RNG call site remains in the pipeline")

        # determinism is NON-VACUOUS: the transcript really exercises the seed
        roll_seen = any("[Success Rate:" in (r["result"].get("output", "") or "") for r in records1)
        pw_seen = any("Password: jmiller_pass" in (r["result"].get("output", "") or "") for r in records1)
        ck("determinism proof is NON-VACUOUS (transcript has the seeded roll AND drawn password)",
           roll_seen and pw_seen, f"roll={roll_seen} password={pw_seen}")

        # ── cross-seed variance sweep ────────────────────────────────────────
        print("\n  -- cross-seed variance sweep --")
        sweep = variance_sweep(ad, seed, n=8)
        distinct = set(sweep)
        ck("cross-seed sweep (8 seeds) yields >=2 distinct (exploit,crack) outcomes",
           len(distinct) >= 2, f"distinct={len(distinct)} of 8: {sorted(distinct)}")
        if len(distinct) < 2:
            finding(f"exploit/crack outcome did NOT vary across 8 seeds ({sorted(distinct)}) — "
                    f"unseeded-RNG suspected (re-check; same-seed determinism is proven separately)")

        # ── end sanity ───────────────────────────────────────────────────────
        print("\n  -- end sanity --")
        gs = final.get("gameStatus") or {}
        ck("end state: game not complete + exactly 1 story mission completed",
           gs.get("isComplete") is False and gs.get("completedStoryMissions") == 1,
           f"isComplete={gs.get('isComplete')} completedStoryMissions={gs.get('completedStoryMissions')}")

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
        print(f"ROUND 1 MET — {passed}/{total} checks. UGT drove the_breadcrumb to completion "
              f"through the real handler, rewards landed once, every refusal was state-inert, "
              f"invariants held every step, and the run replays byte-identically on the same seed. "
              f"Ready for Round 2.")
        return 0
    print(f"ROUND 1 NOT MET — {passed}/{total} checks passed. Fix the failures above and re-run.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
