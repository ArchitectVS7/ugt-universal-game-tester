#!/usr/bin/env python3
"""
Pond Conspiracy protocol spike — raw JSON-lines validation of the REAL game
running headless under the harness (the-pond/tests/harness/ugt_harness.gd)
BEFORE any adapter exists.

Spawns `godot --headless --fixed-fps 60 -s ugt_harness.gd` directly (a local
`Harness` Popen helper, NO adapter) and asserts the contract the future
PondHarnessAdapter will be built on. Checks:

  1.  boot -> a {"op":"ready"} line from the frozen engine
  2.  create -> ok, the real Player exists at full health (hp == max_hp)
  3.  save hygiene: meta save redirected to user://ugt_harness_meta.save and
      the meta state is VIRGIN (total_runs == 1) — the real user save with its
      test-polluted run counter (finding PC-2) is never read or written
  4.  EventBus tap: the create-time signal burst (state_changed,
      arena_type_selected) is drained into the create response
  5.  pause discipline: two no-frame `state` ops -> identical physics frame
      counter and player position (the world is FROZEN between commands)
  6.  step 60 frames holding move-right -> exactly 60 physics frames elapse
      and the player moves ~200px (move_speed 200 px/s @ 60fps)
  7.  releasing input stops the player (30 idle frames -> position unchanged)
  8.  the threat is real: enemies spawn within 30s of game time
  9.  wave state is structurally readable (current_wave >= 1, boss_wave == 5)
  10. dodge i-frames: step with dodge held -> _is_invulnerable within the
      0.3s window (PRD FR-01)
  11. quit -> ok response, process exits 0
  12. stderr hygiene: no SCRIPT ERROR / Parse Error (the 3 known-benign
      BulletUpHell teardown thread errors — finding PC-3 — are whitelisted)

Plus two INFORMATIONAL probes (printed, never gating a spike):
  - attack probe: aim at the nearest enemy and cycle attack presses — does any
    enemy lose hp / die? (kill mechanics are R1's gate, not the spike's)
  - determinism probe: two fresh processes, same seed, same scripted input ->
    compare final player/enemy state (R3 replay feasibility data; the global
    RNG is seeded by the harness, tongue crits are not — finding PC-1)

Run (from the UGT repo root; needs godot 4.7 on PATH or at the gate.sh spots):
    python3 integrations/pond/spike_pond.py

Exit 0 == all checks pass. Findings print regardless — a failed check is data.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time

sys.path.insert(0, ".")

from ugt.core.trial import GateRunner  # noqa: E402

POND_ROOT = os.environ.get("POND_ROOT", os.path.expanduser("~/Dev/Games/the-pond"))
HARNESS_SCRIPT = "res://tests/harness/ugt_harness.gd"
SEED = 20260719
EXPECTED_META_SAVE = "user://ugt_harness_meta.save"

# Benign stderr noise that must not fail check 12.
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


def find_godot() -> str:
    """Locate godot the same way the game's own scripts/gate.sh does."""
    candidates = [os.environ.get("UGT_GODOT_BIN", "")]
    from shutil import which
    candidates.append(which("godot") or "")
    candidates.append("/opt/homebrew/bin/godot")
    candidates.append("/Applications/Godot.app/Contents/MacOS/Godot")
    for c in candidates:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    raise SystemExit("spike: no executable godot binary found (set UGT_GODOT_BIN)")


class Harness:
    """Minimal raw driver over the headless game (one JSON line in, one out).

    Protocol lines carry "ugt": true; everything else on stdout is game log
    noise and is kept (not swallowed) for post-mortems.
    """

    _EOF = object()

    def __init__(self, godot: str):
        self.p = subprocess.Popen(
            [godot, "--headless", "--fixed-fps", "60",
             "--path", POND_ROOT, "-s", HARNESS_SCRIPT],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1, cwd=POND_ROOT,
        )
        self.noise: list[str] = []
        self.stderr_lines: list[str] = []
        # Dedicated reader thread + queue — NEVER select() on the buffered
        # stdout object (readline() can buffer coalesced lines Python-side and
        # select() then starves on an empty kernel pipe; timing-dependent).
        self._lines: queue.Queue = queue.Queue()
        self._stdout_thread = threading.Thread(target=self._drain_stdout, daemon=True)
        self._stdout_thread.start()
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()

    def _drain_stdout(self) -> None:
        for line in self.p.stdout:
            self._lines.put(line.rstrip("\n"))
        self._lines.put(self._EOF)

    def _drain_stderr(self) -> None:
        for line in self.p.stderr:
            self.stderr_lines.append(line.rstrip("\n"))

    def read_msg(self, timeout: float = 60.0) -> dict:
        deadline = time.time() + timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise TimeoutError("no protocol line within %.0fs" % timeout)
            try:
                line = self._lines.get(timeout=min(remaining, 0.5))
            except queue.Empty:
                continue
            if line is self._EOF:
                raise RuntimeError(
                    "EOF from harness (exit %s); stderr tail:\n%s"
                    % (self.p.poll(), "\n".join(self.stderr_lines[-15:])))
            line = line.strip()
            if not line.startswith("{"):
                if line:
                    self.noise.append(line)
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                self.noise.append(line)
                continue
            if msg.get("ugt") is True:
                return msg
            self.noise.append(line)

    def send(self, req: dict) -> None:
        self.p.stdin.write(json.dumps(req) + "\n")
        self.p.stdin.flush()

    def rpc(self, req: dict, timeout: float = 60.0) -> dict:
        self.send(req)
        return self.read_msg(timeout)

    def step(self, frames: int, inp: dict | None = None, timeout: float = 120.0) -> dict:
        return self.rpc({"op": "step", "frames": frames, "input": inp or {}}, timeout)

    def close(self) -> int:
        try:
            if self.p.poll() is None:
                self.p.stdin.close()
        except OSError:
            pass
        try:
            self.p.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.p.kill()
            self.p.wait()
        self._stderr_thread.join(timeout=5)
        return self.p.returncode


