/**
 * T-006 — flavor text is presentation, and pure.
 *
 * These tests build REAL round records by running the engine, never by
 * hand-crafting a fake record, so a line can only be asserted against data the
 * game actually produces.
 */

import { describe, expect, it } from 'vitest'
import { ALLOCATIONS, applyAction, createInitialState } from './engine.js'
import { flavorLines } from './flavor.js'

/** Play `actions` in order from a fresh battle and return the final state. */
function play(seed, actions) {
  return actions.reduce((state, id) => applyAction(state, id), createInitialState(seed))
}

describe('flavorLines', () => {
  it('returns a non-empty array of non-empty strings for every preset', () => {
    ALLOCATIONS.forEach((_preset, index) => {
      const record = play('flavor-seed', [index]).last_round
      const lines = flavorLines(record)
      expect(Array.isArray(lines)).toBe(true)
      expect(lines.length).toBeGreaterThan(0)
      lines.forEach((line) => {
        expect(typeof line).toBe('string')
        expect(line.trim().length).toBeGreaterThan(0)
      })
    })
  })

  it('is deterministic — the same record always yields the same prose', () => {
    const record = play('flavor-seed', [2]).last_round
    const first = flavorLines(record)
    for (let i = 0; i < 5; i += 1) {
      expect(flavorLines(record)).toEqual(first)
    }
    // And the same battle replayed from the same seed reads identically.
    expect(flavorLines(play('flavor-seed', [2]).last_round)).toEqual(first)
  })

  it('names the posture the player actually committed to', () => {
    expect(flavorLines(play('flavor-seed', [0]).last_round)).toContain(
      'Your soldiers charge forward!',
    )
    expect(flavorLines(play('flavor-seed', [3]).last_round)).toContain(
      'Your line advances and holds.',
    )
    expect(flavorLines(play('flavor-seed', [6]).last_round)).toContain(
      'Your soldiers brace behind the earthworks.',
    )
  })

  it('prints a reinforcements line exactly when the engine granted the dice', () => {
    // Rounds 1 and 2: no reinforcements in the record, none in the prose.
    for (const rounds of [[3], [3, 3]]) {
      const record = play('flavor-seed', rounds).last_round
      expect(record.player.bonuses.reinforcements).toBe(0)
      expect(record.enemy.bonuses.reinforcements).toBe(0)
      expect(flavorLines(record).some((l) => /reinforcements arrive/i.test(l))).toBe(false)
    }

    // Round 3: the engine grants them to both sides, so both lines appear —
    // including the PRD's sample sentence, verbatim.
    const record = play('flavor-seed', [3, 3, 3]).last_round
    expect(record.round).toBe(3)
    expect(record.player.bonuses.reinforcements).toBeGreaterThan(0)
    expect(record.enemy.bonuses.reinforcements).toBeGreaterThan(0)
    const lines = flavorLines(record)
    expect(lines.some((l) => l.startsWith('Your reinforcements arrive!'))).toBe(true)
    expect(lines.some((l) => l.startsWith('Enemy reinforcements arrive!'))).toBe(true)
  })

  it('mentions morale only when the record carries a morale die', () => {
    // Round 1 opens 20 v 20 — a tie grants morale to nobody.
    const opening = play('flavor-seed', [0]).last_round
    expect(opening.player.bonuses.morale).toBe(0)
    expect(opening.enemy.bonuses.morale).toBe(0)
    expect(flavorLines(opening).some((l) => /morale surges/.test(l))).toBe(false)

    // Somewhere in a long battle one side pulls ahead; wherever the engine
    // recorded a morale die, the prose must say so (and vice versa).
    const battle = play('morale-seed', [0, 0, 0, 0, 0, 0, 0, 0])
    let sawMorale = false
    battle.log.forEach((record) => {
      const lines = flavorLines(record)
      const claimsPlayer = lines.some((l) => l.startsWith('Advancing with confidence'))
      const claimsEnemy = lines.some((l) => l.startsWith('The enemy advances with confidence'))
      expect(claimsPlayer).toBe(record.player.bonuses.morale > 0)
      expect(claimsEnemy).toBe(record.enemy.bonuses.morale > 0)
      sawMorale = sawMorale || claimsPlayer || claimsEnemy
    })
    // Guard against a vacuous pass: the battle must actually contain a surge.
    expect(sawMorale).toBe(true)
  })

  it('never leaks undefined/NaN into a line across a full battle', () => {
    const battle = play('long-seed', Array.from({ length: 12 }, (_, i) => i % ALLOCATIONS.length))
    expect(battle.log.length).toBeGreaterThan(0)
    battle.log.forEach((record) => {
      flavorLines(record).forEach((line) => {
        expect(line).not.toMatch(/undefined|NaN|\[object/)
      })
    })
  })
})
