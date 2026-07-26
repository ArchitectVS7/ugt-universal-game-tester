/**
 * T-007 — the projection and the installer, in isolation.
 *
 * Runs in the default `node` environment: `installUgtHooks` takes its target as
 * a parameter, so install/uninstall semantics are assertable against a plain
 * object with no jsdom and no React. The end-to-end "drive a battle through
 * `window`" proof lives in `src/hooks.integration.test.jsx`.
 *
 * Every state fixture here comes from the REAL engine (`createInitialState` +
 * `applyAction`), never a hand-built literal — a literal would only prove the
 * projection copies a literal.
 */

import { describe, expect, it, vi } from 'vitest'
import { HOOK_NAMES, installUgtHooks, toContractState } from './ugtHooks.js'
import { applyAction, createInitialState } from './engine.js'

/** The exact top-level keys PRD.md's `__GET_STATE__` sample carries. */
const CONTRACT_KEYS = ['player', 'enemy', 'round_number', 'battle_over', 'winner']

/** The exact per-side keys. */
const SIDE_KEYS = ['force_strength', 'bonus_dice']

/** Play `seq` from a fresh battle and return the final engine state. */
function play(seed, seq) {
  let state = createInitialState(seed)
  for (const actionId of seq) state = applyAction(state, actionId)
  return state
}

describe('toContractState — shape', () => {
  it('emits exactly the PRD contract keys, in the PRD order', () => {
    const projection = toContractState(createInitialState('shape'))
    expect(Object.keys(projection)).toEqual(CONTRACT_KEYS)
    expect(Object.keys(projection.player)).toEqual(SIDE_KEYS)
    expect(Object.keys(projection.enemy)).toEqual(SIDE_KEYS)
  })

  it('leaks no engine bookkeeping over the wire', () => {
    // Mid-battle, so `log`/`last_round`/`reinforcements_used` are all populated
    // — a projection built from a fresh state could pass vacuously.
    const state = play('leak', [0, 1, 2, 3])
    expect(state.log.length).toBe(4)
    expect(state.player.reinforcements_used).toBe(true)

    const projection = toContractState(state)
    // Asserted on the KEY LIST, not on values: a field explicitly set to
    // `undefined` would satisfy a value check and still be a leak in shape.
    for (const leaked of ['seed', 'roll_counter', 'last_round', 'log']) {
      expect(Object.keys(projection)).not.toContain(leaked)
    }
    expect(Object.keys(projection.player)).not.toContain('reinforcements_used')
    expect(Object.keys(projection.enemy)).not.toContain('reinforcements_used')
  })

  it('survives a JSON round trip unchanged (Playwright serializes it)', () => {
    const state = play('wire', [0, 4, 2])
    const projection = toContractState(state)
    // An accidental `undefined` field would be dropped silently by the browser
    // boundary; this catches it.
    expect(JSON.parse(JSON.stringify(projection))).toEqual(projection)
  })
})

describe('toContractState — values', () => {
  it('copies the engine\'s numbers verbatim', () => {
    const state = play('values', [0, 6, 3, 1])
    const projection = toContractState(state)

    expect(projection.player.force_strength).toBe(state.player.force_strength)
    expect(projection.player.bonus_dice).toBe(state.player.bonus_dice)
    expect(projection.enemy.force_strength).toBe(state.enemy.force_strength)
    expect(projection.enemy.bonus_dice).toBe(state.enemy.bonus_dice)
    expect(projection.round_number).toBe(state.round_number)
    expect(projection.battle_over).toBe(state.battle_over)
    expect(projection.winner).toBe(state.winner)

    // Non-vacuity: the battle really moved off the opening position.
    expect(projection.round_number).toBe(4)
    expect(projection.player.force_strength).toBeLessThan(20)
  })

  it('reports winner null while the battle is live, and the engine\'s verdict once it is not', () => {
    const live = toContractState(play('values', [0, 6]))
    expect(live.battle_over).toBe(false)
    expect(live.winner).toBeNull()

    // Verified fixture: seed-a, all-attack, decides for the player on round 11.
    const decided = play('seed-a', Array(11).fill(0))
    expect(decided.battle_over).toBe(true)
    const projection = toContractState(decided)
    expect(projection.winner).toBe('player')
    expect(projection.enemy.force_strength).toBe(0)
  })
})

