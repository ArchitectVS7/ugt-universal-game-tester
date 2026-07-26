/**
 * Dice Duel — game engine (rules live here, never in the React tree).
 *
 * Layer 1 (T-002): the seeded RNG. Dice are a pure function of
 * `(seed, rollCounter)` — there is no module-level mutable state, so calling
 * these helpers in any order, any number of times, always yields the same
 * answer for the same arguments. `rollCounter` is owned by the caller (it
 * lives in game state, per PRD "RNG discipline") and advances once per die.
 *
 * Mirrors `examples/harness-game/engine.py`'s `rng_counter` pattern; JS has no
 * synchronous stdlib hash, so the digest below is implemented inline rather
 * than pulling in a dependency.
 *
 * Layer 2 (T-003): allocation presets, bonus-dice rules, and round resolution
 * — see the banner comment further down.
 */

/** Faces on a die. */
export const DIE_FACES = 6

/** A die showing this face or higher is a hit (PRD: "shows 5 or 6"). */
export const HIT_THRESHOLD = 5

/**
 * Hash `${seed}:${rollCounter}` down to a uint32.
 *
 * FNV-1a supplies the string mixing; the splitmix32-style finalizer that
 * follows supplies the avalanche. The finalizer is NOT optional: raw FNV-1a
 * over keys differing only in a trailing digit has poor low-bit diffusion, and
 * `% 6` reads exactly those low bits — without it, adjacent roll counters
 * produce visibly correlated faces.
 *
 * @param {string} seed already normalized via `String(seed)`
 * @param {number} rollCounter
 * @returns {number} uint32
 */
