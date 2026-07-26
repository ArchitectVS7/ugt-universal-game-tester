// @vitest-environment jsdom

/**
 * T-007 — the UGT contract, driven the way the Playwright adapter drives it.
 *
 * NOT ONE BUTTON IS CLICKED in this file. Every action goes through
 * `window.__SEND_ACTION__` / `__RESET__`, exactly as `ugt/adapters/playwright.py`
 * would, and the expected answer is recomputed from the engine independently —
 * including the projection itself, which is re-derived inline rather than
 * imported from `ugtHooks.js`. Importing `toContractState` here would only prove
 * the hooks call it; recomputing it proves the projection is right.
 *
 * Conventions follow `src/App.test.jsx`: React's own `act` + `createRoot` (no
 * `@testing-library/react`, which the scaffold does not ship), `data-testid`
 * queries, and `console.error`/`console.warn` spies asserted empty in
 * `afterEach` for every test — that is the PRD's "a full battle completes
 * without console errors" criterion.
 */

import { StrictMode, act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App.jsx'
import { MAX_ROUNDS, STARTING_FS, applyAction, createInitialState } from './engine.js'
import { DEFAULT_SEED } from './useBattle.js'

let container
let root
let errorSpy
let warnSpy

/**
 * The PRD's `__GET_STATE__` shape, recomputed here on purpose.
 *
 * This is the independent oracle: if `ugtHooks.js` drops or renames a field,
 * the deep-equal against this literal fails. Reusing the production projection
 * would make that mutation invisible.
 */
function expectedProjection(state) {
  return {
    player: {
      force_strength: state.player.force_strength,
      bonus_dice: state.player.bonus_dice,
    },
    enemy: {
      force_strength: state.enemy.force_strength,
      bonus_dice: state.enemy.bonus_dice,
    },
    round_number: state.round_number,
    battle_over: state.battle_over,
    winner: state.winner,
  }
}

function byId(testId) {
  return document.querySelector(`[data-testid="${testId}"]`)
}

function allById(testId) {
  return Array.from(document.querySelectorAll(`[data-testid="${testId}"]`))
}

/**
 * Call a hook inside `act` so React's re-render flushes.
 *
 * An unwrapped call raises React's "not wrapped in act" console.error, which
 * the spies below would catch — that is intended. It enforces correct usage in
 * the test harness; it is not a reason to loosen the spy.
 */
async function hook(fn) {
  let result
  await act(async () => {
    result = fn()
  })
  return result
}

function expectQuietConsole() {
  expect(errorSpy.mock.calls).toEqual([])
  expect(warnSpy.mock.calls).toEqual([])
}

/** A varied 12-action script, crossing the reinforcement round. */
const SCRIPT = [0, 1, 2, 3, 4, 5, 6, 0, 1, 2, 3, 4]

beforeEach(async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
  warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})

  container = document.createElement('div')
  document.body.appendChild(container)
  await act(async () => {
    root = createRoot(container)
    root.render(<App />)
  })
})

afterEach(async () => {
  await act(async () => root.unmount())
  container.remove()
  container = null
  expectQuietConsole()
  vi.restoreAllMocks()
})

