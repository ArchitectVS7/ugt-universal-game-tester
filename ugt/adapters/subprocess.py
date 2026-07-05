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
        return response.get("state", {})

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

        return state, terminated, truncated, info

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
