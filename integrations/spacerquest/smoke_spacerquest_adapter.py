#!/usr/bin/env python3
"""
SpacerQuest (Rimward) adapter smoke — drives the REAL Rimward engine THROUGH the
T-1003 stdio protocol (packages/sim/dist/protocol-stdio.js), proving the raw
UGT → Rimward wire end to end with no Gym layer in between. The full UGT
campaign (smoke-test / verify / train / evaluate at volume) runs through the
CLI via rimward_gym_bridge.py + ugt.config.yaml — see HANDOFF.md; the
SpacerQuest-side invariant sweep lives in packages/sim protocol-campaign.

The Rimward wire is line-delimited JSON: one request object per line in, one
response object per line out, in order:

    {"type":"new-game","seed":42}            -> {"type":"state-summary","summary":{...}}
    {"type":"start-day"}                     -> {"type":"state-summary","summary":{...}}   (DAWN->DAY)
    {"type":"legal-actions"}                 -> {"type":"legal-actions","legalActions":{...}}
    {"type":"apply-action","action":{...}}   -> {"type":"action-result","summary":{...},"events":[...]}
    {"type":"end-day"}                       -> {"type":"state-summary","summary":{...}}   (DAY->next DAWN)

Run (from the UGT repo root; node on PATH, SpacerQuest built):
    npm --prefix ../SpacerQuest run build -w @spacerquest/sim   # once
    python3 integrations/spacerquest/smoke_spacerquest_adapter.py

Exit 0 == all checks pass. Prints a short transcript as evidence.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
UGT_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
DEFAULT_BIN = os.path.join(UGT_ROOT, "..", "SpacerQuest", "packages", "sim", "dist", "protocol-stdio.js")
BIN = os.environ.get("SPACERQUEST_STDIO_BIN", DEFAULT_BIN)
SEED = int(os.environ.get("UGT_SEED", "42"))


class RimwardWire:
    """Minimal driver over the Rimward stdio protocol — spawn node, exchange
    line-delimited JSON. One request in, one response out."""

    def __init__(self, bin_path: str):
        self.proc = subprocess.Popen(
            ["node", bin_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    def send(self, req: dict) -> dict:
        assert self.proc.stdin and self.proc.stdout
        self.proc.stdin.write(json.dumps(req) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            err = self.proc.stderr.read() if self.proc.stderr else ""
            raise RuntimeError(f"Rimward wire closed unexpectedly. stderr: {err}")
        return json.loads(line.strip())

    def close(self) -> None:
        if self.proc.stdin:
            self.proc.stdin.close()
        self.proc.terminate()
        try:
            self.proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def form_action(spec: dict) -> dict:
    """Turn a LegalActionSpec into a concrete PlayerAction: take the fixed
    discriminants, then the FIRST legal value of every parameter domain."""
    action: dict = {"type": spec["type"]}
    for key in ("action", "storyletId", "choiceId"):
        if key in spec:
            action[key] = spec[key]
    for pkey, pspec in spec.get("params", {}).items():
        kind = pspec["kind"]
        if kind in ("die-index", "system-id", "contract-index", "enum"):
            choices = pspec["choices"]
            if not choices:
                continue
            action[pkey] = choices[0]
        elif kind == "int":
            action[pkey] = pspec["min"]
        elif kind == "fixed":
            action[pkey] = pspec["value"]
    return action


def main() -> int:
    if not os.path.exists(BIN):
        print(f"  [FAIL] built protocol bin not found: {BIN}")
        print("         Build it: npm --prefix ../SpacerQuest run build -w @spacerquest/sim")
        return 1

    wire = RimwardWire(BIN)
    checks: list[tuple[str, bool, str]] = []

    def ck(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, ok, detail))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))

    try:
        # 1. new-game → a state-summary at day 1, DAWN.
        r = wire.send({"type": "new-game", "seed": SEED})
        ck("new-game returns state-summary at DAWN",
           r.get("type") == "state-summary" and r["summary"]["phase"] == "DAWN",
           f"day={r['summary']['day']} credits={r['summary']['credits']}")

        # 2. start-day → DAY with a full dawn hand.
        r = wire.send({"type": "start-day"})
        dice = r["summary"]["diceRemaining"]
        ck("start-day rolls the day (DAY + 5 dice)",
           r["summary"]["phase"] == "DAY" and len(dice) == 5,
           f"diceRemaining={dice}")

        # 3. legal-actions → a non-empty spec list.
        r = wire.send({"type": "legal-actions"})
        specs = r["legalActions"]["actions"]
        ck("legal-actions advertises choices", r["type"] == "legal-actions" and len(specs) > 0,
           f"{len(specs)} action specs")

        # 4. Drive a handful of legal apply-actions; every one must come back as an
        #    action-result, and NONE may carry an ActionBlocked (the parity
        #    guarantee — legal-actions never advertises a blocked action).
        applied = 0
        blocked = 0
        for _ in range(20):
            legal = wire.send({"type": "legal-actions"})["legalActions"]
            specs = legal["actions"]
            if not legal["diceRemaining"] or not specs:
                wire.send({"type": "end-day"})
                wire.send({"type": "start-day"})
                continue
            action = form_action(specs[0])
            res = wire.send({"type": "apply-action", "action": action})
            if res.get("type") != "action-result":
                ck("apply-action returned action-result", False, json.dumps(res)[:120])
                break
            applied += 1
            if any(e.get("type") == "ActionBlocked" for e in res.get("events", [])):
                blocked += 1
        ck("apply-action drives ≥10 legal actions", applied >= 10, f"{applied} applied")
        ck("ZERO ActionBlocked from legal picks (protocol parity)", blocked == 0,
           f"{blocked} blocked")

        # 5. end-day advances to the next DAWN.
        # (may already be DAWN if the loop ended a day; state-summary confirms.)
        summ = wire.send({"type": "state-summary"})["summary"]
        if summ["phase"] == "DAY":
            summ = wire.send({"type": "end-day"})["summary"]
        ck("end-day / day loop lands on a fresh DAWN", summ["phase"] == "DAWN",
           f"day={summ['day']}")

    finally:
        wire.close()

    passed = sum(1 for _, ok, _ in checks if ok)
    print(f"\n  {passed}/{len(checks)} checks passed")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
