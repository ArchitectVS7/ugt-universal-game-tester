#!/usr/bin/env python3
"""
Warzones → UGT IPC Bridge

A thin JSON-over-stdin/stdout wrapper around the existing Warzones Python sim
(from warzones-ml/sim/). This script allows UGT to control Warzones games via
the standard subprocess adapter protocol without modifying any sim code.

Protocol:
  stdin  → {"command": "reset"} or {"command": "step", "action_id": N} or {"command": "close"}
  stdout ← {"state": {...}, "terminated": bool, "truncated": bool, "info": {...}}

Usage:
  Invoked automatically by UGT's SubprocessAdapter. Not intended for direct use.
  The ugt.config.yaml engine.entry field should point to this file.

Dependencies:
  Requires the warzones-ml/sim package to be importable. This script adds the
  warzones-ml directory to sys.path at startup.
"""

import sys
import os
import json
import random

# Add the warzones-ml directory to sys.path so we can import the sim modules
WARZONES_ML_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "warzones", "warzones-ml")
WARZONES_ML_DIR = os.path.abspath(WARZONES_ML_DIR)
sys.path.insert(0, WARZONES_ML_DIR)

from sim.turn_manager import create_new_game, process_end_turn
from sim.victory import check as check_victory
from sim.combat import resolve_combat, calculate_salvage


class WarzonesBridge:
    """Wraps the Warzones sim in the UGT IPC protocol."""

    def __init__(self, sector_count=1000, bot_count=10):
        self.sector_count = sector_count
        self.bot_count = bot_count
        self.state = None
        self.rng = None
        self.base_seed = int(os.environ.get("UGT_SEED", random.randint(0, 999999)))
        self.episode_count = 0

    def reset(self):
        """Reset the game and return initial state."""
        episode_seed = self.base_seed + self.episode_count
        self.episode_count += 1
        self.state, self.rng = create_new_game(
            seed=episode_seed, sector_count=self.sector_count, bot_count=self.bot_count
        )
        return self._build_response(terminated=False, truncated=False)

    def step(self, action_id):
        """Execute an action and return the new state."""
        s = self.state
        p = s.player

        # Auto-correct: if no AP and trying non-end-turn action, force end turn
        if action_id != 0 and p.action_points <= 0:
            action_id = 0

        # === Action Execution ===
        # Matches the action space from warzones_env_sim.py exactly
        if action_id == 0:  # End Turn
            process_end_turn(s, self.rng)

        elif action_id == 1:  # Scan (costs 0.5 AP)
            if p.can_afford_ap(0.5):
                p.spend_ap(0.5)

        elif action_id == 2:  # Deploy Fighter (costs 1 AP, 1 fighter)
            if p.can_afford_ap(1) and p.ship.fighters > 0:
                p.spend_ap(1)
                p.ship.fighters -= 1
                sector = s.get_sector(p.current_sector_id)
                if sector:
                    sector.deployed_fighters += 1
                    sector.controlled_by = 'player'
            else:
                p.spend_ap(1)

        elif action_id == 3:  # Warp to connected sector
            if p.can_afford_ap(1):
                sector = s.get_sector(p.current_sector_id)
                if sector and sector.connected_sector_ids:
                    target_id = self.rng.choice(sector.connected_sector_ids)
                    p.spend_ap(1)
                    p.current_sector_id = target_id
                    # Auto-combat with aggressive bots
                    bots_in_sector = [
                        b for b in s.bots
                        if b.is_alive and b.current_sector_id == target_id
                    ]
                    for bot in bots_in_sector:
                        if bot.archetype == 'Pirate' or (
                            bot.personality and bot.personality.attack_on_sight
                        ):
                            combat_sector = s.get_sector(target_id)
                            result = resolve_combat(
                                p.ship, bot.ship, combat_sector, p.name, bot.name, self.rng
                            )
                            if result.outcome == 'ATTACKER_WINS':
                                salvage = calculate_salvage(bot.ship, self.rng)
                                p.add_credits(salvage)
                                s.total_credits_earned += salvage
                            break
                else:
                    p.spend_ap(1)
            else:
                p.spend_ap(1)

        elif action_id == 4:  # Trade at Port
            if p.can_afford_ap(0.5):
                p.spend_ap(0.5)
                port = s.get_port(p.current_sector_id)
                if port:
                    for commodity_id, qty in list(p.cargo.items.items()):
                        if qty > 0 and port.buys_commodity(commodity_id):
                            price = port.get_buy_price(commodity_id)
                            revenue = qty * price
                            p.cargo.remove(commodity_id, qty)
                            p.add_credits(revenue)
                    for commodity_id in port.inventory.keys():
                        if port.sells_commodity(commodity_id):
                            price = port.get_sell_price(commodity_id)
                            afford_qty = int(p.credits // price)
                            space_qty = p.ship.cargo_capacity - p.cargo.total_quantity
                            buy_qty = min(afford_qty, space_qty)
                            if buy_qty > 0:
                                cost = buy_qty * price
                                p.spend_credits(cost)
                                p.cargo.add(commodity_id, buy_qty)
            else:
                p.spend_ap(0.5)

        # === Check Victory / Defeat ===
        victory = check_victory(s)
        game_over = victory['is_game_over']
        player_won = victory['player_won']
        turn_limit = s.turn_number >= 500
        terminated = game_over or turn_limit

        return self._build_response(
            terminated=terminated,
            truncated=False,
            victory_info=victory,
        )

    def _build_response(self, terminated, truncated, victory_info=None):
        """Build the standard UGT IPC response."""
        s = self.state
        p = s.player

        player_sectors = sum(1 for sec in s.sectors if sec.controlled_by == 'player')
        enemy_sectors = sum(1 for sec in s.sectors if sec.controlled_by and sec.controlled_by != 'player')
        bots_alive = sum(1 for b in s.bots if b.is_alive)

        is_victory = victory_info and victory_info.get('player_won', False)

        state = {
            "turn": s.turn_number,
            "player": {
                "credits": p.credits,
                "ap": p.action_points,
                "sectors_owned": player_sectors,
                "hull": p.ship.hull,
                "max_hull": p.ship.max_hull,
            },
            "enemy": {
                "sectors_owned": enemy_sectors,
                "bots_alive": bots_alive,
            },
            "game_over": 1.0 if (victory_info and victory_info['is_game_over']) else 0.0,
            "player_won": 1.0 if is_victory else 0.0,
            "victory": is_victory,
            "telemetry": {
                "total_credits_earned": s.total_credits_earned,
                "bots_killed": sum(1 for b in s.bots if not b.is_alive),
            },
        }

        info = {}
        if victory_info:
            info["victory_condition"] = victory_info.get("condition", "None")
            info["victory_message"] = victory_info.get("message", "")

        return {
            "state": state,
            "terminated": terminated,
            "truncated": truncated,
            "info": info,
        }


def main():
    bridge = WarzonesBridge()

    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            cmd = json.loads(line.strip())
        except Exception:
            continue

        command = cmd.get("command")
        if command == "reset":
            response = bridge.reset()
        elif command == "step":
            action_id = cmd.get("action_id", 0)
            response = bridge.step(action_id)
        elif command == "close":
            break
        else:
            response = {"error": f"Unknown command: {command}"}

        print(json.dumps(response))
        sys.stdout.flush()


if __name__ == "__main__":
    main()
