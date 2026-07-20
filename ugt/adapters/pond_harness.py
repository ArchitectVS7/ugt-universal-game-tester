"""
PondHarnessAdapter — drives the REAL Pond Conspiracy game (the-pond, Godot 4.7
bullet-hell) through its JSON-lines headless harness
(the-pond/tests/harness/ugt_harness.gd), never a re-implementation (the
sim_bridge lesson).

The harness runs the actual game under `godot --headless --fixed-fps 60`,
frozen between commands (it blocks on stdin inside _physics_process). One JSON
request per line in, one response per line out; protocol lines carry
"ugt": true (everything else on stdout is game log noise, kept for
post-mortems). Ops:

  {"op":"create","seed":N}                 -> real TestArena, run starts, snapshot
  {"op":"step","frames":N,"input":{...}}   -> exactly N physics frames, snapshot
  {"op":"state"}                           -> snapshot, zero frames
  {"op":"quit"}                            -> clean shutdown

Like every UGT adapter this contains NO game logic — it is a transport layer
that (a) spawns/speaks to the harness and (b) composes each discrete action id
into held named-action input (move/attack/dodge + the player's own
aim_target_override hook) for a fixed number of physics frames. Aim targets
come from structural reads of the harness's OWN enemy list (nearest active
enemy) — never from rules, costs, or predictions. Attack/dodge ids choreograph
a press→release edge inside the step because the game reads those actions with
is_action_just_pressed(), exactly like a player's click.

One episode per process: the game's run loop starts in TestArena._ready(), so
reset() restarts the subprocess (a ~2s headless boot) and creates a fresh
arena. The harness redirects the meta save, so every episode starts from a
virgin meta state (run #1 — run count is a difficulty input, T-040).
"""
from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import time

from ugt.adapters.base import BaseAdapter

DEFAULTS = {
    "game_root": os.path.expanduser("~/Dev/Games/the-pond"),
    "harness_script": "res://tests/harness/ugt_harness.gd",
    "godot_bin": "",              # "" -> find_godot() lookup (gate.sh order)
    "seed": 20260719,
    "frames_per_step": 30,        # 0.5s of game time per discrete action
    "max_steps": 600,             # truncation: 5 min of game time
}

# id -> action name. MUST stay in lockstep with
# integrations/pond/ugt.config.yaml and `_compose` below. Every id is a pure
# input macro; the only state consulted is the harness's own enemy list /
# player position (structural reads), never game rules.
_DEFAULT_ACTION_NAMES = {
    0: "idle",           # no input held
    1: "move_n",         # 8-way movement, held for the whole step
    2: "move_ne",
    3: "move_e",
    4: "move_se",
    5: "move_s",
    6: "move_sw",
    7: "move_w",
    8: "move_nw",
    9: "attack_nearest",   # stand, aim at nearest active enemy, one attack press
    10: "dodge",           # one dodge press (i-frames, FR-01)
    11: "chase_nearest",   # move toward nearest active enemy, aim at it
    12: "kite_nearest",    # move away from nearest enemy, aim it, one attack press
    13: "retreat_spawn",   # move toward the episode's spawn point (disengage)
}

_MOVE_VECTORS = {
    "move_n": (0, -1), "move_ne": (1, -1), "move_e": (1, 0),
    "move_se": (1, 1), "move_s": (0, 1), "move_sw": (-1, 1),
    "move_w": (-1, 0), "move_nw": (-1, -1),
}


def find_godot() -> str:
    """Locate godot the same way the game's own scripts/gate.sh does."""
    for c in (os.environ.get("UGT_GODOT_BIN", ""),
              shutil.which("godot") or "",
              "/opt/homebrew/bin/godot",
              "/Applications/Godot.app/Contents/MacOS/Godot"):
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    raise RuntimeError("no executable godot binary found (set UGT_GODOT_BIN)")


