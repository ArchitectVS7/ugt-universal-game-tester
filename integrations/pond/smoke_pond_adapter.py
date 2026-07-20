#!/usr/bin/env python3
"""
Pond Conspiracy adapter smoke — the SAME path the trial rounds will use
(PondHarnessAdapter -> headless harness -> real game), after the raw spike
(spike_pond.py, 13/13) validated the protocol underneath. Checks:

  1. connect + reset(seed) -> normalized flat state (full hp, run active,
     spawn pos captured, virgin meta: total_runs == 1)
  2. step(move_e) -> player_x advances ~frames_per_step/60 * 200px and the
     raw snapshot frame counter advances exactly frames_per_step
  3. EVERY action id (0..13) steps without exception; info carries
     actionName/frames/phase; aim ids report aimed_at once enemies exist
  4. an unmapped action id raises NotImplementedError (the anti-sim_bridge
     discipline: never fabricate behavior)
  5. same-seed reset + identical 6-step script -> identical state fingerprint
     (adapter-level determinism, the R3 replay foundation)
  6. bare reset() derives distinct per-episode seeds (hunter contract)
  7. truncation fires at max_steps, terminated stays False
  8. close() -> subprocess actually gone; stderr shows no script/parse errors
     (PC-3 teardown noise whitelisted)

Run (from the UGT repo root; needs godot 4.7 on PATH or UGT_GODOT_BIN):
    python3 integrations/pond/smoke_pond_adapter.py

Exit 0 == all checks pass. Findings print regardless — a failed check is data.
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from ugt.core.trial import GateRunner  # noqa: E402
from ugt.utils.config_parser import UgtConfig  # noqa: E402
from ugt.adapters.pond_harness import PondHarnessAdapter  # noqa: E402

CONFIG_PATH = "integrations/pond/ugt.config.yaml"
SEED = 20260720

STDERR_WHITELIST = (
    "Thread must have been started",   # PC-3: BuHSpawner._exit_tree teardown
    "BuHSpawner.gd",
    "GDScript backtrace",
    "[0] _exit_tree",
    "at: wait_to_finish",
    "ObjectDB instances were leaked",
    "resources still in use",
    "at: cleanup",
    "at: clear",
    "WARNING",
)

# Fixed 6-step script for the determinism fingerprint (ids, not randomness).
SCRIPT = [3, 3, 5, 9, 10, 0]   # E, E, S, attack_nearest, dodge, idle


def fingerprint(adapter: PondHarnessAdapter) -> dict:
    """Wall-clock-free view of the raw snapshot (run_stats carries ms
    timestamps, so it is excluded)."""
    snap = adapter.last_snapshot or {}
    run = dict(snap.get("run") or {})
    run.pop("stats", None)
    return {
        "arena": adapter.arena_id,
        "frame": snap.get("frame"),
        "player": snap.get("player"),
        "enemies": snap.get("enemies"),
        "bullets": snap.get("bullets"),
        "wave": snap.get("wave"),
        "run": run,
    }


def main() -> int:
    gate = GateRunner()
    ck = gate.ck
    config = UgtConfig(CONFIG_PATH)
    adapter = PondHarnessAdapter(config)
    print("Pond Conspiracy adapter smoke — BaseAdapter path over the harness\n")

    try:
        # ── 1. connect + reset ───────────────────────────────────────────────
        print("  -- 1. connect + reset --")
        adapter.connect()
        state = adapter.reset(seed=SEED)
        ck("reset(seed) -> full hp, run active, spawn captured, virgin meta",
           state["player_hp"] == state["player_max_hp"] > 0
           and state["run_active"] == 1 and state["player_dead"] == 0
           and adapter.spawn_pos is not None and state["total_runs"] == 1,
           f"hp={state['player_hp']}/{state['player_max_hp']} "
           f"arena={adapter.arena_id!r} spawn={adapter.spawn_pos} "
           f"total_runs={state['total_runs']}")

        # ── 2. one movement step ─────────────────────────────────────────────
        print("\n  -- 2. step(move_e) --")
        frame_before = (adapter.last_snapshot or {}).get("frame", 0)
        x_before = state["player_x"]
        after, terminated, truncated, info = adapter.step(3)  # move_e
        frames = (adapter.last_snapshot or {}).get("frame", 0) - frame_before
        dx = after["player_x"] - x_before
        expected = adapter.frames_per_step / 60.0 * 200.0  # move_speed 200px/s
        # total_runs must STAY 1 across the first frame: the PC-4 double
        # start_run used to spawn a duplicate TestArena + count run #2 here.
        ck("step(move_e) -> exact frames + ~expected movement, single run",
           frames == adapter.frames_per_step
           and abs(dx - expected) <= expected * 0.35
           and terminated is False and truncated is False
           and info.get("actionName") == "move_e"
           and after["total_runs"] == 1,
           f"frames={frames} dx={dx:.1f} (expected ~{expected:.0f}) "
           f"phase={info.get('phase')} total_runs={after['total_runs']}")

        # ── 3. the full action vocabulary ────────────────────────────────────
        print("\n  -- 3. all 14 action ids --")
        failures = []
        aimed_seen = False
        for action_id in range(14):
            name = adapter.action_name(action_id)
            try:
                st, term, trunc, info = adapter.step(action_id)
                if info.get("actionName") != name or "frames" not in info \
                        or "phase" not in info:
                    failures.append(f"{action_id}:{name} info incomplete")
                if info.get("aimed_at") is not None:
                    aimed_seen = True
                if term:
                    # Dying mid-vocabulary is game data, not an adapter fault —
                    # but the smoke needs a live run; re-arm and continue.
                    adapter.reset(seed=SEED + 99)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{action_id}:{name} raised "
                                f"{type(exc).__name__}: {exc}")
        # Ensure at least one aim-capable id actually aimed: wait for enemies,
        # then attack_nearest must report its structural target.
        tries = 0
        while not aimed_seen and tries < 15:
            st, term, trunc, info = adapter.step(9)  # attack_nearest
            aimed_seen = info.get("aimed_at") is not None
            tries += 1
            if term:
                adapter.reset(seed=SEED + 99)
        ck("all 14 ids step; info complete; aim ids target real enemies",
           not failures and aimed_seen,
           "; ".join(failures) or f"aimed_at seen (extra tries={tries}) "
           f"enemy_count={st['enemy_count']}")

        # ── 4. unmapped action refuses ───────────────────────────────────────
        print("\n  -- 4. unmapped action id --")
        try:
            adapter.step(99)
            ck("unmapped id raises NotImplementedError", False,
               "step(99) silently did something")
        except NotImplementedError as exc:
            ck("unmapped id raises NotImplementedError", True, str(exc)[:70])

        # ── 5. same-seed scripted determinism ────────────────────────────────
        print("\n  -- 5. same-seed scripted determinism --")
        adapter.reset(seed=SEED + 1)
        for a in SCRIPT:
            adapter.step(a)
        fp_a = fingerprint(adapter)
        adapter.reset(seed=SEED + 1)
        for a in SCRIPT:
            adapter.step(a)
        fp_b = fingerprint(adapter)
        diffs = [k for k in fp_a if fp_a[k] != fp_b[k]]
        ck("same seed + same 6-step script -> identical fingerprint",
           not diffs, f"diverged on {diffs}" if diffs else
           f"frame={fp_a['frame']} enemies={len(fp_a['enemies'] or [])}")

        # ── 6. bare reset derives distinct episode seeds ─────────────────────
        print("\n  -- 6. bare reset() episodes --")
        adapter.reset()
        s1 = adapter.last_seed
        adapter.reset()
        s2 = adapter.last_seed
        ck("two bare reset() episodes -> distinct seeds",
           s1 != s2 and s1 is not None, f"{s1} vs {s2}")

        # ── 7. truncation ────────────────────────────────────────────────────
        print("\n  -- 7. truncation at max_steps --")
        adapter.max_steps = 4
        adapter.reset(seed=SEED + 7)
        truncated_at, terminated = None, False
        for i in range(6):
            _, terminated, truncated, _ = adapter.step(0)
            if terminated:
                break
            if truncated:
                truncated_at = i + 1
                break
        ck("truncated fires at max_steps (=4), terminated stays False",
           truncated_at == 4 and terminated is False,
           f"truncatedAt={truncated_at} terminated={terminated}")

    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        gate.ck("exception-free run", False, f"{type(exc).__name__}: {exc}")
    finally:
        # ── 8. close ─────────────────────────────────────────────────────────
        print("\n  -- 8. close --")
        adapter.close()
        gone = adapter.process is None
        bad = [ln for ln in adapter.stderr_lines
               if ("SCRIPT ERROR" in ln or "Parse Error" in ln)
               and not any(w in ln for w in STDERR_WHITELIST)]
        gate.ck("close() reaps the subprocess; stderr clean",
                gone and not bad,
                f"gone={gone} badStderr={len(bad)}"
                + (f"; first: {bad[0]}" if bad else ""))

    return gate.finish(
        "SMOKE",
        "The adapter faithfully relays the harness contract — reset/step/close, "
        "full input-macro vocabulary, deterministic scripted episodes, "
        "truncation. Ready for R1.")


if __name__ == "__main__":
    sys.exit(main())
