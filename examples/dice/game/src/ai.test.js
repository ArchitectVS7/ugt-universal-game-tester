import { describe, it, expect } from 'vitest'
import {
  ALLOCATIONS,
  MAX_ROUNDS,
  POOL_SIZE,
  STARTING_FS,
  applyAction,
  chooseEnemyPreset,
  createInitialState,
  presetForForceStrength,
  resolveRound,
} from './engine.js'

/** Every legal action id, for sweeps. */
const ACTION_IDS = ALLOCATIONS.map((_, i) => i)

/** Every reachable Force Strength value, 0 through 20. */
const ALL_FS = Array.from({ length: STARTING_FS + 1 }, (_, fs) => fs)

/**
 * A state with the two sides' FS forced, plus arbitrary overrides — so the AI
 * can be interrogated at an exact FS without playing rounds up to it.
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

/** Drive a whole battle through the AI wrapper, collecting each state. */
function playBattle(seed, actions) {
  let s = createInitialState(seed)
  const states = [s]
  for (let i = 0; i < actions.length; i += 1) {
    s = applyAction(s, actions[i])
    states.push(s)
  }
  return { final: s, states }
}

/* --------------------------------------------------------------------------
 * A. The Accept criterion, head-on: "the AI's chosen preset is a pure function
 *    of its current FS (same FS → same preset, across repeated calls)".
 * ------------------------------------------------------------------------ */

describe('AI choice is a pure function of its own Force Strength', () => {
  it('returns the identical preset across repeated calls, at every FS', () => {
    for (const fs of ALL_FS) {
      const first = presetForForceStrength(fs)
      for (let call = 0; call < 10; call += 1) {
        expect(presetForForceStrength(fs)).toBe(first)
      }
    }
  })

  it('returns the identical preset across repeated calls through chooseEnemyPreset', () => {
    for (const fs of ALL_FS) {
      const state = withFS('repeat', 20, fs)
      const first = chooseEnemyPreset(state)
      for (let call = 0; call < 10; call += 1) {
        expect(chooseEnemyPreset(state)).toBe(first)
      }
      // A structurally different state at the same enemy FS must agree: the
      // answer depends on the number, not on the object it arrived in.
      const other = withFS('a-totally-different-seed', 3, fs, {
        round_number: 7,
        roll_counter: 999,
        enemy: { bonus_dice: 4, reinforcements_used: true },
      })
      expect(chooseEnemyPreset(other)).toBe(first)
    }
  })

  it('ignores every input except its own FS', () => {
    const ENEMY_FS = 12
    const baseline = chooseEnemyPreset(withFS('base', 20, ENEMY_FS))

    // D13: no round number, no player FS, no seed, no counter, no memory.
    const variations = [
      { seed: 'another-seed' },
      { round_number: 0 },
      { round_number: 11 },
      { roll_counter: 0 },
      { roll_counter: 4321 },
      { enemy: { bonus_dice: 3 } },
      { enemy: { reinforcements_used: true } },
      { log: [{ round: 1 }, { round: 2 }] },
      { last_round: { round: 5 } },
      { battle_over: false },
    ]
    for (const overrides of variations) {
      expect(chooseEnemyPreset(withFS('base', 20, ENEMY_FS, overrides))).toBe(baseline)
    }

    // The player's strength in particular: the heuristic is not reactive.
    for (const playerFS of ALL_FS) {
      expect(chooseEnemyPreset(withFS('base', playerFS, ENEMY_FS))).toBe(baseline)
    }
  })
})

/* --------------------------------------------------------------------------
 * B. The heuristic itself: defense dice ∝ 1 − own_FS/20, rounded to the
 *    nearest preset, remainder to attack.
 * ------------------------------------------------------------------------ */

