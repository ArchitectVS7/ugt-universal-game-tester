#!/usr/bin/env python3
"""
NEXUS protocol spike — raw-HTTP validation of the three UGT test routes against
the REAL running nexus-world-builder server (apps/game, `next dev` on :3100).

This is the ground-truth probe BEFORE trusting the adapter: it speaks plain
`requests` to bootstrap-player / reset-episode / closed-alpha / player-state and
asserts the contract the NexusHttpAdapter is built on. 8 checks:

  1. bootstrap-player is well-formed (userId + playerId)
  2. reset pins the seed: two post_tutorial resets on the SAME seed return
     rngSeed==seed / rngCounter==0, AND a seed-DEPENDENT command (exploit's
     seeded success roll) replays byte-identical across the two resets — and is
     a REAL command result (has the success-rate roll), not a rejection string
  3. six commands return a well-formed CommandResult (JSON, no 500/HTML)
  4. player-state reflects a real state change (a compromise appears)
  5. an invariant holds: rngCounter advances exactly once per command
  6. a garbage command is inert (success:false, gameplay state unchanged)
  7. a FRESH reset is the documented blank slate (level 1 / xp 0 / credits 1000)

Run (server up — verify the LISTEN pid is yours: lsof -nP -iTCP:3100 -sTCP:LISTEN):
    python3 integrations/nexus/spike_nexus.py

Exit 0 == 7/7. Findings are printed regardless — a failed check is data.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, ".")

import requests

from ugt.utils.config_parser import UgtConfig

CONFIG_PATH = "integrations/nexus/ugt.config.yaml"
SEED = "nexus-spike-seed"
# neighbor_pc — seeded by prisma/seed-story.ts, securityLevel 2, weak_password vuln.
HACK_IP = "192.168.1.105"
HACK_VULN = "weak_password"


def main() -> int:
    cfg = UgtConfig(CONFIG_PATH).data["engine"]
    base = str(cfg.get("base_url")).rstrip("/")
    key = cfg.get("api_key") or os.environ.get("TEST_API_KEY")
    if not key:
        print("No API key (engine.api_key / TEST_API_KEY). Aborting.")
        return 1

    s = requests.Session()
    s.headers.update({"X-Test-API-Key": key, "Content-Type": "application/json"})

    checks: list[tuple[str, bool, str]] = []
    findings: list[str] = []

    def ck(name: str, ok: bool, detail: str = ""):
        checks.append((name, ok, detail))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))

    def finding(text: str):
        findings.append(text)
        print(f"  [FINDING] {text}")

    def post(path, body, timeout=60):
        r = s.post(f"{base}{path}", json=body, timeout=timeout)
        return r

    def cmd(player_id, command, server_id=None, path="/"):
        return post("/api/test/closed-alpha", {
            "playerId": player_id, "command": command,
            "currentServerId": server_id, "currentPath": path,
        }).json()

    def pstate(player_id):
        return s.get(f"{base}/api/test/player-state",
                     params={"playerId": player_id}, timeout=30).json()

    def reset(player_id, seed, baseline="post_tutorial"):
        return post("/api/test/reset-episode", {
            "playerId": player_id, "seed": seed,
            "difficulty": "normal", "baseline": baseline,
        }).json()

    print(f"NEXUS spike — raw HTTP against {base}\n")
    try:
        # ── 1. bootstrap ─────────────────────────────────────────────────────
        print("  -- 1. bootstrap --")
        boot = post("/api/test/bootstrap-player", {"prefix": "spike"}).json()
        pid = boot.get("playerId")
        ck("bootstrap-player returns userId + playerId",
           bool(pid) and bool(boot.get("userId")),
           f"playerId={pid}")

        # ── 2. reset pins seed + seed-dependent replay ───────────────────────
        print("\n  -- 2. seed pinning + seed-dependent replay --")

        def episode_exploit_output(seed):
            rr = reset(pid, seed)
            # connect surfaces the real server id; exploit draws the seeded roll.
            c = cmd(pid, f"connect {HACK_IP}")
            sid = (c.get("stateChanges") or {}).get("currentServerId")
            ex = cmd(pid, f"exploit {HACK_VULN}", server_id=sid)
            return rr, ex.get("output", "")

        r1, out1 = episode_exploit_output(SEED)
        r2, out2 = episode_exploit_output(SEED)
        seed_pinned = (r1.get("rngSeed") == SEED and r1.get("rngCounter") == 0
                       and r2.get("rngSeed") == SEED and r2.get("rngCounter") == 0)
        genuine = ("Success Rate" in out1) and ("Command not found" not in out1)
        ck("reset pins rngSeed/rngCounter:0 on both resets", seed_pinned,
           f"r1=({r1.get('rngSeed')},{r1.get('rngCounter')}) r2=({r2.get('rngSeed')},{r2.get('rngCounter')})")
        ck("a seed-DEPENDENT command replays byte-identical (and is a real roll)",
           out1 == out2 and genuine,
           "exploit output identical + contains the success-rate roll"
           if (out1 == out2 and genuine)
           else f"identical={out1 == out2} genuine_roll={genuine}")
        if out1 != out2:
            finding("same-seed exploit output diverges — an unseeded RNG call site remains "
                    "in the command pipeline")

        # cross-check seed-DEPENDENCE (informational): the exploit roll draws the
        # seeded RNG, so its OUTCOME must vary across seeds. NOTE the base success
        # rate here is ~90% (level 5 vs securityLevel 2), so most seeds succeed —
        # a couple of seeds colliding on the same outcome is EXPECTED, not a bug.
        # Sweep enough seeds to observe the variance directly.
        sweep_outcomes = set()
        for i in range(16):
            _, o = episode_exploit_output(f"{SEED}-sweep-{i}")
            sweep_outcomes.add("OK" if "successful" in o else "FAIL")
        if len(sweep_outcomes) > 1:
            print(f"       (seed-dependence confirmed: exploit outcome varied across 16 seeds "
                  f"-> {sweep_outcomes})")
        else:
            finding(f"exploit outcome did NOT vary across 16 seeds (all {sweep_outcomes}) — at a "
                    f"~90% success rate an all-same run is statistically plausible (~19%), and "
                    f"same-seed determinism is separately proven above; re-run to confirm before "
                    f"treating as an unseeded-RNG defect")

        # ── 3. six commands are well-formed CommandResults ───────────────────
        print("\n  -- 3. six well-formed CommandResults --")
        reset(pid, SEED)
        c_conn = cmd(pid, f"connect {HACK_IP}")
        sid = (c_conn.get("stateChanges") or {}).get("currentServerId")
        samples = {
            "status": cmd(pid, "status"),
            "help": cmd(pid, "help"),
            "missions": cmd(pid, "missions"),
            "scan": cmd(pid, "scan"),
            "connect": c_conn,
            "exploit": cmd(pid, f"exploit {HACK_VULN}", server_id=sid),
        }
        malformed = [k for k, v in samples.items()
                     if not isinstance(v, dict) or "success" not in v or "output" not in v]
        ck("6 commands return well-formed CommandResult (no 500/HTML)",
           not malformed,
           f"malformed={malformed}" if malformed else "all have success+output")

        # ── 4. player-state reflects a state change ──────────────────────────
        print("\n  -- 4. observable state change --")
        st = pstate(pid)
        comp = st.get("compromisedServers") or []
        ck("player-state shows the exploit's compromise",
           any(cs.get("ipAddress") == HACK_IP for cs in comp),
           f"compromisedServers={[cs.get('ipAddress') for cs in comp]}")

        # ── 5. invariant: rngCounter advances once per command ───────────────
        print("\n  -- 5. rngCounter invariant --")
        reset(pid, SEED)
        before_counter = pstate(pid).get("rngCounter")
        for c in ("status", "help", "scan"):
            cmd(pid, c)
        after_counter = pstate(pid).get("rngCounter")
        delta = (after_counter or 0) - (before_counter or 0)
        ck("rngCounter advances exactly once per command (3 commands -> +3)",
           delta == 3, f"before={before_counter} after={after_counter} delta={delta}")

        # ── 6. garbage command is inert ──────────────────────────────────────
        print("\n  -- 6. refusal is inert --")
        reset(pid, SEED)
        st_before = pstate(pid)
        garbage = cmd(pid, "zzqqwertybogus")
        st_after = pstate(pid)
        gameplay_unchanged = (
            st_before.get("level") == st_after.get("level")
            and st_before.get("xp") == st_after.get("xp")
            and st_before.get("credits") == st_after.get("credits")
            and (st_before.get("compromisedServers") or []) == (st_after.get("compromisedServers") or [])
        )
        ck("garbage command -> success:false and gameplay state unchanged",
           garbage.get("success") is False and gameplay_unchanged,
           f"success={garbage.get('success')} gameplay_unchanged={gameplay_unchanged}")
        counter_ticked = (st_after.get("rngCounter") or 0) - (st_before.get("rngCounter") or 0)
        if counter_ticked:
            finding(f"a rejected command still advanced rngCounter by {counter_ticked} — this is "
                    f"BY DESIGN in NEXUS (handler ticks the cursor unconditionally, before command "
                    f"lookup, for position-stable replay), noted for completeness, not a defect")

        # ── 7. fresh reset is the blank slate ────────────────────────────────
        print("\n  -- 7. fresh baseline blank slate --")
        reset(pid, SEED, baseline="fresh")
        fresh = pstate(pid)
        ck("fresh reset -> level 1 / xp 0 / credits 1000",
           fresh.get("level") == 1 and str(fresh.get("xp")) == "0" and str(fresh.get("credits")) == "1000",
           f"level={fresh.get('level')} xp={fresh.get('xp')} credits={fresh.get('credits')}")

    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        ck("exception-free run", False, f"{type(exc).__name__}: {exc}")

    passed = sum(1 for _, ok, _ in checks if ok)
    total = len(checks)
    print(f"\n{'=' * 70}")
    if findings:
        print("FINDINGS / notes:")
        for i, f in enumerate(findings, 1):
            print(f"  {i}. {f}")
        print()
    print(f"SPIKE {'PASSED' if passed == total else 'FAILED'} — {passed}/{total} checks.")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
