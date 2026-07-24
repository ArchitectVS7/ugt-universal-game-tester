import os
import random
import sys
import json

class MockGame:
    def __init__(self):
        # Reproducibility: seed from UGT_SEED and advance per episode, exactly as a
        # real bridge should (see UGT-USER-MANUAL.md §4a). The core economy here is
        # deterministic; the seed drives `enemy.credits` — a genuine per-episode
        # random walk — so two runs with the same UGT_SEED are byte-identical and a
        # different seed produces a different enemy trajectory. Nothing the
        # feature-map asserts depends on it.
        self.base_seed = int(os.environ.get("UGT_SEED", 12345))
        self.episode_count = 0
        self.rng = random.Random(self.base_seed)
        self.credits = 100
        self.ap = 10
        self.turns_elapsed = 0
        self.enemy_credits = 0
        self.victory = False
        self.defeat = False

    def get_state(self):
        return {
            "player": {
                "credits": self.credits,
                "ap": self.ap
            },
            "enemy": {
                "credits": self.enemy_credits
            },
            "turns_elapsed": self.turns_elapsed,
            "victory": self.victory,
            "defeat": self.defeat
        }

    def reset(self):
        # Per-episode seed so a same-seed re-run reproduces every episode.
        self.rng = random.Random(self.base_seed + self.episode_count)
        self.episode_count += 1
        self.credits = 100
        self.ap = 10
        self.turns_elapsed = 0
        self.enemy_credits = self.rng.randint(0, 100)
        self.victory = False
        self.defeat = False
        return self.get_state()

    def step(self, action_id):
        # Action space: 0: wait, 1: invest_credits, 2: end_turn
        if action_id == 0:
            # wait
            pass
        elif action_id == 1:
            # invest_credits
            if self.ap >= 2:
                self.credits += 50
                self.ap -= 2
        elif action_id == 2:
            # end_turn
            self.turns_elapsed += 1
            self.ap = 10
            # A seeded random walk for the rival economy (reproducible per seed).
            self.enemy_credits = max(0, min(100, self.enemy_credits + self.rng.randint(-20, 20)))

        # Check endgame
        if self.credits >= 500:
            self.victory = True
        elif self.turns_elapsed >= 20:
            self.defeat = True

        terminated = self.victory or self.defeat
        truncated = False
        info = {}

        return self.get_state(), terminated, truncated, info

def main():
    game = MockGame()
    
    # Process newline delimited JSON commands from stdin
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            cmd = json.loads(line.strip())
        except Exception:
            continue

        command = cmd.get("command")
        if command == "reset":
            state = game.reset()
            response = {"state": state}
        elif command == "step":
            action_id = cmd.get("action_id", 0)
            state, terminated, truncated, info = game.step(action_id)
            response = {
                "state": state,
                "terminated": terminated,
                "truncated": truncated,
                "info": info
            }
        elif command == "close":
            break
        else:
            response = {"error": f"Unknown command: {command}"}

        print(json.dumps(response))
        sys.stdout.flush()

if __name__ == "__main__":
    main()