class PondHarnessAdapter(BaseAdapter):
    """Transport-only handle on the running headless game. NO game logic."""

    def __init__(self, config=None):
        super().__init__(config)
        eng = {}
        if config is not None:
            try:
                eng = config.data.get("engine", {}) or {}
            except AttributeError:
                eng = {}

        self.game_root = str(
            os.environ.get("POND_ROOT")
            or eng.get("game_root")
            or DEFAULTS["game_root"])
        self.harness_script = str(eng.get("harness_script",
                                          DEFAULTS["harness_script"]))
        self.godot_bin = str(
            os.environ.get("UGT_GODOT_BIN")
            or eng.get("godot_bin")
            or DEFAULTS["godot_bin"]) or find_godot()
        self.seed = int(eng.get("seed", DEFAULTS["seed"]))
        self.frames_per_step = int(eng.get("frames_per_step",
                                           DEFAULTS["frames_per_step"]))
        self.max_steps = int(eng.get("max_steps", DEFAULTS["max_steps"]))

        # action_id -> name (from config, else the default table).
        self._action_names = dict(_DEFAULT_ACTION_NAMES)
        if config is not None:
            try:
                mapped = {}
                for k, v in (config.action_mappings or {}).items():
                    mapped[int(k)] = v.get("name") if isinstance(v, dict) else str(v)
                if mapped:
                    self._action_names = mapped
            except Exception:
                self._action_names = dict(_DEFAULT_ACTION_NAMES)

        self.process = None
        self.noise: list[str] = []          # non-protocol stdout (game logs)
        self.stderr_lines: list[str] = []
        self._stderr_thread = None
        # Protocol lines arrive via a dedicated reader thread + queue. NEVER
        # select() on the buffered stdout object: readline() can slurp several
        # coalesced lines into Python's internal buffer, the kernel pipe goes
        # empty, and select() then starves on data that is already buffered
        # (bit us as a timing-dependent create-timeout flake in the smoke).
        self._stdout_thread = None
        self._lines: queue.Queue = queue.Queue()
        self.last_snapshot: dict | None = None  # raw harness snapshot (gates)
        self.arena_id = None
        self.spawn_pos: list | None = None       # player pos at create
        self.last_seed: int | None = None
        self._step_count = 0
        self._reset_count = 0

    # ── public read-only mirrors of the other harness adapters ──────────────
    @property
    def step_count(self):
        return self._step_count

    def action_name(self, action_id: int) -> str:
        return self._action_names.get(int(action_id), f"unknown_{action_id}")

    # ── BaseAdapter lifecycle ────────────────────────────────────────────────
    def connect(self):
        """Validate the toolchain; the subprocess itself is (re)spawned per
        reset() because the game's run loop starts at scene _ready()."""
        if not os.path.isdir(self.game_root):
            raise RuntimeError(f"game_root not found: {self.game_root}")
        script_fs = os.path.join(self.game_root,
                                 self.harness_script.replace("res://", "", 1))
        if not os.path.isfile(script_fs):
            raise RuntimeError(f"harness script not found: {script_fs}")
        return True

    def reset(self, seed=None, run_number=None):
        """Fresh episode: restart the headless game and create the arena.

        Returns the normalized flat state dict. A bare reset() derives a
        distinct per-episode seed (base seed + episode index) so consecutive
        exploit-hunter episodes explore different randomness; pass `seed` for
        an exact replay.

        `run_number` pins the lifetime run count the game boots with. It is a
        real config key, not a convenience: run count selects the ARENA
        (LevelGenerator thresholds 1-3 / 4-8 / 9+), the per-wave enemy count and
        the bullet-speed tier (T-040/T-042). Without it every episode starts
        from a virgin meta save and only ever sees run 1's Polluted Wetland, so
        two of the three arenas are unreachable through the wire.
        """
        self._kill_process()
        self._reset_count += 1
        self._step_count = 0
        self.last_seed = int(seed) if seed is not None \
            else self.seed + self._reset_count - 1

        self.process = subprocess.Popen(
            [self.godot_bin, "--headless", "--fixed-fps", "60",
             "--path", self.game_root, "-s", self.harness_script],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1, cwd=self.game_root)
        self._lines = queue.Queue()
        self._stdout_thread = threading.Thread(
            target=self._drain_stdout, args=(self.process,), daemon=True)
        self._stdout_thread.start()
        self._stderr_thread = threading.Thread(target=self._drain_stderr,
                                               daemon=True)
        self._stderr_thread.start()

        ready = self._read_msg(timeout=120)
        if ready.get("op") != "ready":
            raise RuntimeError(f"harness did not become ready: {ready}")
        create_req = {"op": "create", "seed": self.last_seed}
        if run_number is not None:
            create_req["run_number"] = int(run_number)
        self.last_run_number = run_number
        created = self._rpc(create_req, timeout=120)
        if created.get("ok") is not True:
            raise RuntimeError(f"create failed: {created}")
        self.last_snapshot = created
        self.arena_id = created.get("arena_id")
        player = created.get("player") or {}
        self.spawn_pos = list(player.get("pos") or [0, 0])
        return self._normalize(created)

    def step(self, action_id):
        """Hold the id's input macro for frames_per_step physics frames."""
        if self.process is None or self.process.poll() is not None:
            raise RuntimeError("no live episode — call reset() first")
        name = self.action_name(action_id)
        phases, aimed_at = self._compose(name)

        snap = None
        events: list = []
        for frames, inp in phases:
            snap = self._rpc({"op": "step", "frames": frames, "input": inp},
                             timeout=120)
            if snap.get("ok") is not True:
                raise RuntimeError(f"step failed: {snap}")
            events.extend(snap.get("events", []))
        snap["events"] = events           # full step's drained event stream
        self.last_snapshot = snap
        self._step_count += 1

        state = self._normalize(snap)
        terminated = bool(state["player_dead"]) or \
            (snap.get("run") or {}).get("phase") == "RUN_END"
        truncated = (not terminated) and self._step_count >= self.max_steps
        info = {
            "actionName": name,
            "frames": self.frames_per_step,
            "events": events,
            "aimed_at": aimed_at,
            "phase": (snap.get("run") or {}).get("phase"),
            "arena_id": self.arena_id,
        }
        return state, terminated, truncated, info

    def level_up_pending(self) -> bool:
        """True while the real LevelUpUI is on screen (the game is paused and
        a player could not move until they pick a card)."""
        lvl = (self.last_snapshot or {}).get("level_up") or {}
        return bool(lvl.get("pending"))

    def level_up_options(self) -> list:
        """The mutation cards currently on screen, in laid-out order."""
        lvl = (self.last_snapshot or {}).get("level_up") or {}
        return list(lvl.get("options") or [])

    def choose_mutation(self, index: int = 0, frames: int = 40):
        """Pick level-up card `index` by CLICKING it — the only input path the
        real MutationCard accepts — then let the UI's fade-out tween finish and
        unpause the tree.

        Returns (state, events). Raises if no level-up is pending or the click
        is refused; the harness never fabricates a selection.
        """
        if self.process is None or self.process.poll() is not None:
            raise RuntimeError("no live episode — call reset() first")
        snap = self._rpc({"op": "choose", "index": int(index),
                          "frames": int(frames)}, timeout=120)
        if snap.get("ok") is not True:
            raise RuntimeError(f"choose failed: {snap}")
        self.last_snapshot = snap
        self._step_count += 1
        return self._normalize(snap), snap.get("events", [])

    def close(self):
        self._kill_process()

    # ── input composition (pure macros over structural reads) ────────────────
    def _compose(self, name: str):
        """action name -> ([(frames, input_dict), ...], aimed_at).

        Attack/dodge presses are split into press→release phases inside the
        step because the game consumes them with is_action_just_pressed() —
        the same edge a player's click produces. Phase frame counts always sum
        to frames_per_step.
        """
        total = self.frames_per_step
        nearest = self._nearest_enemy_pos()
        aimed_at = None

        if name in _MOVE_VECTORS:
            dx, dy = _MOVE_VECTORS[name]
            return [(total, {"move": [dx, dy]})], None

        if name == "attack_nearest":
            inp = {}
            if nearest is not None:
                inp["aim"] = nearest
                aimed_at = nearest
            return self._mash(total, inp, "attack"), aimed_at

        if name == "dodge":
            return self._mash(total, {}, "dodge"), None

        if name == "chase_nearest":
            move = self._dir_to(nearest) if nearest is not None else [0, 0]
            inp = {"move": move}
            if nearest is not None:
                inp["aim"] = nearest
                aimed_at = nearest
            return [(total, inp)], aimed_at

        if name == "kite_nearest":
            away = [0, 0]
            if nearest is not None:
                d = self._dir_to(nearest)
                away = [-d[0], -d[1]]
                aimed_at = nearest
            inp = {"move": away}
            if nearest is not None:
                inp["aim"] = nearest
            return self._mash(total, inp, "attack"), aimed_at

        if name == "retreat_spawn":
            move = self._dir_to(self.spawn_pos) if self.spawn_pos else [0, 0]
            return [(total, {"move": move})], None

        if name == "idle":
            return [(total, {})], None

        raise NotImplementedError(
            f"action '{name}' is not mapped in PondHarnessAdapter._compose — "
            f"refusing to fabricate behavior for it")

    # Mash cadence: `_MASH_ON` frames held, `_MASH_OFF` released, repeated for
    # the whole step (~6 presses/sec). A SINGLE press per step is not enough:
    # the game consumes attack/dodge with is_action_just_pressed() and buffers
    # NOTHING, while one tongue cycle costs 0.55s (0.15 extend + 0.1 retract +
    # 0.3 cooldown) and a dodge costs 0.8s — both longer than a 0.5s step. A
    # once-per-step press therefore phase-locks inside the cooldown and is
    # silently dropped essentially every time (finding PC-5: it produced ZERO
    # kills across ~45 point-blank attack steps before this was fixed). A real
    # player mashes; so does the macro, and every cooldown edge gets an input.
    _MASH_ON = 4
    _MASH_OFF = 6

    def _mash(self, total: int, base: dict, action: str):
        """Repeated press->release edges of `action` across the whole step,
        with `base` (move/aim) held throughout. Frame counts sum to `total`."""
        phases, spent = [], 0
        while spent < total:
            on = min(self._MASH_ON, total - spent)
            phases.append((on, {**base, action: True}))
            spent += on
            if spent >= total:
                break
            off = min(self._MASH_OFF, total - spent)
            phases.append((off, {**base, action: False}))
            spent += off
        return phases

    def _player_pos(self):
        player = (self.last_snapshot or {}).get("player") or {}
        return player.get("pos")

    def _nearest_enemy_pos(self):
        """Structural read: nearest ACTIVE enemy in the harness's own list."""
        ppos = self._player_pos()
        enemies = (self.last_snapshot or {}).get("enemies") or []
        if ppos is None or not enemies:
            return None
        best = min(enemies, key=lambda e: (e["pos"][0] - ppos[0]) ** 2
                   + (e["pos"][1] - ppos[1]) ** 2)
        return list(best["pos"])

    def _dir_to(self, target):
        """Unit-ish 8-way direction from the player toward target."""
        ppos = self._player_pos()
        if ppos is None or target is None:
            return [0, 0]
        dx, dy = target[0] - ppos[0], target[1] - ppos[1]
        thresh = 8.0  # dead-zone so a reached target stops producing input
        return [(1 if dx > thresh else -1 if dx < -thresh else 0),
                (1 if dy > thresh else -1 if dy < -thresh else 0)]

    # ── state normalization (flat dict for obs mappings + gates) ─────────────
    def _normalize(self, snap: dict) -> dict:
        player = snap.get("player") or {}
        enemies = snap.get("enemies") or []
        run = snap.get("run") or {}
        wave = snap.get("wave") or {}
        pos = player.get("pos") or [0.0, 0.0]
        dead = player.get("dead")
        # A vanished player node is a death, not "no data" (post-death frees).
        player_dead = 1 if (dead is True or snap.get("player") is None) else 0

        nearest_dist = 99999.0
        for e in enemies:
            d = ((e["pos"][0] - pos[0]) ** 2 + (e["pos"][1] - pos[1]) ** 2) ** 0.5
            nearest_dist = min(nearest_dist, d)

        return {
            "frame": snap.get("frame", 0),
            "player_x": float(pos[0]),
            "player_y": float(pos[1]),
            "player_hp": player.get("hp") if player.get("hp") is not None else 0,
            "player_max_hp": player.get("max_hp") or 0,
            "player_dead": player_dead,
            "player_invulnerable": 1 if player.get("invulnerable") else 0,
            "enemy_count": len(enemies),
            "nearest_enemy_dist": nearest_dist,
            "bullets": snap.get("bullets", -1),
            "wave": wave.get("current_wave") or 0,
            "boss_wave": wave.get("boss_wave") or 0,
            "run_active": 1 if run.get("active") else 0,
            "total_runs": run.get("total_runs") or 0,
            "events_count": len(snap.get("events", [])),
            "paused": 1 if snap.get("paused") else 0,
            "level_up_pending": 1 if (snap.get("level_up") or {}).get("pending")
            else 0,
            "mutations_taken": len(((snap.get("mutations") or {})
                                    .get("active_ids") or [])),
            "evidence_count": len(((snap.get("narrative") or {})
                                   .get("evidence") or [])),
        }

    # ── wire plumbing ────────────────────────────────────────────────────────
    _EOF = object()

    def _drain_stdout(self, proc):
        """Reader thread: every stdout line into the queue, EOF as sentinel."""
        for line in proc.stdout:
            self._lines.put(line.rstrip("\n"))
        self._lines.put(self._EOF)

    def _drain_stderr(self):
        proc = self.process
        if proc is None or proc.stderr is None:
            return
        for line in proc.stderr:
            self.stderr_lines.append(line.rstrip("\n"))

    def _rpc(self, req: dict, timeout: float = 60.0) -> dict:
        self.process.stdin.write(json.dumps(req) + "\n")
        self.process.stdin.flush()
        return self._read_msg(timeout)

    def _read_msg(self, timeout: float = 60.0) -> dict:
        deadline = time.time() + timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise TimeoutError(f"no protocol line within {timeout:.0f}s")
            try:
                line = self._lines.get(timeout=min(remaining, 0.5))
            except queue.Empty:
                continue
            if line is self._EOF:
                raise RuntimeError(
                    "EOF from harness (exit %s); stderr tail:\n%s"
                    % (self.process.poll(),
                       "\n".join(self.stderr_lines[-15:])))
            line = line.strip()
            if line.startswith("{"):
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    self.noise.append(line)
                    continue
                if msg.get("ugt") is True:
                    return msg
            if line:
                self.noise.append(line)

    def _kill_process(self):
        proc, self.process = self.process, None
        if proc is None:
            return
        try:
            if proc.poll() is None:
                try:
                    proc.stdin.write(json.dumps({"op": "quit"}) + "\n")
                    proc.stdin.flush()
                except (OSError, ValueError):
                    pass
                try:
                    proc.stdin.close()
                except (OSError, ValueError):
                    pass
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        if self._stdout_thread is not None:
            self._stdout_thread.join(timeout=5)
            self._stdout_thread = None
        if self._stderr_thread is not None:
            self._stderr_thread.join(timeout=5)
            self._stderr_thread = None
