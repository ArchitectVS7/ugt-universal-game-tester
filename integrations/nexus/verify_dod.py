#!/usr/bin/env python3
"""
NEXUS Phase-0 definition-of-done — ONE full hack loop through the REAL game,
driven THROUGH NexusHttpAdapter (transport primitives + type_text), asserting the
real observable state moved. This is the P0-2 gate for "UGT can actually play the
game", not just reach it.

The loop (post_tutorial baseline, so the surface is unlocked — R0/NX-P0-1):
    reset -> scan -> connect 192.168.1.105 -> exploit weak_password -> cat <file>
Definition of done (all must hold):
  A. connect surfaced a real currentServerId (carried by the adapter, since the
     closed-alpha route is stateless on nav — R3)
  B. a compromisedServers entry APPEARS in player-state after the exploit
  C. rngCounter advanced exactly once per command issued (no double/zero draws)
  D. no negative resources (credits >= 0, xp non-decreasing)
  E. no crash / no soft-lock (every command returned a JSON CommandResult)

Run (server up on :3100):
    python3 integrations/nexus/verify_dod.py

Exit 0 == DoD MET.
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from ugt.adapters.nexus_http import NexusHttpAdapter
from ugt.utils.config_parser import UgtConfig

CONFIG_PATH = "integrations/nexus/ugt.config.yaml"
HACK_IP = "192.168.1.105"       # neighbor_pc (seed-story), securityLevel 2, weak_password
HACK_VULN = "weak_password"
# A file that exists on neighbor_pc per the winnable-story fixtures.
HACK_FILE = "/Users/jmiller/Documents/work_vpn.txt"


def main() -> int:
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

    print("NEXUS Phase-0 DoD — one full hack loop through the REAL game\n")
    try:
        ad.connect()
        state0 = ad.reset()
        counter0 = state0.get("rngCounter", 0)
        xp0 = state0.get("xp", 0)
        commands_issued = 0
        no_crash = True

        def drive(command):
            nonlocal commands_issued, no_crash
            s, term, trunc, info = ad.type_text_step(command)
            commands_issued += 1
            res = info.get("result") or {}
            if not isinstance(res, dict) or "success" not in res:
                no_crash = False
            return s, res

        print(f"  reset baseline={ad.baseline}: level={state0.get('level')} "
              f"discovered={state0.get('discoveredServersCount')} "
              f"compromised={state0.get('compromisedServersCount')} rngCounter={counter0}")

        # scan (recon) -----------------------------------------------------
        s_scan, r_scan = drive("scan")
        ck("scan is unlocked and succeeds (R0 resolved by post_tutorial baseline)",
           bool(r_scan.get("success")),
           "scan refused — R0 unresolved; is baseline=post_tutorial?" if not r_scan.get("success")
           else f"discovered={s_scan.get('discoveredServersCount')} servers")

        # connect (nav-state carry) ----------------------------------------
        s_conn, r_conn = drive(f"connect {HACK_IP}")
        carried_sid = ad._cur_server_id
        ck("A. connect surfaced a currentServerId the adapter carries forward",
           bool(r_conn.get("success")) and bool(carried_sid),
           f"currentServerId={carried_sid}")

        # exploit (compromise) ---------------------------------------------
        s_exp, r_exp = drive(f"exploit {HACK_VULN}")
        ck("exploit executed its real (seeded) success roll",
           "Success Rate" in (r_exp.get("output") or ""),
           "no roll in output — command may be locked/mis-routed"
           if "Success Rate" not in (r_exp.get("output") or "") else "roll fired")
        comp = s_exp.get("compromisedServers") or []
        compromised_here = any(c.get("ipAddress") == HACK_IP for c in comp)
        ck("B. a compromisedServers entry appears in player-state",
           compromised_here,
           f"compromised={[c.get('ipAddress') for c in comp]}")
        if not compromised_here and r_exp.get("success"):
            finding("exploit reported success but no compromisedServers row appeared — "
                    "persistence gap between the command handler and player-state")

        # cat (read on the compromised host) -------------------------------
        s_cat, r_cat = drive(f"cat {HACK_FILE}")
        # cat may legitimately fail if the file path differs; it's part of the loop
        # for exercise, not a hard gate. Record honestly.
        if not r_cat.get("success"):
            finding(f"cat {HACK_FILE} did not succeed ({r_cat.get('error')!r}) — the loop still "
                    f"proved compromise via exploit; the exact fixture path may differ")

        # ── invariants ────────────────────────────────────────────────────
        final = ad._read_state()
        counter_final = final.get("rngCounter", 0)
        ck("C. rngCounter advanced exactly once per command",
           counter_final - counter0 == commands_issued,
           f"issued={commands_issued} counterDelta={counter_final - counter0}")
        ck("D. no negative resources (credits>=0, xp non-decreasing)",
           final.get("credits", 0) >= 0 and final.get("xp", 0) >= xp0,
           f"credits={final.get('credits')} xp {xp0}->{final.get('xp')}")
        ck("E. no crash / soft-lock (every command returned a CommandResult)",
           no_crash, "all commands returned JSON CommandResults")

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
        print("FINDINGS / notes:")
        for i, f in enumerate(findings, 1):
            print(f"  {i}. {f}")
        print()
    if passed == total:
        print(f"DoD MET — {passed}/{total} checks. UGT drove a real hack loop (scan -> connect -> "
              f"exploit -> compromise) through the adapter against the live server.")
        return 0
    print(f"DoD NOT MET — {passed}/{total} checks passed.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
