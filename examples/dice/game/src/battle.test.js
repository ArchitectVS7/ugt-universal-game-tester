import { describe, it, expect } from 'vitest'
import {
  MAX_ROUNDS,
  STARTING_FS,
  createInitialState,
  evaluateOutcome,
  resolveRound,
} from './engine.js'

/** Preset index shorthands, so the tests read like the PRD. */
const ALL_ATTACK = 0 // (6,0)
const EVEN = 3 // (3,3)
const ALL_DEFENSE = 6 // (0,6)

/** Every value `winner` is allowed to take once the battle is over. */
const DECIDED = ['player', 'enemy', 'draw']

/**
 * An initial state with FS forced, so an end condition can be pinned to one
 * exact situation without playing rounds up to it.
 */
function withFS(seed, playerFS, enemyFS, overrides = {}) {
  const base = createInitialState(seed)
  const { player = {}, enemy = {}, ...rest } = overrides
  return {
    ...base,
    ...rest,
    player: { ...base.player, force_strength: playerFS, ...player },
    enemy: { ...base.enemy, force_strength: enemyFS, ...enemy },
  }
}

/**
 * Play until the battle reports itself over, or until a safety cap well past
 * the round cap. The extra rounds are deliberate: they also exercise the
 * post-battle no-op guard (D10).
 */
function playUntilOver(state, playerPreset, enemyPreset, cap = MAX_ROUNDS + 3) {
  let s = state
  const states = []
  for (let i = 0; i < cap; i += 1) {
    s = resolveRound(s, playerPreset, enemyPreset)
    states.push(s)
  }
  return { final: s, states }
}

describe('evaluateOutcome — the end-condition rule, in isolation', () => {
  it('is decisive when exactly one side is at or below 0', () => {
    expect(evaluateOutcome(20, 0, 5)).toEqual({ battle_over: true, winner: 'player' })
    expect(evaluateOutcome(0, 20, 5)).toEqual({ battle_over: true, winner: 'enemy' })
  })

  it('D9 — a same-round double knockout is a draw', () => {
    expect(evaluateOutcome(0, 0, 5)).toEqual({ battle_over: true, winner: 'draw' })
  })

  it('reads FS ≤ 0, not FS === 0, so a negative FS still ends the battle', () => {
    expect(evaluateOutcome(-3, 20, 5)).toEqual({ battle_over: true, winner: 'enemy' })
    expect(evaluateOutcome(20, -1, 5)).toEqual({ battle_over: true, winner: 'player' })
    expect(evaluateOutcome(-1, -8, 5)).toEqual({ battle_over: true, winner: 'draw' })
  })

  it('runs on with no winner while both sides are alive and under the cap', () => {
    for (const [p, e] of [
      [20, 20],
      [1, 1],
      [20, 1],
      [1, 20],
    ]) {
      expect(evaluateOutcome(p, e, 0)).toEqual({ battle_over: false, winner: null })
      expect(evaluateOutcome(p, e, MAX_ROUNDS - 1)).toEqual({ battle_over: false, winner: null })
    }
  })

  it(`draws at exactly ${MAX_ROUNDS} completed rounds, never before, never after`, () => {
    for (let r = 0; r <= MAX_ROUNDS + 1; r += 1) {
      const over = r >= MAX_ROUNDS
      expect(evaluateOutcome(20, 20, r)).toEqual({
        battle_over: over,
        winner: over ? 'draw' : null,
      })
    }
  })

  it('is decisive even on the final round — a knockout beats the round cap', () => {
    expect(evaluateOutcome(20, 0, MAX_ROUNDS)).toEqual({ battle_over: true, winner: 'player' })
    expect(evaluateOutcome(0, 20, MAX_ROUNDS)).toEqual({ battle_over: true, winner: 'enemy' })
    expect(evaluateOutcome(20, 0, MAX_ROUNDS + 5)).toEqual({ battle_over: true, winner: 'player' })
  })

  it('agrees with the literals a fresh battle opens on', () => {
    const fresh = createInitialState('agree')
    const rule = evaluateOutcome(STARTING_FS, STARTING_FS, 0)
    expect({ battle_over: fresh.battle_over, winner: fresh.winner }).toEqual(rule)
  })
})

