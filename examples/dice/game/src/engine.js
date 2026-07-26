/**
 * Dice Duel — game engine (rules live here, never in the React tree).
 *
 * T-002 scope: the seeded RNG layer only. Dice are a pure function of
 * `(seed, rollCounter)` — there is no module-level mutable state, so calling
 * these helpers in any order, any number of times, always yields the same
 * answer for the same arguments. `rollCounter` is owned by the caller (it
 * lives in game state, per PRD "RNG discipline") and advances once per die.
 *
 * Mirrors `examples/harness-game/engine.py`'s `rng_counter` pattern; JS has no
 * synchronous stdlib hash, so the digest below is implemented inline rather
 * than pulling in a dependency.
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
