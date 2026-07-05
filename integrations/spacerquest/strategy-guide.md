# SpacerQuest — LLM Playtest Strategy Guide (real server)

> Every number below is sourced from the game code (constants.ts, auth.ts dev-setup,
> economy.ts, docking.ts, upgrades.ts, end-turn.ts) — 2026-07-05. If the game contradicts
> this guide, TRUST THE GAME and flag the mismatch with `potential_bug`. Concrete rule:
> if any number this guide states is contradicted by the game TWICE, you MUST file a
> `potential_bug` describing guide-said vs game-did — that is part of your job.

## CRITICAL: The Profitable Loop (do this, in order)

1. **First two actions of a fresh run:** `upgrade_weapons`, then `upgrade_shields`
   (20,000 cr each: 10→20 strength). Every trip forces a combat encounter and the
   starting ship (weapons 10 / shields 10) LOSES most fights — upgrading first turns
   forced encounters into loot instead of losses.
2. `accept_cargo` — signs delivery contract #1 from the manifest board (only when
   `destination == 0`; if `destination > 0` you already have one).
3. `navigate_cargo_dest` — launches and arrives. An encounter fires EVERY trip
   (deterministic). If `in_combat == 1` after arriving: `combat_attack` repeatedly
   until `in_combat == 0`. Loot is enemy-dependent and often SMALL (baseLoot + your
   BF÷10 — frequently only ~70 cr), and every combat round burns fuel equal to
   weapons÷2 — combat is a toll you fight through, DELIVERIES are the profit. Use
   `combat_retreat` only if `hull_condition <= 3` (retreat ALWAYS succeeds).
4. Delivery is AUTOMATIC on arrival — credits += payment, score += 2.
5. **If you LOST the fight (battles_lost went up) or a launch fails with "Ship too
   badly damaged": `repair_ship` before anything else.** A damaged ship cannot lift
   off, and you cannot end the turn until you finish your 2 trips — repair is the
   only way out of that corner.
6. After 2 trips (`trip_count == 2`): `end_turn` (required — the 3rd launch is
   blocked until you do). Then back to step 2.
7. `buy_fuel` (buys 100 units) when `fuel < 200`.

## Win, loss, and what "progress" means

- **Win:** score ≥ 10,000 → Conqueror (character retires with honors). Cargo delivery
  gives **+2 score**; rim deliveries, patrol battles, duels (+10), rescues (+11) give
  more. This is a marathon by design — your job is a strong score/credits VELOCITY,
  not reaching 10,000 in one session.
- **Ranks by score:** COMMANDER 150 (you start at 148 — your first delivery earns the
  points, and the promotion + honorarium land at your NEXT `end_turn`, not instantly),
  CAPTAIN 300, COMMODORE 450, ADMIRAL 750, TOP_DOG 1200, GRAND_MUFTI 1650,
  MEGA_HERO 2250, GIGA_HERO 2700. Promotions pay an honorarium (credits).
- **Setbacks (not game over):** combat defeat costs cargo pods / half fuel; getting
  stranded (`is_lost == 1`) needs rescue; jail (`in_jail == 1`) needs bail. Flag a
  `potential_bug` if you can't recover from any of these.

## Starting State (after each reset — exact)

| Field | Value |
|-------|-------|
| credits | 100,000 cr |
| score | 148 (2 short of COMMANDER) |
| rank | LIEUTENANT (rank_index 0) |
| fuel | 800 units |
| hull 30 (cond 9) · weapons 10 · shields 10 · drives 10 · nav 40 | |
| cargo_pods | 0 loaded (capacity 200) |
| current_system | 1 (Sun-3) |
| trip_count | 0 (limit 2 per turn) |

## Economy facts (judge balance against these)

- Cargo payment = (value·distance ÷ 3)·pods + fuel×5 + 1,000, **capped at 15,000 cr**
  (rim contracts pay 1.4×, capped 25,000). Expect ~2,000–15,000 per delivery.
- Wrong-destination delivery pays 50% and costs −5 score. Never do it on purpose.
- Fuel prices: Sun-3 = 8 cr/unit, Mira-9 (system 8) = 4, Vega-6 = 6, most others 5.
- Component upgrade = +10 strength, price = (strength÷10 + 1) × 10,000 cr — so
  weapons 10→20 costs 20k, 20→30 costs 30k. `upgrade_cheapest` picks your
  lowest-strength core component (hull/drives/weapons/shields).
- Combat power (Battle Factor) comes ONLY from your ship (weapons·cond + shields·cond
  + support components + battles won) — rank gives no combat bonus.

## Action Vocabulary (these are ALL the mapped actions)

| Name | When |
|------|------|
| wait | Never (wasted step) — only if truly nothing else is legal |
| buy_fuel | fuel < 200 (buys 100 units at the local port) |
| accept_cargo | destination == 0 and trip_count < 2 |
| navigate_cargo_dest | destination > 0 (launch + arrive + auto-deliver) |
| deliver_cargo | Only to CONFIRM a delivery happened (it's automatic) — not needed in the loop |
| upgrade_cheapest | credits > 40,000 and weapons+shields already ≥ 20 |
| end_turn | trip_count == 2 (resets trips; other spacers take their turns) |
| combat_attack | in_combat == 1 and hull_condition > 3 |
| combat_retreat | in_combat == 1 and hull_condition <= 3 |
| upgrade_weapons | First action of a run; again when credits allow |
| upgrade_shields | Second action of a run; again when credits allow |
| repair_ship | After LOSING a fight, or when a launch fails with "Ship too badly damaged" — repairs all damage at the shipyard (cost scales with damage) |

You may also explore with `press_key`/`type_text` (single keys sent to the CURRENT
screen — e.g. from the main menu: T=Traders, S=Shipyard, P=Pub, B=Bank, D=End turn,
X=Stats). If a screen looks broken (raw JSON, `undefined`, NaN, empty render), flag
`potential_bug` — exploring is encouraged AFTER the core loop is running profitably.

## Good state looks like

- credits trending UP across trips (delivery payment > fuel spend)
- score +2 or more per delivery; rank_index rising at the thresholds above
- battles WON after weapons/shields hit 20+ (early losses are expected, chronic
  losses after upgrading are a balance flag, not your mistake — report it)
- hull_condition ≥ 7; fuel ≥ 200 before each launch

## Danger signs

- fuel < 100 → buy_fuel NOW (stranded = rescue fees)
- hull_condition ≤ 3 → retreat from combat; consider upgrade_cheapest (hull)
- credits < 20,000 and weapons still 10 → you upgraded too much or fought too little;
  prioritize cargo runs
- trip_count == 2 and you keep trying to fly → you MUST end_turn (this is the rule,
  not a bug)

## Bug signatures (flag with potential_bug)

- Credits unchanged after a completed delivery (arrival at the contract destination)
- destination still > 0 after a successful navigate_cargo_dest
- score does NOT increase (+2 minimum) on a correct delivery
- rank_index not advancing at the FIRST end_turn after score crossed a threshold
  (rank recalculates at turn processing, not instantly — instant non-advance is normal)
- in_combat == 1 persisting after 20+ combat_attack actions with battles_won/lost
  unchanged (combat stall)
- end_turn confirmed but trip_count does not reset to 0
- Negative credits or fuel anywhere, ever
- EPISODE_RESET markers are NORMAL (fresh episode), never a bug