describe('toContractState — isolation', () => {
  it('returns a fresh object every call, never an alias of engine state', () => {
    const state = play('isolate', [2, 2])
    const a = toContractState(state)
    const b = toContractState(state)

    expect(a).not.toBe(b)
    expect(a.player).not.toBe(b.player)
    expect(a.player).not.toBe(state.player)
    expect(a).toEqual(b)
  })

  it('cannot corrupt engine state when the caller mutates the result', () => {
    const state = play('isolate', [0])
    const before = state.player.force_strength
    const projection = toContractState(state)

    projection.player.force_strength = -999
    projection.winner = 'player'

    expect(state.player.force_strength).toBe(before)
    expect(state.winner).toBeNull()
    expect(toContractState(state).player.force_strength).toBe(before)
  })
})

describe('installUgtHooks', () => {
  /** A seam of spies, so delegation can be asserted without React. */
  function spySeam(state) {
    return {
      getState: vi.fn(() => state),
      sendAction: vi.fn(() => state),
      reset: vi.fn(() => state),
    }
  }

  it('installs every hook name as a function and removes them on uninstall', () => {
    const target = {}
    const uninstall = installUgtHooks(target, spySeam(createInitialState('install')))

    for (const name of HOOK_NAMES) {
      expect(typeof target[name], name).toBe('function')
    }
    // The three contract names PRD.md requires are present by literal name, not
    // merely "whatever HOOK_NAMES happens to list".
    expect(typeof target.__GET_STATE__).toBe('function')
    expect(typeof target.__SEND_ACTION__).toBe('function')
    expect(typeof target.__RESET__).toBe('function')
    // D18: the adapter's optional soft-reset alias, same function object.
    expect(target.__RESET_GAME__).toBe(target.__RESET__)

    uninstall()
    for (const name of HOOK_NAMES) {
      expect(name in target, name).toBe(false)
    }
  })

  it('leaves a newer install in place when a stale cleanup runs (StrictMode)', () => {
    const target = {}
    const uninstallFirst = installUgtHooks(target, spySeam(createInitialState('a')))
    const first = target.__GET_STATE__

    // React 19 StrictMode mounts, unmounts, then mounts again — the second
    // install lands before the first cleanup fires.
    installUgtHooks(target, spySeam(createInitialState('b')))
    const second = target.__GET_STATE__
    expect(second).not.toBe(first)

    uninstallFirst()

    for (const name of HOOK_NAMES) {
      expect(typeof target[name], name).toBe('function')
    }
    expect(target.__GET_STATE__).toBe(second)
  })

  it('delegates to the seam rather than forking its own state', () => {
    const state = play('delegate', [1, 1])
    const seam = spySeam(state)
    const target = {}
    installUgtHooks(target, seam)

    expect(target.__GET_STATE__()).toEqual(toContractState(state))
    expect(seam.getState).toHaveBeenCalledTimes(1)

    const sent = target.__SEND_ACTION__(3)
    expect(seam.sendAction).toHaveBeenCalledTimes(1)
    expect(seam.sendAction).toHaveBeenCalledWith(3)
    expect(sent).toEqual(toContractState(state))

    target.__RESET__('other-seed')
    expect(seam.reset).toHaveBeenCalledTimes(1)
    expect(seam.reset).toHaveBeenCalledWith('other-seed')

    // D17: no argument reaches the seam as `undefined`, so `reset`'s default
    // parameter (replay the current seed) is what fires.
    target.__RESET__()
    expect(seam.reset).toHaveBeenLastCalledWith(undefined)
  })

  it('propagates the engine\'s RangeError for an illegal action id (D16)', () => {
    const state = createInitialState('errors')
    const target = {}
    installUgtHooks(target, {
      getState: () => state,
      sendAction: (actionId) => applyAction(state, actionId),
      reset: () => state,
    })

    expect(() => target.__SEND_ACTION__(7)).toThrow(RangeError)
    expect(() => target.__SEND_ACTION__(-1)).toThrow(RangeError)
    expect(() => target.__SEND_ACTION__('0')).toThrow(RangeError)
    // …but every legal id goes through.
    for (let id = 0; id < 7; id += 1) {
      expect(target.__SEND_ACTION__(id).round_number).toBe(1)
    }
  })
})
