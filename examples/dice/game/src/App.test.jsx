// @vitest-environment jsdom

/**
 * T-006 — the battle screen, driven the way a player drives it.
 *
 * Every interaction in this file is a REAL click dispatched into the mounted
 * DOM; the engine is imported only to compute the *expected* answer
 * independently, never to advance the UI. That is what proves the screen
 * renders engine state rather than doing arithmetic of its own.
 *
 * `@testing-library/react` is deliberately not used (and not installed) — the
 * scaffold ships no such dependency, and React's own `act` + `createRoot` are
 * enough for a component of this size.
 */

import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App.jsx'
import { ALLOCATIONS, MAX_ROUNDS, STARTING_FS, applyAction, createInitialState } from './engine.js'
import { DEFAULT_SEED } from './useBattle.js'

let container
let root
let errorSpy
let warnSpy

/** Query one `data-testid` node out of the mounted tree. */
function byId(testId) {
  return document.querySelector(`[data-testid="${testId}"]`)
}

/** Query every node carrying a `data-testid`. */
function allById(testId) {
  return Array.from(document.querySelectorAll(`[data-testid="${testId}"]`))
}

/** Dispatch a real bubbling click, flushed through React. */
async function click(testId) {
  const el = byId(testId)
  expect(el, `no element with data-testid="${testId}"`).toBeTruthy()
  await act(async () => {
    el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
  })
}

/**
 * Assert the run produced no console noise (PRD acceptance criterion).
 *
 * Called explicitly by the scripted-battle test AND from `afterEach` for every
 * test in this file. The blanket check is not belt-and-braces, it is required:
 * React caches several dev warnings per component name (`ownerHasKeyUseWarning`
 * and friends), so a missing-key warning raised by the FIRST test that renders
 * the log is silently absent from every later test. Checking only inside the
 * scripted-battle test would therefore pass even with the keys removed — that
 * exact mutation was tried, and it slipped through.
 */
function expectQuietConsole() {
  // `.mock.calls` rather than `.not.toHaveBeenCalled()` so a failure prints the
  // offending message instead of just a count.
  expect(errorSpy.mock.calls).toEqual([])
  expect(warnSpy.mock.calls).toEqual([])
}

beforeEach(async () => {
  // React 19 logs a console.error when `act` is used outside an act environment
  // — which would fail the very assertion under test, for harness reasons.
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  // Installed BEFORE the first render, so mount-time warnings are captured too.
  errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
  warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})

  // Attached to the document: React 19 delegates events at the root container,
  // so clicks are inert on a detached node.
  container = document.createElement('div')
  document.body.appendChild(container)
  await act(async () => {
    root = createRoot(container)
    // Bare, not inside StrictMode: `main.jsx` keeps StrictMode for the app; a
    // double-invoked render here would only obscure what is being asserted.
    root.render(<App />)
  })
})

afterEach(async () => {
  await act(async () => root.unmount())
  container.remove()
  container = null
  // Every test in this file, not just the scripted battle — see above.
  expectQuietConsole()
  vi.restoreAllMocks()
})

describe('App — opening state', () => {
  it('renders one button per allocation preset, labelled from the engine table', () => {
    ALLOCATIONS.forEach((preset, index) => {
      const button = byId(`alloc-${index}`)
      expect(button, `alloc-${index} missing`).toBeTruthy()
      expect(button.textContent).toContain(`${preset.attack} ATK`)
      expect(button.textContent).toContain(`${preset.defense} DEF`)
      expect(button.disabled).toBe(false)
    })
    expect(allById('alloc-0').length).toBe(1)
    expect(document.querySelectorAll('.alloc-button').length).toBe(ALLOCATIONS.length)
  })

  it('opens at full strength on both sides, round 0, with an empty log', () => {
    expect(byId('fs-value-player').textContent).toBe(String(STARTING_FS))
    expect(byId('fs-value-enemy').textContent).toBe(String(STARTING_FS))
    expect(byId('fs-bar-player').style.width).toBe('100%')
    expect(byId('fs-bar-enemy').style.width).toBe('100%')
    expect(byId('round-number').textContent).toBe('0')
    expect(byId('outcome')).toBeNull()
    expect(allById('log-entry').length).toBe(0)
    expect(byId('round-log').textContent).toContain('The armies face off')
  })
})

