#!/usr/bin/env python3
"""
DDD adapter smoke test — drives the REAL harness THROUGH DddHarnessAdapter, so the
BaseAdapter contract itself is exercised (not just raw JSON lines). 5 checks:

  1. connect() spawns a live harness process
  2. reset() returns a normalized state dict (turn / p0 / p1 / stateHash /
     resultKind == "ONGOING")
  3. several step(1) calls each return a (dict, bool, bool, dict) 4-tuple with a
     non-empty info["stateHash"], info["command"]=="act", and a known
     info["action"]["t"]
  4. _read_state() returns a normalized dict (the name the ExploitHunter probes)
  5. close() is clean

Run (from the UGT repo root; node >=24, DDD deps installed):
    python3 integrations/ddd/smoke_ddd_adapter.py

Exit 0 == 5/5.
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from ugt.adapters.ddd_harness import DddHarnessAdapter  # noqa: E402
from ugt.utils.config_parser import UgtConfig  # noqa: E402

CONFIG_PATH = "integrations/ddd/ugt.config.yaml"
KNOWN_ACTION_TYPES = {"MULLIGAN", "COMMIT_SELECTION", "COMMIT_PASS"}


def main() -> int:
    cfg = UgtConfig(CONFIG_PATH)
    ad = DddHarnessAdapter(cfg)
    checks: list[tuple[str, bool, str]] = []

    def ck(name: str, ok: bool, detail: str = ""):
        checks.append((name, ok, detail))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))

    print("DDD adapter smoke — through DddHarnessAdapter\n")
    try:
        # ── 1. connect ───────────────────────────────────────────────────────
        ad.connect()
        alive = ad.process is not None and ad.process.poll() is None
        ck("connect() spawns a live harness process", alive,
           f"pid={ad.process.pid if ad.process else None}")

        # ── 2. reset ─────────────────────────────────────────────────────────
        state = ad.reset()
        ck("reset() returns a normalized ONGOING state dict",
           isinstance(state, dict) and "turn" in state and "p0" in state
           and "p1" in state and bool(state.get("stateHash"))
           and state.get("resultKind") == "ONGOING",
           f"turn={state.get('turn')} phase={state.get('phase')} "
           f"p0.hp={state.get('p0', {}).get('hp')} p1.hp={state.get('p1', {}).get('hp')}")

        # ── 3. several steps, each a valid 4-tuple ───────────────────────────
        tuple_ok = True
        detail = []
        for _ in range(8):
            out = ad.step(1)  # commit_random policy
            good = (isinstance(out, tuple) and len(out) == 4
                    and isinstance(out[0], dict) and isinstance(out[1], bool)
                    and isinstance(out[2], bool) and isinstance(out[3], dict))
            if good:
                info = out[3]
                act = info.get("action") or {}
                good = (bool(info.get("stateHash")) and info.get("command") == "act"
                        and act.get("t") in KNOWN_ACTION_TYPES)
                detail.append(f"seat{info.get('seat')}:{act.get('t')}")
            tuple_ok = tuple_ok and good
            if out[1]:  # terminated
                detail.append(f"[term:{out[0].get('resultKind')}]")
                break
        ck("8 step(1) calls each return (dict,bool,bool,dict) with a valid act info",
           tuple_ok, " ".join(detail))

        # ── 4. _read_state returns a normalized dict ─────────────────────────
        rs = ad._read_state()
        ck("_read_state() returns a normalized dict (hunter crash-recovery hook)",
           isinstance(rs, dict) and "p0" in rs and "resultKind" in rs,
           f"resultKind={rs.get('resultKind')} turn={rs.get('turn')} "
           f"stepCount={ad.step_count}")

        # ── 5. clean close ───────────────────────────────────────────────────
        ad.close()
        ck("close() is clean (process torn down)", ad.process is None, "process=None")

    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        ck("exception-free run", False, f"{type(exc).__name__}: {exc}")
    finally:
        ad.close()

    passed = sum(1 for _, ok, _ in checks if ok)
    total = len(checks)
    print(f"\n{'=' * 70}")
    print(f"SMOKE {'PASSED' if passed == total else 'FAILED'} — {passed}/{total} checks.")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
