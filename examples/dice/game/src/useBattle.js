/**
 * Dice Duel — the React ↔ engine seam.
 *
 * This module holds NO game rules. It calls `createInitialState` / `applyAction`
 * and stores whatever the engine hands back; every question about damage,
 * bonuses, the enemy's allocation or whether the battle is over is answered by
 * `src/engine.js` alone (TASKS.md standing constraint: rules live in the
 * engine, components only render state and dispatch actions).
 *
 * Why the `useRef` mirror: T-007 exposes `window.__SEND_ACTION__(actionId)`,
 * which must return the NEW state synchronously and must survive several calls
 * inside one tick (a black-box adapter will drive a whole battle in a loop).
 * A `useState` updater cannot do either — `state` is stale until React
 * re-renders — so the ref is the authoritative "current state" and `setState`
 * exists to trigger the render. Both are written in the same statement, so they
 * can never disagree.
 *
 * Lives in a `.js` file rather than inside `App.jsx` because the repo's eslint
 * config enables `react-refresh/only-export-components`, which flags a `.jsx`
 * module that exports both a component and a non-component.
 */

import { useCallback, useRef, useState } from 'react'
import { applyAction, createInitialState } from './engine.js'

/**
 * Seed used when nothing else is specified.
 *
 * A fixed string, not a timestamp: the PRD's determinism criterion ("same seed
 * + same action sequence reproduces byte-identical state") should hold for a
 * plain page load, and the component test reproduces battles from it.
 */
export const DEFAULT_SEED = 'dice-duel'

/**
 * Battle state plus the two dispatchers the UI (and later the UGT hooks) use.
 *
 * @param {string|number} [initialSeed]
 * @returns {{state: object, sendAction: (actionId: number) => object, reset: (seed?: string|number) => object}}
 */
export function useBattle(initialSeed = DEFAULT_SEED) {
  // `useState(fn)` so the initial battle is built once, not on every render.
  const [state, setState] = useState(() => createInitialState(initialSeed))
  const stateRef = useRef(state)

  /**
   * Dispatch one player allocation and return the resulting state.
   *
   * Post-battle calls are the engine's D10 no-op (same object back), and an
   * out-of-range id is the engine's `RangeError` — neither is re-implemented
   * or swallowed here.
   */
  const sendAction = useCallback((actionId) => {
    const next = applyAction(stateRef.current, actionId)
    stateRef.current = next
    setState(next)
    return next
  }, [])

  /** Start a fresh battle; defaults to replaying the current seed. */
  const reset = useCallback((seed = stateRef.current.seed) => {
    const fresh = createInitialState(seed)
    stateRef.current = fresh
    setState(fresh)
    return fresh
  }, [])

  return { state, sendAction, reset }
}
