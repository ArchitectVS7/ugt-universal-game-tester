# SpacerQuest → UGT IPC Simulator Bridge (⚠️ RETIRED — cautionary example)

> **Do not extend or imitate this.** This bridge reimplemented SpacerQuest's game logic and silently drifted
> from the real game (it had no combat and broken upgrades) — every agent trained against it learned a
> different game. It is the failure mode UGT's #1 rule ("drive the real running game, never a
> re-implementation") exists to prevent. See `../../PLAN-FORWARD.md` and
> `../../Dev/PLAN-FORWARD-spacerquest.md`. The pitch below is preserved unedited as the record of how
> reasonable the wrong approach sounded.

This example integrates **SpacerQuest v4.0** with the **Universal Game Tester (UGT)** framework. 

Rather than automating the game via a brittle and high-latency browser adapter (which would require launching Chromium, navigating web pages, and parsing xterm.js ANSI feeds), this integration uses UGT's headless **Subprocess Adapter** coupled with a high-performance **TypeScript IPC Bridge** (`sim_bridge.ts`).

---

## Architecture

The bridge executes directly inside the same environment as the SpacerQuest backend. It maps high-level RL actions to underlying server-side routing inputs, bypassing the frontend completely but exercising the exact same game rules:

```
┌─────────────────┐
│   UGT Python    │  Reinforcement Learning policy (PPO)
└────────┬────────┘
         │
         │  JSON stdin/stdout IPC
         ▼
┌─────────────────┐
│  sim_bridge.ts  │  TypeScript Subprocess Wrapper (running via tsx)
└────────┬────────┘
         ├──────────────────────────────────────────────┐
         ▼                                              ▼
┌─────────────────────────────────┐           ┌───────────────────┐
│  SpacerQuest Server Controllers │           │  Prisma Database  │
│  - handleScreenRequest()        │           │  - spacerquest_ugt│
│  - handleScreenInput()          │           └───────────────────┘
└─────────────────────────────────┘
```

---

## State Space (20-Element Box)

The UGT agent observes a standardized 20-element vector extracted directly from the database after every action:

1. `character.credits` — Combined low and high credits representation.
2. `character.score` — Current points (aiming for 10,000 for victory).
3. `character.rank_index` — Numeric mapping of rank (0 = Lieutenant, 8 = Giga Hero).
4. `character.current_system` — Star system ID (1 to 28).
5. `character.trip_count` — Travel trips completed during the current turn.
6. `character.battles_won` — Tracked lifetime victories.
7. `character.cargo_pods` — Number of loaded cargo pods.
8. `character.destination` — Destination system for currently accepted cargo contract.
9. `ship.fuel` — Loaded ship fuel.
10. `ship.hull_strength` — Maximum hull integrity.
11. `ship.hull_condition` — Current hull condition (0 to 9).
12. `ship.drive_strength` — Drive strength.
13. `ship.weapon_strength` — Equipped weapon strength.
14. `ship.shield_strength` — Equipped shield strength.
15. `ship.has_cloaker` — Cloaking device equipped (0 or 1).
16. `ship.has_auto_repair` — Auto-repair module equipped (0 or 1).
17. `character.is_lost` — Flag for being lost in deep space.
18. `character.in_combat` — Flag indicating whether the player is currently engaged in combat.
19. `character.bank_balance` — Credits currently deposited in the bank.
20. `turn_number` — Step index within the episode.

---

## Action Space (15 Discrete Options)

The RL policy selects from 15 discrete macro actions, which the bridge translates into specific terminal key sequences and resolves instantly:

* `0`: **Wait** — No-op stay at main menu.
* `1`: **Navigate Cheap Fuel** — Route to closest system with discount fuel (Sun-3, Mira-9, Vega-6).
* `2`: **Navigate Cargo Dest** — Route to current cargo contract destination.
* `3`: **Navigate Neighbor** — Route to an adjacent star system.
* `4`: **Buy Fuel** — Visit Traders and buy maximum affordable fuel.
* `5`: **Sell Fuel** — Visit Traders and sell surplus fuel.
* `6`: **Accept Cargo** — Negotiate and accept a new contract.
* `7`: **Deliver Cargo** — Route to destination system and deliver goods.
* `8`: **Upgrade Cheapest** — Visit the shipyard and purchase the cheapest available component upgrade.
* `9`: **Repair Ship** — Full structural repairs.
* `10`: **Combat Attack** — Attack target during active combat.
* `11`: **Combat Retreat** — Attempt to flee active combat.
* `12`: **Pub Gamble** — Play Wheel of Fortune (betting 100cr on number 7).
* `13`: **Bank Deposit** — Deposit half of current held credits to secure them from pirates.
* `14`: **End Turn** — Relinquish control and allow NPC bots to execute.

---

## Setup & Verification

### 1. Database Provisioning
Ensure the PostgreSQL Docker container is running and seed the isolated `spacerquest_ugt` database:
```bash
# From spacerquest-web directory:
DATABASE_URL=postgresql://spacerquest:spacerquest@localhost:5454/spacerquest_ugt npx prisma db push
DATABASE_URL=postgresql://spacerquest:spacerquest@localhost:5454/spacerquest_ugt npx tsx prisma/seed.ts
```

### 2. Run Smoke Test
Run the connection and verification check to make sure that the bridge communicates cleanly and all 20 state values map correctly:
```bash
# From UGT root directory:
python3 -m ugt.cli smoke-test --config examples/spacerquest/ugt.config.yaml --profile explorer
```

### 3. Run Training
Train a Reinforcement Learning agent (PPO policy) to maximize score, credits, and travel:
```bash
# Train using the explorer profile
python3 -m ugt.cli train --config examples/spacerquest/ugt.config.yaml --profile explorer

# Or train using the trader profile
python3 -m ugt.cli train --config examples/spacerquest/ugt.config.yaml --profile trader
```

### 4. Tensorboard Dashboard
Monitor your agent's learning progress (cumulative rewards, episode lengths, value losses):
```bash
python3 -m ugt.cli dashboard --logdir ./logs
```

### 5. Evaluation
Evaluate a trained model over 50 test episodes to analyze victory rates and state coverage:
```bash
python3 -m ugt.cli evaluate --config examples/spacerquest/ugt.config.yaml --profile explorer --model ./models/ppo_explorer_final --episodes 50
```
