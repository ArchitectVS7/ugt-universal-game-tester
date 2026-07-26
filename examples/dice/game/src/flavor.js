/**
 * Dice Duel — flavor text for the round log.
 *
 * PRESENTATION ONLY. Every line below is derived from fields the engine already
 * computed and wrote into the round record (`state.log[i]` / `state.last_round`,
 * built by `resolveRound`). Nothing here re-derives a rule:
 *
 *   - "reinforcements arrive" is printed because `bonuses.reinforcements > 0`,
 *     never because `record.round === 3`;
 *   - "morale surges" because `bonuses.morale > 0`, never because one FS is
 *     bigger than the other;
 *   - damage numbers are read off `damage_taken`, never recomputed from hits.
 *
 * It is also RNG-free: the posture wording is chosen by `preset_index` (a
 * lookup), so the same record always yields the same prose — no `Math.random()`
 * anywhere, per the standing RNG-discipline constraint.
 *
 * The win/loss/draw banner is deliberately NOT here: that comes from
 * `state.winner` at the App level.
 */

import { ALLOCATIONS } from './engine.js'

/**
 * Which of the three posture bands a preset index falls in.
 *
 * Purely a wording bucket over the ALLOCATIONS table (index 0 = all-attack …
 * last = all-defense), derived from the table's own length so it cannot drift
 * if the table ever changes size.
 *
 * @param {number} presetIndex
 * @returns {'aggressive'|'balanced'|'defensive'}
 */
function posture(presetIndex) {
  const last = ALLOCATIONS.length - 1
  if (presetIndex <= 1) return 'aggressive'
  if (presetIndex >= last - 1) return 'defensive'
  return 'balanced'
}

const PLAYER_POSTURE = {
  aggressive: 'Your soldiers charge forward!',
  balanced: 'Your line advances and holds.',
  defensive: 'Your soldiers brace behind the earthworks.',
}

const ENEMY_POSTURE = {
  aggressive: 'The enemy surges out of the treeline!',
  balanced: 'The enemy presses forward behind a shield line.',
  defensive: 'The enemy falls back into cover.',
}

/** "attack"/"defense" as it should read in prose. */
function targetWord(target) {
  return target === 'defense' ? 'defense' : 'attack'
}

/**
 * The bonus-dice lines one side earned, in a fixed order.
 *
 * Each line appears only when its field is non-zero — so an empty array is the
 * correct, meaningful output for a quiet round.
 *
 * @param {object} side one side of a round record
 * @param {boolean} isPlayer whose voice to write in
 * @returns {string[]}
 */
function bonusLines(side, isPlayer) {
  const { morale, dug_in: dugIn, reinforcements, target } = side.bonuses
  const lines = []
  if (morale > 0) {
    lines.push(
      isPlayer
        ? `Advancing with confidence — your morale surges (+${morale} attack die).`
        : `The enemy advances with confidence — their morale surges (+${morale} attack die).`,
    )
  }
  if (dugIn > 0) {
    lines.push(
      isPlayer
        ? `Your soldiers dig in (+${dugIn} defense die).`
        : `Enemy soldiers dig in (+${dugIn} defense die).`,
    )
  }
  if (reinforcements > 0) {
    lines.push(
      // The PRD names "Enemy reinforcements arrive!" as sample flavor text, so
      // that sentence is kept verbatim and the die count trails it.
      isPlayer
        ? `Your reinforcements arrive! (+${reinforcements} ${targetWord(target)} dice)`
        : `Enemy reinforcements arrive! (+${reinforcements} ${targetWord(target)} dice)`,
    )
  }
  return lines
}

/**
 * The exchange line describing what one side's volley did to the other.
 *
 * @param {object} attacker the side that threw the attack dice
 * @param {object} defender the side that took the damage
 * @param {boolean} isPlayer true when the player is the attacker
 * @returns {string}
 */
function exchangeLine(attacker, defender, isPlayer) {
  const opening = isPlayer
    ? `Your volley: ${attacker.attack_hits} hit(s) against ${defender.defense_hits} blocked`
    : `Enemy fire: ${attacker.attack_hits} hit(s) against ${defender.defense_hits} blocked`
  if (defender.damage_taken === 0) {
    return isPlayer
      ? `${opening} — the enemy line gives no ground.`
      : `${opening} — your line holds; no ground given.`
  }
  return isPlayer
    ? `${opening} — the enemy loses ${defender.damage_taken} strength (now ${defender.force_strength_after}).`
    : `${opening} — you lose ${defender.damage_taken} strength (now ${defender.force_strength_after}).`
}

/**
 * Turn one round record into ordered prose for the log.
 *
 * Deterministic and pure: same record in, same array of strings out.
 *
 * @param {object} record an entry of `state.log` (or `state.last_round`)
 * @returns {string[]}
 */
export function flavorLines(record) {
  const { player, enemy } = record
  return [
    PLAYER_POSTURE[posture(player.preset_index)],
    ENEMY_POSTURE[posture(enemy.preset_index)],
    ...bonusLines(player, true),
    ...bonusLines(enemy, false),
    exchangeLine(player, enemy, true),
    exchangeLine(enemy, player, false),
  ]
}