def player_pos(snap: dict) -> list:
    return (snap.get("player") or {}).get("pos") or [None, None]


def run_scripted(godot: str, seed: int) -> dict:
    """Fresh process, fixed seed, fixed input script -> comparable end state.

    Used by the informational determinism probe. Wall-clock-derived fields
    (run_stats timestamps) are excluded from the fingerprint.
    """
    h = Harness(godot)
    h.read_msg(120)  # ready
    h.rpc({"op": "create", "seed": seed})
    h.step(60, {"move": [1, 0]})
    h.step(60, {"move": [0, 1]})
    snap = h.step(120, {"move": [-1, -1], "dodge": True})
    h.rpc({"op": "quit"})
    h.close()
    return {
        "player_pos": player_pos(snap),
        "player_hp": (snap.get("player") or {}).get("hp"),
        "enemies": [(e.get("type"), e.get("pos"), e.get("hp"))
                    for e in snap.get("enemies", [])],
        "bullets": snap.get("bullets"),
        "wave": snap.get("wave"),
    }


def main() -> int:
    godot = find_godot()
    print(f"spike: godot at {godot}")
    print(f"spike: game at {POND_ROOT}\n")
    gate = GateRunner()

    h = Harness(godot)

    # --- 1: boot ---------------------------------------------------------------
    try:
        ready = h.read_msg(timeout=120)
    except (RuntimeError, TimeoutError) as e:
        gate.ck("boot: ready line from frozen engine", False, str(e))
        return gate.finish("POND SPIKE", "")
    gate.ck("boot: ready line from frozen engine",
            ready.get("op") == "ready" and ready.get("ok") is True,
            f"godot {ready.get('godot')}")

    # --- 2: create -------------------------------------------------------------
    created = h.rpc({"op": "create", "seed": SEED}, timeout=120)
    player = created.get("player") or {}
    gate.ck("create: ok with a live Player at full health",
            created.get("ok") is True and player.get("hp") is not None
            and player.get("hp") == player.get("max_hp"),
            f"arena_id={created.get('arena_id')} hp={player.get('hp')}/{player.get('max_hp')}"
            f" pos={player.get('pos')}")

    # --- 3: save hygiene ---------------------------------------------------------
    total_runs = (created.get("run") or {}).get("total_runs")
    gate.ck("save hygiene: meta redirected + virgin state (run #1)",
            created.get("meta_save_path") == EXPECTED_META_SAVE and total_runs == 1,
            f"meta_save_path={created.get('meta_save_path')} total_runs={total_runs}")

    # --- 4: EventBus tap ---------------------------------------------------------
    ev_names = [e.get("signal") for e in created.get("events", [])]
    gate.ck("EventBus tap: create-time signal burst drained",
            "state_changed" in ev_names and "arena_type_selected" in ev_names,
            f"events={ev_names}")

    # --- 5: pause discipline -------------------------------------------------
    s1 = h.rpc({"op": "state"})
    s2 = h.rpc({"op": "state"})
    gate.ck("pause discipline: world frozen between commands",
            s1.get("frame") == s2.get("frame") and player_pos(s1) == player_pos(s2),
            f"frame={s1.get('frame')}=={s2.get('frame')} pos={player_pos(s1)}")

    # --- 6: step advances exactly N frames and input moves the player -----------
    before = s2
    after = h.step(60, {"move": [1, 0]})
    frames_elapsed = (after.get("frame") or 0) - (before.get("frame") or 0)
    dx = player_pos(after)[0] - player_pos(before)[0]
    gate.ck("step: exactly 60 physics frames elapse",
            frames_elapsed == 60, f"elapsed={frames_elapsed}")
    gate.ck("step: held move-right moves the player ~200px",
            140 <= dx <= 260, f"dx={dx:.1f} (move_speed 200 px/s)")

    # --- 7: release stops movement ----------------------------------------------
    idle = h.step(30, {})
    gate.ck("input release: player halts",
            player_pos(idle) == player_pos(after),
            f"pos={player_pos(idle)}")

    # --- 8: enemies spawn --------------------------------------------------------
    enemy_count = len(idle.get("enemies", []))
    frames_waited = 0
    snap = idle
    while enemy_count == 0 and frames_waited < 1800:
        snap = h.step(120, {})
        frames_waited += 120
        enemy_count = len(snap.get("enemies", []))
    gate.ck("threat: enemies spawn within 30s of game time",
            enemy_count > 0,
            f"count={enemy_count} after +{frames_waited} frames; "
            f"types={sorted(set(str(e.get('type')) for e in snap.get('enemies', [])))}")

    # --- 9: wave state readable ----------------------------------------------------
    wave = snap.get("wave") or {}
    gate.ck("wave state: structurally readable",
            isinstance(wave.get("current_wave"), (int, float)) and wave.get("current_wave") >= 1
            and wave.get("boss_wave") == 5,
            f"wave={wave}")

    # --- informational: attack probe ---------------------------------------------
    kills, hp_dropped = 0, False
    if enemy_count > 0:
        for i in range(20):
            cur = h.rpc({"op": "state"})
            enemies = cur.get("enemies", [])
            if not enemies:
                break
            ppos = player_pos(cur)
            nearest = min(enemies, key=lambda e: (e["pos"][0] - ppos[0]) ** 2
                          + (e["pos"][1] - ppos[1]) ** 2)
            # press (6 frames) then release (6 frames): a real click cycle
            r1 = h.step(6, {"attack": True, "aim": nearest["pos"]})
            r2 = h.step(6, {"attack": False, "aim": nearest["pos"]})
            for resp in (r1, r2):
                kills += sum(1 for e in resp.get("events", [])
                             if e.get("signal") == "enemy_killed")
                for e in resp.get("enemies", []):
                    if e.get("hp") is not None and e.get("max_hp") is not None \
                            and e["hp"] < e["max_hp"]:
                        hp_dropped = True
    print(f"  [INFO] attack probe: enemy_killed events={kills}, "
          f"enemy hp dropped={hp_dropped} (kill mechanics gate in R1, not here)")

    # --- 10: dodge i-frames --------------------------------------------------------
    dodge = h.step(6, {"dodge": True})
    gate.ck("dodge: i-frames open within the 0.3s window (FR-01)",
            (dodge.get("player") or {}).get("invulnerable") is True,
            f"invulnerable={(dodge.get('player') or {}).get('invulnerable')} "
            f"cooldown={(dodge.get('player') or {}).get('dodge_cooldown')}")

    # --- 11: clean quit --------------------------------------------------------------
    quit_resp = h.rpc({"op": "quit"})
    code = h.close()
    gate.ck("quit: clean shutdown", quit_resp.get("ok") is True and code == 0,
            f"exit={code}")

    # --- 12: stderr hygiene -----------------------------------------------------------
    bad = [ln for ln in h.stderr_lines
           if ("SCRIPT ERROR" in ln or "Parse Error" in ln)
           and not any(w in ln for w in STDERR_WHITELIST)]
    gate.ck("stderr hygiene: no script/parse errors",
            not bad, f"{len(bad)} bad lines" + (f"; first: {bad[0]}" if bad else ""))

    # --- informational: same-seed determinism probe ---------------------------------
    print("\n  [INFO] determinism probe: two fresh processes, same seed, same script …")
    try:
        fp_a = run_scripted(godot, SEED)
        fp_b = run_scripted(godot, SEED)
        if fp_a == fp_b:
            print("  [INFO] determinism probe: IDENTICAL end state — R3 same-seed "
                  "replay looks feasible once PC-1 (tongue crit RNG) lands")
        else:
            diffs = [k for k in fp_a if fp_a[k] != fp_b[k]]
            print(f"  [INFO] determinism probe: DIVERGED on {diffs} — corroborates "
                  f"finding PC-1; R3 replay needs upstream seeding work")
            print(f"         a={ {k: fp_a[k] for k in diffs} }")
            print(f"         b={ {k: fp_b[k] for k in diffs} }")
    except (RuntimeError, TimeoutError) as e:
        print(f"  [INFO] determinism probe: could not run ({e})")

    return gate.finish(
        "POND SPIKE",
        "The raw harness contract holds — safe to build PondHarnessAdapter on it.")


if __name__ == "__main__":
    sys.exit(main())