describe('UGT hooks — mounting', () => {
  it('exposes the three contract hooks on window', () => {
    expect(typeof window.__GET_STATE__).toBe('function')
    expect(typeof window.__SEND_ACTION__).toBe('function')
    expect(typeof window.__RESET__).toBe('function')
    // The adapter's optional soft-reset alias (D18).
    expect(typeof window.__RESET_GAME__).toBe('function')
  })

  it('reports the opening position in the PRD shape', () => {
    expect(window.__GET_STATE__()).toEqual({
      player: { force_strength: STARTING_FS, bonus_dice: 0 },
      enemy: { force_strength: STARTING_FS, bonus_dice: 0 },
      round_number: 0,
      battle_over: false,
      winner: null,
    })
    // …and that literal is what the engine actually produces.
    expect(window.__GET_STATE__()).toEqual(expectedProjection(createInitialState(DEFAULT_SEED)))
  })

  it('leaves working hooks behind under StrictMode, as main.jsx mounts it', async () => {
    // `src/main.jsx` wraps <App /> in <StrictMode>, and every other test in
    // this file mounts <App /> bare — so without this one, the configuration
    // that actually ships is never exercised. StrictMode's development
    // double-invoke was probed here and runs install → cleanup → install, so
    // this asserts the end state that matters to the adapter: after the extra
    // mount/cleanup cycle, `window` still carries hooks wired to the live
    // battle. (The installer's stale-cleanup identity guard is a separate
    // concern, pinned in `ugtHooks.test.js`.)
    await act(async () => root.unmount())
    container.remove()

    container = document.createElement('div')
    document.body.appendChild(container)
    await act(async () => {
      root = createRoot(container)
      root.render(
        <StrictMode>
          <App />
        </StrictMode>,
      )
    })

    expect(typeof window.__GET_STATE__).toBe('function')
    // Not merely present — actually wired to the live battle.
    expect(window.__GET_STATE__().round_number).toBe(0)
    const returned = (await hook(() => window.__SEND_ACTION__(0))).state
    expect(returned).toEqual(expectedProjection(applyAction(createInitialState(DEFAULT_SEED), 0)))
    expect(window.__GET_STATE__()).toEqual(returned)
    expect(byId('round-number').textContent).toBe('1')
  })

  it('returns the structured envelope, with terminated tracking battle_over (D14)', async () => {
    // The regression this guards: __SEND_ACTION__ used to return the bare state,
    // which put ugt/adapters/playwright.py on its legacy branch. That branch reads
    // lifecycle via state.pop('terminated') — a key this game never sent — so a
    // black-box driver never saw a battle end and kept driving finished matches.
    await hook(() => window.__RESET__('seed-a'))

    const first = await hook(() => window.__SEND_ACTION__(0))
    expect(Object.keys(first).sort()).toEqual(['info', 'state', 'terminated', 'truncated'])
    expect(first.truncated).toBe(false)
    expect(first.info).toEqual({})
    expect(first.state).toEqual(window.__GET_STATE__())
    expect(first.terminated).toBe(false)
    expect(first.terminated).toBe(first.state.battle_over)

    // Drive to the end and confirm terminated flips with it, rather than being
    // hardcoded false — the whole point of the change.
    let last = first
    for (let i = 0; i < MAX_ROUNDS && !last.state.battle_over; i += 1) {
      last = await hook(() => window.__SEND_ACTION__(0))
      expect(last.terminated, `round ${last.state.round_number}`).toBe(last.state.battle_over)
    }
    expect(last.state.battle_over).toBe(true)
    expect(last.terminated).toBe(true)

    // __GET_STATE__ and __RESET__ are untouched: still the bare projection.
    expect(Object.keys(window.__GET_STATE__())).not.toContain('terminated')
    const fresh = await hook(() => window.__RESET__('seed-a'))
    expect(Object.keys(fresh)).not.toContain('terminated')
  })

  it('removes the hooks when the app unmounts', async () => {
    await act(async () => root.unmount())
    expect('__GET_STATE__' in window).toBe(false)
    expect('__SEND_ACTION__' in window).toBe(false)
    expect('__RESET__' in window).toBe(false)
    expect('__RESET_GAME__' in window).toBe(false)

    // `afterEach` unmounts again; a second unmount of an already-unmounted root
    // is a no-op, and re-rendering keeps the teardown symmetric.
    await act(async () => {
      root = createRoot(container)
      root.render(<App />)
    })
  })
})

describe('UGT hooks — a full battle by hook only', () => {
  it('runs 12 rounds via __SEND_ACTION__, matching __GET_STATE__ at every step', async () => {
    // The independent chain: the same script through the raw engine.
    let oracle = createInitialState(DEFAULT_SEED)

    for (let i = 0; i < SCRIPT.length; i += 1) {
      oracle = applyAction(oracle, SCRIPT[i])
      const returned = (await hook(() => window.__SEND_ACTION__(SCRIPT[i]))).state

      // (a) what the hook returned is what a subsequent read reports…
      expect(returned, `round ${i + 1} return vs read`).toEqual(window.__GET_STATE__())
      // (b) …and both match the engine computed outside the UI entirely.
      expect(returned, `round ${i + 1} vs engine`).toEqual(expectedProjection(oracle))
      // The round counter advances exactly one per action.
      expect(returned.round_number).toBe(i + 1)
      // RETUNE 2026-07-26: this seed used to survive all 12 scripted actions.
      // At STARTING_FS = 12 it is decided on round 10, so the loop stops at the
      // real end instead of asserting a round count that balance now owns.
      if (returned.battle_over) break
    }

    // Verified fixture for DEFAULT_SEED + SCRIPT, RETUNED 2026-07-26: this used
    // to run the full 12 rounds to a draw with both sides alive. At
    // STARTING_FS = 12 the same script decides on round 10 for the player.
    // What this test is actually for is the round-by-round agreement between
    // the hook return, a fresh read, and an engine oracle computed outside the
    // UI — all of which is asserted in the loop above and is unaffected by
    // balance. The end-state assertions are restated rather than dropped.
    const final = window.__GET_STATE__()
    expect(final.round_number).toBe(10)
    expect(final.battle_over).toBe(true)
    expect(final.winner).toBe('player')
    expect(final.enemy.force_strength).toBe(0)
    expect(final.player.force_strength).toBeGreaterThan(0)

    expectQuietConsole()
  })

  it('answers with the CURRENT state inside one tick, not the last render', async () => {
    // The load-bearing case for `useBattle`'s ref mirror. A driver can call
    // `__SEND_ACTION__` and then `__GET_STATE__` (or several actions in a row)
    // without ever yielding to React, so nothing has re-rendered in between. A
    // `getState` closing over the render `state` returns a whole round of stale
    // data here, while every assertion in the act-per-call tests above would
    // still pass — this is the only test that catches it.
    let oracle = createInitialState(DEFAULT_SEED)
    const seen = []

    await act(async () => {
      for (const actionId of [0, 1, 2]) {
        const returned = window.__SEND_ACTION__(actionId).state
        // Read back immediately, in the same tick, before React flushes.
        seen.push({ returned, read: window.__GET_STATE__() })
      }
    })

    seen.forEach((step, i) => {
      oracle = applyAction(oracle, [0, 1, 2][i])
      expect(step.returned, `action ${i} return`).toEqual(expectedProjection(oracle))
      expect(step.read, `action ${i} same-tick read`).toEqual(expectedProjection(oracle))
      expect(step.read.round_number).toBe(i + 1)
    })

    // And the screen caught up once the tick ended.
    expect(byId('round-number').textContent).toBe('3')
  })

  it('keeps the rendered screen in sync with hook-driven actions', async () => {
    for (const actionId of SCRIPT) {
      await hook(() => window.__SEND_ACTION__(actionId))
    }

    // This is the assertion that kills a hooks layer keeping its own private
    // engine state while the screen sits frozen at 20/20 round 0.
    const state = window.__GET_STATE__()
    expect(byId('fs-value-player').textContent).toBe(String(state.player.force_strength))
    expect(byId('fs-value-enemy').textContent).toBe(String(state.enemy.force_strength))
    expect(byId('round-number').textContent).toBe(String(state.round_number))
    expect(allById('log-entry').length).toBe(state.round_number)
    expect(byId('outcome')).not.toBeNull()
  })
})