describe('the allocation heuristic', () => {
  it('matches the full FS → preset table', () => {
    // Index = FS. Computed by hand from round(POOL_SIZE * (STARTING_FS - fs) /
    // STARTING_FS) and checked against the implementation; if these disagree the
    // implementation is what is wrong, not this table.
    //
    // RETUNED 2026-07-26 with STARTING_FS 20 -> 12, then 12 -> 8 for the D18
    // depth fix. A full FS -> preset table is inherently a function of
    // STARTING_FS, so it has to be restated by hand every time — which is the
    // point of it. Deriving it from the same formula the implementation uses
    // would make this test vacuous (O2).
    //
    // At STARTING_FS = 8: round(6 * (8 - fs) / 8) = round(0.75 * (8 - fs)) =
    //   fs 0..8 -> 6.0, 5.25, 4.5, 3.75, 3.0, 2.25, 1.5, 0.75, 0.0
    //          -> 6,    5,    5*,  4,    3,   2,    2*,  1,    0     (* = half-up)
    const expected = [6, 5, 5, 4, 3, 2, 2, 1, 0]
    expect(expected).toHaveLength(STARTING_FS + 1)
    expect(ALL_FS.map(presetForForceStrength)).toEqual(expected)
  })

  it('goes all-attack at full strength, all-defense when destroyed, even at half', () => {
    expect(presetForForceStrength(STARTING_FS)).toBe(0)
    expect(ALLOCATIONS[presetForForceStrength(STARTING_FS)]).toEqual({ attack: 6, defense: 0 })

    expect(presetForForceStrength(0)).toBe(6)
    expect(ALLOCATIONS[presetForForceStrength(0)]).toEqual({ attack: 0, defense: 6 })

    expect(presetForForceStrength(STARTING_FS / 2)).toBe(3)
    expect(ALLOCATIONS[presetForForceStrength(STARTING_FS / 2)]).toEqual({ attack: 3, defense: 3 })
  })

  it('breaks the two half-way ties toward defense (D11)', () => {
    // With STARTING_FS = 8 and POOL_SIZE = 6 the ratio is 0.75 * (8 - fs), so a
    // half-way value needs (8 - fs) ≡ 2 (mod 4) — exactly fs = 6 (→ 1.5) and
    // fs = 2 (→ 4.5). Math.round is half-up, so each rounds to the MORE
    // defensive preset. That is the decision, not a rounding accident.
    //
    // The count of half-way cases is itself a function of the constants and has
    // swung twice: 2 at STARTING_FS = 20 (fs 15, 5), then SIX at 12 (every odd
    // fs, where the ratio was exactly fs/2), and back to 2 at 8. The test name
    // says "the two", so assert the count rather than trusting the name.
    const halfWay = ALL_FS.filter((fs) => {
      const r = (POOL_SIZE * (STARTING_FS - fs)) / STARTING_FS
      return Math.abs(r - Math.floor(r) - 0.5) < 1e-9
    })
    expect(halfWay).toEqual([2, 6])
    expect(presetForForceStrength(6)).toBe(2)
    expect(presetForForceStrength(2)).toBe(5)
  })

  it('never asks for more defense as its strength rises', () => {
    for (let fs = 1; fs <= STARTING_FS; fs += 1) {
      expect(presetForForceStrength(fs)).toBeLessThanOrEqual(presetForForceStrength(fs - 1))
    }
    // ... and it genuinely varies: a constant would pass the check above.
    expect(new Set(ALL_FS.map(presetForForceStrength)).size).toBe(ALLOCATIONS.length)
  })

  it('clamps out-of-range Force Strength to a legal preset (D12)', () => {
    expect(presetForForceStrength(-5)).toBe(ALLOCATIONS.length - 1)
    expect(presetForForceStrength(STARTING_FS + 5)).toBe(0)
    for (const fs of [-1000, -100, -0.5, 0.5, 7.5, 19.5, 1000]) {
      const index = presetForForceStrength(fs)
      expect(Number.isInteger(index)).toBe(true)
      expect(index).toBeGreaterThanOrEqual(0)
      expect(index).toBeLessThanOrEqual(ALLOCATIONS.length - 1)
      expect(ALLOCATIONS[index]).toBeDefined()
    }
  })

  it('depends on ALLOCATIONS being indexed by defense-die count', () => {
    // The mapping "rounded defense dice === preset index" is only correct
    // because of this. Asserted rather than assumed: if the preset table is
    // ever reordered, this fails loudly instead of the AI silently misplaying.
    expect(ALLOCATIONS).toHaveLength(POOL_SIZE + 1)
    ALLOCATIONS.forEach((preset, i) => {
      expect(preset.defense).toBe(i)
      expect(preset.attack).toBe(POOL_SIZE - i)
      // "remainder to attack": every preset spends the whole pool.
      expect(preset.attack + preset.defense).toBe(POOL_SIZE)
    })
  })

  it('throws on a non-numeric or non-finite Force Strength rather than coercing', () => {
    for (const bad of [NaN, undefined, null, '10', '', Infinity, -Infinity, {}, []]) {
      expect(() => presetForForceStrength(bad)).toThrow(TypeError)
    }
  })
})

