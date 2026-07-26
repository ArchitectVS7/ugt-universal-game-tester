import { describe, it, expect } from 'vitest'
import {
  ALLOCATIONS,
  DUG_IN_THRESHOLD,
  MAX_ROUNDS,
  POOL_SIZE,
  REINFORCEMENT_DICE,
  REINFORCEMENT_ROUND,
  STARTING_FS,
  createInitialState,
  resolveRound,
  rollPool,
  sideBonuses,
} from './engine.js'

/** Preset index shorthands, so the tests read like the PRD. */
const ALL_ATTACK = 0 // (6,0)
const EVEN = 3 // (3,3)
const ALL_DEFENSE = 6 // (0,6)

/**
 * An initial state with FS (and optionally round/flags) forced, so a bonus rule
 * can be pinned to one exact situation without playing rounds up to it.
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

/** Roll the four pools independently, in the engine's fixed D3 order. */
function expectedRound(seed, counter, pAtk, pDef, eAtk, eDef) {
  const playerAttack = rollPool(pAtk, seed, counter)
  const playerDefense = rollPool(pDef, seed, playerAttack.rollCounter)
  const enemyAttack = rollPool(eAtk, seed, playerDefense.rollCounter)
  const enemyDefense = rollPool(eDef, seed, enemyAttack.rollCounter)
  return {
    playerAttack,
    playerDefense,
    enemyAttack,
    enemyDefense,
    damageToPlayer: Math.max(0, enemyAttack.hits - playerDefense.hits),
    damageToEnemy: Math.max(0, playerAttack.hits - enemyDefense.hits),
    rollCounter: enemyDefense.rollCounter,
  }
}

/** Play `n` rounds from a state with fixed presets, returning the final state. */
function playRounds(state, n, playerPreset, enemyPreset) {
  let s = state
  for (let i = 0; i < n; i += 1) {
    s = resolveRound(s, playerPreset, enemyPreset)
  }
  return s
}

describe('allocation presets', () => {
  it('is the PRD’s 7 presets, in __SEND_ACTION__ id order', () => {
    expect(ALLOCATIONS.map((p) => [p.attack, p.defense])).toEqual([
      [6, 0],
      [5, 1],
      [4, 2],
      [3, 3],
      [2, 4],
      [1, 5],
      [0, 6],
    ])
  })

  it('every preset spends exactly the 6-die pool', () => {
    for (const p of ALLOCATIONS) {
      expect(p.attack + p.defense).toBe(POOL_SIZE)
    }
  })
})

describe('createInitialState', () => {
  it('opens at 20/20 with zero bonus dice, round 0, no winner', () => {
    const s = createInitialState('open')
    expect(s.player).toEqual({ force_strength: STARTING_FS, bonus_dice: 0, reinforcements_used: false })
    expect(s.enemy).toEqual({ force_strength: STARTING_FS, bonus_dice: 0, reinforcements_used: false })
    expect(s.round_number).toBe(0)
    expect(s.roll_counter).toBe(0)
    expect(s.battle_over).toBe(false)
    expect(s.winner).toBeNull()
    expect(s.log).toEqual([])
    expect(s.last_round).toBeNull()
  })

  it('normalizes the seed, so 5 and "5" play the same battle', () => {
    expect(resolveRound(createInitialState(5), EVEN, EVEN)).toEqual(
      resolveRound(createInitialState('5'), EVEN, EVEN),
    )
  })
})

