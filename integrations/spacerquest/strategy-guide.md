# SpacerQuest — LLM Playtest Strategy Guide

## CRITICAL: The Only Loop That Earns Score

DO THIS in exact order, then repeat forever:

1. `upgrade_cheapest` — first action only. Costs 10,000 cr, upgrades hull, unlocks cargo capacity.
2. `accept_cargo` — pick up contract. **Works from ANY system. Do NOT navigate anywhere first.**
3. `navigate_cargo_dest` — fly to destination. Auto-delivers on arrival. Earns score + credits.
4. If trip_count == 2 after navigating: call `end_turn` FIRST (resets trip_count to 0), THEN go to step 2.
5. Go to step 2 (accept next contract). Repeat forever.

**If fuel == 0 or < 10**: call `buy_fuel` ONCE, then immediately go back to whichever step you were on.
**NEVER call navigate_neighbor** — it wastes a trip slot and earns nothing.
**NEVER call accept_cargo when destination > 0** — you already have a contract; deliver it first.
**NEVER call navigate_cargo_dest when trip_count == 2** — it will silently fail; call end_turn first.

---

## Win Condition

Accumulate **10,000 score points**. This grants Conqueror rank and ends the game
(the Andromeda wormhole / Maligna route opens). Score comes from:
- Cargo deliveries (primary source, ~50–200 points per delivery)
- Combat victories
- Completing missions

The game ends in **defeat** when hull_condition = 0 AND credits = 0 simultaneously.
You lose both your hull AND your credits — not just one of them.

---

## Starting State

| Field | Value |
|-------|-------|
| credits | 1,000 cr |
| fuel | 50 units |
| current_system | 1 (Sun-3) |
| rank | LIEUTENANT (rank_index=0) |
| hull_strength | 5 |
| hull_condition | 9/9 |
| cargo_pods | 0 (no trading yet) |

**The single most important early action: upgrade_cheapest (which upgrades hull).** Hull
strength determines cargo capacity and unlocks the cargo trading loop. After upgrading
hull once (hull_strength goes from 5 → 15), you gain cargo pods and can start using
accept_cargo. All upgrades cost 10,000 cr — hull is the highest-value target every time.

**CRITICAL SEQUENCE — follow this exactly:**
1. Start: upgrade_cheapest (costs 10,000 cr, upgrades hull, unlocks cargo capacity)
2. IMMEDIATELY after upgrade: accept_cargo — do NOT navigate first. accept_cargo works
   from ANY system and assigns you a delivery contract (cargo_pods → 50, destination → N).
3. Then: navigate_cargo_dest to fly to the destination and auto-deliver.
4. Repeat from step 2 for income.

**DO NOT navigate_neighbor between upgrade and accept_cargo.** Navigation costs credits
and doesn't bring you closer to cargo. If cargo_pods == 0 and destination == 0, call
accept_cargo NOW.

---

## Core Game Loop

```
EARLY GAME (rank_index 0–3):
  → sell_fuel (50 units) → earn credits
  → navigate to cheap fuel system (1, 8, or 14) → buy_fuel
  → save up 10,000 cr → upgrade_cheapest (hull strength)
  → once cargo_pods >= 1: enter cargo loop

CARGO LOOP (main income):
  → accept_cargo (get a delivery contract with destination)
  → navigate_cargo_dest (fly to destination system)
  → (cargo is auto-delivered on arrival)
  → back to start for next contract

MID GAME (rank_index 3–6):
  → upgrade weapons and shields alongside hull
  → accept combat_attack when in_combat (for battle_won score)
  → combat_retreat when ship condition < 5

LATE GAME (rank_index 7–8, score > 8000):
  → focus exclusively on cargo deliveries for score
  → bank_deposit to protect credits
  → repair_ship whenever hull_condition < 7
```

---

## Action Vocabulary

| ID | Name | When to use |
|----|------|-------------|
| 0 | wait | Never — it's a no-op that wastes a step |
| 1 | navigate_cheap_fuel | When fuel < 100 and you're not near a cheap system |
| 2 | navigate_cargo_dest | When you have a cargo contract (destination > 0) |
| 3 | navigate_neighbor | When exploring or repositioning |
| 4 | buy_fuel | After arriving at a cheap fuel system (1, 8, 14) |
| 5 | sell_fuel | When fuel > 300 and you need quick credits |
| 6 | accept_cargo | When cargo_pods == 0 and destination == 0 (pick up a new contract) |
| 7 | deliver_cargo | Redundant with navigate_cargo_dest — use 2 instead |
| 8 | upgrade_cheapest | When credits > 5,000 (robotics upgrade) or > 10,000 (hull) |
| 9 | repair_ship | When hull_condition < 7 |
| 10 | combat_attack | When in_combat == 1 and weapon_strength >= 5 |
| 11 | combat_retreat | When in_combat == 1 and hull_condition <= 3 |
| 12 | pub_gamble_wheel | Sparingly — high variance, mostly avoid |
| 13 | bank_deposit | When credits > 20,000 (protect earnings) |
| 14 | end_turn | Every ~10 actions to let bot events tick |

---

## Cheap Fuel Systems

| System | Fuel Price |
|--------|-----------|
| 1 (Sun-3) | 8 cr/unit |
| 8 (Mira-9) | 4 cr/unit |
| 14 (Vega-6) | 6 cr/unit |

Always navigate to system 8 or 14 to refuel — they are 2–4× cheaper than other systems.

---

## Good State Looks Like

- `character.credits` increasing steadily over time
- `character.trip_count` increasing (delivering cargo regularly)
- `ship.hull_condition` staying at 8–9
- `character.cargo_pods >= 1` by turn 50
- `character.score` growing each cargo delivery
- `ship.fuel >= 100` before any long journey

## Danger Signs

- `ship.fuel < 20` — you may be unable to travel. Navigate to nearest cheap system first.
- `ship.hull_condition < 4` — critical. Repair immediately or you'll be destroyed.
- `character.credits < 500 AND ship.fuel < 20` — terminal spiral. Use sell_fuel to get credits.
- `character.destination > 0 AND cargo_pods == 0` — stuck. Use wait to skip (cargo contracts lapse).
- `in_combat == 1 AND weapon_strength < 3` — retreat immediately.

## Bug Signatures (flag with potential_bug)

- Credits unchanged after accepting and delivering a cargo contract
- `destination` still > 0 after navigate_cargo_dest (travel didn't resolve)
- `current_system` unchanged after navigate_neighbor (travel didn't fire)
- `hull_condition` decreased without a combat event
- `player_won = 1` before `character.score >= 10000`
- `character.rank_index` not increasing as `character.score` increases
- `in_combat = 1` persisting for more than 3 turns (combat stuck)
- Any action returning credits < 0 (negative credits should be impossible)