describe('App — a manual allocation click', () => {
  it('resolves one round and updates the bars and the log', async () => {
    // The truth, computed independently of the UI.
    const expected = applyAction(createInitialState(DEFAULT_SEED), 0)

    await click('alloc-0')

    expect(byId('round-number').textContent).toBe('1')
    expect(byId('fs-value-player').textContent).toBe(String(expected.player.force_strength))
    expect(byId('fs-value-enemy').textContent).toBe(String(expected.enemy.force_strength))
    expect(byId('fs-bar-enemy').style.width).toBe(
      `${(expected.enemy.force_strength / STARTING_FS) * 100}%`,
    )

    const entries = allById('log-entry')
    expect(entries.length).toBe(1)
    expect(entries[0].textContent).toContain('Round 1')
    // Flavor text keyed to the preset that was actually clicked.
    expect(entries[0].textContent).toContain('Your soldiers charge forward!')
    // The damage the engine recorded is what the log reports.
    expect(entries[0].textContent).toContain(String(expected.last_round.player.attack_hits))
  })

  it('keeps stacking rounds, newest dispatch first', async () => {
    await click('alloc-0')
    await click('alloc-6')
    await click('alloc-3')

    const entries = allById('log-entry')
    expect(entries.length).toBe(3)
    expect(entries[0].textContent).toContain('Round 3')
    expect(entries[2].textContent).toContain('Round 1')
    expect(byId('round-number').textContent).toBe('3')
  })
})

describe('App — a scripted multi-round battle', () => {
  it('runs to a finish without a single console.error or console.warn', async () => {
    // A varied script so aggressive, balanced and defensive presets all render,
    // and the reinforcement round (3) is crossed.
    const script = [0, 3, 6, 1, 4, 2, 5, 0, 3, 6, 1, 4]

    for (let i = 0; i < script.length && !byId('outcome'); i += 1) {
      await click(`alloc-${script[i % script.length]}`)
    }

    // Non-vacuity guards: the battle must actually have been played out before
    // the console assertions below can mean anything.
    const rounds = Number(byId('round-number').textContent)
    expect(rounds).toBeGreaterThanOrEqual(3)
    expect(allById('log-entry').length).toBe(rounds)
    expect(byId('outcome')).not.toBeNull()
    expect(byId('outcome').textContent.length).toBeGreaterThan(0)
    expect(rounds).toBeLessThanOrEqual(MAX_ROUNDS)

    expectQuietConsole()
  })
})

describe('App — after the battle', () => {
  /** Play the scripted battle to its end. */
  async function playToEnd() {
    const script = [0, 3, 6, 1, 4, 2, 5, 0, 3, 6, 1, 4]
    for (let i = 0; i < script.length && !byId('outcome'); i += 1) {
      await click(`alloc-${script[i % script.length]}`)
    }
    expect(byId('outcome')).not.toBeNull()
  }

  it('disables every allocation button and offers a fresh battle', async () => {
    await playToEnd()

    ALLOCATIONS.forEach((_preset, index) => {
      expect(byId(`alloc-${index}`).disabled).toBe(true)
    })
    expect(byId('new-battle')).not.toBeNull()

    // A blind extra click changes nothing (the engine's post-battle no-op).
    const rounds = byId('round-number').textContent
    await click('alloc-0')
    expect(byId('round-number').textContent).toBe(rounds)
    expectQuietConsole()
  })

  it('musters a new battle back to the opening position', async () => {
    await playToEnd()
    await click('new-battle')

    expect(byId('round-number').textContent).toBe('0')
    expect(byId('fs-value-player').textContent).toBe(String(STARTING_FS))
    expect(byId('fs-value-enemy').textContent).toBe(String(STARTING_FS))
    expect(allById('log-entry').length).toBe(0)
    expect(byId('outcome')).toBeNull()
    expect(byId('alloc-0').disabled).toBe(false)

    // And it plays on: the first round of the new battle matches a fresh
    // engine battle on the same seed, i.e. the reset really reseeded.
    const expected = applyAction(createInitialState(DEFAULT_SEED), 2)
    await click('alloc-2')
    expect(byId('fs-value-player').textContent).toBe(String(expected.player.force_strength))
    expect(byId('fs-value-enemy').textContent).toBe(String(expected.enemy.force_strength))
    expectQuietConsole()
  })
})
