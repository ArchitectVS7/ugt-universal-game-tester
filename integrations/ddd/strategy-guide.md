# DDD — playtest strategy guide (legal-action drive mode)

DDD is a two-player deterministic dueling card game. You drive whichever seat the
engine is currently waiting on (`pendingSeat`) — you play BOTH seats over the course
of a match, one decision at a time. Play the seat you are acting for to WIN: each
decision should be the best move for THAT seat, using only the information shown.

## How to answer
- Respond with `action_type="legal_action"` and `value` set to the NUMBER (index)
  of the action you want from the LEGAL ACTIONS list. Nothing else is a valid move.
- Never invent an action that is not in the list — only the numbered options are legal.

## THE CORE RULE: the type triangle (read this first)
Every card has a TYPE. Three types counter each other, rock-paper-scissors:

- **ATTACK beats SPELL** · **SPELL beats DEFENSE** · **DEFENSE beats ATTACK**
- A card that counters the opposing card gets **+5 Power**. Damage dealt is the
  POWER DIFFERENCE between the two revealed cards, so +5 usually decides the clash
  outright. The countered card is not penalised; only the winner gains.
- EFFECT and HYBRID are neutral (never counter, never countered). A mirror (same
  type both sides) grants nothing.

**Predicting the opponent's type and playing its counter is the single strongest
move in the game.** A correct DEFENSE into their ATTACK is worth more than almost
any card upgrade.

## Stance (public, both players — your read signal #1)
Each player's `stance` follows the TYPE of their last played card: an ATTACK puts
you in AGGRESSIVE, a DEFENSE in DEFENSIVE, anything else (Spell/Effect/Hybrid/Pass)
in BALANCED.

