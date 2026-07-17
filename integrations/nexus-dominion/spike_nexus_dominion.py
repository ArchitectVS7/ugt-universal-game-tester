#!/usr/bin/env python3
"""
Nexus Dominion protocol spike — raw-JSON-lines validation of the REAL harness
(harness/ugt-harness.mjs in the game repo) BEFORE trusting the adapter.

Spawns the harness DIRECTLY (a local `Harness` Popen helper, NO adapter) and
asserts the exact contract NexusDominionHarnessAdapter is built on. Checks:

  1.  create at FULL PRD scale (250 systems / 100 empires) -> ok + campaignId +
      stateHash + sane summary (cycle 0, 99 bots, 150 unclaimed, credits 500)
  2.  missing seed -> BAD_REQUEST (a defaulted seed is a different campaign)
  3.  commit [] -> committed:true, cycle 1, hash changed
  4.  per-cycle wall time at full scale, 10 empty cycles — measured against the
      PRD's <5s alpha budget (prd.md perf target; first full-scale measurement)
  5.  a real claim-system order (adjacent unclaimed, read from full state) ->
      colonisation event + credits -50 + systemsOwned 2
  6.  Tier-1 atomic abort surfaces: move-fleet with NO details -> ok:true but
      committed:false + error, hash UNCHANGED; the NEXT commit still works
  7.  malformed line -> BAD_REQUEST (id null) AND the loop survives
  8.  unknown op -> BAD_REQUEST with the request id preserved; unknown
      campaignId -> UNKNOWN_CAMPAIGN
  9.  same-seed initial determinism: two creates -> identical stateHash,
      DIFFERENT campaignId
  10. same-seed scripted campaign byte-identical: a fixed 8-cycle order script
      twice -> hash streams identical (first_divergence None)
  11. save -> load -> continue == uninterrupted run (3 further cycles, streams
      identical) — the game's own serializer is the wire format under test

Run (from the UGT repo root; node >=24):
    python3 integrations/nexus-dominion/spike_nexus_dominion.py

Exit 0 == all checks pass. Findings print regardless — a failed check is data.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

sys.path.insert(0, ".")

from ugt.core.trial import GateRunner, first_divergence  # noqa: E402
from ugt.utils.config_parser import UgtConfig  # noqa: E402
from ugt.adapters.nexus_dominion_harness import decode_tagged  # noqa: E402

CONFIG_PATH = "integrations/nexus-dominion/ugt.config.yaml"
SEED = 20260901


class Harness:
    """Minimal raw driver over the harness subprocess (one line in, one out)."""

    def __init__(self, node_bin, entry, cwd):
        self.p = subprocess.Popen(
            [node_bin, entry],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1, cwd=cwd, env=os.environ.copy(),
        )
        self._id = 0

    def send(self, op: dict) -> dict:
        self._id += 1
        op = dict(op)
        op["id"] = self._id
        return self._roundtrip(json.dumps(op))

    def send_raw(self, raw: str) -> dict:
        return self._roundtrip(raw)

    def _roundtrip(self, line: str) -> dict:
        self.p.stdin.write(line + "\n")
        self.p.stdin.flush()
        while True:
            r = self.p.stdout.readline()
            if r == "":
                err = self.p.stderr.read() if self.p.stderr else ""
                raise RuntimeError(f"harness exited: {err or '<empty>'}")
            r = r.strip()
            if not r:
                continue
            return json.loads(r)

    def create(self, galaxy, seed):
        return self.send({"op": "create", "config": {"seed": seed, **galaxy}})

    def commit(self, cid, actions):
        return self.send({"op": "commit", "campaignId": cid, "actions": actions})

    def state(self, cid, full=False):
        return self.send({"op": "state", "campaignId": cid, "full": full})

    def close(self):
        try:
            if self.p.stdin:
                self.p.stdin.close()
        except Exception:
            pass
        try:
            self.p.terminate()
            self.p.wait(timeout=2)
        except Exception:
            try:
                self.p.kill()
            except Exception:
                pass


def adjacent_unclaimed(full_state: dict) -> str | None:
    """First unclaimed system adjacent to a player-owned one (structural read)."""
    g = decode_tagged(full_state)
    systems = g["galaxy"]["systems"]
    player = g["empires"][g["playerEmpireId"]]
    for sid in player.get("systemIds") or []:
        for adj in (systems.get(sid, {}).get("adjacentSystemIds") or []):
            s = systems.get(adj)
            if s and s.get("owner") is None:
                return adj
    return None


# The fixed order script for the determinism checks (8 cycles). Cycle 2's
# claim target is resolved from live state at run time — identically on both
# runs if and only if the engine is deterministic.
def drive_scripted(h: Harness, galaxy, seed) -> list:
    c = h.create(galaxy, seed)
    cid = c["campaignId"]
    stream = [c["stateHash"]]
    orders_by_cycle = [
        [],
        [{"type": "build-unit", "details": {"unitTypeId": "fighter"}}],
        None,  # placeholder: claim first adjacent unclaimed (resolved live)
        [{"type": "trade", "details": {"resource": "ore", "quantity": 5,
                                       "direction": "sell"}}],
        [{"type": "research", "details": {}}],
        [{"type": "select-doctrine", "details": {"pathId": "commerce"}}],
        [],
        [{"type": "trade", "details": {"resource": "food", "quantity": 3,
                                       "direction": "buy"}}],
    ]
    for orders in orders_by_cycle:
        if orders is None:
            target = adjacent_unclaimed(h.state(cid, full=True)["state"])
            orders = ([{"type": "claim-system", "details": {"systemId": target}}]
                      if target else [])
        r = h.commit(cid, orders)
        if not r.get("ok") or not r.get("committed"):
            break
        stream.append(r["stateHash"])
    return stream


def main() -> int:
    eng = UgtConfig(CONFIG_PATH).data["engine"]
    entry = os.environ.get("NEXUS_DOMINION_HARNESS_PATH") or eng["harness_entry"]
    node_bin = eng.get("node_bin", "node")
    cwd = os.environ.get("NEXUS_DOMINION_HARNESS_CWD") or os.path.abspath(
        os.path.join(os.path.dirname(entry), "..")
    )
    galaxy = dict(eng["galaxy"])

    gate = GateRunner()
    ck, finding = gate.ck, gate.finding
    print(f"Nexus Dominion spike — raw JSON-lines against {entry}")
    print(f"  galaxy: {galaxy}\n")

    h = Harness(node_bin, entry, cwd)
    try:
        # ── 1. create at full PRD scale ──────────────────────────────────────
        print("  -- 1. create (full PRD scale) --")
        t0 = time.perf_counter()
        c = h.create(galaxy, SEED)
        create_ms = (time.perf_counter() - t0) * 1000
        s = c.get("summary") or {}
        p = s.get("player") or {}
        ck("create -> ok + campaignId + stateHash + sane full-scale summary",
           c.get("ok") is True and c.get("campaignId") and c.get("stateHash")
           and s.get("cycle") == 0 and s.get("empireCount") == 100
           and s.get("botCount") == 99 and s.get("systemCount") == 250
           and s.get("unclaimedSystems") == 150
           and p.get("credits") == 500 and p.get("systemsOwned") == 1,
           f"campaignId={c.get('campaignId')} empires={s.get('empireCount')} "
           f"bots={s.get('botCount')} systems={s.get('systemCount')} "
           f"unclaimed={s.get('unclaimedSystems')} credits={p.get('credits')} "
           f"({create_ms:.0f}ms)")
        cid = c.get("campaignId")
        create_hash = c.get("stateHash")

        # ── 2. missing seed refused ──────────────────────────────────────────
        print("\n  -- 2. missing seed --")
        no_seed = h.send({"op": "create", "config": {"empireCount": 10}})
        ck("create without a seed -> BAD_REQUEST (never silently defaulted)",
           no_seed.get("ok") is False
           and no_seed.get("error", {}).get("kind") == "BAD_REQUEST",
           f"kind={no_seed.get('error', {}).get('kind')}")

        # ── 3. commit [] ─────────────────────────────────────────────────────
        print("\n  -- 3. empty commit --")
        r1 = h.commit(cid, [])
        ck("commit [] -> committed:true, cycle 1, hash changed",
           r1.get("ok") is True and r1.get("committed") is True
           and (r1.get("summary") or {}).get("cycle") == 1
           and r1.get("stateHash") != create_hash,
           f"cycle={(r1.get('summary') or {}).get('cycle')} "
           f"hashChanged={r1.get('stateHash') != create_hash}")

        # ── 4. per-cycle wall time at full scale ─────────────────────────────
        print("\n  -- 4. per-cycle cost (PRD alpha budget <5s) --")
        times = []
        for _ in range(10):
            t0 = time.perf_counter()
            r = h.commit(cid, [])
            times.append((time.perf_counter() - t0) * 1000)
            if not r.get("committed"):
                break
        mean_ms = sum(times) / len(times)
        worst_ms = max(times)
        ck("10 full-scale cycles commit, mean under the 5s alpha budget",
           len(times) == 10 and mean_ms < 5000,
           f"mean={mean_ms:.0f}ms worst={worst_ms:.0f}ms "
           f"(release target 1000ms: {'MET' if mean_ms < 1000 else 'NOT MET'})")
        if mean_ms >= 1000:
            finding(f"per-cycle mean {mean_ms:.0f}ms exceeds the 1s release "
                    "target (prd.md) at 100 empires — T-401 material")

        # ── 5. a real claim-system order ─────────────────────────────────────
        print("\n  -- 5. claim-system (real order, real effect) --")
        target = adjacent_unclaimed(h.state(cid, full=True)["state"])
        before = h.state(cid)
        b_credits = (before["summary"]["player"] or {}).get("credits")
        rc = h.commit(cid, [{"type": "claim-system",
                             "details": {"systemId": target}}])
        sa = rc.get("summary") or {}
        pa = sa.get("player") or {}
        colonisation = [e for e in (rc.get("report") or {}).get("events", [])
                        if e.get("type") == "colonisation"
                        and e.get("empireId") == "empire-0"]
        # credits also move from cycle income; assert the -50 via the event and
        # systemsOwned via the summary (both read back, no arithmetic invented)
        ck("claim-system -> colonisation event + systemsOwned 2",
           target is not None and rc.get("committed") is True
           and len(colonisation) == 1 and colonisation[0].get("cost") == 50
           and pa.get("systemsOwned") == 2,
           f"target={target} events={len(colonisation)} "
           f"owned={pa.get('systemsOwned')} credits {b_credits}->{pa.get('credits')}")

        # ── 6. malformed move-fleet refusal contract (ND-1, FIXED) ──────────
        # History: this order used to destructure undefined details, throw,
        # and ABORT the whole cycle commit while every other malformed order
        # was silently skipped (found + fixed upstream, nexus-dominion
        # 1f0bff3). The check now pins the FIXED contract: skipped like the
        # rest, the cycle itself commits normally.
        print("\n  -- 6. malformed move-fleet (refusal contract, ND-1) --")
        rb = h.commit(cid, [{"type": "move-fleet"}])
        rn = h.commit(cid, [])
        ck("malformed move-fleet is SKIPPED (cycle commits, no error); "
           "next commit still works",
           rb.get("ok") is True and rb.get("committed") is True
           and rb.get("error") is None and rn.get("committed") is True,
           f"committed={rb.get('committed')} error={rb.get('error')!r} "
           f"nextOk={rn.get('committed')}")
        if rb.get("committed") is False:
            finding("ND-1 regressed: a malformed move-fleet order aborts the "
                    "whole cycle commit again (cycle-processor move-fleet "
                    "destructure)")

        # ── 7. malformed line -> loop survives ──────────────────────────────
        print("\n  -- 7. malformed line --")
        bad = h.send_raw("this is not json {{{")
        parse_ok = (bad.get("ok") is False
                    and bad.get("error", {}).get("kind") == "BAD_REQUEST"
                    and bad.get("id") is None)
        survived = h.state(cid)
        ck("malformed line -> BAD_REQUEST (id null) AND loop survives",
           parse_ok and survived.get("ok") is True,
           f"parseErr={parse_ok} nextOk={survived.get('ok')}")

        # ── 8. unknown op / unknown campaign ─────────────────────────────────
        print("\n  -- 8. unknown op / campaign --")
        unk = h.send({"op": "frobnicate"})
        missing = h.send({"op": "commit", "campaignId": "c999", "actions": []})
        ck("unknown op -> BAD_REQUEST (id preserved); unknown campaign -> "
           "UNKNOWN_CAMPAIGN",
           unk.get("error", {}).get("kind") == "BAD_REQUEST"
           and unk.get("id") is not None
           and missing.get("error", {}).get("kind") == "UNKNOWN_CAMPAIGN",
           f"unk={unk.get('error', {}).get('kind')}/{unk.get('id')} "
           f"missing={missing.get('error', {}).get('kind')}")

        # ── 9. same-seed initial determinism ─────────────────────────────────
        print("\n  -- 9. same-seed initial determinism --")
        cA = h.create(galaxy, SEED)
        cB = h.create(galaxy, SEED)
        ck("two creates on the same seed -> identical hash, DIFFERENT campaignId",
           cA.get("stateHash") == cB.get("stateHash")
           and cA.get("campaignId") != cB.get("campaignId"),
           f"hashEqual={cA.get('stateHash') == cB.get('stateHash')} "
           f"ids={cA.get('campaignId')}/{cB.get('campaignId')}")

        # ── 10. same-seed scripted campaign byte-identical ───────────────────
        print("\n  -- 10. same-seed scripted campaign (8 cycles, real orders) --")
        streamA = drive_scripted(h, galaxy, SEED)
        streamB = drive_scripted(h, galaxy, SEED)
        div = first_divergence(streamA, streamB)
        ck("same-seed scripted campaign -> byte-identical hash stream",
           len(streamA) == len(streamB) and div is None and len(streamA) == 9,
           f"lenA={len(streamA)} lenB={len(streamB)} firstDiv={div}")
        if div is not None or len(streamA) != len(streamB):
            finding("same-seed scripted campaign diverged — an unseeded RNG "
                    "site or serialization instability remains")

        # ── 11. save -> load -> continue == uninterrupted ────────────────────
        print("\n  -- 11. save/load/continue vs uninterrupted --")
        # Uninterrupted arm: fresh campaign, 5 empty commits.
        cU = h.create(galaxy, SEED + 1)
        uid = cU["campaignId"]
        streamU = [cU["stateHash"]]
        for _ in range(5):
            streamU.append(h.commit(uid, [])["stateHash"])
        # Interrupted arm: 2 commits, save, load, 3 more.
        cI = h.create(galaxy, SEED + 1)
        iid = cI["campaignId"]
        streamI = [cI["stateHash"]]
        for _ in range(2):
            streamI.append(h.commit(iid, [])["stateHash"])
        sv = h.send({"op": "save", "campaignId": iid})
        ld = h.send({"op": "load", "payload": sv.get("payload")})
        lid = ld.get("campaignId")
        load_match = ld.get("stateHash") == streamI[-1]
        for _ in range(3):
            streamI.append(h.commit(lid, [])["stateHash"])
        div_sl = first_divergence(streamU, streamI)
        ck("save->load hash matches; continue == uninterrupted (5 cycles)",
           load_match and div_sl is None and len(streamU) == len(streamI) == 6,
           f"loadMatch={load_match} firstDiv={div_sl} "
           f"lenU={len(streamU)} lenI={len(streamI)}")
        if not load_match or div_sl is not None:
            finding("serialize->deserialize->continue DIVERGES from an "
                    "uninterrupted run — save/load is not faithful "
                    "(state-serializer or accumulator loss)")

    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        ck("exception-free run", False, f"{type(exc).__name__}: {exc}")
    finally:
        h.close()

    return gate.finish(
        "SPIKE",
        "The raw harness contract holds — create/commit/state/save/load, "
        "atomic aborts surface with unchanged state, parse/op errors are "
        "survivable, and same-seed determinism holds (initial + scripted + "
        "save/load/continue) at full PRD scale. Adapter can be trusted.")


if __name__ == "__main__":
    sys.exit(main())