describe('Accept 1 — all-attack vs all-defense damage math', () => {
  const seed = 'redoubt'
  const start = createInitialState(seed)
  const next = resolveRound(start, ALL_ATTACK, ALL_DEFENSE)

  it('grants no bonuses at 20 vs 20 in round 1, so pools are exactly 6/0 and 0/6', () => {
    expect(next.last_round.player.bonuses).toEqual({
      morale: 0,
      dug_in: 0,
      reinforcements: 0,
      target: 'attack',
    })
    expect(next.last_round.enemy.bonuses).toEqual({
      morale: 0,
      dug_in: 0,
      reinforcements: 0,
      target: 'defense',
    })
    expect([next.last_round.player.attack_dice, next.last_round.player.defense_dice]).toEqual([6, 0])
    expect([next.last_round.enemy.attack_dice, next.last_round.enemy.defense_dice]).toEqual([0, 6])
  })

  it('applies (opponent attack hits − own defense hits), floored at 0', () => {
    const e = expectedRound(seed, 0, 6, 0, 0, 6)
    expect(next.last_round.player.attack_hits).toBe(e.playerAttack.hits)
    expect(next.last_round.enemy.defense_hits).toBe(e.enemyDefense.hits)
    expect(next.player.force_strength).toBe(STARTING_FS - e.damageToPlayer)
    expect(next.enemy.force_strength).toBe(STARTING_FS - e.damageToEnemy)
    // The all-defense side rolls zero attack dice, so it deals nothing.
    expect(next.last_round.enemy.attack_hits).toBe(0)
    expect(next.last_round.player.damage_taken).toBe(0)
    expect(next.player.force_strength).toBe(STARTING_FS)
  })

  it('golden values: seed "redoubt", (6,0) vs (0,6) → FS 20 / 16 after round 1', () => {
    // Literals below are cross-checked against an independent rollPool
    // computation, not pasted from the implementation's output.
    expect(next.last_round.player.attack_rolls).toEqual([2, 6, 5, 6, 5, 4])
    expect(next.last_round.enemy.defense_rolls).toEqual([4, 2, 3, 3, 4, 3])
    expect(next.player.force_strength).toBe(20)
    expect(next.enemy.force_strength).toBe(16)
    const e = expectedRound(seed, 0, 6, 0, 0, 6)
    expect(e.playerAttack.hits).toBe(4) // 6,5,6,5
    expect(e.enemyDefense.hits).toBe(0) // 4,2,3,3,4,3
    expect(e.damageToEnemy).toBe(4)
    expect(e.damageToPlayer).toBe(0)
  })

  it('never heals: defense hits in excess of incoming attack hits deal 0 damage', () => {
    // Seed "picket": the attacker lands 2 hits into 3 defense hits → 0 damage,
    // not −1, and FS does not creep upward.
    const s = resolveRound(createInitialState('picket'), ALL_DEFENSE, ALL_ATTACK)
    expect(s.last_round.enemy.attack_hits).toBe(2)
    expect(s.last_round.player.defense_hits).toBe(3)
    expect(s.last_round.player.damage_taken).toBe(0)
    expect(s.player.force_strength).toBe(STARTING_FS)
    expect(s.enemy.force_strength).toBe(STARTING_FS)
  })

  it('clamps FS to exactly 0, never below', () => {
    // FS 1 against a full attack pool; with dug-in the defender still cannot
    // out-block 6+ attack dice on every seed, so scan seeds for a lethal one.
    let sawZero = false
    for (let i = 0; i < 40 && !sawZero; i += 1) {
      const s = resolveRound(withFS(`lethal${i}`, 1, STARTING_FS), ALL_DEFENSE, ALL_ATTACK)
      expect(s.player.force_strength).toBeGreaterThanOrEqual(0)
      if (s.last_round.player.damage_taken > 1) {
        expect(s.player.force_strength).toBe(0)
        sawZero = true
      }
    }
    expect(sawZero).toBe(true)
  })

  it('advances roll_counter by exactly the sum of the four pool sizes', () => {
    const r = next.last_round
    const total =
      r.player.attack_dice + r.player.defense_dice + r.enemy.attack_dice + r.enemy.defense_dice
    expect(next.roll_counter).toBe(start.roll_counter + total)
    expect(total).toBe(12)
    // And once bonuses are live, the counter still tracks the actual pools.
    const bonusy = resolveRound(withFS('cnt', 10, 5), EVEN, EVEN)
    const b = bonusy.last_round
    expect(bonusy.roll_counter).toBe(
      b.player.attack_dice + b.player.defense_dice + b.enemy.attack_dice + b.enemy.defense_dice,
    )
  })

  it('increments the round counter and records the round in the log', () => {
    expect(next.round_number).toBe(1)
    expect(next.log).toHaveLength(1)
    expect(next.log[0]).toBe(next.last_round)
    expect(next.last_round.round).toBe(1)
    expect(next.last_round.player.preset_index).toBe(ALL_ATTACK)
    expect(next.last_round.enemy.preset_index).toBe(ALL_DEFENSE)
  })

  it('does not mutate the state it was given', () => {
    const s = createInitialState('immutable')
    const snapshot = structuredClone(s)
    resolveRound(s, ALL_ATTACK, ALL_DEFENSE)
    expect(s).toEqual(snapshot)
  })

  it('is still in progress after round 1, so battle_over is false and winner null', () => {
    // The end-condition rule itself is covered in battle.test.js (T-004);
    // asserted here so a round that decides nothing stays undecided.
    expect(next.battle_over).toBe(false)
    expect(next.winner).toBeNull()
  })
})