describe('UGT hooks — decisive outcomes', () => {
  it('resolves a loss and then ignores further blind actions (D10)', async () => {
    // Verified fixture: seed-b + SCRIPT decides for the enemy on round 6.
    await hook(() => window.__RESET__('seed-b'))

    let decided = null
    for (let i = 0; i < SCRIPT.length; i += 1) {
      const returned = (await hook(() => window.__SEND_ACTION__(SCRIPT[i]))).state
      if (returned.battle_over) {
        decided = returned
        break
      }
    }

    expect(decided).not.toBeNull()
    expect(decided.round_number).toBe(3)
    expect(decided.winner).toBe('enemy')
    expect(decided.player.force_strength).toBe(0)

    // A black-box driver keeps sending: the state must not budge, and nothing
    // may reach the console (PRD acceptance).
    for (const actionId of [0, 3, 6]) {
      const after = (await hook(() => window.__SEND_ACTION__(actionId))).state
      expect(after).toEqual(decided)
    }
    expect(window.__GET_STATE__()).toEqual(decided)
    expectQuietConsole()
  })

  it('resolves a win, so all three winner values are exercised over the wire', async () => {
    // Verified fixture: 'crown', all-attack, decides for the player on round 8.
    // Was seed-a/round 11; after the 2026-07-26 retune seed-a resolves for the
    // ENEMY, so keeping it would have quietly turned this into a second copy of
    // the loss case while still claiming to cover a win.
    await hook(() => window.__RESET__('crown'))

    let decided = null
    for (let i = 0; i < MAX_ROUNDS; i += 1) {
      const returned = (await hook(() => window.__SEND_ACTION__(0))).state
      if (returned.battle_over) {
        decided = returned
        break
      }
    }

    expect(decided).not.toBeNull()
    expect(decided.round_number).toBe(8)
    expect(decided.winner).toBe('player')
    expect(decided.enemy.force_strength).toBe(0)
  })
})

describe('UGT hooks — determinism (PRD acceptance)', () => {
  /** Reset to `seed`, replay `SCRIPT`, and capture every returned state. */
  async function replay(seed) {
    await hook(() => window.__RESET__(seed))
    const trace = []
    for (const actionId of SCRIPT) {
      const returned = (await hook(() => window.__SEND_ACTION__(actionId))).state
      trace.push(JSON.stringify(returned))
    }
    return trace
  }

  it('reproduces byte-identical state for the same seed and action sequence', async () => {
    const first = await replay(DEFAULT_SEED)
    const second = await replay(DEFAULT_SEED)

    expect(second.length).toBe(SCRIPT.length)
    for (let i = 0; i < first.length; i += 1) {
      expect(second[i], `round ${i + 1} diverged`).toBe(first[i])
    }
  })

  it('actually reseeds — a different seed produces a different battle', async () => {
    // Without this guard, a `__RESET__` that ignored its argument would pass
    // the replay test above vacuously.
    const a = await replay(DEFAULT_SEED)
    const b = await replay('seed-b')
    expect(a).not.toEqual(b)
  })

  it('replays the current seed when __RESET__ is called with no argument (D17)', async () => {
    const baseline = await replay(DEFAULT_SEED)

    // Mid-battle, then a bare reset.
    await hook(() => window.__SEND_ACTION__(0))
    await hook(() => window.__SEND_ACTION__(6))
    const fresh = await hook(() => window.__RESET__())

    expect(fresh).toEqual(expectedProjection(createInitialState(DEFAULT_SEED)))
    expect(fresh.round_number).toBe(0)
    expect(fresh.player.force_strength).toBe(STARTING_FS)

    const again = []
    for (const actionId of SCRIPT) {
      again.push(JSON.stringify((await hook(() => window.__SEND_ACTION__(actionId))).state))
    }
    expect(again).toEqual(baseline)
  })
})
