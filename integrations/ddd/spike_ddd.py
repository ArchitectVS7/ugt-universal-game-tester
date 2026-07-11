#!/usr/bin/env python3
"""
DDD protocol spike — raw-JSON-lines validation of the REAL DDD harness
(packages/harness/bin/harness.mjs) BEFORE trusting the adapter.

Spawns the harness DIRECTLY (a local `Harness` Popen helper, NO adapter) and
asserts the exact contract DddHarnessAdapter is built on. 10 GateRunner checks:

  1. create -> ok + matchId + stateHash + two views (hp30 / deck35 / hand5)
  2. legal in MULLIGAN -> ok, exactly {MULLIGAN keep, MULLIGAN full, CONCEDE}
  3. act both mulligans keep -> phase reaches SELECTION; each ok act changes hash
  4. legal in SELECTION -> ok, COMMIT_SELECTION entries + CONCEDE
  5. RULES_ERROR shape: COMMIT_PASS while a card is affordable AND a MULLIGAN in
     SELECTION each -> ok:false / applied:false / error.kind==RULES_ERROR with an
     UNCHANGED-state hash
  6. a malformed line -> PARSE_ERROR (id:null) AND the loop survives (a later
     legal still responds)
  7. an unknown op -> UNKNOWN_OP with the request id preserved
  8. same-seed initial determinism: two creates on the same seed -> identical
     initial stateHash, DIFFERENT matchId
  9. same-seed scripted match byte-identical: drive a fixed short sequence twice
     against same-seed creates -> hash streams A/B identical (first_divergence None
     and equal length)
 10. replay op -> verified:true, divergedAtTurn:null

Run (from the UGT repo root; node >=24, DDD deps installed):
    python3 integrations/ddd/spike_ddd.py

Exit 0 == 10/10. Findings print regardless — a failed check is data.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

sys.path.insert(0, ".")

from ugt.core.trial import GateRunner, first_divergence  # noqa: E402
from ugt.utils.config_parser import UgtConfig  # noqa: E402

CONFIG_PATH = "integrations/ddd/ugt.config.yaml"
SEED = "ddd-spike-seed"


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
        """Send a JSON op (auto-assigning a monotonic id); return the response."""
        self._id += 1
        op = dict(op)
        op["id"] = self._id
        return self._roundtrip(json.dumps(op))

    def send_raw(self, raw: str) -> dict:
        """Send a raw line verbatim (for the malformed-line probe)."""
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

    # convenience op builders
    def create(self, cfg, seed):
        return self.send({"op": "create", "config": cfg, "seed": seed})

    def legal(self, match_id, player):
        return self.send({"op": "legal", "matchId": match_id, "player": player})

    def act(self, match_id, action):
        return self.send({"op": "act", "matchId": match_id, "action": action})

    def replay(self, match_id):
        return self.send({"op": "replay", "matchId": match_id})

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


def _pending_seat(views):
    """Which seat the engine is waiting on, from cached views (spike-local)."""
    if views[0].get("result", {}).get("kind") != "ONGOING":
        return None
    phase = views[0].get("phase")
    if phase == "MULLIGAN":
        for s in (0, 1):
            if views[s]["me"].get("mulliganUsed") is False:
                return s
    elif phase == "SELECTION":
        for s in (0, 1):
            if views[s]["me"].get("committedSelection") is None:
                return s
    return None


def _first_non_concede(actions):
    for a in actions:
        if a.get("t") != "CONCEDE":
            return a
    return None


def drive_scripted(h, cfg, seed, nsteps):
    """Create a match on `seed` and drive a fixed deterministic policy (first legal
    non-CONCEDE action for the pending seat) for up to nsteps. Return the hash
    stream (create hash + one per applied act)."""
    resp = h.create(cfg, seed)
    views = resp["views"]
    stream = [resp["stateHash"]]
    match_id = resp["matchId"]
    for _ in range(nsteps):
        seat = _pending_seat(views)
        if seat is None:
            break
        lg = h.legal(match_id, seat)
        action = _first_non_concede(lg.get("actions", []))
        if action is None:
            break
        r = h.act(match_id, action)
        if not r.get("ok"):
            break
        views = r["views"]
        stream.append(r["stateHash"])
    return stream


def main() -> int:
    eng = UgtConfig(CONFIG_PATH).data["engine"]
    entry = os.environ.get("DDD_HARNESS_PATH") or eng["harness_entry"]
    node_bin = eng.get("node_bin", "node")
    cwd = os.environ.get("DDD_HARNESS_CWD") or os.path.abspath(
        os.path.join(os.path.dirname(entry), "..", "..", "..")
    )
    cfg = {
        "decks": eng["decks"],
        "format": eng["format"],
        "enabledWaves": eng["enabledWaves"],
        "maxTurns": eng["maxTurns"],
    }

    gate = GateRunner()
    ck, finding = gate.ck, gate.finding
    print(f"DDD spike — raw JSON-lines against {entry}\n")

    h = Harness(node_bin, entry, cwd)
    try:
        # ── 1. create ────────────────────────────────────────────────────────
        print("  -- 1. create --")
        c = h.create(cfg, SEED)
        v = c.get("views") or [{}, {}]
        me0 = v[0].get("me", {}) if len(v) > 0 else {}
        me1 = v[1].get("me", {}) if len(v) > 1 else {}
        ck("create -> ok + matchId + stateHash + two views (hp30/deck35/hand5)",
           c.get("ok") is True and c.get("matchId") and c.get("stateHash")
           and len(v) == 2
           and me0.get("hp") == 30 and me0.get("deckCount") == 35 and len(me0.get("hand", [])) == 5
           and me1.get("hp") == 30 and me1.get("deckCount") == 35 and len(me1.get("hand", [])) == 5,
           f"matchId={c.get('matchId')} hp0={me0.get('hp')} deck0={me0.get('deckCount')} "
           f"hand0={len(me0.get('hand', []))} phase={v[0].get('phase')}")
        m1 = c.get("matchId")
        create_hash = c.get("stateHash")

        # ── 2. legal in MULLIGAN ─────────────────────────────────────────────
        print("\n  -- 2. legal (MULLIGAN) --")
        lg0 = h.legal(m1, 0)
        types = sorted({a.get("t") for a in lg0.get("actions", [])})
        fulls = sorted(a.get("full") for a in lg0.get("actions", []) if a.get("t") == "MULLIGAN")
        ck("legal in MULLIGAN -> {MULLIGAN keep, MULLIGAN full, CONCEDE}",
           lg0.get("ok") is True and types == ["CONCEDE", "MULLIGAN"] and fulls == [False, True],
           f"types={types} mulligan.full={fulls}")

        # ── 3. act both mulligans keep -> SELECTION ──────────────────────────
        print("\n  -- 3. act mulligans -> SELECTION --")
        a0 = h.act(m1, {"t": "MULLIGAN", "player": 0, "full": False})
        a1 = h.act(m1, {"t": "MULLIGAN", "player": 1, "full": False})
        phase_after = a1.get("views", [{}])[0].get("phase")
        hashes_change = (a0.get("ok") and a1.get("ok")
                         and a0.get("stateHash") != create_hash
                         and a1.get("stateHash") != a0.get("stateHash"))
        ck("both mulligan keep -> phase SELECTION; each ok act changes the hash",
           phase_after == "SELECTION" and hashes_change,
           f"phase={phase_after} h0!=create={a0.get('stateHash') != create_hash} "
           f"h1!=h0={a1.get('stateHash') != a0.get('stateHash')}")
        selection_hash = a1.get("stateHash")

        # ── 4. legal in SELECTION ────────────────────────────────────────────
        print("\n  -- 4. legal (SELECTION) --")
        lg_sel = h.legal(m1, 0)
        sel_types = {a.get("t") for a in lg_sel.get("actions", [])}
        commit_entries = [a for a in lg_sel.get("actions", []) if a.get("t") == "COMMIT_SELECTION"]
        ck("legal in SELECTION -> COMMIT_SELECTION entries + CONCEDE",
           lg_sel.get("ok") is True and "COMMIT_SELECTION" in sel_types
           and "CONCEDE" in sel_types and len(commit_entries) >= 1,
           f"types={sorted(sel_types)} commit_entries={len(commit_entries)}")

        # ── 5. RULES_ERROR shape (unchanged-state hash) ──────────────────────
        print("\n  -- 5. RULES_ERROR shape --")
        r_pass = h.act(m1, {"t": "COMMIT_PASS", "player": 0})
        pass_ok = (r_pass.get("ok") is False and r_pass.get("applied") is False
                   and r_pass.get("error", {}).get("kind") == "RULES_ERROR"
                   and r_pass.get("stateHash") == selection_hash)
        r_mull = h.act(m1, {"t": "MULLIGAN", "player": 0, "full": False})
        mull_ok = (r_mull.get("ok") is False and r_mull.get("applied") is False
                   and r_mull.get("error", {}).get("kind") == "RULES_ERROR"
                   and r_mull.get("stateHash") == selection_hash)
        ck("illegal acts -> RULES_ERROR (ok:false/applied:false) + UNCHANGED hash",
           pass_ok and mull_ok,
           f"COMMIT_PASS: code={r_pass.get('error', {}).get('rulesError', {}).get('code')} "
           f"hashUnchanged={r_pass.get('stateHash') == selection_hash}; "
           f"MULLIGAN-in-SELECTION: code={r_mull.get('error', {}).get('rulesError', {}).get('code')} "
           f"hashUnchanged={r_mull.get('stateHash') == selection_hash}")

        # ── 6. malformed line -> PARSE_ERROR, loop survives ──────────────────
        print("\n  -- 6. malformed line + loop survival --")
        bad = h.send_raw("this is not valid json {{{")
        parse_ok = (bad.get("op") == "error" and bad.get("id") is None
                    and bad.get("error", {}).get("kind") == "PARSE_ERROR")
        survived = h.legal(m1, 0)
        ck("malformed line -> PARSE_ERROR (id:null) AND loop survives",
           parse_ok and survived.get("ok") is True,
           f"parseErr={parse_ok} nextLegalOk={survived.get('ok')}")

        # ── 7. unknown op -> UNKNOWN_OP, id preserved ────────────────────────
        print("\n  -- 7. unknown op --")
        unk = h.send({"op": "frobnicate", "matchId": m1})
        ck("unknown op -> UNKNOWN_OP with the request id preserved",
           unk.get("error", {}).get("kind") == "UNKNOWN_OP" and unk.get("id") is not None,
           f"kind={unk.get('error', {}).get('kind')} id={unk.get('id')}")

        # ── 8. same-seed initial determinism ─────────────────────────────────
        print("\n  -- 8. same-seed initial determinism --")
        cA = h.create(cfg, SEED)
        cB = h.create(cfg, SEED)
        ck("two creates on the same seed -> identical initial hash, DIFFERENT matchId",
           cA.get("stateHash") == cB.get("stateHash")
           and cA.get("matchId") != cB.get("matchId"),
           f"hashEqual={cA.get('stateHash') == cB.get('stateHash')} "
           f"matchIds={cA.get('matchId')}/{cB.get('matchId')}")

        # ── 9. same-seed scripted match byte-identical ───────────────────────
        print("\n  -- 9. same-seed scripted match --")
        streamA = drive_scripted(h, cfg, SEED, nsteps=12)
        streamB = drive_scripted(h, cfg, SEED, nsteps=12)
        div = first_divergence(streamA, streamB)
        ck("same-seed scripted match -> byte-identical hash stream (>init)",
           len(streamA) == len(streamB) and div is None and len(streamA) > 1,
           f"lenA={len(streamA)} lenB={len(streamB)} firstDiv={div}")
        if div is not None or len(streamA) != len(streamB):
            finding("same-seed scripted match diverged — an unseeded RNG call site "
                    "remains in the engine/harness")

        # ── 10. replay op ────────────────────────────────────────────────────
        print("\n  -- 10. replay --")
        # Drive a fresh match a few plies, then replay-verify it.
        rc = h.create(cfg, SEED)
        rmid = rc["matchId"]
        rviews = rc["views"]
        for _ in range(6):
            seat = _pending_seat(rviews)
            if seat is None:
                break
            lg = h.legal(rmid, seat)
            action = _first_non_concede(lg.get("actions", []))
            if action is None:
                break
            ra = h.act(rmid, action)
            if not ra.get("ok"):
                break
            rviews = ra["views"]
        rep = h.replay(rmid)
        ck("replay -> verified:true, divergedAtTurn:null",
           rep.get("ok") is True and rep.get("verified") is True
           and rep.get("divergedAtTurn") is None,
           f"verified={rep.get('verified')} divergedAtTurn={rep.get('divergedAtTurn')}")
        if rep.get("verified") is not True:
            finding(f"replay did not verify: {rep!r}")

    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        ck("exception-free run", False, f"{type(exc).__name__}: {exc}")
    finally:
        h.close()

    return gate.finish(
        "SPIKE",
        "The raw DDD harness contract holds — create/legal/act/replay, RULES_ERROR "
        "on illegal moves with unchanged state, PARSE_ERROR/UNKNOWN_OP resilience, "
        "and same-seed determinism (initial + scripted). Adapter can be trusted.")


if __name__ == "__main__":
    sys.exit(main())