describe('Accept 1 — decisive win (enemy FS reaches 0)', () => {
  const seed = 'vanguard'
  const { final, states } = playUntilOver(createInitialState(seed), ALL_ATTACK, ALL_ATTACK)

  it('ends the battle with winner "player"', () => {
    expect(final.battle_over).toBe(true)
    expect(final.winner).toBe('player')
  })

  it('leaves the enemy at exactly 0 and the player standing', () => {
    expect(final.enemy.force_strength).toBe(0)
    expect(final.player.force_strength).toBeGreaterThan(0)
  })

  it('is decisive, not a round-cap draw', () => {
    expect(final.round_number).toBeLessThan(MAX_ROUNDS)
  })

  // Golden values RECOMPUTED for the 2026-07-26 retune (STARTING_FS 20 -> 12).
  // A golden test is supposed to break when balance changes — that is what makes
  // it a golden test — so these are restated, not loosened.
  it('golden: seed "vanguard", all-attack mirror → player wins round 6 at FS 3', () => {
    expect(final.round_number).toBe(6)
    expect(final.player.force_strength).toBe(3)
    expect(final.log).toHaveLength(6)
    // The knockout is recorded in the round that dealt it.
    expect(final.last_round.enemy.force_strength_after).toBe(0)
  })

  it('flips exactly once and stays flipped for the rest of the call sequence', () => {
    const flips = states.filter((s, i) => s.battle_over && !(states[i - 1]?.battle_over ?? false))
    expect(flips).toHaveLength(1)
    expect(states.at(-1).battle_over).toBe(true)
  })
})

describe('Accept 2 — decisive loss (player FS reaches 0)', () => {
  const seed = 'bastion'
  const { final } = playUntilOver(createInitialState(seed), ALL_ATTACK, ALL_ATTACK)

  it('ends the battle with winner "enemy"', () => {
    expect(final.battle_over).toBe(true)
    expect(final.winner).toBe('enemy')
  })

  it('leaves the player at exactly 0 and the enemy standing', () => {
    expect(final.player.force_strength).toBe(0)
    expect(final.enemy.force_strength).toBeGreaterThan(0)
  })

  it('is decisive, not a round-cap draw', () => {
    expect(final.round_number).toBeLessThan(MAX_ROUNDS)
  })

  it('golden: seed "bastion", all-attack mirror → enemy wins round 4 at FS 6', () => {
    expect(final.round_number).toBe(4)
    expect(final.enemy.force_strength).toBe(6)
    expect(final.log).toHaveLength(4)
    expect(final.last_round.player.force_strength_after).toBe(0)
  })

  it('also fires from a forced near-death state, in one round', () => {
    const s = resolveRound(withFS('rout', 1, STARTING_FS), ALL_ATTACK, ALL_ATTACK)
    expect(s.player.force_strength).toBe(0)
    expect(s.winner).toBe('enemy')
    expect(s.battle_over).toBe(true)
    expect(s.round_number).toBe(1)
  })
})

describe('Accept 3 — draw by round cap', () => {
  // All-defense vs all-defense allocates 0 attack dice on both sides, and no
  // bonus can create one: morale needs a strict FS lead (impossible when
  // nothing takes damage), dug-in and the round-3 reinforcements both route to
  // Defense. So this battle CANNOT end decisively on any seed — the draw here
  // is a property of the rules, not of a lucky seed.
  const seed = 'entrenched'
  const { final, states } = playUntilOver(createInitialState(seed), ALL_DEFENSE, ALL_DEFENSE)

  it(`reaches round ${MAX_ROUNDS} and stops there with winner "draw"`, () => {
    expect(final.round_number).toBe(MAX_ROUNDS)
    expect(final.battle_over).toBe(true)
    expect(final.winner).toBe('draw')
  })

  it('leaves both sides alive and untouched at full strength', () => {
    expect(final.player.force_strength).toBe(STARTING_FS)
    expect(final.enemy.force_strength).toBe(STARTING_FS)
  })

  it(`logs exactly ${MAX_ROUNDS} rounds — the cap is never overrun`, () => {
    expect(final.log).toHaveLength(MAX_ROUNDS)
    expect(final.log.at(-1).round).toBe(MAX_ROUNDS)
  })

  it(`is still live at round ${MAX_ROUNDS - 1} — it draws AT the cap, not before`, () => {
    const penultimate = states[MAX_ROUNDS - 2]
    expect(penultimate.round_number).toBe(MAX_ROUNDS - 1)
    expect(penultimate.battle_over).toBe(false)
    expect(penultimate.winner).toBeNull()
  })

  it('holds on any seed, because no attack die is ever rolled', () => {
    for (const s of ['a', 'b', 'c', 'd', 'e']) {
      const { final: f } = playUntilOver(createInitialState(s), ALL_DEFENSE, ALL_DEFENSE)
      expect(f.winner).toBe('draw')
      expect(f.round_number).toBe(MAX_ROUNDS)
      expect(f.player.force_strength).toBe(STARTING_FS)
      expect(f.enemy.force_strength).toBe(STARTING_FS)
    }
  })
})

