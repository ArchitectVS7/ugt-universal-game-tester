/**
 * Dice Duel — the battle screen.
 *
 * This tree renders engine state and dispatches action ids. It contains no
 * rules: it never computes damage, never decides whether the battle is over,
 * never picks the enemy's allocation, and never re-derives why a bonus die was
 * granted. Everything it shows is a field the engine already wrote.
 *
 * The `window.__GET_STATE__` / `__SEND_ACTION__` / `__RESET__` hooks are NOT
 * here — they are T-007, and they will mount on the same `useBattle` seam.
 */

import { ALLOCATIONS, MAX_ROUNDS, STARTING_FS } from './engine.js'
import { flavorLines } from './flavor.js'
import { useBattle } from './useBattle.js'
import './App.css'

/**
 * Outcome banner wording. A lookup over `state.winner`'s documented enum
 * (`null | "player" | "enemy" | "draw"`), not a rule — the engine decides who
 * won, this only names it.
 */
const OUTCOME_TEXT = {
  player: 'Victory — the enemy force is broken.',
  enemy: 'Defeat — your force is broken.',
  draw: 'Draw — both banners still stand at dusk.',
}

/** One side's Force Strength plaque + bar. */
function ForceBar({ side, label, name }) {
  // Presentation-only arithmetic: FS as a percentage of the starting value.
  const pct = Math.max(0, Math.min(100, (side.force_strength / STARTING_FS) * 100))
  return (
    <section className={`force force-${name}`}>
      <h2 className="force-label">{label}</h2>
      <p className="force-value">
        <span data-testid={`fs-value-${name}`}>{side.force_strength}</span>
        <span className="force-max"> / {STARTING_FS}</span>
      </p>
      <div className="bar">
        <div className="bar-fill" data-testid={`fs-bar-${name}`} style={{ width: `${pct}%` }} />
      </div>
      {side.bonus_dice > 0 ? (
        <p className="force-bonus" data-testid={`bonus-${name}`}>
          +{side.bonus_dice} bonus dice last round
        </p>
      ) : null}
    </section>
  )
}

/** The 7 fixed allocations, mapped straight off the engine's table. */
function AllocationButtons({ disabled, onPick }) {
  return (
    <section className="alloc">
      <h2 className="alloc-title">Commit the pool</h2>
      <div className="alloc-row">
        {ALLOCATIONS.map((preset, index) => (
          <button
            key={index}
            type="button"
            className="alloc-button"
            data-testid={`alloc-${index}`}
            disabled={disabled}
            onClick={() => onPick(index)}
          >
            <span className="alloc-atk">{preset.attack} ATK</span>
            <span className="alloc-sep">/</span>
            <span className="alloc-def">{preset.defense} DEF</span>
          </button>
        ))}
      </div>
    </section>
  )
}

/** Scrolling dispatch log, newest round first. */
function RoundLog({ log }) {
  return (
    <section className="log-panel">
      <h2 className="log-title">Field dispatches</h2>
      <ol className="log" data-testid="round-log">
        {log.length === 0 ? (
          <li className="log-entry log-empty">The armies face off across the valley.</li>
        ) : (
          [...log].reverse().map((record) => (
            <li className="log-entry" data-testid="log-entry" key={record.round}>
              <h3 className="log-round">Round {record.round}</h3>
              {flavorLines(record).map((line, i) => (
                <p className="log-line" key={i}>
                  {line}
                </p>
              ))}
            </li>
          ))
        )}
      </ol>
    </section>
  )
}

function App() {
  const { state, sendAction, reset } = useBattle()

  return (
    <main className="app">
      <header className="masthead">
        <h1 className="title">Dice Duel</h1>
        <p className="round-track">
          Round <span data-testid="round-number">{state.round_number}</span> of {MAX_ROUNDS}
        </p>
      </header>

      {state.battle_over ? (
        <p className={`outcome outcome-${state.winner}`} data-testid="outcome">
          {OUTCOME_TEXT[state.winner]}
        </p>
      ) : null}

      <div className="forces">
        <ForceBar side={state.player} label="Your force" name="player" />
        <ForceBar side={state.enemy} label="Enemy force" name="enemy" />
      </div>

      <AllocationButtons disabled={state.battle_over} onPick={sendAction} />

      {state.battle_over ? (
        <button
          type="button"
          className="new-battle"
          data-testid="new-battle"
          onClick={() => reset()}
        >
          Muster a new battle
        </button>
      ) : null}

      <RoundLog log={state.log} />
    </main>
  )
}

export default App