describe('Accept 2 — Morale surge triggers only when FS is strictly greater', () => {
  const cases = [
    { name: '20 vs 19 → player only', p: 20, e: 19, pm: 1, em: 0 },
    { name: '19 vs 20 → enemy only', p: 19, e: 20, pm: 0, em: 1 },
    { name: '20 vs 20 (tie) → neither', p: 20, e: 20, pm: 0, em: 0 },
    { name: '11 vs 11 (tie, above dug-in) → neither', p: 11, e: 11, pm: 0, em: 0 },
  ]

  for (const c of cases) {
    it(c.name, () => {
      const s = resolveRound(withFS('morale', c.p, c.e), EVEN, EVEN)
      expect(s.last_round.player.bonuses.morale).toBe(c.pm)
      expect(s.last_round.enemy.bonuses.morale).toBe(c.em)
      // All these FS are above the dug-in threshold, so attack = preset + morale.
      expect(s.last_round.player.attack_dice).toBe(ALLOCATIONS[EVEN].attack + c.pm)
      expect(s.last_round.enemy.attack_dice).toBe(ALLOCATIONS[EVEN].attack + c.em)
      expect(s.last_round.player.defense_dice).toBe(ALLOCATIONS[EVEN].defense)
    })
  }

  it('1 vs 1 (tie, both dug in) → no morale for anyone, defense bonus for both', () => {
    const s = resolveRound(withFS('morale-low', 1, 1), EVEN, EVEN)
    for (const side of ['player', 'enemy']) {
      expect(s.last_round[side].bonuses.morale).toBe(0)
      expect(s.last_round[side].bonuses.dug_in).toBe(1)
      expect(s.last_round[side].attack_dice).toBe(3)
      expect(s.last_round[side].defense_dice).toBe(4)
    }
  })

  it('reads FS as it stood at round start, not after this round’s damage', () => {
    // Player starts 1 ahead; whatever damage lands, the morale die was already
    // granted for this round on the pre-damage comparison.
    const s = resolveRound(withFS('pre', 20, 19), ALL_ATTACK, ALL_ATTACK)
    expect(s.last_round.player.bonuses.morale).toBe(1)
    expect(s.last_round.player.attack_dice).toBe(7)
  })
})

describe('Accept 3 — Dug in triggers at FS ≤ 10', () => {
  const boundary = [
    { fs: 20, dug: 0 },
    { fs: 11, dug: 0 },
    { fs: DUG_IN_THRESHOLD, dug: 1 },
    { fs: 9, dug: 1 },
    { fs: 1, dug: 1 },
  ]

  for (const { fs, dug } of boundary) {
    it(`player FS ${fs} → dug_in ${dug} (enemy at 20 stays undug)`, () => {
      const s = resolveRound(withFS('dug', fs, 20), EVEN, EVEN)
      expect(s.last_round.player.bonuses.dug_in).toBe(dug)
      expect(s.last_round.enemy.bonuses.dug_in).toBe(0)
      expect(s.last_round.player.defense_dice).toBe(ALLOCATIONS[EVEN].defense + dug)
      expect(s.last_round.enemy.defense_dice).toBe(ALLOCATIONS[EVEN].defense)
    })

    it(`enemy FS ${fs} → dug_in ${dug} (independently of the player)`, () => {
      const s = resolveRound(withFS('dug', 20, fs), EVEN, EVEN)
      expect(s.last_round.enemy.bonuses.dug_in).toBe(dug)
      expect(s.last_round.player.bonuses.dug_in).toBe(0)
      expect(s.last_round.enemy.defense_dice).toBe(ALLOCATIONS[EVEN].defense + dug)
    })
  }

  it('stacks with morale: FS 10 vs 5 → (3,3) becomes 4 attack / 4 defense', () => {
    const s = resolveRound(withFS('stack', 10, 5), EVEN, EVEN)
    expect(s.last_round.player.bonuses).toMatchObject({ morale: 1, dug_in: 1, reinforcements: 0 })
    expect(s.last_round.player.attack_dice).toBe(4)
    expect(s.last_round.player.defense_dice).toBe(4)
    // The trailing side is dug in but has no morale.
    expect(s.last_round.enemy.bonuses).toMatchObject({ morale: 0, dug_in: 1, reinforcements: 0 })
    expect(s.last_round.enemy.attack_dice).toBe(3)
    expect(s.last_round.enemy.defense_dice).toBe(4)
  })

  it('adds the dug-in die even to an all-attack allocation (0 defense → 1)', () => {
    const s = resolveRound(withFS('dug-atk', 8, 20), ALL_ATTACK, EVEN)
    expect(s.last_round.player.defense_dice).toBe(1)
    expect(s.last_round.player.defense_rolls).toHaveLength(1)
  })
})

