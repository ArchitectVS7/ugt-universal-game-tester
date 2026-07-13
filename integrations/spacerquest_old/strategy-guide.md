# SpacerQuest — LLM Playtest Strategy Guide (real server)

> Every number below is sourced from the game code (constants.ts, auth.ts dev-setup,
> economy.ts, docking.ts, upgrades.ts, combat.ts, end-turn.ts) — 2026-07-06. If the game
> contradicts this guide, TRUST THE GAME and flag the mismatch with `potential_bug` — if
> any number here is contradicted TWICE, filing that bug is part of your job.

## CRITICAL: The Profitable Loop (do this, in order)

1. **First two actions of a fresh run:** `upgrade_weapons`, then `upgrade_shields`
   (20,000 cr each: 10→20 strength). Every trip forces a combat encounter and the
   starting ship (weapons 10 / shields 10) LOSES most fights — upgrading first turns
   forced encounters into loot instead of losses.
2. **FUEL-RESERVE RULE, check before every launch and every attack (this is what
   prevents the weapons-heavy/no-fuel death spiral):** `attack_cost = floor(weapons
   ÷ 2)`, minimum 1. The game's actual malfunction line is `fuel < attack_cost` —
   below THAT, an attack MALFUNCTIONS (skipped, no fuel burned, enemy still fires
   free). Don't cut it that close: require `fuel ≥ 3 × attack_cost` (a 3-round
   buffer) before `navigate_cargo_dest` and before each `combat_attack`, so a bad
   round or two never drops you onto the malfunction line mid-fight. Below the
   3× buffer, `buy_fuel` before launching; below the 1× line mid-fight,
   `combat_retreat` (always succeeds, free) instead of grinding malfunctions.
3. `accept_cargo` — signs delivery contract #1 from the manifest board (only when
   `destination == 0`; if `destination > 0` you already have one).
4. `navigate_cargo_dest` — launches and arrives. An encounter fires EVERY trip
   (deterministic). If `in_combat == 1` after arriving: `combat_attack` repeatedly
   until `in_combat == 0`, obeying the fuel-reserve rule above. Loot is
   enemy-dependent and often SMALL (baseLoot + your BF÷10 — frequently only ~70
   cr) — combat is a toll you fight through, DELIVERIES are the profit. Also
   `combat_retreat` if `hull_condition <= 3`.
5. Delivery is AUTOMATIC on arrival — credits += payment, score += 2 + trip distance + battles won this trip − battles lost (longer hauls and fight wins pay MORE score).
6. **If you LOST the fight (battles_lost went up) or a launch fails with "Ship too
   badly damaged": `repair_ship` before anything else.** A damaged ship cannot lift
   off — repair is the only way out of that corner.
7. **Trips are an ALLOWANCE, not a quota** (up to 3 per turn; `trip_count` resets
   on `end_turn`). Prefer flying all 3 for score, but if you can't pass the
   fuel-reserve check for another trip, `end_turn` instead of grinding `wait` — it
   is always allowed regardless of `trip_count` (the confirm screen will ask
   "You have N unused trip(s) today. End turn anyway?" — expected, not an error).
   The 3-trip cap on launches is unchanged: a 4th launch attempt is still blocked.
8. `buy_fuel` (buys 100 units) when `fuel < 200` or when it fails the fuel-reserve
   rule above, whichever comes first.

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
| trip_count | 0 (limit 3 per turn) |

## Economy facts (judge balance against these)

- Cargo payment = (value·distance ÷ 3)·pods + fuel×5 + 1,000, **capped at 15,000 cr**
  (rim contracts pay 1.4×, capped 25,000). Expect ~2,000–15,000 per delivery.
- Wrong-destination delivery pays 50% and costs −5 score. Never do it on purpose.
- Fuel prices: Sun-3 = 8 cr/unit, Mira-9 (system 8) = 4, Vega-6 = 6, most others 5.
- Component upgrade = +10 strength, price = (strength÷10 + 1) × 10,000 cr — so
  weapons 10→20 costs 20k, 20→30 costs 30k. `upgrade_cheapest` picks your
  lowest-strength core component (hull/drives/weapons/shields).
- Every +10 weapons adds ~5 fuel/round to the attack cost (see fuel-reserve rule,
  step 2) — bigger guns you can't feed are a net loss, not a power spike.
- Combat power (Battle Factor) comes ONLY from your ship (weapons·cond + shields·cond
  + support components + battles won) — rank gives no combat bonus.

## Action Vocabulary (these are ALL the mapped actions)

| Name | When |
|------|------|
| wait | Never (wasted step) — only if truly nothing else is legal |
| buy_fuel | fuel < 200 (buys 100 units at the local port) |
| accept_cargo | destination == 0 and trip_count < 3 |
| navigate_cargo_dest | destination > 0 (launch + arrive + auto-deliver) |
| deliver_cargo | Only to CONFIRM a delivery happened (it's automatic) — not needed in the loop |
| upgrade_cheapest | credits > 40,000 AND weapons+shields already ≥ 20 AND the fuel-reserve rule (step 2) is currently satisfied — if fuel is below reserve, `buy_fuel` instead, even with credits > 40,000 |
| end_turn | trip_count == 3, or earlier if you can't pass the fuel-reserve check for another trip (allowance, not a quota; resets trips, other spacers take their turns) |
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
- hull_condition ≥ 7; fuel ≥ 200 and fuel-reserve rule (step 2) satisfied before
  each launch/attack

## Danger signs

- fuel < 100 → buy_fuel NOW (stranded = rescue fees)
- fuel-reserve rule fails (fuel < 3 × floor(weapons÷2)) → buy_fuel or
  combat_retreat, don't launch/attack — the death-spiral guard: big weapons with
  no fuel to fire them just feed the enemy free hits
- hull_condition ≤ 3 → retreat from combat; consider upgrade_cheapest (hull)
- credits < 20,000 and weapons still 10 → you upgraded too much or fought too little;
  prioritize cargo runs
- trip_count == 3 and you keep trying to fly → the 4th launch is blocked, you MUST
  end_turn. Ending turn EARLIER than trip_count == 3 is also fine — trips are an
  allowance, not a requirement to fly all 3 before ending

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
