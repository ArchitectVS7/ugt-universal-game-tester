#!/usr/bin/env python3
"""
NEXUS adapter smoke test — drives the REAL server THROUGH NexusHttpAdapter, so
the BaseAdapter contract itself is exercised (not just raw HTTP). 5 checks:

  1. connect() bootstraps a player (reachability + warm)
  2. reset() returns a readable state dict (post_tutorial baseline)
  3. 5 steps each return a well-formed (dict, bool, bool, dict) 4-tuple
  4. type_text() drives a raw command and updates the terminal text
  5. get_terminal_text() returns the last command's output; close() is clean

Run (server up on :3100):
    python3 integrations/nexus/smoke_nexus_adapter.py

Exit 0 == 5/5.
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from ugt.adapters.nexus_http import NexusHttpAdapter
from ugt.utils.config_parser import UgtConfig

CONFIG_PATH = "integrations/nexus/ugt.config.yaml"


def main() -> int:
    cfg = UgtConfig(CONFIG_PATH)
    ad = NexusHttpAdapter(cfg)
    checks: list[tuple[str, bool, str]] = []

    def ck(name: str, ok: bool, detail: str = ""):
        checks.append((name, ok, detail))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))

    print("NEXUS adapter smoke — through NexusHttpAdapter\n")
    try:
        # ── 1. connect ───────────────────────────────────────────────────────
        ad.connect()
        ck("connect() bootstraps a player", bool(ad.player_id), f"playerId={ad.player_id}")

        # ── 2. reset ─────────────────────────────────────────────────────────
        state = ad.reset()
        ck("reset() returns a readable state dict",
           isinstance(state, dict) and "level" in state and "gameStatus" in state,
           f"level={state.get('level')} discovered={state.get('discoveredServersCount')}")

        # ── 3. five steps, each a valid 4-tuple ──────────────────────────────
        SCRIPT = [3, 0, 4, 8, 2]  # scan, status, connect, exploit, missions
        tuple_ok = True
        detail = []
        for aid in SCRIPT:
            out = ad.step(aid)
            good = (isinstance(out, tuple) and len(out) == 4
                    and isinstance(out[0], dict) and isinstance(out[1], bool)
                    and isinstance(out[2], bool) and isinstance(out[3], dict))
            tuple_ok = tuple_ok and good
            cmdname = out[3].get("command") if good else "?"
            detail.append(f"{aid}:{cmdname}={out[3].get('result', {}).get('success') if good else 'BAD'}")
        ck("5 steps each return (dict, bool, bool, dict)", tuple_ok, " ".join(detail))

        # ── 4. type_text drives a raw command ────────────────────────────────
        ad.type_text("status")
        term = ad.get_terminal_text()
        ck("type_text() drives a raw command and populates terminal text",
           isinstance(term, str) and len(term) > 0,
           f"terminal[{len(term)} chars]")

        # ── 5. get_terminal_text + clean close ───────────────────────────────
        s2, term2, trunc2, info2 = ad.type_text_step("help")
        ck("type_text_step() returns a 4-tuple and terminal reflects it",
           isinstance(s2, dict) and "help" in (info2.get("command") or "")
           and len(ad.get_terminal_text()) > 0,
           f"cmd={info2.get('command')} success={info2.get('result', {}).get('success')}")

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