describe('Accept 4 — Reinforcements: once, at round 3, per side, routed by own allocation', () => {
  it('fires in exactly one round — round 3 — across a full 12-round battle', () => {
    const s = playRounds(createInitialState('reinf'), MAX_ROUNDS, EVEN, EVEN)
    // Both sides survive all 12 rounds on this seed, so no round is skipped by
    // T-004's post-battle no-op guard and the log really is 12 long. If this
    // ever fails, the seed stopped going the distance — pick another one, never
    // weaken the guard.
    expect(s.player.force_strength).toBeGreaterThan(0)
    expect(s.enemy.force_strength).toBeGreaterThan(0)
    expect(s.log).toHaveLength(MAX_ROUNDS)
    for (const side of ['player', 'enemy']) {
      const firing = s.log.filter((r) => r[side].bonuses.reinforcements > 0)
      expect(firing).toHaveLength(1)
      expect(firing[0].round).toBe(REINFORCEMENT_ROUND)
      expect(firing[0][side].bonuses.reinforcements).toBe(REINFORCEMENT_DICE)
    }
    expect(s.log[REINFORCEMENT_ROUND - 1].round).toBe(REINFORCEMENT_ROUND)
  })

  it('flips reinforcements_used from false to true across round 3', () => {
    const beforeR3 = playRounds(createInitialState('flag'), REINFORCEMENT_ROUND - 1, EVEN, EVEN)
    expect(beforeR3.player.reinforcements_used).toBe(false)
    expect(beforeR3.enemy.reinforcements_used).toBe(false)
    const afterR3 = resolveRound(beforeR3, EVEN, EVEN)
    expect(afterR3.player.reinforcements_used).toBe(true)
    expect(afterR3.enemy.reinforcements_used).toBe(true)
    const afterR4 = resolveRound(afterR3, EVEN, EVEN)
    expect(afterR4.last_round.player.bonuses.reinforcements).toBe(0)
    expect(afterR4.player.reinforcements_used).toBe(true)
  })

  it('cannot fire twice even if a round-3 state is resolved again', () => {
    const spent = playRounds(createInitialState('twice'), REINFORCEMENT_ROUND, EVEN, EVEN)
    // Force the round counter back to the reinforcement round; the spent flag
    // must still veto a second grant.
    const rewound = { ...spent, round_number: REINFORCEMENT_ROUND - 1 }
    const again = resolveRound(rewound, EVEN, EVEN)
    expect(again.last_round.player.bonuses.reinforcements).toBe(0)
    expect(again.last_round.enemy.bonuses.reinforcements).toBe(0)
  })

  const routing = [
    { name: 'all-attack (6,0)', preset: ALL_ATTACK, target: 'attack', atk: 8, def: 0 },
    { name: 'all-defense (0,6)', preset: ALL_DEFENSE, target: 'defense', atk: 0, def: 8 },
    { name: 'tie (3,3) → Attack', preset: EVEN, target: 'attack', atk: 5, def: 3 },
    { name: 'attack-heavy (4,2)', preset: 2, target: 'attack', atk: 6, def: 2 },
    { name: 'defense-heavy (2,4)', preset: 4, target: 'defense', atk: 2, def: 6 },
  ]

  for (const c of routing) {
    it(`routes to whichever pool got the most: ${c.name}`, () => {
      // Round 3 (round_number 2), both sides at 20 so morale/dug-in stay 0 and
      // the pool sizes isolate the reinforcement dice.
      const s = resolveRound(withFS('route', 20, 20, { round_number: 2 }), c.preset, EVEN)
      expect(s.last_round.player.bonuses.reinforcements).toBe(REINFORCEMENT_DICE)
      expect(s.last_round.player.bonuses.target).toBe(c.target)
      expect(s.last_round.player.attack_dice).toBe(c.atk)
      expect(s.last_round.player.defense_dice).toBe(c.def)
    })
  }

  it('routes each side independently by its own allocation', () => {
    const s = resolveRound(withFS('indep', 20, 20, { round_number: 2 }), ALL_ATTACK, ALL_DEFENSE)
    expect(s.last_round.player.bonuses).toMatchObject({ reinforcements: 2, target: 'attack' })
    expect(s.last_round.enemy.bonuses).toMatchObject({ reinforcements: 2, target: 'defense' })
    expect([s.last_round.player.attack_dice, s.last_round.player.defense_dice]).toEqual([8, 0])
    expect([s.last_round.enemy.attack_dice, s.last_round.enemy.defense_dice]).toEqual([0, 8])
  })

  it('routes on the base preset, so a morale/dug-in die cannot redirect it', () => {
    // (3,3) + morale would be 4 attack / 3 defense; (3,3) + dug-in would be
    // 3/4. Either way the tie-break reads the preset and sends 2 to attack.
    const dugIn = resolveRound(withFS('base', 8, 20, { round_number: 2 }), EVEN, EVEN)
    expect(dugIn.last_round.player.bonuses).toMatchObject({ dug_in: 1, target: 'attack' })
    expect(dugIn.last_round.player.attack_dice).toBe(5)
    expect(dugIn.last_round.player.defense_dice).toBe(4)
  })

  it('sets bonus_dice to morale + dug_in + reinforcements for the round just resolved', () => {
    const s = resolveRound(withFS('bd', 8, 20, { round_number: 2 }), EVEN, EVEN)
    const b = s.last_round.player.bonuses
    expect(b).toMatchObject({ morale: 0, dug_in: 1, reinforcements: 2 })
    expect(s.player.bonus_dice).toBe(3)
    expect(s.enemy.bonus_dice).toBe(s.last_round.enemy.bonuses.morale + 2)
    // And it resets to the next round's value rather than accumulating.
    const after = resolveRound(s, EVEN, EVEN)
    expect(after.player.bonus_dice).toBe(
      after.last_round.player.bonuses.morale + after.last_round.player.bonuses.dug_in,
    )
  })

  it('is 0 on a fresh state', () => {
    expect(createInitialState('fresh').player.bonus_dice).toBe(0)
    expect(createInitialState('fresh').enemy.bonus_dice).toBe(0)
  })
})

