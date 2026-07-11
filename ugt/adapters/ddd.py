import json
import subprocess
import os
import sys
import random
from ugt.adapters.base import BaseAdapter

class DDDSubprocessAdapter(BaseAdapter):
    """
    Adapter specifically for the DDD JSON-lines harness.
    Handles the simultaneous P0/P1 nature of DDD by simulating a random opponent.
    """
    def __init__(self, config):
        super().__init__(config)
        self.process = None
        self.match_id = None
        self.rng = random.Random()

    def connect(self):
        entry_cmd = self.config.engine_entry
        config_dir = os.path.dirname(os.path.abspath(self.config.filepath))
        
        if entry_cmd.endswith(".js"):
            cmd = ["node", entry_cmd]
        else:
            cmd = entry_cmd.split()

        try:
            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,  # Line buffered
                cwd=config_dir,
            )
        except Exception as e:
            raise RuntimeError(f"Failed to spawn DDD harness with command '{cmd}': {e}")

    def _send_command(self, cmd_dict):
        if not self.process or self.process.poll() is not None:
            raise RuntimeError("Harness subprocess is not running.")
        
        msg = json.dumps(cmd_dict) + "\n"
        self.process.stdin.write(msg)
        self.process.stdin.flush()

        line = self.process.stdout.readline()
        if not line:
            err = self.process.stderr.read()
            raise RuntimeError(f"Harness terminated unexpectedly. Stderr: {err}")
        
        try:
            resp = json.loads(line.strip())
            if not resp.get("ok"):
                raise RuntimeError(f"Harness error: {resp.get('error')}")
            return resp
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Invalid JSON response from harness: '{line.strip()}' - {e}")

    def reset(self):
        if not self.process or self.process.poll() is not None:
            self.connect()

        seed = self.config.data.get("training", {}).get("seed", 42)
        
        # Hardcode basic config for now, or read from self.config?
        # A real implementation could parse decks from ugt.config.yaml or just use tutorials.
        match_config = {
            "format": "TUTORIAL",
            "enabledWaves": { "stanceEcho": False, "chainsPredictions": False },
            "maxTurns": 50,
            "decks": ["bb_tutorial", "sw_tutorial"]
        }

        resp = self._send_command({
            "cmd": "create",
            "seed": str(seed),
            "config": match_config
        })

        self.match_id = resp["matchId"]
        self.rng = random.Random(seed) # reset opponent RNG
        return resp["view0"]

    def _get_legal_actions(self, player):
        resp = self._send_command({
            "cmd": "legal",
            "matchId": self.match_id,
            "player": player
        })
        return resp.get("actions", [])

    def step(self, action_id):
        # 1. P0 (Agent) acts
        p0_actions = self._get_legal_actions(0)
        
        if not p0_actions:
            # We are probably terminated already or stuck
            return self._get_latest_view(), True, False, {"error": "No legal actions for P0"}

        # Map integer to legal action safely
        chosen_p0_action = p0_actions[int(action_id) % len(p0_actions)]

        p0_resp = self._send_command({
            "cmd": "act",
            "matchId": self.match_id,
            "player": 0,
            "action": chosen_p0_action
        })

        latest_view = p0_resp["view0"]

        # 2. Loop: simulate P1 actions until it's P0's turn again or the match ends
        while latest_view["result"]["kind"] == "ONGOING":
            # Check if P0 needs to act again (e.g. they both need to act, but P0 goes first? 
            # Actually, both act simultaneously in DDD, so P1 needs to act now)
            p0_needs_action = len(self._get_legal_actions(0)) > 0
            if p0_needs_action:
                # wait, if P0 needs an action NOW, we should break out and let UGT supply it!
                # But wait, usually both submit in SELECTION. If P0 submitted, P0 has 0 legal actions 
                # until P1 submits and the phase advances.
                break
            
            p1_actions = self._get_legal_actions(1)
            if p1_actions:
                # exclude CONCEDE unless it's the only one
                non_concede = [a for a in p1_actions if a.get("t") != "CONCEDE"]
                pool = non_concede if non_concede else p1_actions
                chosen_p1_action = self.rng.choice(pool)

                p1_resp = self._send_command({
                    "cmd": "act",
                    "matchId": self.match_id,
                    "player": 1,
                    "action": chosen_p1_action
                })
                latest_view = p1_resp["view0"]
            else:
                # If neither P0 nor P1 has actions but ONGOING... deadlock?
                # This shouldn't happen in DDD. Break to avoid infinite loop.
                break

        terminated = latest_view["result"]["kind"] != "ONGOING"
        is_win = latest_view["result"].get("winner") == 0

        info = {"victory": is_win}
        latest_view["info"] = info # So UGT can read it

        return latest_view, terminated, False, info

    def _get_latest_view(self):
        # We can't query state without an action, but `create` and `act` return it.
        # Actually, if we just want it, maybe we don't have a direct query in harness.
        # It's fine, we return empty or crash.
        return {}

    def close(self):
        if self.process:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
            self.process = None
