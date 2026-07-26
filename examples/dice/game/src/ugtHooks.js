/**
 * Dice Duel — the UGT window hooks (T-007).
 *
 * This module contains NO game rules. It is a serialization + installation
 * layer over the `useBattle` seam: every value it emits is a field the engine
 * already wrote, copied verbatim. It never computes damage, never decides
 * whether the battle is over, never validates an action id (that is the
 * engine's `RangeError`), and never invents a default for a missing field.
 *
 * React-free on purpose, so it is unit-testable in the repo's default `node`
 * test environment and so `installUgtHooks` can be pointed at a plain object
 * instead of the real `window`.
 *
 * Decisions pinned here so a reviewer need not re-litigate them:
 *
 * D14 (REVISED 2026-07-26) — `__SEND_ACTION__` RETURNS THE STRUCTURED ENVELOPE
 *   `{state, terminated, truncated, info}`.
 *
 *   It originally returned the bare projected state, because PRD.md said it
 *   "resolves one full round … and returns the new state". That was honest to
 *   the PRD and it cost real coverage: `ugt/adapters/playwright.py` falls back
 *   to a legacy branch for a bare state and reads lifecycle off the state dict
 *   via `state.pop("terminated")`. This game reports `battle_over`, never
 *   `terminated`, so UGT never saw a battle end and kept driving concluded
 *   matches. UGT's R3 measured the damage: only ~9% of a 120-step random
 *   episode landed on a live battle; the other 91% hammered a finished one.
 *
 *   Returning the envelope puts the adapter on its preferred branch. Note this
 *   is NOT the same as adding `terminated` to `toContractState`: the adapter
 *   pops lifecycle keys in `step()` but not in `reset()`, so that route would
 *   make the two return different shapes. `__GET_STATE__` and `__RESET__` still
 *   return exactly the PRD's projection, unchanged.
 *
 * D15 — THE PROJECTION IS EXACTLY THE PRD'S SEVEN FIELDS, built as a fresh
 *   literal on every call, with fresh nested objects. Engine bookkeeping
 *   (`seed`, `roll_counter`, `last_round`, `log`, per-side `reinforcements_used`)
 *   never crosses the wire, and a caller that mutates the result cannot corrupt
 *   engine state.
 *
 * D16 — ERRORS PROPAGATE. An out-of-range or non-integer action id raises the
 *   engine's `RangeError` (a contract violation should be loud, not coerced);
 *   a post-battle action is the engine's D10 no-op, so a full battle plus
 *   trailing blind actions produces zero console errors, per PRD acceptance.
 *   The hook layer adds no validation of its own — that would be a rule.
 *
 * D17 — `__RESET__()` WITH NO ARGUMENT REPLAYS THE CURRENT SEED (the default
 *   parameter on `useBattle`'s `reset` fires on `undefined`), and returns the
 *   projected fresh state. The PRD does not specify a return value; returning
 *   the new state is additive and makes a reset testable in one expression.
 *
 * D18 — `__RESET_GAME__` is aliased to the same function. That is the
 *   *optional* soft-reset hook `ugt/adapters/playwright.py` probes for; without
 *   it every adapter-side `reset()` is a full page reload. It is an alias, not
 *   a fourth behaviour, and changes none of the three contract hooks.
 *
 * Deliberately NOT built here: `window.__STEP_COMPLETE__` (a step-pacing flag
 * the adapter probes — it belongs with the integration's `step_delay_ms`
 * tuning; this game resolves a round synchronously, so the adapter's timeout
 * path is correct) and any URL `?seed=` plumbing (an integration can call
 * `__RESET__(seed)` through `page.evaluate`).
 */

/** The three contract hook names, plus D18's alias. */
export const HOOK_NAMES = Object.freeze([
  '__GET_STATE__',
  '__SEND_ACTION__',
  '__RESET__',
  '__RESET_GAME__',
])

/**
 * Project engine state down to the PRD's `__GET_STATE__` shape.
 *
 * Field-for-field copies, in the PRD's key order. No arithmetic, no `??`
 * fallbacks — a fallback would paper over a real engine bug and hand the
 * black-box driver a plausible lie.
 *
 * @param {object} state engine state (see `createInitialState`)
 * @returns {{player: {force_strength: number, bonus_dice: number}, enemy: {force_strength: number, bonus_dice: number}, round_number: number, battle_over: boolean, winner: null|'player'|'enemy'|'draw'}}
 */
export function toContractState(state) {
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

/**
 * Install the UGT hooks onto `target` (the real `window` in the app).
 *
 * The hooks are one-liners over the seam because `__SEND_ACTION__` must return
 * the NEW state synchronously and must survive several calls inside one tick —
 * a black-box adapter drives a whole battle in a loop. That is exactly why
 * `useBattle` keeps its `useRef` mirror and why `getState` reads the ref, not
 * the render state.
 *
 * `target` is a parameter rather than a hard-coded `window` so the install and
 * uninstall semantics are assertable without jsdom.
 *
 * @param {object} target usually `window`
 * @param {{getState: () => object, sendAction: (actionId: number) => object, reset: (seed?: string|number) => object}} seam
 * @returns {() => void} uninstall
 */
export function installUgtHooks(target, { getState, sendAction, reset }) {
  const hooks = {
    __GET_STATE__: () => toContractState(getState()),
    // D14 (revised): the STRUCTURED envelope, so a black-box driver can see the
    // battle end. `terminated` mirrors the engine's own `battle_over`; nothing
    // is computed here, so this stays a projection and not a rule.
    __SEND_ACTION__: (actionId) => {
      const state = toContractState(sendAction(actionId))
      return { state, terminated: state.battle_over, truncated: false, info: {} }
    },
    __RESET__: (seed) => toContractState(reset(seed)),
  }
  // D18: the adapter's optional soft-reset name, same function object.
  hooks.__RESET_GAME__ = hooks.__RESET__

  for (const name of HOOK_NAMES) {
    target[name] = hooks[name]
  }

  return function uninstallUgtHooks() {
    for (const name of HOOK_NAMES) {
      // Only remove what THIS call installed, so a stale cleanup can never tear
      // down a newer install and leave the page hookless (the adapter's
      // `__GET_STATE__` wait would then time out with no useful error).
      //
      // Measured, not assumed: React 19's StrictMode double-invoke was probed
      // in this repo and runs install → cleanup → install, i.e. SEQUENTIALLY,
      // so StrictMode on its own is safe with or without this guard. The guard
      // is for the overlapping case — two `<App />`s mounted at once, or a
      // future React ordering change — where the identity check is the only
      // thing that keeps the live hooks live. `ugtHooks.test.js` pins it.
      if (target[name] === hooks[name]) {
        delete target[name]
      }
    }
  }
}