describe('sideBonuses (the symmetric helper both sides use)', () => {
  it('is a pure function of its arguments', () => {
    const args = [10, 12, 2, ALLOCATIONS[EVEN], false]
    expect(sideBonuses(...args)).toEqual(sideBonuses(...args))
  })

  it('never grants reinforcements outside round 3', () => {
    for (let r = 0; r < MAX_ROUNDS; r += 1) {
      const { reinforcements } = sideBonuses(20, 20, r, ALLOCATIONS[EVEN], false)
      expect(reinforcements).toBe(r + 1 === REINFORCEMENT_ROUND ? REINFORCEMENT_DICE : 0)
    }
  })
})

describe('determinism + discipline', () => {
  it('reproduces an identical state and log for the same seed and action sequence', () => {
    const actions = [0, 6, 3, 1, 5, 2, 4, 3, 0, 6, 2, 3]
    const run = () => {
      let s = createInitialState('replay')
      actions.forEach((a, i) => {
        s = resolveRound(s, a, actions[(i + 5) % actions.length])
      })
      return s
    }
    expect(run()).toEqual(run())
  })

  it('diverges on a different seed within 12 rounds', () => {
    const a = playRounds(createInitialState('seed-a'), MAX_ROUNDS, ALL_ATTACK, ALL_ATTACK)
    const b = playRounds(createInitialState('seed-b'), MAX_ROUNDS, ALL_ATTACK, ALL_ATTACK)
    expect(a.log).not.toEqual(b.log)
  })

  it('never calls Math.random() over a full battle', () => {
    const real = Math.random
    Math.random = () => {
      throw new Error('Math.random() called in engine')
    }
    try {
      expect(() => playRounds(createInitialState('discipline'), MAX_ROUNDS, EVEN, EVEN)).not.toThrow()
    } finally {
      Math.random = real
    }
  })

  it('throws on an invalid preset index rather than silently coercing', () => {
    const s = createInitialState('bad')
    for (const bad of [-1, 7, 2.5, '0', undefined, null, NaN]) {
      expect(() => resolveRound(s, bad, EVEN)).toThrow(RangeError)
      expect(() => resolveRound(s, EVEN, bad)).toThrow(RangeError)
    }
  })
})