| Stance | Combat modifier (on that player's own cards) | Focus regen/turn |
|---|---|---|
| AGGRESSIVE | their Attacks +1 Power, their Defenses −1 | +0 |
| DEFENSIVE | their Defenses +1 Shield, their Attacks −1 | +2 (richest) |
| BALANCED | none | +1 |

How to use it:
- **Reading:** an AGGRESSIVE opponent keeps +1 by attacking again — they are
  rewarded for repeating, so expect ATTACK more often than chance and consider
  answering with DEFENSE (+5 counter AND shields). Same logic for other stances.
- **Self-management:** repeating your own type keeps your +1; crossing types eats
  −1 once. DEFENSIVE is the only stance that pays extra Focus — a turn of Defense
  both shields you and funds your next expensive card.
- **The tension:** committing makes you stronger AND telegraphs you. Sometimes
  break your own pattern precisely because you are telegraphed.

## Echo (public — your read signal #2)
`echo` on each seat shows that player's last played card as `{cardType, focusCost}`
(null before their first play). It is truthful. Combined with stance and the deck
lists below, it is your basis for predicting their next type.

## Chains (public — your read signal #3)
`chain.history` is that player's rolling last-3 played types; completing a chain
pays next turn: 3 consecutive ATTACK → next Attack +3 Power ("Momentum Rush");
2 consecutive DEFENSE → Shield 4; 2 SPELL within the last 4 → draw 2. A player
one step from a chain will usually chase it — that is a strong prediction, and
chasing your own chains is real value if the telegraph won't be punished.

## Other state fields
- Per seat: `hp` (0–30, take the OPPONENT to 0 to win), `focus` (pays card costs,
  +1/turn base plus stance regen, cap 5, carries over), `handCount` (cap 7),
  `deckCount`, `graveyardCount`, `shieldPool` (absorbs damage first, expires each
  turn), `statuses` (active effects like Burn ticking on that player), `modifiers`
  (persistent effects, e.g. future-cost discounts).
- `hasCommitted: true` on the other seat means it locked in this round's choice —
  WHAT it committed (card or pass) is hidden, by design. Use stance/echo/chain to
  infer it.
- `phase` is `MULLIGAN` first, then repeated `SELECTION` steps.

## What the legal actions mean
- `MULLIGAN` — its `_hand` field lists your opening hand's card ids. `full:false`
  keeps the hand (usually correct); `full:true` redraws everything (only if the
  hand is unplayable, e.g. all high-cost).
- `COMMIT_SELECTION` — play a card this round. Its `_card` field names the card;
  look it up in the reference below before choosing. Any `targets` shown are
  already filled with engine-approved ids — pick by card, not by target.
- Variants of the same card with a `prediction` value (ATTACK/DEFENSE/...) are the
  Rare-prediction option: you secretly predict the TYPE of the opponent's NEXT
  card. Right ≈ bonus Focus, wrong ≈ small Focus penalty. **Your reads come from
  their stance, echo, chain history and deck list** — when those line up (e.g.
  AGGRESSIVE stance + ATTACK echo + attack-heavy deck), a prediction variant is
  worth taking; otherwise take the plain (null) variant.
- `COMMIT_PASS` — commit nothing (only when you cannot afford any card worth playing).
- `CONCEDE` — forfeit. Only legitimate at a provably lost position (e.g. facing
  certain lethal with no answer); otherwise play matches out.

## Keyword meanings in the card reference
- "scales" / "counters up" = the card gets stronger per SAME-ARCHETYPE card in
  YOUR OWN graveyard (e.g. +1 power each, capped ~6). Swarm's engine: fill your
  graveyard (discard/cheap plays), then swing with scalers. NOTE: returning cards
  from graveyard to hand REMOVES them from that count — recursion and scaling
  spend the same resource; sequence deliberately.
- "return N from graveyard" to HAND is capped by the 7-card hand limit — at a full
  hand only the freed slot refills (~1 card). Play returns when your hand is small.
- "burn N" = damage over the following turns; shields don't stop it once applied.

## Card reference — bb_competitive (Blitzblade: fast aggression)
- bb_quick_slash ×3 — ATTACK, cost 0, power 3.
- bb_swift_strike ×3 — ATTACK, cost 1, power 5. +2 if opposing card is DEFENSE.
- bb_blade_flurry ×3 — ATTACK, cost 1, power 4, scales.
- bb_combat_reflexes ×3 — DEFENSE, cost 1, power 3. Shield 3; +1 vs ATTACK.
- bb_lightning_riposte ×2 — DEFENSE, cost 1, power 3. Shield 2; burn 3 if all damage blocked.
- bb_weapon_training ×3 — SPELL, cost 1, power 2. Draw 1; +2 to future cards.
- bb_battle_instinct ×3 — EFFECT, cost 0, power 3. Draw 1 if opponent's hand is larger.
- bb_warriors_charge ×3 — ATTACK, cost 2, power 6. +2 when your HP is low.
- bb_reckless_swing ×3 — ATTACK, cost 2, power 7.
- bb_tactical_strike ×2 — ATTACK, cost 2, power 4. Draw 1; scales.
- bb_blade_dancer ×2 — ATTACK, cost 2, power 5, scales.
- bb_burning_blade ×2 — SPELL, cost 2, power 4. Burn 2 to opponent.
- bb_battle_fury ×2 — HYBRID, cost 3, power 7.
- bb_perfect_strike ×1 — ATTACK, cost 3, power 7. Drain 3 from opposing card.
- bb_adrenaline_rush ×1 — EFFECT, cost 3, power 5. Draw 2; future cards cost 1 less.
- bb_warriors_resolve ×1 — DEFENSE, cost 3, power 4. Shield 5; heal 5 when HP low.
- bb_berserkers_rage ×2 — ATTACK, cost 4, power 6. +2 when HP low; burn 2.
- bb_arcblade_surge ×1 — SPELL, cost 4, power 8. +3 when HP low; burn 3.

## Card reference — sw_competitive (Swarm: economy + attrition)
- sw_hatchling ×3 — ATTACK, cost 0, power 2, scales.
- sw_drone_worker ×3 — ATTACK, cost 0, power 2. +2 with counters up.
- sw_tunnel_crawler ×3 — ATTACK, cost 1, power 5. +1 with counters up.
- sw_chitin_shell ×3 — DEFENSE, cost 1, power 3. Shield 4.
- sw_swarm_scout ×3 — EFFECT, cost 1, power 3. Draw 1; +1.
- sw_hive_tender ×3 — EFFECT, cost 1, power 3. Heal 2 (+2 more with counters up).
- sw_spawning_pool ×3 — SPELL, cost 1, power 3. Discard 1, draw 2.
- sw_colony_growth ×2 — EFFECT, cost 1, power 3. Draw 2.
- sw_brood_mother ×2 — HYBRID, cost 3, power 5.
- sw_feeding_frenzy ×2 — ATTACK, cost 3, power 5, scales.
- sw_collective_mind ×2 — SPELL, cost 3, power 3. Future cards cost 1 less.
- sw_adaptation_chamber ×2 — DEFENSE, cost 3, power 4. Shield 4; return 2 from graveyard.
- sw_deep_emergence ×1 — DEFENSE, cost 3, power 4. Shield 5; return 2 from graveyard.
- sw_endless_tide ×1 — SPELL, cost 3, power 5. Return 3 from graveyard; future discount.
- sw_nest_builder ×3 — EFFECT, cost 4, power 3. Return 1 from graveyard.
- sw_overwhelming_numbers ×2 — ATTACK, cost 4, power 6, scales.
- sw_hive_overmind ×1 — EFFECT, cost 4, power 6, scales; draw.
- sw_abyssal_maw ×1 — ATTACK, cost 4, power 7, scales; opponent discards 2.

## Basic strategy
- Spend focus efficiently: playing a cheap card usually beats passing; don't bank
  focus you cannot use.
- **Always ask first: what TYPE will they reveal?** Use their stance, echo, chain
  history and deck identity; if you have a confident read, play the counter type —
  it is worth +5. Blitzblade telegraphs ATTACK heavily; DEFENSE farms it.
- Blitzblade wants to close fast: high power-per-cost ATTACKs, constant HP
  pressure — but vary your type when the opponent starts countering you.
- Swarm wants card economy first (draw, graveyard growth), then scaled swings;
  use DEFENSE liberally against an AGGRESSIVE opponent (counter +5, shields, and
  +2 regen); time recursion for when your hand is small and your scalers are done
  feeding on the graveyard.
- Mulligan only a hand you truly cannot afford to play in the first turns.

## Goal
Play every match to a real result — reduce the opposing seat's `hp` to 0. Watch for
anything that looks wrong (HP/focus out of range, a card vanishing, an action that
changes nothing, an effect that contradicts its card text above) and flag it via
`potential_bug`.