/* --------------------------------------------------------------------------
 * C. applyAction is wiring only — it must add no rules of its own.
 * ------------------------------------------------------------------------ */

describe('applyAction', () => {
  it('is exactly resolveRound with the AI preset', () => {
    for (const enemyFS of [20, 17, 15, 10, 5, 2]) {
      const state = withFS('wiring', 14, enemyFS)
      for (const actionId of ACTION_IDS) {
        expect(applyAction(state, actionId)).toEqual(
          resolveRound(state, actionId, chooseEnemyPreset(state)),
        )
      }
    }
  })

  it('records the preset chosen from the PRE-round FS, not the post-damage FS', () => {
    const { states } = playBattle('ai-2', Array(10).fill(0))
    let sawDifference = false
    for (let i = 1; i < states.length; i += 1) {
      const before = states[i - 1]
      const after = states[i]
      expect(after.last_round.enemy.preset_index).toBe(chooseEnemyPreset(before))
      if (chooseEnemyPreset(before) !== chooseEnemyPreset(after)) sawDifference = true
    }
    // At least one round must have moved the enemy across a preset boundary,
    // otherwise "pre-round vs post-round" would be untested either way.
    expect(sawDifference).toBe(true)
  })

  it('is inert once the battle is over, and does not burn roll_counter', () => {
    const { final } = playBattle('ai-2', Array(MAX_ROUNDS).fill(0))
    expect(final.battle_over).toBe(true)
    for (const actionId of ACTION_IDS) {
      expect(applyAction(final, actionId)).toBe(final)
    }
    expect(applyAction(final, 0).roll_counter).toBe(final.roll_counter)
  })

  it('throws on an invalid action id rather than silently coercing', () => {
    const state = createInitialState('bad-action')
    for (const bad of [-1, 7, 2.5, '0', undefined, null, NaN]) {
      expect(() => applyAction(state, bad)).toThrow(RangeError)
    }
  })
})

/* --------------------------------------------------------------------------
 * D. Determinism discipline — the whole reason the heuristic has no RNG.
 * ------------------------------------------------------------------------ */

describe('determinism', () => {
  it('never calls Math.random() over a full AI-driven battle', () => {
    const real = Math.random
    Math.random = () => {
      throw new Error('Math.random() called in engine')
    }
    try {
      expect(() => playBattle('discipline', Array(MAX_ROUNDS).fill(3))).not.toThrow()
    } finally {
      Math.random = real
    }
  })

  it('replays byte-identically for the same seed and action sequence', () => {
    const actions = [0, 3, 6, 2, 5, 1, 4, 3, 0, 6, 2, 4]
    const a = playBattle('replay-ai', actions)
    const b = playBattle('replay-ai', actions)
    expect(JSON.stringify(a.final)).toBe(JSON.stringify(b.final))
    expect(a.final.log).toEqual(b.final.log)
    expect(a.final.log.map((r) => r.enemy.preset_index)).toEqual(
      b.final.log.map((r) => r.enemy.preset_index),
    )
  })

  it('visibly shifts toward defense as the enemy weakens', () => {
    const { final } = playBattle('ai-2', Array(MAX_ROUNDS).fill(0))
    const presets = final.log.map((r) => r.enemy.preset_index)
    const strengths = final.log.map((r) => r.enemy.force_strength_after)

    // FS never heals, and the heuristic is monotonic, so the chosen preset can
    // only ever move toward defense over a battle.
    for (let i = 1; i < presets.length; i += 1) {
      expect(strengths[i]).toBeLessThanOrEqual(strengths[i - 1])
      expect(presets[i]).toBeGreaterThanOrEqual(presets[i - 1])
    }
    // A constant AI would satisfy the above; this is what proves it is live.
    expect(presets[0]).toBe(0)
    expect(new Set(presets).size).toBeGreaterThan(1)
    expect(presets[presets.length - 1]).toBeGreaterThan(presets[0])
  })
})
