import json
import subprocess
import os
import sys
from ugt.adapters.base import BaseAdapter

class SubprocessAdapter(BaseAdapter):
    """
    Adapter for headless, simulation-based games.
    Spawns the simulator as a background process and communicates via JSON over stdin/stdout.
    """
    def __init__(self, config):
        super().__init__(config)
        self.process = None
        # Rolling narration tail — see _record_narration / get_terminal_text.
        self._narration = []

    def connect(self):
        entry_cmd = self.config.engine_entry
        config_dir = os.path.dirname(os.path.abspath(self.config.filepath))
        
        # If it's a python script, run it with the current python interpreter
        if entry_cmd.endswith(".py"):
            cmd = [sys.executable, entry_cmd]
        elif entry_cmd.endswith(".js"):
            cmd = ["node", entry_cmd]
        else:
            cmd = entry_cmd.split()

        seed = self.config.data.get("training", {}).get("seed", 42)
        process_env = os.environ.copy()
        process_env["UGT_SEED"] = str(seed)

        try:
            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,  # Line buffered
                cwd=config_dir,
                env=process_env,
            )
        except Exception as e:
            raise RuntimeError(f"Failed to spawn subprocess simulation with command '{cmd}': {e}")

    def _send_command(self, cmd_dict):
        if not self.process or self.process.poll() is not None:
            raise RuntimeError("Subprocess is not running. Check connection or game crashes.")
        
        # Send command
        msg = json.dumps(cmd_dict) + "\n"
        self.process.stdin.write(msg)
        self.process.stdin.flush()

        # Read response
        line = self.process.stdout.readline()
        if not line:
            # Check for standard errors
            err = self.process.stderr.read()
            raise RuntimeError(f"Subprocess terminated unexpectedly. Stderr: {err}")
        
        try:
            return json.loads(line.strip())
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Invalid JSON response from subprocess: '{line.strip()}' - {e}")

    def reset(self):
        # If the process isn't running or reset needs a restart, restart it
        if not self.process or self.process.poll() is not None:
            self.connect()

        response = self._send_command({"command": "reset"})
        state = response.get("state", {})

        # A reset starts a NEW episode, so the previous one's narration must not
        # survive into it — otherwise the first prompt of episode 2 shows the
        # last thing that happened in episode 1, which reads as the present.
        self._narration.clear()

        # A game is allowed to narrate its opening position on reset, and one
        # that does was being thrown away here: only `step` recorded narration,
        # so the tier's FIRST decision was always made with an empty terminal
        # panel however much prose the game had sent. For a game whose opening
        # screen IS its room description, that cost the player character a move
        # to re-read something it should already have been holding.
        self._record_narration(response.get("info", {}), state)
        return state

    def reset_seeded(self, seed):
        """Start a fresh episode on `seed` — `{"command": "reset", "seed": N}`.

        The game MUST acknowledge the seed it actually used, either as a
        top-level `seed` or as `info.seed` in its reset response. If it does
        not, this raises rather than returning a state.

        That is deliberate and is the whole point of the method. A bridge that
        does not understand the extra key parses the JSON, ignores `seed`, and
        returns a perfectly normal episode on its own internal counter — no
        error anywhere. The tier would then report N episodes, aggregate over an
        N-sized denominator, and be describing one seed re-rolled N times. That
        is exactly the silent-ignore failure `BaseAdapter.reset_seeded` exists to
        forbid (LESSONS §B P9), and it is invisible in the output, so it cannot
        be left to trust: an unacknowledged seed is treated as an unsupported
        one. A game opts in by echoing the seed back.
        """
        if not self.process or self.process.poll() is not None:
            self.connect()

        response = self._send_command({"command": "reset", "seed": int(seed)})
        state = response.get("state", {})
        info = response.get("info", {}) or {}
        ack = response.get("seed", info.get("seed"))

        if ack is None:
            raise NotImplementedError(
                f"{type(self).__name__}.reset_seeded({seed}) — the game at "
                f"'{self.config.engine_entry}' did not acknowledge the seed. Its "
                f"reset response carried no top-level 'seed' and no 'info.seed', "
                f"so there is no evidence it used the one requested rather than "
                f"its own. Echo the seed back from the reset handler to opt in; "
                f"until then do not treat this game's episodes as independent "
                f"samples."
            )
        if int(ack) != int(seed):
            raise RuntimeError(
                f"{type(self).__name__}.reset_seeded({seed}) — the game "
                f"acknowledged a DIFFERENT seed ({ack}). Episodes would not be "
                f"the ones the caller asked for."
            )

        self._narration.clear()
        self._record_narration(info, state)
        return state

    def step(self, action_id):
        # Send action to simulator
        response = self._send_command({
            "command": "step",
            "action_id": int(action_id)
        })

        state = response.get("state", {})
        terminated = response.get("terminated", False)
        truncated = response.get("truncated", False)
        info = response.get("info", {})

        self._record_narration(info, state)
        return state, terminated, truncated, info

    # ── Narration channel ───────────────────────────────────────────────────
    # `BaseAdapter.get_terminal_text()` returns "" for adapters that cannot
    # expose text, and a subprocess game had no way to opt in — so the playtest
    # tier rendered an EMPTY terminal panel, silently, for every simulation-engine
    # game. That is survivable for a game whose state dict says everything; it is
    # fatal for one whose genre IS prose. Found on a Node text adventure whose
    # bridge produced room descriptions, examine text and authored refusals, all
    # of which the tier threw away: the pilot was playing a text adventure with
    # no text and nothing in the output said so.
    #
    # The field is CONFIGURED, not hardcoded, because a game's narration can
    # legitimately live anywhere in its response:
    #
    #     playtest:
    #       narration_field: "info.message"   # default
    #
    # A dotted path resolved against {"info": ..., "state": ...}. Set it to null
    # to opt out. A game that never fills the field simply narrates nothing,
    # which is the honest version of today's behaviour rather than a silent one:
    # `narration_is_live()` lets a pre-flight assert the channel really carries.

    def _narration_path(self):
        cfg = (getattr(self.config, "data", None) or {}).get("playtest") or {}
        if "narration_field" not in cfg:
            return ("info", "message")
        raw = cfg.get("narration_field")
        return tuple(raw.split(".")) if raw else None

    def _record_narration(self, info, state):
        path = self._narration_path()
        if not path:
            return
        node = {"info": info, "state": state}
        for key in path:
            if not isinstance(node, dict):
                return
            node = node.get(key)
        if isinstance(node, str) and node:
            self._narration.append(node)
            # Bounded: a long episode must not grow this without limit. The tail
            # is what a player has just read, which is what the budget wants.
            if len(self._narration) > 200:
                del self._narration[:-200]

    def narration_is_live(self) -> bool:
        """True once the game has actually sent narration. A pre-flight can
        assert this instead of trusting that the field was wired up — an
        unfilled field and a game with nothing to say look identical."""
        return bool(self._narration)

    def get_terminal_text(self, chars: int = 600) -> str:
        """The tail of the game's own narration, newest last, within `chars`."""
        if not self._narration:
            return ""
        out = []
        used = 0
        for line in reversed(self._narration):
            if used + len(line) + 1 > chars and out:
                break
            out.append(line)
            used += len(line) + 1
        return "\n".join(reversed(out))

    def close(self):
        if self.process:
            if self.process.poll() is None:
                try:
                    self._send_command({"command": "close"})
                except Exception:
                    pass
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
            self.process = None