function hashKey(seed, rollCounter) {
  const key = `${seed}:${rollCounter}`
  let h = 2166136261
  for (let i = 0; i < key.length; i += 1) {
    h ^= key.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  // splitmix32 finalizer
  h ^= h >>> 16
  h = Math.imul(h, 0x21f0aaad)
  h ^= h >>> 15
  h = Math.imul(h, 0x735a2d97)
  h ^= h >>> 15
  return h >>> 0
}

/**
 * Roll one d6.
 *
 * Pure function of `(seed, rollCounter)` — never consults `Math.random()` and
 * keeps no hidden stream state, so the same pair always returns the same face.
 * The seed is normalized with `String()`, so `__RESET__(5)` and
 * `__RESET__("5")` play the identical battle.
 *
 * @param {string|number} seed
 * @param {number} rollCounter
 * @returns {number} a face in [1, 6]
 */
export function rollDie(seed, rollCounter) {
  if (!Number.isInteger(rollCounter)) {
    throw new TypeError(`rollDie: rollCounter must be an integer, got ${String(rollCounter)}`)
  }
  return (hashKey(String(seed), rollCounter) % DIE_FACES) + 1
}

/**
 * Is this die face a hit?
 *
 * Exported so the UI and later rules never re-derive the 5-6 threshold
 * outside this module.
 *
 * @param {number} face
 * @returns {boolean}
 */
export function isHit(face) {
  return face >= HIT_THRESHOLD
}

/**
 * Roll a pool of `n` d6 and count 5-6 hits.
 *
 * Consumes exactly one counter tick per die, in order: die `i` is rolled at
 * `rollCounter + i`. Returns the advanced counter for the caller to store back
 * into game state; nothing passed in is mutated.
 *
 * `n === 0` is valid and legal — the `(6,0)` preset rolls an empty defense
 * pool — and returns the counter unchanged.
 *
 * @param {number} n number of dice, a non-negative integer
 * @param {string|number} seed
 * @param {number} rollCounter
 * @returns {{rolls: number[], hits: number, rollCounter: number}}
 */
export function rollPool(n, seed, rollCounter) {
  if (!Number.isInteger(n) || n < 0) {
    throw new TypeError(`rollPool: n must be a non-negative integer, got ${String(n)}`)
  }
  if (!Number.isInteger(rollCounter)) {
    throw new TypeError(`rollPool: rollCounter must be an integer, got ${String(rollCounter)}`)
  }
  const key = String(seed)
  const rolls = []
  let hits = 0
  for (let i = 0; i < n; i += 1) {
    const face = rollDie(key, rollCounter + i)
    rolls.push(face)
    if (isHit(face)) hits += 1
  }
  return { rolls, hits, rollCounter: rollCounter + n }
}

/* ------------------------------------------------------------------------- *
 * T-003 — allocation presets, bonus-dice rules, and round resolution.
 *
 * Everything below is still pure: `resolveRound` takes a state and returns a
 * brand-new one. Battle end conditions (`battle_over` / `winner`) and the AI
 * opponent are deliberately NOT here — they belong to T-004 and T-005.
 * ------------------------------------------------------------------------- */

/**
 * The 7 fixed allocations, indexed by the `__SEND_ACTION__` action id.
 *
 * Index 0 is all-attack `(6,0)`, index 6 all-defense `(0,6)` — this ordering is
 * part of the UGT hooks contract in PRD.md and must not be reshuffled.
 */
export const ALLOCATIONS = Object.freeze([
  Object.freeze({ attack: 6, defense: 0 }),
  Object.freeze({ attack: 5, defense: 1 }),
  Object.freeze({ attack: 4, defense: 2 }),
  Object.freeze({ attack: 3, defense: 3 }),
  Object.freeze({ attack: 2, defense: 4 }),
  Object.freeze({ attack: 1, defense: 5 }),
  Object.freeze({ attack: 0, defense: 6 }),
])

/** Dice each side allocates per round, before bonuses. */
export const POOL_SIZE = 6

/** Both sides open the battle at this Force Strength. */
export const STARTING_FS = 20

/** FS at or below this ("half") grants the Dug in defense die. */
export const DUG_IN_THRESHOLD = 10

/** Reinforcements are worth this many dice, all to one pool. */
export const REINFORCEMENT_DICE = 2

/**
 * Reinforcements arrive at the start of this round, 1-indexed.
 *
 * D1 — round numbering: `round_number` in state counts *completed* rounds and
 * starts at 0 (the PRD's `__GET_STATE__` sample shows 0 before any round).
 * The round being resolved right now is therefore `state.round_number + 1`.
 */
export const REINFORCEMENT_ROUND = 3

/**
 * The battle ends in a draw after this many rounds. Unused by T-003 — declared
 * here so T-004 does not invent a second numbering convention.
 */
export const MAX_ROUNDS = 12

/** A fresh side record. */
function newSide() {
  return {
    force_strength: STARTING_FS,
    // D5: bonus dice granted in the most recently resolved round.
    bonus_dice: 0,
    reinforcements_used: false,
  }
}

/**
 * A brand-new battle state.
 *
 * The five contract fields (`player`, `enemy`, `round_number`, `battle_over`,
 * `winner`) and the two per-side contract fields (`force_strength`,
 * `bonus_dice`) match PRD.md exactly. The extra fields (`seed`,
 * `roll_counter`, `last_round`, `log`, `reinforcements_used`) are engine
 * bookkeeping — D6: `__GET_STATE__` is a *projection* of this state, built in
 * T-007; nothing here may rename or retype a contract field.
 *
 * @param {string|number} seed
 * @returns {object} state
 */
export function createInitialState(seed) {
  return {
    seed: String(seed),
    roll_counter: 0,
    round_number: 0,
    // T-004 owns end conditions; T-003 carries these through untouched.
    battle_over: false,
    winner: null,
    player: newSide(),
    enemy: newSide(),
    last_round: null,
    log: [],
  }
}

/**
 * The bonus dice one side earns this round.
 *
 * Symmetric on purpose: player and enemy call the identical helper, so the two
 * sides cannot drift apart. D2 — every input is read from the state as it
 * stands at round *start*, before any damage this round.
 *
 * @param {number} ownFS this side's FS at round start
 * @param {number} oppFS the opponent's FS at round start
 * @param {number} roundNumber completed rounds so far (see D1)
 * @param {{attack: number, defense: number}} preset this side's allocation
 * @param {boolean} reinforcementsUsed whether this side already spent them
 * @returns {{morale: number, dug_in: number, reinforcements: number, target: string}}
 */
export function sideBonuses(ownFS, oppFS, roundNumber, preset, reinforcementsUsed) {
  // Morale surge: *strictly* greater. A tie grants nothing to either side.
  const morale = ownFS > oppFS ? 1 : 0
  // Dug in: at or below half strength.
  const dugIn = ownFS <= DUG_IN_THRESHOLD ? 1 : 0
  // Reinforcements: exactly once, at the start of round 3, per side.
  // Guarding on BOTH the spent flag and the round number is deliberate — the
  // flag is what makes "exactly once" structurally assertable.
  const reinforcements =
    !reinforcementsUsed && roundNumber + 1 === REINFORCEMENT_ROUND ? REINFORCEMENT_DICE : 0
  // D4 — routing reads the side's BASE preset, not the bonus-adjusted pool, so
  // a morale/dug-in die can never flip where reinforcements land. `>=` is what
  // sends the (3,3) tie to Attack, per PRD.
  const target = preset.attack >= preset.defense ? 'attack' : 'defense'
  return { morale, dug_in: dugIn, reinforcements, target }
}

/** Validate an action id / preset index, throwing rather than coercing. */
function presetAt(index, label) {
  if (!Number.isInteger(index) || index < 0 || index >= ALLOCATIONS.length) {
    throw new RangeError(
      `resolveRound: ${label} must be an integer in [0, ${ALLOCATIONS.length - 1}], got ${String(index)}`,
    )
  }
  return ALLOCATIONS[index]
}

/** Pool sizes for one side, given its preset and this round's bonuses. */
function poolSizes(preset, bonuses) {
  return {
    attack_dice: preset.attack + bonuses.morale + (bonuses.target === 'attack' ? bonuses.reinforcements : 0),
    defense_dice:
      preset.defense + bonuses.dug_in + (bonuses.target === 'defense' ? bonuses.reinforcements : 0),
  }
}

/**
 * Resolve one full round: both sides act simultaneously, dice roll, damage
 * applies, FS updates, the round counter increments.
 *
 * D8 — the enemy's allocation is an explicit parameter. T-005 adds the
 * deterministic `chooseEnemyPreset(state)` heuristic and the single-argument
 * `applyAction(state, actionId)` wrapper on top of this signature; there is no
 * placeholder AI here on purpose.
 *
 * D7 — the input state is never mutated; a brand-new state (with new nested
 * objects) comes back, because same-seed replay comparisons depend on it.
 *
 * @param {object} state
 * @param {number} playerPresetIndex 0-6
 * @param {number} enemyPresetIndex 0-6
 * @returns {object} the new state
 */
export function resolveRound(state, playerPresetIndex, enemyPresetIndex) {
  const playerPreset = presetAt(playerPresetIndex, 'playerPresetIndex')
  const enemyPreset = presetAt(enemyPresetIndex, 'enemyPresetIndex')

  const { seed, round_number: roundNumber } = state
  const playerFS = state.player.force_strength
  const enemyFS = state.enemy.force_strength

  // D2: both sides' bonuses come from the pre-resolution snapshot.
  const playerBonuses = sideBonuses(
    playerFS,
    enemyFS,
    roundNumber,
    playerPreset,
    state.player.reinforcements_used,
  )
  const enemyBonuses = sideBonuses(
    enemyFS,
    playerFS,
    roundNumber,
    enemyPreset,
    state.enemy.reinforcements_used,
  )

  const playerPools = poolSizes(playerPreset, playerBonuses)
  const enemyPools = poolSizes(enemyPreset, enemyBonuses)

  // D3 — FIXED ROLL ORDER, part of the determinism contract: player attack,
  // player defense, enemy attack, enemy defense. `roll_counter` advances once
  // per die across all four pools; reordering these calls changes every
  // battle, so it must not be "tidied".
  let counter = state.roll_counter
  const playerAttack = rollPool(playerPools.attack_dice, seed, counter)
  counter = playerAttack.rollCounter
  const playerDefense = rollPool(playerPools.defense_dice, seed, counter)
  counter = playerDefense.rollCounter
  const enemyAttack = rollPool(enemyPools.attack_dice, seed, counter)
  counter = enemyAttack.rollCounter
  const enemyDefense = rollPool(enemyPools.defense_dice, seed, counter)
  counter = enemyDefense.rollCounter

  // Net damage = opponent's attack hits − own defense hits, floored at 0.
  const damageToPlayer = Math.max(0, enemyAttack.hits - playerDefense.hits)
  const damageToEnemy = Math.max(0, playerAttack.hits - enemyDefense.hits)

  // FS floors at exactly 0, never below (PRD Mechanics).
  const playerFSAfter = Math.max(0, playerFS - damageToPlayer)
  const enemyFSAfter = Math.max(0, enemyFS - damageToEnemy)

  const sideAfter = (side, bonuses, fsAfter) => ({
    force_strength: fsAfter,
    // D5: this round's total bonus dice, the field `__GET_STATE__` exposes.
    bonus_dice: bonuses.morale + bonuses.dug_in + bonuses.reinforcements,
    reinforcements_used: side.reinforcements_used || bonuses.reinforcements > 0,
  })

  // Structured data only — no flavor strings. T-006 renders prose from this.
  const record = {
    round: roundNumber + 1,
    player: {
      preset_index: playerPresetIndex,
      preset: { ...playerPreset },
      bonuses: { ...playerBonuses },
      attack_dice: playerPools.attack_dice,
      defense_dice: playerPools.defense_dice,
      attack_rolls: playerAttack.rolls,
      defense_rolls: playerDefense.rolls,
      attack_hits: playerAttack.hits,
      defense_hits: playerDefense.hits,
      damage_taken: damageToPlayer,
      force_strength_after: playerFSAfter,
    },
    enemy: {
      preset_index: enemyPresetIndex,
      preset: { ...enemyPreset },
      bonuses: { ...enemyBonuses },
      attack_dice: enemyPools.attack_dice,
      defense_dice: enemyPools.defense_dice,
      attack_rolls: enemyAttack.rolls,
      defense_rolls: enemyDefense.rolls,
      attack_hits: enemyAttack.hits,
      defense_hits: enemyDefense.hits,
      damage_taken: damageToEnemy,
      force_strength_after: enemyFSAfter,
    },
  }

  return {
    ...state,
    roll_counter: counter,
    round_number: roundNumber + 1,
    // T-004 owns end conditions — carried through unchanged, and entry is
    // deliberately NOT guarded on `battle_over` here (that guard is T-004's).
    battle_over: state.battle_over,
    winner: state.winner,
    player: sideAfter(state.player, playerBonuses, playerFSAfter),
    enemy: sideAfter(state.enemy, enemyBonuses, enemyFSAfter),
    last_round: record,
    log: [...state.log, record],
  }
}