describe('Accept 4 — winner is null exactly while battle_over is false', () => {
  const battles = [
    { name: 'decisive win', seed: 'vanguard', p: ALL_ATTACK, e: ALL_ATTACK },
    { name: 'decisive loss', seed: 'bastion', p: ALL_ATTACK, e: ALL_ATTACK },
    { name: 'round-cap draw', seed: 'entrenched', p: ALL_DEFENSE, e: ALL_DEFENSE },
    { name: 'grinding (3,3) mirror', seed: 'attrition', p: EVEN, e: EVEN },
  ]

  it('holds on a fresh state, before any round is resolved', () => {
    const s = createInitialState('fresh')
    expect(s.battle_over).toBe(false)
    expect(s.winner).toBeNull()
  })

  for (const b of battles) {
    it(`holds after every single round of the ${b.name} battle`, () => {
      const { states } = playUntilOver(createInitialState(b.seed), b.p, b.e)
      let sawOver = false
      for (const s of states) {
        if (s.battle_over) {
          expect(DECIDED).toContain(s.winner)
          sawOver = true
        } else {
          expect(s.winner).toBeNull()
          // battle_over must never flip back to false once set.
          expect(sawOver).toBe(false)
        }
      }
      expect(sawOver).toBe(true)
    })
  }
})

describe('D9 — mutual destruction end to end', () => {
  // Seed changed 'assault' -> 'breach' for the retune. 'assault' no longer
  // produces mutual destruction at STARTING_FS = 12, so keeping it would have
  // meant this case silently stopped testing what its name says. 'breach' was
  // found by sweeping seeds for one that still ends with BOTH sides at 0.
  it('seed "breach", all-attack mirror: both sides hit 0 in the same round → draw', () => {
    const { final } = playUntilOver(createInitialState('breach'), ALL_ATTACK, ALL_ATTACK)
    expect(final.player.force_strength).toBe(0)
    expect(final.enemy.force_strength).toBe(0)
    expect(final.battle_over).toBe(true)
    expect(final.winner).toBe('draw')
    // Both knockouts land in the same round record — this is genuinely
    // simultaneous damage, not two sequential deaths.
    expect(final.last_round.player.force_strength_after).toBe(0)
    expect(final.last_round.enemy.force_strength_after).toBe(0)
    expect(final.round_number).toBe(6)
  })

  it('also fires from a forced 1-vs-1 state', () => {
    const s = resolveRound(withFS('mutual', 1, 1), ALL_ATTACK, ALL_ATTACK)
    expect(s.last_round.player.damage_taken).toBeGreaterThan(0)
    expect(s.last_round.enemy.damage_taken).toBeGreaterThan(0)
    expect([s.player.force_strength, s.enemy.force_strength]).toEqual([0, 0])
    expect(s.winner).toBe('draw')
  })
})

describe('D10 — a post-battle action is an inert no-op', () => {
  const { final } = playUntilOver(createInitialState('entrenched'), ALL_DEFENSE, ALL_DEFENSE)

  it('returns the identical state object, unchanged', () => {
    let s = final
    for (let i = 0; i < 5; i += 1) {
      const next = resolveRound(s, EVEN, EVEN)
      expect(next).toBe(s)
      s = next
    }
    expect(s.round_number).toBe(MAX_ROUNDS)
    expect(s.log).toHaveLength(MAX_ROUNDS)
    expect(s.winner).toBe('draw')
  })

  it('freezes roll_counter, so replay past the end stays byte-identical', () => {
    const counter = final.roll_counter
    expect(resolveRound(final, ALL_ATTACK, ALL_DEFENSE).roll_counter).toBe(counter)
  })

  it('does not resurrect a defeated side', () => {
    const dead = playUntilOver(createInitialState('bastion'), ALL_ATTACK, ALL_ATTACK).final
    const after = resolveRound(dead, ALL_DEFENSE, ALL_DEFENSE)
    expect(after.player.force_strength).toBe(0)
    expect(after.winner).toBe('enemy')
    expect(after).toBe(dead)
  })

  it('still rejects an invalid preset index, so caller bugs are never masked', () => {
    for (const bad of [-1, 7, 2.5, '0', undefined, null, NaN]) {
      expect(() => resolveRound(final, bad, EVEN)).toThrow(RangeError)
      expect(() => resolveRound(final, EVEN, bad)).toThrow(RangeError)
    }
  })
})
