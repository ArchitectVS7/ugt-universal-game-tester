#!/usr/bin/env python3
"""
Nexus Dominion adapter smoke — the SAME path the trial rounds use
(NexusDominionHarnessAdapter -> harness -> real engine), after the raw spike
has validated the protocol underneath. Checks:

  1. connect + reset(seed) -> normalized flat state (cycle 0, player_* fields,
     stateHash present)
  2. step(pass) -> committed cycle 1, hash stream grew, terminated=False
  3. EVERY action id (0..19) steps without exception; non-probe ids commit;
     info carries actionName/orders/committed
  4. same-seed reset -> identical initial stateHash (adapter-level determinism)
  5. bare reset() derives distinct per-episode seeds (hunter contract)
  6. truncation fires at max_cycles

Run (from the UGT repo root):
    python3 integrations/nexus-dominion/smoke_nexus_dominion_adapter.py
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from ugt.core.trial import GateRunner  # noqa: E402
from ugt.utils.config_parser import UgtConfig  # noqa: E402
from ugt.adapters.nexus_dominion_harness import (  # noqa: E402
    NexusDominionHarnessAdapter,
)

CONFIG_PATH = "integrations/nexus-dominion/ugt.config.yaml"
SEED = 20260902


def main() -> int:
    gate = GateRunner()
    ck = gate.ck
    config = UgtConfig(CONFIG_PATH)
    adapter = NexusDominionHarnessAdapter(config)
    print("Nexus Dominion adapter smoke — BaseAdapter path over the harness\n")

    try:
        # ── 1. connect + reset ───────────────────────────────────────────────
        print("  -- 1. connect + reset --")
        adapter.connect()
        state = adapter.reset(seed=SEED)
        ck("reset(seed) -> cycle 0, player_* fields, stateHash",
           state.get("cycle") == 0 and state.get("player_credits") == 500
           and state.get("player_systemsOwned") == 1
           and isinstance(state.get("stateHash"), str)
           and state.get("empireCount") == 100,
           f"cycle={state.get('cycle')} credits={state.get('player_credits')} "
           f"hash={state.get('stateHash')}")
        initial_hash = state.get("stateHash")

        # ── 2. one step ──────────────────────────────────────────────────────
        print("\n  -- 2. step(pass) --")
        after, terminated, truncated, info = adapter.step(0)
        ck("step(0) -> cycle 1, committed, hash stream grew, not terminated",
           after.get("cycle") == 1 and info.get("committed") is True
           and terminated is False and truncated is False
           and len(adapter.hash_stream) == 2,
           f"cycle={after.get('cycle')} committed={info.get('committed')} "
           f"stream={len(adapter.hash_stream)}")

        # ── 3. the full action vocabulary ────────────────────────────────────
        print("\n  -- 3. all 20 action ids --")
        failures = []
        for action_id in range(20):
            name = adapter.action_name(action_id)
            try:
                _, _, _, info = adapter.step(action_id)
                # A probe order may abort the commit (that is engine data, not
                # an adapter fault); every non-probe id must commit.
                if not info.get("probe") and info.get("committed") is not True:
                    failures.append(f"{action_id}:{name} did not commit "
                                    f"(error={info.get('error')!r})")
                if info.get("actionName") != name or "orders" not in info:
                    failures.append(f"{action_id}:{name} info incomplete")
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{action_id}:{name} raised "
                                f"{type(exc).__name__}: {exc}")
        ck("all 20 ids step; every non-probe id commits; info complete",
           not failures, "; ".join(failures) or
           f"cycle now {adapter._read_state().get('cycle')}")

        # ── 4. same-seed reset determinism ───────────────────────────────────
        print("\n  -- 4. same-seed reset --")
        again = adapter.reset(seed=SEED)
        ck("reset(same seed) -> identical initial stateHash",
           again.get("stateHash") == initial_hash,
           f"{again.get('stateHash')} vs {initial_hash}")

        # ── 5. bare reset derives distinct episode seeds ─────────────────────
        print("\n  -- 5. bare reset() episodes --")
        h1 = adapter.reset().get("stateHash")
        h2 = adapter.reset().get("stateHash")
        ck("two bare reset() episodes -> different campaigns",
           h1 != h2, f"{h1} vs {h2}")

        # ── 6. truncation ────────────────────────────────────────────────────
        print("\n  -- 6. truncation at max_cycles --")
        adapter.max_cycles = 3
        adapter.reset(seed=SEED + 7)
        truncated_at = None
        for i in range(5):
            _, terminated, truncated, _ = adapter.step(0)
            if truncated:
                truncated_at = i + 1
                break
        ck("truncated fires at max_cycles (=3), terminated stays False",
           truncated_at == 3 and terminated is False,
           f"truncatedAt={truncated_at}")

    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        gate.ck("exception-free run", False, f"{type(exc).__name__}: {exc}")
    finally:
        adapter.close()

    return gate.finish(
        "SMOKE",
        "The adapter faithfully relays the harness contract — reset/step/close, "
        "full action vocabulary, deterministic resets, truncation. "
        "Ready for R1.")


if __name__ == "__main__":
    sys.exit(main())
