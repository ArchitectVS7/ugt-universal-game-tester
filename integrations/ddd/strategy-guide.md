# DDD — playtest strategy guide (legal-action drive mode)

DDD is a two-player deterministic dueling card game. You drive whichever seat the
engine is currently waiting on (`pendingSeat`) — you play BOTH seats over the course
of a match, one decision at a time. Play the seat you are acting for to WIN: each
decision should be the best move for THAT seat, using only the information shown.

## How to answer
- Respond with `action_type="legal_action"` and `value` set to the NUMBER (index)
  of the action you want from the LEGAL ACTIONS list. Nothing else is a valid move.
- Never invent an action that is not in the list — only the numbered options are legal.

## Reading the state
- `p0` and `p1` are the two seats. `pendingSeat` is the seat you are acting for now.
- Per seat: `hp` (0–30, you win by taking the OPPONENT to 0), `focus` (the resource
  that pays card costs, regenerates each turn), `handCount`, `deckCount`,
  `graveyardCount`, `stance`, `shieldPool` (absorbs damage first).
- `hasCommitted: true` on the other seat means it has already locked in this round's
  choice — but WHAT it committed (card or pass) is hidden from you, by design.
- `phase` is `MULLIGAN` first (decide your opening hand), then repeated `SELECTION`
  steps (commit a card or pass); `resultKind` stays `ONGOING` until the match ends.

## What the legal actions mean
- `MULLIGAN` — its `_hand` field lists your opening hand's card ids (see the card
  reference below). `full:false` keeps the hand (usually correct); `full:true`
  redraws everything (only if the hand is unplayable, e.g. all high-cost).
- `COMMIT_SELECTION` — play a card this round. Its `_card` field names the card;
  look it up in the reference below before choosing. Any `targets` shown are
  already filled with engine-approved ids — pick by card, not by target.
- Variants of the same card with a `prediction` value (ATTACK/DEFENSE/...) are the
  Rare-prediction option: you secretly predict the TYPE of the opponent's NEXT
  card. Right ≈ bonus Focus, wrong ≈ small Focus penalty. Only use a prediction
  variant when you have a real read; otherwise take the plain (null) variant.
- `COMMIT_PASS` — commit nothing (only when you cannot afford any card worth playing).
- `CONCEDE` — forfeit. Do NOT pick this; you are here to play matches out.

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
  focus you cannot use. Cards with "scales" grow with repeated same-type play.
- Blitzblade wants to close fast: prefer high power-per-cost ATTACKs, keep the
  pressure on HP. Swarm wants card economy first (draw/return), then swings.
- Mulligan only a hand you truly cannot afford to play in the first turns.

## Goal
Play every match to a real result — reduce the opposing seat's `hp` to 0. Watch for
anything that looks wrong (HP/focus out of range, a card vanishing, an action that
changes nothing, an effect that contradicts its card text above) and flag it via
`potential_bug`.
